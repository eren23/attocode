"""Cloud failure paths must release resources and preserve budget reservations."""
import datetime as dt
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
from types import SimpleNamespace

import psutil
import pytest

from eval.quality.cloud import TAG, batch, execute_batch, quote, reap, reconcile, reserve


@pytest.mark.parametrize('seconds', [0, -1, 5401])
def test_worker_timeout_cannot_be_disabled(seconds):
    from eval.quality.cloud import worker_command
    with pytest.raises(ValueError, match='positive'):
        worker_command('true', seconds)


def test_worker_timeout_kills_term_resistant_detached_descendant(tmp_path):
    from eval.quality.cloud import worker_command

    if os.environ.get('QUALITY_TEST_SYSTEMD') != '1':
        pytest.skip('Dedicated Linux CI enables the systemd worker test')
    assert sys.platform == 'linux' and shutil.which('systemd-run') and shutil.which('sudo')
    # Single-quote the value so the worker shell, not systemd, owns expansion.
    successful = worker_command("value='literal $dollar'; printf '%s' \"$value\"", 5)
    completed = subprocess.run(['sudo', '-n', '/bin/sh', '-c', successful],
                               capture_output=True, text=True, timeout=10)
    successful_unit = next(a.split('=', 1)[1] for a in shlex.split(successful) if a.startswith('--unit='))
    subprocess.run(['sudo', '-n', 'rmdir', '/run/' + successful_unit + '.started'], check=True)
    assert completed.returncode == 0 and completed.stdout == 'literal $dollar', completed.stderr
    record = tmp_path / 'worker.json'
    child = 'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'
    script = (
        'import json,os,signal,subprocess,sys,time; from pathlib import Path; '
        'signal.signal(signal.SIGTERM, signal.SIG_IGN); '
        f'p=subprocess.Popen([sys.executable,"-c",{child!r}], start_new_session=True); '
        f'Path({str(record)!r}).write_text(json.dumps([os.getpid(), p.pid])); '
        'time.sleep(60)'
    )
    command = worker_command('exec ' + shlex.join([sys.executable, '-c', script]), 1)
    unit = next(a.split('=', 1)[1] for a in shlex.split(command) if a.startswith('--unit='))
    try:
        result = subprocess.run(['sudo', '-n', '/bin/sh', '-c', command],
                                capture_output=True, text=True, timeout=18)
        assert result.returncode != 0, result.stdout + result.stderr
        assert record.exists(), result.stderr
        pids = json.loads(record.read_text())
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and any(psutil.pid_exists(pid) for pid in pids):
            time.sleep(.05)
        for pid in pids:
            try:
                assert psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
            except psutil.NoSuchProcess:
                pass
    finally:
        subprocess.run(['sudo', '-n', 'systemctl', 'stop', unit], capture_output=True, timeout=15)
        subprocess.run(['sudo', '-n', 'rmdir', '/run/' + unit + '.started'], check=True)


