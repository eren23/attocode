"""Scale qualification controls: no billed API calls, real small gateway inputs."""

import asyncio
import hashlib
import importlib
import importlib.util
import json
import os
import shutil
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def retain_control_json(tmp_path, request):
    yield
    if folder := os.environ.get("SCALE_CONTROL_EVIDENCE"):
        target = Path(folder) / request.node.name
        for path in tmp_path.rglob("*.json"):
            if path.is_file() and not path.is_symlink() and ".attocode" not in path.parts:
                destination = target / path.relative_to(tmp_path)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)


def module(name):
    name = "eval.quality.scale_" + name
    assert importlib.util.find_spec(name) is not None, "scale qualification feature absent"
    return importlib.import_module(name)


def reservation():
    base = [
        {"id": str(i), "month": "2026-10", "reserved_usd": 1, "cleanup_verified": True}
        for i in range(23)
    ]
    raw = json.dumps(base)
    row = {
        "id": "scale-1",
        "month": "2026-10",
        "reserved_usd": 1,
        "cleanup_verified": False,
        "campaign": "20261029-scale-qualification",
        "selection": "capacity",
        "run_tag": "quality-scale-1",
    }
    return {
        "baseline_raw": raw,
        "baseline_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "ledger": base + [row],
        "reservation_id": row["id"],
        "batch": "capacity",
        "month": "2026-10",
        "monthly_reserved_limit_usd": 26,
        "max_batches": 3,
        "product_commit": "b4ce67f3584aad4c2e324029fac8d9b9fcdc98a8",
    }


def test_valid_reserved_row():
    data = reservation()
    assert (
        module("evidence").validate_reservation(data, "capacity", month="2026-10")["id"]
        == "scale-1"
    )


@pytest.mark.parametrize(
    "damage",
    [
        "prefix",
        "baseline_hash",
        "unresolved",
        "month",
        "limit",
        "count",
        "batch",
        "duplicate",
        "release",
        "selection",
        "finished",
    ],
)
def test_reservation_rejects_invalid_admission(damage):
    data = reservation()
    if damage == "prefix":
        data["ledger"][0] = {**data["ledger"][0], "reserved_usd": 0}
    if damage == "baseline_hash":
        data["baseline_sha256"] = "0" * 64
    if damage == "unresolved":
        data["ledger"][0]["cleanup_verified"] = False
    if damage == "month":
        data["month"] = "2026-11"
    if damage == "limit":
        data["monthly_reserved_limit_usd"] = 27
    if damage == "count":
        data["max_batches"] = 4
    if damage == "batch":
        data["batch"] = "real"
    if damage == "duplicate":
        data["ledger"][-1]["id"] = "0"
        data["reservation_id"] = "0"
    if damage == "release":
        data["product_commit"] = "0" * 40
    if damage == "selection":
        data["ledger"][-1]["selection"] = "real"
    if damage == "finished":
        data["ledger"][-1]["cleanup_verified"] = True
    with pytest.raises(ValueError):
        module("evidence").validate_reservation(data, "capacity", month="2026-10")


def test_repeated_dispatch_cannot_relaunch_deleted_worker():
    m = module("evidence")
    title = "Scale capacity scale-1"
    m.unique_dispatch([{"id": 1, "display_title": title}], 1, title, 1)
    with pytest.raises(ValueError):
        m.unique_dispatch(
            [{"id": 1, "display_title": title}, {"id": 2, "display_title": title}], 2, title, 1
        )
    with pytest.raises(ValueError):
        m.unique_dispatch([{"id": 1, "display_title": title}], 1, title, 2)


def test_complete_coverage_requires_actual_parsed_files():
    good = {"phase": "ready", "parsed_files": 32, "total_files": 33, "discovery_truncated": False}
    module("evidence").admit_coverage(good, 32)


@pytest.mark.parametrize("damage", ["warming", "missing", "truncated", "short", "bool", "unknown"])
def test_coverage_rejects_false_readiness(damage):
    data = {"phase": "ready", "parsed_files": 32, "total_files": 33, "discovery_truncated": False}
    if damage == "warming":
        data["phase"] = "hydrating"
    if damage == "missing":
        data.pop("parsed_files")
    if damage == "truncated":
        data["discovery_truncated"] = True
    if damage == "short":
        data["parsed_files"] = 31
    if damage == "bool":
        data["parsed_files"] = True
    if damage == "unknown":
        data.pop("discovery_truncated")
    with pytest.raises(ValueError):
        module("evidence").admit_coverage(data, 32)


