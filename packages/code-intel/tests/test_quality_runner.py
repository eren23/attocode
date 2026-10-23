"""Resource limits, interruption and cleanup must be enforced, not advisory."""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import psutil
import pytest

from eval.quality.runner import GIB, MARKER, environment, managed_root, prune, supervise, write_json


def test_refuse_unowned_directory_and_symlink(tmp_path):
    root = tmp_path / "unowned"
    root.mkdir()
    (root / "keep").write_text("user data")
    with pytest.raises(ValueError, match="unowned"):
        managed_root(root)
    alias = tmp_path / "alias"
    alias.symlink_to(root)
    with pytest.raises(ValueError, match="symlink"):
        managed_root(alias)
    assert (root / "keep").read_text() == "user data"


def test_deadline_stops_child_and_caps_log(tmp_path):
    root = managed_root(tmp_path / "managed")
    row = supervise([sys.executable, "-c", "import time; print('x' * 100000, flush=True); time.sleep(30)"],
                    cwd=tmp_path, env=environment(root), root=root, log=root / "test.log",
                    deadline=time.monotonic() + 1, max_bytes=GIB, log_cap=1024)
    assert row["status"] == "incomplete" and row["reason"] == "deadline"
    assert row["seconds"] < 5 and row["cleanup_verified"]
    assert row["log_truncated"] and (root / "test.log").stat().st_size == 1024


def test_small_progress_is_visible_before_the_child_exits(tmp_path):
    root = managed_root(tmp_path / "managed")
    log, release = root / "live.log", root / "release"
    command = [sys.executable, "-c",
               "import pathlib,sys,time; print('progress',flush=True); "
               "release=pathlib.Path(sys.argv[1]); "
               "exec('while not release.exists(): time.sleep(.02)')", str(release)]
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(supervise, command, cwd=tmp_path, env=environment(root),
                             root=root, log=log, deadline=time.monotonic() + 8, max_bytes=GIB)
        try:
            deadline = time.monotonic() + 5
            while (not log.exists() or not log.read_bytes()) and time.monotonic() < deadline:
                time.sleep(.02)
            assert log.read_text() == "progress\n"
            assert not result.done()  # EOF must not be required to publish the record.
        finally:
            release.touch()
        row = result.result(timeout=10)
    assert row["status"] == "passed" and row["cleanup_verified"]


def test_disk_admission_does_not_start_process(tmp_path):
    root = managed_root(tmp_path / "managed")
    row = supervise(["this-command-must-not-run"], cwd=tmp_path, env={}, root=root,
                    log=root / "log", deadline=time.monotonic() + 10, max_bytes=1)
    assert row["reason"] == "admission_budget"


@pytest.mark.parametrize('target_kind', ['file', 'directory'])
def test_disk_accounting_counts_links_without_following_external_targets(tmp_path, target_kind):
    from eval.quality.runner import disk_bytes

    root, external = tmp_path / 'owned', tmp_path / 'outside'
    root.mkdir()
    external.mkdir()
    data = root / 'sparse.bin'
    with data.open('wb') as stream:
        stream.truncate(2**20)
    (external / 'large.bin').write_bytes(b'x' * (2**20))
    link = root / 'alias'
    link.symlink_to(external if target_kind == 'directory' else external / 'large.bin',
                    target_is_directory=target_kind == 'directory')
    expected = sum(max(p.lstat().st_size, getattr(p.lstat(), 'st_blocks', 0) * 512)
                   for p in (data, link))
    assert disk_bytes(root) == expected


def test_wall_deadline_stops_child_when_monotonic_clock_does_not_advance(tmp_path, monkeypatch):
    from eval.quality import runner

    root = managed_root(tmp_path / "managed")
    wall = [1000.0]
    def suspended_sleep(seconds):
        time.sleep(.01)
        wall[0] += 120  # Resume after suspension; monotonic still reports zero elapsed.
    monkeypatch.setattr(runner, 'time', SimpleNamespace(
        monotonic=lambda: 10.0, time=lambda: wall[0], sleep=suspended_sleep))
    row = supervise([sys.executable, '-c', 'import time; time.sleep(30)'],
                    cwd=tmp_path, env=environment(root), root=root, log=root / 'clock.log',
                    deadline=70, wall_deadline=5000, max_bytes=GIB)
    assert row['reason'] == 'deadline' and row['status'] == 'incomplete'
    assert row['seconds'] == 0 and row['wall_seconds'] >= 120
    assert row['cleanup_verified']