def test_worker_manual_restart_cannot_run_payload_twice(tmp_path):
    from eval.quality.cloud import worker_command

    if os.environ.get('QUALITY_TEST_SYSTEMD') != '1':
        pytest.skip('Dedicated Linux CI enables the systemd restart test')
    record = tmp_path / 'starts'
    command = worker_command(f'echo started >> {shlex.quote(str(record))}; exec sleep 30', 20)
    unit = next(a.split('=', 1)[1] for a in shlex.split(command) if a.startswith('--unit='))
    process = subprocess.Popen(['sudo', '-n', '/bin/sh', '-c', command],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.monotonic() + 8
        while not record.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert record.exists()
        restart = subprocess.run(['sudo', '-n', 'systemctl', 'restart', unit],
                                 capture_output=True, text=True, timeout=8)
        assert restart.returncode != 0, restart.stdout + restart.stderr
        output, _ = process.communicate(timeout=8)
        assert process.returncode != 0, output
        assert record.read_text().splitlines() == ['started']
    finally:
        subprocess.run(['sudo', '-n', 'systemctl', 'stop', unit], capture_output=True, timeout=15)
        subprocess.run(['sudo', '-n', 'rmdir', '/run/' + unit + '.started'], check=True)
        process.communicate(timeout=3)


def test_worker_command_uses_independent_cgroup_and_preserves_shell_text():
    from eval.quality.cloud import worker_command
    script = 'printf "%s" "$literal"; echo "quoted text"'
    command = shlex.split(worker_command(script, 60))
    assert command[-3:] == ['/bin/sh', '-c', script]
    assert '--expand-environment=no' in command
    for setting in ['RuntimeMaxSec=60s', 'TimeoutStopSec=10s', 'KillMode=control-group', 'SendSIGKILL=yes']:
        assert '--property=' + setting in command


@pytest.mark.parametrize('release', [True, False])
def test_worker_apt_lock_wait_with_isolated_package_database(tmp_path, release):
    """Use actual apt/fcntl contention without touching the host package database."""
    import fcntl

    from eval.quality.cloud import WORKER_APT_INSTALL

    if os.environ.get('QUALITY_TEST_SYSTEMD') != '1':
        pytest.skip('Dedicated Linux CI enables worker package-manager checks')
    assert shutil.which('apt-get') and shutil.which('sudo')
    for name in ('dpkg', 'lists/partial', 'archives/partial', 'config'):
        (tmp_path / name).mkdir(parents=True)
    status = tmp_path / 'dpkg/status'
    status.write_text('Package: quality-already-installed\nStatus: install ok installed\n'
                      'Priority: optional\nSection: misc\nArchitecture: all\nVersion: 1.0\n'
                      'Maintainer: Quality Test\nDescription: isolated fixture\n\n')
    (tmp_path / 'sources.list').write_text('')
    args = list(WORKER_APT_INSTALL[:-3]) + ['quality-already-installed']
    assert args[2] == 'DPkg::Lock::Timeout=120'
    args[2] = 'DPkg::Lock::Timeout=2'  # Exercise the same apt option without a two-minute test.
    settings = {
        'Dir::State::status': status,
        'Dir::State::lists': tmp_path / 'lists',
        'Dir::State::extended_states': tmp_path / 'extended_states',
        'Dir::Cache': tmp_path,
        'Dir::Cache::archives': tmp_path / 'archives',
        'Dir::Etc::parts': tmp_path / 'config',
        'Dir::Etc::main': tmp_path / 'absent.conf',
        'Dir::Etc::sourcelist': tmp_path / 'sources.list',
        'Dir::Etc::sourceparts': tmp_path / 'config',
        'Dir::Log': tmp_path,
    }
    options = [arg for key, value in settings.items() for arg in ('-o', f'{key}={value}')]
    command = ['sudo', '-n', args[0], *options, *args[1:], '--no-download', '--no-upgrade']
    with (tmp_path / 'dpkg/lock-frontend').open('w') as lock:
        fcntl.lockf(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        environment = {**os.environ, 'LC_ALL': 'C'}
        immediate = subprocess.run(
            [arg.replace('DPkg::Lock::Timeout=2', 'DPkg::Lock::Timeout=0') for arg in command],
            capture_output=True, text=True, env=environment, timeout=8,
        )
        assert immediate.returncode == 100, immediate.stdout + immediate.stderr
        assert 'Unable to acquire the dpkg frontend lock' in immediate.stderr
        started = time.monotonic()
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, env=environment)
        try:
            if release:
                # A default no-wait install exits here with 100, proving the
                # control distinguishes a bounded wait from immediate failure.
                with pytest.raises(subprocess.TimeoutExpired):
                    process.communicate(timeout=.3)
                fcntl.lockf(lock, fcntl.LOCK_UN)
            output, _ = process.communicate(timeout=8)
            assert process.returncode == (0 if release else 100), output
            if not release:
                assert time.monotonic() - started >= 1
                assert 'Unable to acquire the dpkg frontend lock' in output
            assert status.read_text().count('Package:') == 1
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=3)