def test_export_preserves_raw_and_manifest(tmp_path):
    root = tmp_path / "evidence"
    root.mkdir()
    (root / "raw.json").write_text(json.dumps({"source": "original", "failed": True}, indent=2))
    output = tmp_path / "out.tar.gz"
    receipt = module("evidence").export_evidence(root, output)
    assert receipt["files"] == 1 and receipt["bytes"] > 0
    import tarfile

    with tarfile.open(output) as arc:
        assert json.load(arc.extractfile("raw.json")) == {"source": "original", "failed": True}


@pytest.mark.parametrize("damage", ["symlink", "oversize"])
def test_export_rejects_escape_and_overflow(tmp_path, damage):
    root = tmp_path / "evidence"
    root.mkdir()
    if damage == "symlink":
        (root / "bad.json").symlink_to("/etc/passwd")
    else:
        (root / "bad.log").write_bytes(b"x" * (2 * 2**20 + 1))
    with pytest.raises(ValueError):
        module("evidence").export_evidence(root, tmp_path / "out.tar.gz")


def test_failed_case_cannot_earn_complete():
    m = module("evidence")
    assert m.case_outcome([{"status": "passed", "cleanup_verified": True}]) == "passed"
    for row in [
        {"status": "incomplete", "cleanup_verified": True},
        {"status": "passed", "cleanup_verified": False},
        {"status": "passed", "cleanup_verified": True, "log_truncated": True},
    ]:
        assert m.case_outcome([row]) != "passed"
    assert m.case_outcome([]) != "passed"


def test_source_generation_has_exact_known_edges(tmp_path):
    result = module("workload").generate_tree(tmp_path / "tree", 32)
    assert result["source_files"] == 32 and len(result["source_sha256"]) == 64
    assert (tmp_path / "tree/module_31.py").read_text() == (
        "from module_30 import operation_30\n"
        "def operation_31(value: int) -> int:\n"
        "    return operation_30(value) + 31\n"
    )


def test_real_gateway_phase_and_reopen(tmp_path):
    m = module("workload")
    root = tmp_path / "tree"
    m.generate_tree(root, 32)
    spec = {
        "id": "small",
        "root": str(root),
        "source_files": 32,
        "file": "module_31.py",
        "symbol": "operation_31",
        "line": 2,
        "dependency": "module_30.py",
        "seconds": 60,
    }
    for phase in ("cold", "restart"):
        output = tmp_path / phase
        output.mkdir()
        result = asyncio.run(m.run_phase(spec, phase, output))
        assert result["complete"] and result["coverage"]["parsed_files"] >= 32
        assert result["checks"]["definition"] and result["checks"]["dependency"]
        assert (output / "result.json").is_file()


def test_concurrent_gateway_mutations_and_integrity(tmp_path):
    m = module("workload")
    root = tmp_path / "tree"
    m.generate_tree(root, 32)
    output = tmp_path / "evidence"
    output.mkdir()
    result = asyncio.run(m.lifecycle(root, output, soak_seconds=0))
    assert result["complete"] and result["concurrency_offered"] == [1, 4, 8]
    assert result["max_inflight"] >= 8
    assert all(result["mutations"].values()) and result["sqlite_integrity"]


class FakeAPI:
    def __init__(self, lost=False):
        self.nodes = []
        self.keys = []
        self.lost = lost

    def list(self, resource, query=""):
        assert resource == "droplets"
        return self.nodes

    def request(self, method, path, data=None):
        if path.startswith("/account/keys"):
            if method == "GET":
                return {"ssh_keys": self.keys}
            if method == "POST":
                self.keys.append({"id": 12, "name": data["name"]})
                return {"ssh_key": self.keys[-1]}
            if method == "DELETE":
                self.keys = []
                return {}
        if path == "/droplets" and method == "POST":
            self.nodes.append({"id": 15, "tags": data["tags"]})
            if self.lost:
                raise TimeoutError("lost create response")
            return {"droplet": self.nodes[-1]}
        if path.startswith("/droplets/"):
            if method == "DELETE":
                self.nodes = []
                return {}
            if not self.nodes:
                import urllib.error

                raise urllib.error.HTTPError(path, 404, "absent", {}, None)
            return {"droplet": self.nodes[0]}
        raise AssertionError((method, path))


