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


def test_export_preserves_exact_json_octets(tmp_path):
    import tarfile

    root = tmp_path / "input"
    root.mkdir()
    original = b'{\n  "z": "\\u2603", "a": 1\n}\n'
    (root / "original.json").write_bytes(original)
    archive = tmp_path / "export.tar.gz"
    module("evidence").export_evidence(root, archive)
    with tarfile.open(archive) as exported:
        actual = exported.extractfile("original.json").read()
    (tmp_path / "exported.json").write_bytes(actual)
    assert actual == original


def test_export_preserves_real_journal_blob_identity(tmp_path):
    import tarfile

    from eval.quality.experiment_evidence import Journal

    journal = Journal(tmp_path / "journal", 2**20)
    reference = journal.response({"tool": "inspect_symbol"}, {"snippet": "snowman \u2603\n"})
    archive = tmp_path / "journal.tar.gz"
    module("evidence").export_evidence(journal.root, archive)
    with tarfile.open(archive) as exported:
        actual = exported.extractfile(reference["path"]).read()
    (tmp_path / "exported-blob.json").write_bytes(actual)
    (tmp_path / "blob-reference.json").write_text(json.dumps(reference))
    assert len(actual) == reference["bytes"]
    assert hashlib.sha256(actual).hexdigest() == reference["sha256"]


def test_invalid_json_stays_incomplete_export(tmp_path):
    root = tmp_path / "invalid"
    root.mkdir()
    (root / "bad.json").write_bytes(b"{not-json}\n")
    result = module("evidence").safe_export(root, tmp_path / "invalid.tar.gz")
    assert result["complete"] is False


def test_qualified_receipt_covers_current_control_inventory():
    import ast

    expected = 0
    for node in ast.parse(Path(__file__).read_text()).body:
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
            continue
        cases = 1
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "parametrize"
            ):
                cases *= len(ast.literal_eval(decorator.args[1]))
        expected += cases
    callback, receipt, run, jobs = qualification()
    receipt["new"] = expected
    callback(receipt, run, jobs, "e" * 40, "f" * 40)
    receipt["new"] = 68
    with pytest.raises(ValueError):
        callback(receipt, run, jobs, "e" * 40, "f" * 40)


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
        "bootstrap_key_id": 77,
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
        "path",
        "tag",
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
    if damage == "path":
        data["ledger"][-1]["id"] = data["reservation_id"] = "../escape"
    if damage == "tag":
        data["ledger"][-1]["run_tag"] = "quality-scale-../escape"
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
    good = {
        "phase": "ready",
        "parsed_files": 32,
        "total_files": 32,
        "reference_indexed_files": 32,
        "discovery_truncated": False,
    }
    module("evidence").admit_coverage(good, 32)


@pytest.mark.parametrize(
    "damage",
    [
        "warming",
        "missing",
        "truncated",
        "short",
        "bool",
        "unknown",
        "partial",
        "references",
        "missing_refs",
    ],
)
def test_coverage_rejects_false_readiness(damage):
    data = {
        "phase": "ready",
        "parsed_files": 32,
        "total_files": 32,
        "reference_indexed_files": 32,
        "discovery_truncated": False,
    }
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
    if damage == "partial":
        data["total_files"] = 33
    if damage == "references":
        data["reference_indexed_files"] = 31
    if damage == "missing_refs":
        data.pop("reference_indexed_files")
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


def test_eligible_source_count_separates_discovery_from_parsing(tmp_path):
    (tmp_path / "entry.py").write_text("def entry():\n    return 1\n")
    (tmp_path / "README.md").write_text("# Source documentation\n")
    assert [p.name for p in module("workload").eligible_sources(tmp_path)] == ["entry.py"]


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
                if path.startswith("/account/keys/"):
                    import urllib.error

                    if not self.keys:
                        raise urllib.error.HTTPError(path, 404, "absent", {}, None)
                    return {"ssh_key": self.keys[0]}
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


def qualification():
    receipt = {
        "stage": "green",
        "new": 72,
        "old": 58,
        "failed": 0,
        "errors": 0,
        "head": "f" * 40,
        "tree": "e" * 40,
        "run_id": "123",
        "attempt": "1",
    }
    run = {
        "id": 123,
        "head_sha": "f" * 40,
        "run_attempt": 1,
        "event": "push",
        "path": ".github/workflows/quality-scale.yml",
        "status": "completed",
        "conclusion": "success",
    }
    jobs = [
        {"name": "controls", "conclusion": "success"},
        {"name": "access-check", "conclusion": "success"},
        {"name": "worker-smoke", "conclusion": "success"},
    ]
    m = module("evidence")
    callback = getattr(m, "admit_qualification", None)
    assert callable(callback), "control qualification binding absent"
    return callback, receipt, run, jobs


def test_qualified_controls_and_worker_smoke_are_required():
    callback, receipt, run, jobs = qualification()
    callback(receipt, run, jobs, "e" * 40, "f" * 40)