def test_controller_resume_past_wall_deadline_does_not_start_tests(tmp_path, monkeypatch):
    from eval.quality import cloud

    api = FakeAPI()
    original = api.request
    def request(method, path, data=None):
        result = original(method, path, data)
        if method == 'GET':
            result['droplet'].update(status='active', networks={'v4': [
                {'type': 'public', 'ip_address': '192.0.2.1'}]})
        return result
    api.request = request
    wall = [1000.0]
    monkeypatch.setattr(cloud, 'time', SimpleNamespace(
        time=lambda: wall[0], monotonic=lambda: 10.0, sleep=lambda _: None))
    monkeypatch.setattr(cloud.subprocess, 'run', lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout='{"status":"done","extended_status":"done"}'))
    started = []
    def supervise(command, **kwargs):
        if wall[0] >= kwargs['wall_deadline']:
            return {'status': 'incomplete', 'reason': 'admission_budget'}
        started.append((kwargs['log'].stem, command))
        if kwargs['log'].stem == 'setup':
            wall[0] += cloud.CONTROLLER_SECONDS + 1
        return {'status': 'passed'}
    monkeypatch.setattr(cloud, 'supervise', supervise)
    with pytest.raises(TimeoutError, match='deadline'):
        batch(api, tmp_path / 'managed', execute=execute_batch)
    assert [name for name, _ in started] == ['upload', 'setup']
    assert '--property=RuntimeMaxSec=600s' in started[1][1][-1]
    assert 'ServerAliveInterval=15' in started[1][1]
    assert api.deleted == [42]


@pytest.mark.parametrize('final', ['done', 'degraded done', 'disabled', 'invalid', 'timeout'])
def test_bootstrap_wait_requires_clean_completion_within_original_deadline(tmp_path, monkeypatch, final):
    from eval.quality import cloud

    clock = [100.0]
    monkeypatch.setattr(cloud, 'time', SimpleNamespace(
        monotonic=lambda: clock[0], time=lambda: clock[0],
        sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds)))
    calls = []
    def probe(command, **kwargs):
        calls.append(command)
        assert kwargs['timeout'] <= 6
        if len(calls) == 1:
            return SimpleNamespace(returncode=255, stdout='')
        status = 'running' if len(calls) == 2 or final == 'timeout' else final
        body = 'invalid' if status == 'invalid' else json.dumps({'status': status, 'extended_status': status})
        return SimpleNamespace(returncode=2 if status == 'degraded done' else 0, stdout=body)
    monkeypatch.setattr(cloud.subprocess, 'run', probe)
    if final == 'done':
        cloud.wait_for_bootstrap(['ssh', 'fixture'], {}, tmp_path, deadline=106, wall_deadline=110)
        assert len(calls) == 3 and clock[0] == 104
    else:
        with pytest.raises(TimeoutError if final == 'timeout' else RuntimeError):
            cloud.wait_for_bootstrap(['ssh', 'fixture'], {}, tmp_path, deadline=106, wall_deadline=110)
    assert all(c[-1] == 'cloud-init status --format=json' for c in calls)
    assert clock[0] <= 106