@pytest.mark.parametrize("failure", ["collect", "lost_create", "success"])
def test_controller_cleans_worker_and_ephemeral_key(tmp_path, monkeypatch, failure):
    m = module("campaign")
    api = FakeAPI(lost=failure == "lost_create")
    monkeypatch.setattr(m, "preflight", lambda *args: {"hourly_usd": 0.16667})
    monkeypatch.setattr(m, "make_key", lambda path: "ssh-ed25519 fixture")

    def execute(*args):
        if failure == "collect":
            raise RuntimeError("collection failed")
        return {"complete": True}

    result = m.run(reservation(), tmp_path, api=api, execute=execute, month="2026-10")
    assert result["cleanup_verified"] and result["key_cleanup_verified"]
    assert not api.nodes and not api.keys
    assert result["complete"] == (failure == "success")
    assert (tmp_path / "receipt.json").is_file()


def test_grammar_inventory_missing_native_is_failure():
    with pytest.raises(ValueError):
        module("native").admit_grammars({"ocaml": True, "perl": True})


def test_installed_wheel_source_mismatch_is_rejected(tmp_path):
    import zipfile

    root = tmp_path / "attocode_intel"
    root.mkdir()
    (root / "__init__.py").write_text('__version__="wrong"')
    wheel = tmp_path / "published.whl"
    with zipfile.ZipFile(wheel, "w") as z:
        z.writestr("attocode_intel/__init__.py", '__version__="0.1.20"')
    with pytest.raises(ValueError):
        module("evidence").attest_wheel(wheel, root, hashlib.sha256(wheel.read_bytes()).hexdigest())


def test_large_manifest_export_is_lossless(tmp_path):
    import tarfile

    root = tmp_path / "raw"
    root.mkdir()
    value = {"manifest": "x" * (2 * 2**20 + 100)}
    (root / "large.json").write_text(json.dumps(value))
    output = tmp_path / "results.tar.gz"
    receipt = module("evidence").export_evidence(root, output)
    with tarfile.open(output) as archive:
        parts = sorted(n for n in archive.getnames() if n.startswith("large.json.part"))
        assert len(parts) == 2
        raw = b"".join(archive.extractfile(n).read() for n in parts)
    assert json.loads(raw) == value
    assert receipt["splits"]["large.json"]["sha256"] == hashlib.sha256(raw).hexdigest()


def test_dispatch_batch_and_reservation_binding():
    m = module("evidence")
    assert callable(getattr(m, "dispatch_selection", None)), "dispatch binding absent"
    m.dispatch_selection(reservation(), "capacity", "scale-1")
    for batch, identity in [("real", "scale-1"), ("capacity", "scale-2")]:
        with pytest.raises(ValueError):
            m.dispatch_selection(reservation(), batch, identity)


def test_forced_restart_checkpoint_keeps_gateway_open(tmp_path):
    import signal
    import subprocess
    import sys
    import time

    m = module("workload")
    root = tmp_path / "tree"
    m.generate_tree(root, 32)
    spec = {
        "id": "forced",
        "root": str(root),
        "source_files": 32,
        "file": "module_31.py",
        "symbol": "operation_31",
        "line": 2,
        "dependency": "module_30.py",
        "seconds": 45,
    }
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec))
    marker = tmp_path / "evidence/forced/crash/result.json"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "eval.quality.scale_workload",
            "--phase",
            "crash",
            "--case",
            str(path),
            "--root",
            str(tmp_path),
        ],
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 45
        while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        assert marker.exists(), "missing crash checkpoint"
        result = json.loads(marker.read_text())
        assert result.get("closed") is not True, "crash checkpoint already closed gateway"
        assert result["complete"] and process.poll() is None
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)