@pytest.mark.parametrize("damage", ["stage", "head", "tree", "count", "attempt", "worker"])
def test_incomplete_qualification_rejected(damage):
    callback, receipt, run, jobs = qualification()
    if damage == "stage":
        receipt["stage"] = "boundary-red"
    if damage == "head":
        receipt["head"] = "0" * 40
    if damage == "tree":
        receipt["tree"] = "0" * 40
    if damage == "count":
        receipt["new"] = 71
    if damage == "attempt":
        run["run_attempt"] = 2
    if damage == "worker":
        jobs[-1]["conclusion"] = "skipped"
    with pytest.raises(ValueError):
        callback(receipt, run, jobs, "e" * 40, "f" * 40)


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


def feature(name, function):
    callback = getattr(module(name), function, None)
    assert callable(callback), "review control feature absent: " + function
    return callback


def test_exact_parsed_and_reference_identities():
    feature("evidence", "admit_identities")(
        ["a.py", "pyproject.toml"], ["a.py", "pyproject.toml"], ["a.py", "pyproject.toml"]
    )


@pytest.mark.parametrize("damage", ["missing", "extra", "reference"])
def test_incorrect_indexed_identity_sets_rejected(damage):
    callback = feature("evidence", "admit_identities")
    expected = ["a.py", "pyproject.toml"]
    parsed = expected[:]
    refs = expected[:]
    if damage == "missing":
        parsed.pop()
    if damage == "extra":
        parsed.append("unselected.py")
    if damage == "reference":
        refs.pop()
    with pytest.raises(ValueError):
        callback(expected, parsed, refs)


def test_complete_native_parser_receipt():
    feature("evidence", "admit_parsers")(
        {"files_by_parser": {"tree_sitter": 2}, "files_with_parse_failures": 0}, {"python": True}, 2
    )


@pytest.mark.parametrize("damage", ["grammar", "regex", "failure", "missing", "count"])
def test_missing_or_degraded_parser_evidence_rejected(damage):
    callback = feature("evidence", "admit_parsers")
    analysis = {"files_by_parser": {"tree_sitter": 2}, "files_with_parse_failures": 0}
    grammars = {"python": True}
    if damage == "grammar":
        grammars["python"] = False
    if damage == "regex":
        analysis["files_by_parser"] = {"regex": 2}
    if damage == "failure":
        analysis["files_with_parse_failures"] = 1
    if damage == "missing":
        analysis.pop("files_by_parser")
    if damage == "count":
        analysis["files_by_parser"] = {"tree_sitter": 1}
    with pytest.raises(ValueError):
        callback(analysis, grammars, 2)


def test_interrupted_request_has_durable_offered_record(tmp_path):
    m = module("workload")

    async def exercise():
        entered = asyncio.Event()

        class Gateway:
            async def execute_mcp(self, *args):
                entered.set()
                await asyncio.Event().wait()

        requests = m.Requests(Gateway(), tmp_path)
        task = asyncio.create_task(
            requests.call("search_symbols", {"name": "known", "max_tokens": 1000})
        )
        try:
            await asyncio.wait_for(entered.wait(), 2)
            offered = list(tmp_path.glob("offered-*.json"))
            assert len(offered) == 1, "offered request missing during dispatch"
            row = json.loads(offered[0].read_text())
            assert (
                row["arguments"]["name"] == "known"
                and row["sequence"] == 0
                and "response" not in row
            )
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(exercise())


def test_full_campaign_history_includes_older_reservation():
    callback = feature("evidence", "campaign_runs")
    own = {
        "id": 120,
        "display_title": "Scale capacity reserved",
        "created_at": "2026-10-29T00:00:00Z",
    }
    original = {
        "id": 1,
        "display_title": own["display_title"],
        "created_at": "2026-10-01T00:00:00Z",
    }
    calls = []

    def fetch(page):
        calls.append(page)
        return {
            "workflow_runs": (
                [own]
                + [
                    {"id": i, "display_title": "controls", "created_at": own["created_at"]}
                    for i in range(2, 101)
                ]
            )
            if page == 1
            else [original]
        }

    rows = callback(fetch, "2026-10")
    assert calls == [1, 2] and original in rows
    with pytest.raises(ValueError):
        module("evidence").unique_dispatch(rows, 120, own["display_title"], 1)