@pytest.mark.parametrize("command", ["quote", "reap", "reap-apply", "reconcile"])
def test_maintenance_cli_does_not_import_product_or_workflow_dependencies(command):
    from eval.quality.runner import REPO

    script = r'''
import builtins, sys
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in {'yaml', 'attocode_intel'}:
        raise ImportError('Maintenance unexpectedly requires ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from eval.quality import cloud
seen = []
def dispatch(command, **kwargs):
    seen.append(command)
    return 0
cloud.main = dispatch
command = sys.argv[1]
sys.argv = ['quality', 'cloud', command]
from eval.quality.__main__ import main
assert main() == 0 and seen == [command]
'''
    result = subprocess.run([sys.executable, "-c", script, command], cwd=REPO,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


class FakeAPI:
    def __init__(self, *, fail_create=False, fail_delete=False, rate=.16667):
        self.nodes = []
        self.deleted = []
        self.fail_create, self.fail_delete, self.rate = fail_create, fail_delete, rate

    def list(self, resource, query=""):
        if resource == "sizes":
            return [{"slug": "s-8vcpu-16gb-amd", "available": True, "regions": ["ams3"], "vcpus": 8,
                     "memory": 16384, "price_hourly": self.rate}]
        return self.nodes[:]

    def request(self, method, path, data=None):
        if method == "POST":
            node = {"id": 42, "name": data["name"], "tags": data["tags"], "created_at": "2026-01-01T00:00:00Z"}
            self.nodes.append(node)
            if self.fail_create:
                raise TimeoutError("Response lost after resource creation")
            return {"droplet": node}
        node_id = int(path.rsplit("/", 1)[1])
        if method == "DELETE":
            if self.fail_delete:
                raise RuntimeError("Provider unavailable")
            self.deleted.append(node_id)
            self.nodes = [n for n in self.nodes if n["id"] != node_id]
            return {}
        match = next((n for n in self.nodes if n["id"] == node_id), None)
        if match:
            return {"droplet": match}
        raise urllib.error.HTTPError("test", 404, "missing", {}, None)


def test_quote_rejects_price_over_budget():
    assert quote(FakeAPI())["estimated_70_minutes_usd"] == .1944
    with pytest.raises(ValueError, match="budget"):
        quote(FakeAPI(rate=2))


@pytest.mark.parametrize("change", [
    {"slug": "c-8"}, {"regions": ["nyc1"]}, {"regions": ["fra1"]}, {"available": False},
    {"vcpus": 4}, {"memory": 8192},
])
def test_quote_rejects_unapproved_or_insufficient_capacity(change):
    api = FakeAPI()
    sizes = api.list("sizes")
    sizes[0].update(change)
    api.list = lambda *args: sizes
    with pytest.raises(ValueError, match="capacity unavailable"):
        quote(api)


@pytest.mark.parametrize("mode,expected_calls,passed", [
    ("healthy", 0, True), ("recovered", 3, True), ("unavailable", 3, False),
])
def test_worker_dns_preflight_preserves_working_dns_and_fails_closed(tmp_path, mode, expected_calls, passed):
    from eval.quality.cloud import WORKER_DNS_PREFLIGHT
    # Run the actual setup shell branch with offline stand-ins for system tools.
    script = '''
count=0
timeout() { test "$1" = 15; shift; "$@"; }
getent() {
  count=$((count + 1))
  test "$DNS_MODE" = healthy || { test "$DNS_MODE" = recovered && test "$count" -gt 1; }
}
resolvectl() { printf '%s\\n' "$*" >> "$DNS_TRACE"; }
'''
    trace = tmp_path / "dns.log"
    result = subprocess.run(["/bin/sh", "-ec", script + WORKER_DNS_PREFLIGHT + "echo setup-ready"],
                            env={**os.environ, "DNS_MODE": mode, "DNS_TRACE": str(trace)},
                            capture_output=True, text=True)
    assert (result.returncode == 0) is passed
    assert ("setup-ready" in result.stdout) is passed
    calls = trace.read_text().splitlines() if trace.exists() else []
    assert len(calls) == expected_calls
    if calls:
        assert calls == ["dns eth0 1.1.1.1 8.8.8.8", "domain eth0 ~.", "flush-caches"]


def test_monthly_admission_and_unresolved_cleanup_block():
    ledger = [{"month": "2026-01", "reserved_usd": 1, "estimated_usd": 22.5, "cleanup_verified": True}]
    now = dt.datetime(2026, 1, 2, tzinfo=dt.UTC).timestamp()
    with pytest.raises(ValueError, match="Monthly"):
        reserve(ledger, "new", {"hourly_usd": .25}, now)
    ledger[0]["cleanup_verified"] = False
    with pytest.raises(ValueError, match="cleanup"):
        reserve(ledger, "new", {"hourly_usd": .25}, now)


def test_two_more_reservations_preserve_twenty_one_existing_and_then_refuse():
    ledger = [{"id": str(i), "month": "2026-10", "reserved_usd": 1,
               "estimated_usd": .01, "cleanup_verified": True} for i in range(21)]
    original = [dict(row) for row in ledger]
    now = dt.datetime(2026, 10, 15, tzinfo=dt.UTC).timestamp()
    for i in range(2):
        row = reserve(ledger, f"additional-{i}", {"hourly_usd": .16667}, now)
        with pytest.raises(ValueError, match="cleanup"):
            reserve(ledger, "concurrent", {"hourly_usd": .16667}, now)
        row.update(cleanup_verified=True, estimated_usd=.01)
    with pytest.raises(ValueError, match="Monthly"):
        reserve(ledger, "third", {"hourly_usd": .16667}, now)
    assert ledger[:21] == original
    assert len(ledger) == 23


@pytest.mark.parametrize('case', ['first', 'repair', 'history', 'cleanup', 'exhausted',
                                 'selection', 'passed', 'missing_repair', 'unchanged'])
def test_target_retest_cycle_requires_failed_target_and_real_repair(case):
    from copy import deepcopy

    from eval.quality.cloud import target_retest_attempt
    baseline = [{'id': 'old', 'cleanup_verified': True}]
    ledger = deepcopy(baseline)
    identity = {'source_sha256': 'new', 'harness_sha256': 'same'}
    previous = {'batch': 'target', 'passed': False, 'cleanup_verified': True,
                'source_matrix_identity': {'source_sha256': 'old', 'harness_sha256': 'same'}}
    repair = {'failed_batch': 'target', 'source_commit': 'commit', 'diagnosis': 'measured',
              'validation': 'passed', 'merged_pr': 'PR'}
    if case != 'first':
        ledger.append({'id': 'target', 'cleanup_verified': True,
                       'selection': {'packs': ['cockroach'], 'shard': None, 'suite': 'workflows'}})
    if case == 'history':
        ledger[0]['id'] = 'changed'
    elif case == 'cleanup':
        ledger[-1]['cleanup_verified'] = False
    elif case == 'exhausted':
        ledger.append(deepcopy(ledger[-1]))
    elif case == 'selection':
        ledger[-1]['selection']['suite'] = 'all'
    elif case == 'passed':
        previous['passed'] = True
    elif case == 'missing_repair':
        repair = None
    elif case == 'unchanged':
        identity = previous['source_matrix_identity']
    if case in {'first', 'repair'}:
        assert target_retest_attempt(baseline, ledger, source_commit='commit', identity=identity,
                                    previous=previous, repair=repair) == (1 if case == 'first' else 2)
    else:
        with pytest.raises(ValueError):
            target_retest_attempt(baseline, ledger, source_commit='commit', identity=identity,
                                 previous=previous, repair=repair)


@pytest.mark.parametrize("failure", ["execution", "create_response", "interrupt"])
def test_failure_deletes_only_this_run_and_records_ledger(tmp_path, failure):
    api = FakeAPI(fail_create=failure == "create_response")
    def execute(*args):
        if failure == "interrupt":
            raise KeyboardInterrupt()
        raise RuntimeError(failure)
    with pytest.raises((RuntimeError, TimeoutError, KeyboardInterrupt)):
        batch(api, tmp_path / "managed", execute=execute)
    assert api.deleted == [42] and not api.nodes
    ledger = json.loads((tmp_path / "managed/cloud/ledger.json").read_text())
    assert ledger[0]["cleanup_verified"] and ledger[0]["status"] == "failed"
    assert "estimated_usd" in ledger[0]


def test_failed_deletion_keeps_reservation_and_blocks_new_batch(tmp_path):
    api = FakeAPI(fail_delete=True)
    with pytest.raises(RuntimeError, match="deletion"):
        batch(api, tmp_path / "managed", execute=lambda *args: None)
    ledger = json.loads((tmp_path / "managed/cloud/ledger.json").read_text())
    assert not ledger[0]["cleanup_verified"] and "estimated_usd" not in ledger[0]
    with pytest.raises(ValueError, match="Existing"):
        batch(api, tmp_path / "managed", execute=lambda *args: None)


def test_reaper_only_destroys_expired_project_workers():
    api = FakeAPI()
    api.nodes = [{"id": i, "name": str(i), "tags": tags, "created_at": created}
                 for i, tags, created in [(1, [TAG], "2026-01-01T00:00:00Z"),
                                          (2, ["unrelated"], "2026-01-01T00:00:00Z"),
                                          (3, [TAG], "2026-01-01T03:59:00Z")]]
    now = dt.datetime(2026, 1, 1, 4, tzinfo=dt.UTC)
    assert reap(api, now=now)["nodes"][0]["id"] == 1 and not api.deleted
    assert reap(api, now=now, apply=True)["cleanup_verified"]
    assert api.deleted == [1] and {n["id"] for n in api.nodes} == {2, 3}


def test_external_cleanup_can_reconcile_without_refunding_reservation(tmp_path):
    api = FakeAPI(fail_delete=True)
    with pytest.raises(RuntimeError):
        batch(api, tmp_path / "managed", execute=lambda *args: None)
    assert not reconcile(api, tmp_path / "managed")["cleanup_verified"]
    api.nodes.clear()  # Independent reaper completed.
    result = reconcile(api, tmp_path / "managed")
    assert result["cleanup_verified"] and result["ledger"][0]["reserved_usd"] == 1


def test_collection_failure_still_deletes_worker(tmp_path, monkeypatch):
    from eval.quality import cloud
    api = FakeAPI()
    original = api.request
    def request(method, path, data=None):
        result = original(method, path, data)
        if method == "GET":
            result["droplet"].update(status="active", networks={"v4": [{"type": "public", "ip_address": "192.0.2.1"}]})
        return result
    api.request = request
    monkeypatch.setattr(cloud.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout='{"status":"done","extended_status":"done"}'))
    commands = []
    def supervise(command, **kw):
        commands.append(command)
        return {"status": "failed" if "collect.log" in str(kw["log"]) else "passed"}
    monkeypatch.setattr(cloud, "supervise", supervise)
    with pytest.raises(RuntimeError, match="collection"):
        batch(api, tmp_path / "managed", execute=execute_batch)
    assert api.deleted == [42] and len(commands) == 4


