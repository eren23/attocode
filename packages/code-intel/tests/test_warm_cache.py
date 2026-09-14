import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def bench(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "evals"))
    import warm_cache
    return warm_cache


def test_break_even_requires_correct_results_and_survives_later_costs(bench):
    def rows(times, fail=None):
        return [{"task": str(i), "passed": i != fail, "penalized_seconds": t} for i, t in enumerate(times)]
    result = bench.cumulative_pair(rows([10, 10, 10, 10]), rows([15, 1, 20, 1]))
    assert result["sustained_crossover_task"] == 4
    assert result["cumulative"][1]["saved_seconds"] > 0
    assert result["cumulative"][2]["saved_seconds"] < 0
    failed = bench.cumulative_pair(rows([10, 10]), rows([1, 1], fail=0))
    assert failed["speedup"] is None and failed["sustained_crossover_task"] is None
    with pytest.raises(ValueError, match="aligned"):
        bench.cumulative_pair(rows([1, 2]), rows([1]))


def test_evidence_cannot_be_satisfied_by_echoed_metadata_or_falsey_types(bench):
    payload = {"metadata": {"query": "expected"}, "data": {"items": [], "value": False}}
    assert not bench.grade(payload, [{"path": ["metadata", "query"], "equals": "expected"}])["passed"]
    assert not bench.grade(payload, [{"path": ["data", "value"], "equals": 0}])["passed"]
    assert not bench.grade(payload, [{"path": ["data", "items"], "any": {"name": "expected"}}])["passed"]
    assert bench.grade(payload, [{"path": ["data", "items"], "equals": []}])["passed"]
    fuzzy = {"data": [{"name": "renamed_symbol", "score": .4}]}
    assert bench.grade(fuzzy, [{"path": ["data"], "none": {"name": "old_symbol"}}])["passed"]
    assert not bench.grade(fuzzy, [{"path": ["data"], "none": {"name": "renamed_symbol"}}])["passed"]


def test_edits_reject_wrong_preimage_and_escape(bench, tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "code.py").write_text("original")
    for path in ("../outside", "/absolute", ".attocode/cache/state"):
        with pytest.raises(ValueError):
            bench.apply_edits(root, [{"path": path, "before": None, "after": "changed"}])
    outside = tmp_path / "outside"
    outside.write_text("private")
    (root / "link").symlink_to(outside)
    with pytest.raises(ValueError):
        bench.apply_edits(root, [{"path": "link", "before": "private", "after": "changed"}])
    with pytest.raises(ValueError, match="preimage"):
        bench.apply_edits(root, [{"path": "code.py", "before": "wrong", "after": "changed"}])
    assert outside.read_text() == "private" and (root / "code.py").read_text() == "original"


def test_interrupted_sequence_is_retained_without_replacement(bench, tmp_path, monkeypatch):
    row = {"id": "sample-0-persistent", "repo": "sample", "lane": "persistent", "repeat": 0}
    monkeypatch.setattr(bench, "load", lambda _: {"repositories": [{"id": "sample"}], "schedule": [row], "study_id": "frozen"})
    monkeypatch.setattr(bench, "run_sequence", lambda *a: pytest.fail("Cannot replace a started attempt"))
    monkeypatch.setattr(bench, "report", lambda *a: None)
    (tmp_path / "runs" / row["id"]).mkdir(parents=True)
    bench.run(SimpleNamespace(study=tmp_path))
    assert json.loads((tmp_path / "runs" / row["id"] / "result.json").read_text())["status"] == "interrupted"


def test_worker_timeout_is_bounded_and_process_is_stopped(bench, tmp_path):
    (tmp_path / "warm_cache.py").write_text(
        "import json,os,sys,time\n"
        "print(json.dumps({'ready':True,'pid':os.getpid()}),flush=True)\n"
        "sys.stdin.readline()\n"
        "time.sleep(30)\n"
    )
    instance = bench.Worker(tmp_path, tmp_path, tmp_path, 1, 2)
    try:
        instance.timeout = .1
        with pytest.raises(TimeoutError, match="deadline"):
            instance.request({"operation": "blocked"})
    finally:
        instance.close(force=True)
    assert instance.process.poll() is not None and instance.errors.closed


