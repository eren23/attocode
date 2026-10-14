"""Cloud failure paths must release resources and preserve budget reservations."""
import datetime as dt
import json
import urllib.error
from types import SimpleNamespace

import pytest

from eval.quality.cloud import TAG, batch, execute_batch, quote, reap, reconcile, reserve


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