def test_missing_reaper_blocks_before_provisioning(tmp_path, monkeypatch):
    from eval.quality import cloud
    api = FakeAPI()
    def unavailable():
        raise ValueError("No successful cleanup heartbeat")
    monkeypatch.setattr(cloud, "verify_reaper", unavailable)
    with pytest.raises(ValueError, match="heartbeat"):
        batch(api, tmp_path / "managed")
    assert not api.nodes and not api.deleted


def test_cloud_selection_validated_before_budget_or_provisioning(tmp_path):
    from eval.quality.cloud import workflow_arguments
    assert workflow_arguments(['express'], '1/1', 'workflows') == [
        '--suite', 'workflows', '--pack', 'express', '--shard', '1/1']
    api = FakeAPI()
    with pytest.raises(ValueError, match='Unknown quality packs'):
        batch(api, tmp_path / 'managed', packs=['not-a-pack'], execute=lambda *args: None)
    assert not api.nodes and not (tmp_path / 'managed').exists()


def test_cloud_resume_rejects_changed_inputs_before_reserving(tmp_path, monkeypatch):
    from eval.quality import corpus
    from eval.quality.cloud import validated_resume, workflow_arguments
    identity = {k:'frozen' for k in ('source_sha256','harness_sha256','fixture_sha256','pack_sha256')}
    monkeypatch.setattr(corpus, 'evidence_identity', lambda: identity)
    path = tmp_path / 'resume.json'
    data = {'schema_version':2,'identity':identity.copy(),'manifest_packs':['express'], 'repositories':[]}
    path.write_text(json.dumps(data))
    assert validated_resume(path) == data
    assert workflow_arguments(['express'], None, 'workflows', resume=True)[-2:] == [
        '--resume','/root/job/.attocode/quality/resume.json']
    data['identity']['source_sha256'] = 'different'
    path.write_text(json.dumps(data))
    api = FakeAPI()
    with pytest.raises(ValueError, match='different candidate'):
        batch(api, tmp_path / 'managed', resume=path, execute=lambda *args: None)
    assert not api.nodes and not (tmp_path / 'managed').exists()