def test_freeze_preserved_engine_and_persistent_only_lane(bench, tmp_path):
    source, engine = tmp_path / "source", tmp_path / "preserved"
    source.mkdir()
    engine.mkdir()
    (source / "code.py").write_text("original")
    (engine / "version.py").write_text("VERSION = 'preserved'\n")
    pack = tmp_path / "pack.json"
    pack.write_text(json.dumps({"repositories": [{"id": "sample", "source": str(source), "tasks": [
        {"id": "one", "operation": "symbols", "arguments": {"path": "code.py"},
         "checks": [{"path": ["data"], "equals": []}]},
        {"id": "two", "operation": "symbols", "arguments": {"path": "code.py"},
         "checks": [{"path": ["data"], "equals": []}], "restart": True, "edit_while_closed": True,
         "edits": [{"path": "code.py", "before": "original", "after": "changed"}]},
        {"id": "three", "operation": "symbols", "arguments": {"path": "code.py"},
         "checks": [{"path": ["data"], "equals": []}]},
        {"id": "four", "operation": "symbols", "arguments": {"path": "code.py"},
         "checks": [{"path": ["data"], "equals": []}]}]}]}))
    study = tmp_path / "study"
    bench.freeze(SimpleNamespace(project=tmp_path / "project", study=study, pack=pack,
                                 repetitions=1, seed=1, timeout=30, lanes=["persistent"], engine_source=engine))
    manifest = bench.load(study)
    assert [e["lane"] for e in manifest["schedule"]] == ["persistent"]
    assert (study / "engine/version.py").read_text() == "VERSION = 'preserved'\n"
    (engine / "version.py").write_text("changed after freeze")
    assert bench.load(study)["engine_sha256"] == manifest["engine_sha256"]


def test_offline_edit_happens_after_worker_closes(bench, tmp_path, monkeypatch):
    source = tmp_path / "sources/sample"
    source.mkdir(parents=True)
    (source / "code.py").write_text("old")
    observed = []

    class Worker:
        def __init__(self, study, root, directory, number, timeout):
            self.root, self.pid = root, number

        def request(self, task):
            return {"payload": {"data": (self.root / "code.py").read_text()},
                    "is_error": False, "pid": self.pid}

        def close(self, force=False):
            observed.append((self.pid, (self.root / "code.py").read_text()))

    monkeypatch.setattr(bench, "Worker", Worker)
    tasks = [{"id": "one", "operation": "read", "arguments": {}, "checks": [{"path": ["data"], "equals": "old"}]},
             {"id": "two", "operation": "read", "arguments": {}, "checks": [{"path": ["data"], "equals": "new"}],
              "restart": True, "edit_while_closed": True, "edits": [{"path": "code.py", "before": "old", "after": "new"}]}]
    entry = {"id": "sample-0-persistent", "repo": "sample", "repeat": 0, "lane": "persistent"}
    result = bench.run_sequence(tmp_path, {"timeout_seconds": 10, "study_id": "test"},
                                {"id": "sample", "tasks": tasks}, entry, tmp_path / "run")
    assert result["passed"]
    assert observed == [(1, "old"), (2, "new")]


def test_real_process_restart_preserves_cache_and_detects_unnotified_edits(bench, tmp_path):
    project = Path(__file__).resolve().parents[3]
    source = tmp_path / "input"
    source.mkdir()
    original = "def alpha():\n    return 'before'\n\n def_placeholder = 1\n".replace(" def_placeholder", "def_placeholder")
    (source / "code.py").write_text(original)
    def task(identity, symbol, **kwargs):
        return {"id": identity, "operation": "search_symbols", "arguments": {"name": symbol, "max_tokens": 2000},
                "checks": [{"path": ["data"], "any": {"name": symbol, "file_path": "code.py"}}], **kwargs}
    tasks = [task("cold", "alpha", wait_until_ready=True), task("warm", "alpha"), task("restart", "alpha", restart=True),
             task("edit", "beta", edits=[{"path": "code.py", "before": original, "after": original.replace("alpha", "beta")}]),
             {"id": "old-absent", "operation": "search_symbols", "arguments": {"name": "alpha", "max_tokens": 2000},
              "checks": [{"path": ["data"], "equals": []}]}]
    pack = tmp_path / "pack.json"
    pack.write_text(json.dumps({"repositories": [{"id": "sample", "source": str(source), "tasks": tasks}]}))
    study = tmp_path / "study"
    bench.freeze(SimpleNamespace(project=project, study=study, pack=pack, repetitions=1, seed=1, timeout=30))
    args = SimpleNamespace(study=study)
    bench.run(args)
    records = [json.loads((study / "runs" / f"sample-0-{lane}" / "result.json").read_text()) for lane in bench.LANES]
    assert all(r["passed"] for r in records)
    cold, persistent = (r["rows"] for r in records)
    assert len({r["pid"] for r in cold}) == len(tasks)
    assert persistent[0]["pid"] == persistent[1]["pid"]
    assert persistent[0]["ready_coverage"]["phase"] == "ready"
    assert persistent[0]["readiness_polls"] >= 1
    assert persistent[1]["pid"] != persistent[2]["pid"]
    assert persistent[2]["pid"] == persistent[3]["pid"] == persistent[4]["pid"]
    assert (study / "runs/sample-0-persistent/repository/.attocode/cache").is_dir()
    assert (source / "code.py").read_text() == original
    assert bench.report(args)["agent_comparison"]["native_break_even"] is None
    result_path = study / "runs/sample-0-persistent/result.json"
    saved = result_path.read_text()
    changed = json.loads(saved)
    changed["rows"][0]["seconds"] = 0
    result_path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="record drift"):
        bench.report(args)
    result_path.write_text(saved)
    (study / "sources/sample/code.py").write_text("drift")
    with pytest.raises(ValueError, match="Source drift"):
        bench.load(study)