def test_sigterm_runs_provider_cleanup(tmp_path):
    import signal
    import subprocess
    import sys
    import time

    code = """import time,sys,json
from pathlib import Path
from eval.quality.tests.test_scale_qualification import FakeAPI,reservation
from eval.quality import scale_campaign as m
out=Path(sys.argv[1]); api=FakeAPI()
m.preflight=lambda *args:{'hourly_usd':.16667}
m.make_key=lambda path:'ssh-ed25519 fixture'
def execute(*args):
 (out/'issued.json').write_text('{}')
 time.sleep(60)
 return {'complete':True}
m.run(reservation(),out,api=api,execute=execute,month='2026-10')
"""
    process = subprocess.Popen([sys.executable, "-c", code, str(tmp_path)], start_new_session=True)
    try:
        until = time.monotonic() + 10
        while (
            not (tmp_path / "issued.json").exists()
            and process.poll() is None
            and time.monotonic() < until
        ):
            time.sleep(0.1)
        assert (tmp_path / "issued.json").exists(), "fake worker not issued"
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=15)
        assert (tmp_path / "receipt.json").exists(), "SIGTERM bypassed cleanup receipt"
        receipt = json.loads((tmp_path / "receipt.json").read_text())
        assert (
            not receipt["complete"]
            and receipt["cleanup_verified"]
            and receipt["key_cleanup_verified"]
        )
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)


def test_failure_export_preserves_original_failure_receipt(tmp_path):
    callback = feature("evidence", "safe_export")
    root = tmp_path / "raw"
    root.mkdir()
    failure = {"complete": False, "error": {"message": "first original failure"}}
    (root / "case-result.json").write_text(json.dumps(failure))
    (root / "oversize.log").write_bytes(b"x" * (2 * 2**20 + 1))
    archive = tmp_path / "failure.tar.gz"
    receipt = callback(root, archive)
    import tarfile

    with tarfile.open(archive) as tar:
        assert json.load(tar.extractfile("case-result.json")) == failure
        loss = json.load(tar.extractfile("collection-failure.json"))
        assert loss["complete"] is False and loss["dropped_bytes"] > 0
    assert receipt["complete"] is False and archive.stat().st_size <= 20 * 2**20


def test_native_specs_resolve_all_four_maintained_ids():
    import yaml

    callback = feature("native", "select_specs")
    packs = yaml.safe_load(Path("eval/quality/workflows.yaml").read_text())["repositories"]
    specs = callback(packs)
    assert [(s["id"], s["language"]) for s in specs] == [
        ("ocaml", "ocaml"),
        ("deno", "rust"),
        ("perl5", "perl"),
        ("crystal", "crystal"),
    ]
    assert not any(s.get("queries") for s in specs)


def test_soak_uses_full_remaining_case_budget():
    callback = feature("workload", "remaining_soak")
    assert callback(3300, 200) == 3040 and callback(90, 50) == 0


def test_vm_key_bootstrap_preserves_existing_authorization(tmp_path):
    import stat
    import subprocess

    m = module("campaign")
    callback = feature("campaign", "bootstrap_user_data")
    key = tmp_path / "ephemeral"
    public = m.make_key(key)
    authorized = tmp_path / "ssh" / "authorized_keys"
    authorized.parent.mkdir()
    authorized.write_text("existing-line")
    userdata = callback(public, authorized_keys=authorized)
    assert userdata.startswith("#cloud-config\n")
    data = json.loads(userdata.split("\n", 1)[1])
    assert data["ssh_pwauth"] is False
    for command in data["runcmd"]:
        subprocess.run(command, check=True, timeout=5)
    assert authorized.read_text() == "existing-line\n" + public + "\n"
    assert stat.S_IMODE(authorized.stat().st_mode) == 0o600
    assert stat.S_IMODE(authorized.parent.stat().st_mode) == 0o700


@pytest.mark.parametrize("public", ["invalid-key", "ssh-ed25519 value\nsecond-line"])
def test_vm_key_bootstrap_rejects_invalid_public_input(public):
    callback = feature("campaign", "bootstrap_user_data")
    with pytest.raises(ValueError):
        callback(public)


def test_controller_uses_readonly_registered_bootstrap_metadata(tmp_path, monkeypatch):
    m = module("campaign")

    class ReadOnlyKeys(FakeAPI):
        def __init__(self):
            super().__init__()
            self.keys = [{"id": 77, "name": "existing-bootstrap"}]
            self.body = None

        def request(self, method, path, data=None):
            if path.startswith("/account/keys") and method != "GET":
                import urllib.error

                raise urllib.error.HTTPError(path, 403, "read-only keys", {}, None)
            if path == "/droplets" and method == "POST":
                self.body = data
            return super().request(method, path, data)

    api = ReadOnlyKeys()
    monkeypatch.setattr(m, "preflight", lambda *args: {"hourly_usd": 0.16667})
    monkeypatch.setattr(m, "make_key", lambda path: "ssh-ed25519 fixture")
    result = m.run(
        reservation(), tmp_path, api=api, execute=lambda *args: {"complete": True}, month="2026-10"
    )
    assert result["complete"] and result["cleanup_verified"] and result["key_cleanup_verified"]
    assert api.keys == [{"id": 77, "name": "existing-bootstrap"}]
    assert api.body["ssh_keys"] == [77] and "ssh-ed25519 fixture" in api.body["user_data"]