def test_expired_wall_deadline_refuses_launch(tmp_path):
    root = managed_root(tmp_path / 'managed')
    row = supervise(['must-not-launch'], cwd=tmp_path, env={}, root=root, log=root / 'log',
                    deadline=time.monotonic() + 60, wall_deadline=time.time() - 1, max_bytes=GIB)
    assert row['reason'] == 'admission_budget'


def test_tier_does_not_reset_wall_budget_between_phases(tmp_path, monkeypatch):
    from eval.quality import runner

    wall = [1000.0]
    monkeypatch.setattr(runner, 'time', SimpleNamespace(
        time=lambda: wall[0], monotonic=lambda: 10.0, strftime=time.strftime))
    monkeypatch.setattr(runner, 'commands', lambda *a, **kw: [('first', ['one']), ('second', ['two'])])
    calls = []
    def finished(command, **kwargs):
        calls.append(command)
        assert kwargs['wall_deadline'] == 1002
        wall[0] += 3
        return {'status': 'passed', 'seconds': 0, 'cleanup_verified': True}
    monkeypatch.setattr(runner, 'supervise', finished)
    _, report = runner.run('quick', tmp_path / 'managed', seconds=2)
    assert calls == [['one']]
    assert report['status'] == 'incomplete' and report['remaining_checks'] == ['second']


def test_completed_failure_is_not_pass_or_timeout(tmp_path):
    root = managed_root(tmp_path / "managed")
    row = supervise([sys.executable, "-c", "raise SystemExit(7)"], cwd=tmp_path,
                    env=environment(root), root=root, log=root / "log",
                    deadline=time.monotonic() + 10, max_bytes=GIB)
    assert row["status"] == "failed" and row["exit_code"] == 7


def test_cleanup_preview_only_targets_expired_owned_reports(tmp_path):
    root = managed_root(tmp_path / "managed")
    for name, owner, status in [("old", MARKER, "passed"), ("foreign", "other", "passed"),
                                ("active", MARKER, "running")]:
        directory = root / "runs" / name
        directory.mkdir()
        write_json(directory / "report.json", {"owner": owner, "status": status})
        os.utime(directory / "report.json", (0, 0))
    assert prune(root)["paths"] == [str(root / "runs/old")]
    assert (root / "runs/old").exists()
    prune(root, apply=True)
    assert not (root / "runs/old").exists()
    assert (root / "runs/foreign").exists() and (root / "runs/active").exists()


def test_model_and_cloud_credentials_not_inherited(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    monkeypatch.setenv("DIGITALOCEAN_ACCESS_TOKEN", "must-not-leak")
    env = environment(managed_root(tmp_path / "managed"))
    assert "OPENAI_API_KEY" not in env and "DIGITALOCEAN_ACCESS_TOKEN" not in env
    assert env["HF_HUB_OFFLINE"] == "1"
    assert str(tmp_path) in env["UV_CACHE_DIR"]


def test_deadline_cleans_observed_child_in_separate_session(tmp_path):
    root = managed_root(tmp_path / "managed")
    command = [sys.executable, "-c", "import subprocess,sys,time; "
               "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],start_new_session=True); "
               "print(p.pid,flush=True); time.sleep(30)"]
    row = supervise(command, cwd=tmp_path, env=environment(root), root=root, log=root / "pid.log",
                    deadline=time.monotonic() + 1, max_bytes=GIB)
    child = int((root / "pid.log").read_text().strip())
    assert row["reason"] == "deadline" and row["cleanup_verified"]
    assert not psutil.pid_exists(child) or psutil.Process(child).status() == psutil.STATUS_ZOMBIE