def test_report_export_compacts_json_losslessly_and_rejects_oversize(tmp_path):
    import json
    import tarfile

    from eval.quality.export import export_reports
    root = tmp_path / 'runs'
    run = root / 'one'
    run.mkdir(parents=True)
    data = {'results': [{'symbol':'helper','outcome':'limited'}] * 35000}
    source = run / 'workflows.json'
    source.write_text(json.dumps(data, indent=2))
    assert source.stat().st_size > 2**21
    (run / 'ignored.txt').write_text('not exported')
    (run / 'link.json').symlink_to(source)
    target = tmp_path / 'reports.tar.gz'
    export_reports(root, target)
    with tarfile.open(target) as archive:
        assert archive.getnames() == ['.attocode/quality/runs/one/workflows.json']
        assert json.load(archive.extractfile(archive.getmembers()[0])) == data
        assert archive.getmembers()[0].size <= 2**21
    source.write_text(json.dumps({'large':'x' * (2**21)}))
    with pytest.raises(ValueError, match='export exceeds'):
        export_reports(root, target)


def test_index_probe_uses_existing_budget_and_deletion_but_cannot_be_release_gate(tmp_path):
    from eval.quality.cloud import probe_arguments
    assert probe_arguments(['cockroach']) == ['--pack', 'cockroach', '--seconds', '600']
    api = FakeAPI()
    result = batch(api, tmp_path/'managed', packs=['cockroach'], diagnostic=True, execute=lambda *a: None)
    assert result['cleanup_verified'] and api.deleted == [42]
    assert result['selection'] == {'packs':['cockroach'], 'shard':None, 'suite':'index-probe'}
    assert result['reserved_usd'] == 1


