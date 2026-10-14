"""Resource limits, interruption and cleanup must be enforced, not advisory."""
import os
import sys
import time

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


def test_disk_admission_does_not_start_process(tmp_path):
    root = managed_root(tmp_path / "managed")
    row = supervise(["this-command-must-not-run"], cwd=tmp_path, env={}, root=root,
                    log=root / "log", deadline=time.monotonic() + 10, max_bytes=1)
    assert row["reason"] == "admission_budget"


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
