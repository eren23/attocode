"""Cloud failure paths must release resources and preserve budget reservations."""
import datetime as dt
import json
import os
import shlex
import shutil
import subprocess
import sys
import urllib.error
from types import SimpleNamespace

import pytest

from eval.quality.cloud import TAG, batch, execute_batch, quote, reap, reconcile, reserve


@pytest.mark.parametrize('seconds', [0, -1, 5401])
def test_worker_timeout_cannot_be_disabled(seconds):
    from eval.quality.cloud import worker_command
    with pytest.raises(ValueError, match='positive'):
        worker_command('true', seconds)


def test_worker_timeout_kills_term_resistant_command_without_controller():
    from eval.quality.cloud import worker_command

    if not shutil.which('timeout'):
        pytest.skip('GNU timeout is installed on the Linux worker and Linux CI')
    script = 'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print("started",flush=True); time.sleep(60)'
    command = worker_command('exec ' + shlex.join([sys.executable, '-c', script]), 1)
    result = subprocess.run(['/bin/sh', '-c', command], capture_output=True, text=True, timeout=15)
    assert result.returncode in {137, -9} and 'started' in result.stdout


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
    monkeypatch.setattr(cloud.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=0))
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
    assert 'timeout --signal=TERM --kill-after=10s 600s sh -c' in started[1][1][-1]
    assert 'ServerAliveInterval=15' in started[1][1]
    assert api.deleted == [42]


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
            return [{"slug": "s-8vcpu-16gb-amd", "available": True, "regions": ["fra1"], "vcpus": 8,
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
    {"slug": "c-8"}, {"regions": ["nyc1"]}, {"available": False},
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
    ledger = [{"month": "2026-01", "reserved_usd": 1, "estimated_usd": 9.5, "cleanup_verified": True}]
    now = dt.datetime(2026, 1, 2, tzinfo=dt.UTC).timestamp()
    with pytest.raises(ValueError, match="Monthly"):
        reserve(ledger, "new", {"hourly_usd": .25}, now)
    ledger[0]["cleanup_verified"] = False
    with pytest.raises(ValueError, match="cleanup"):
        reserve(ledger, "new", {"hourly_usd": .25}, now)


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
    monkeypatch.setattr(cloud.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0))
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