@pytest.mark.parametrize('selection', [dict(packs=[]), dict(packs=['cockroach','pandas']),
    dict(packs=['cockroach'], shard='1/1'), dict(packs=['cockroach'], suite='workflows'),
    dict(packs=['cockroach'], resume='report.json'), dict(packs=['unknown'])])
def test_invalid_diagnostic_refused_before_creating_managed_state(tmp_path, selection):
    with pytest.raises(ValueError):
        batch(FakeAPI(), tmp_path/'absent', diagnostic=True, **selection)
    assert not (tmp_path/'absent').exists()


def test_remote_probe_runs_supervised_diagnostic_and_bounded_export(tmp_path, monkeypatch):
    from eval.quality import cloud
    commands = []
    monkeypatch.setattr(cloud, 'wait_for_bootstrap', lambda *a, **kw: None)
    def supervised(command, **kwargs):
        commands.append(command)
        assert kwargs['wall_deadline'] > time.time()
        assert kwargs['max_bytes'] == 5*1024**3
        return {'status':'passed', 'seconds':0, 'cleanup_verified':True}
    monkeypatch.setattr(cloud, 'supervise', supervised)
    api = SimpleNamespace(request=lambda *a: {'droplet':{'status':'active',
        'networks':{'v4':[{'type':'public','ip_address':'192.0.2.1'}]}}})
    execute_batch(api, 42, tmp_path, tmp_path, tmp_path/'key', packs=['cockroach'], diagnostic=True)
    remote = [c[-1] for c in commands if c[0]=='ssh']
    test = next(c for c in remote if 'eval.quality.index_probe' in c)
    assert '--property=RuntimeMaxSec=660s' in test
    assert '--pack cockroach --seconds 600' in test and 'eval.quality broad' not in test
    assert any('eval.quality.export' in c for c in remote)
