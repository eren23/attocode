"""Bounded native fixture evidence must preserve parsing and expose capture loss."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from attocode_intel import __file__ as package_file
from attocode_intel._internal.integrations.context import ts_parser

from eval.quality import corpus

SOURCE = b"let value = 1\n"


def capture_type():
    spec = importlib.util.find_spec("eval.quality.native_capture")
    assert spec is not None, "OCaml capture: bounded native sink is absent"
    from eval.quality.native_capture import NativeCapture
    return NativeCapture


def rows(path):
    return [json.loads(line) for line in path.read_bytes().splitlines()]


class Native:
    """Opaque native boundary double; the bounded product wrapper stays real."""
    def __init__(self, outcome="tree", path=None):
        self.outcome, self.path = outcome, path
        self.timeout_micros = 0
        self.calls = self.resets = 0
        self.tree = object()
        self.raw_before_reset = []

    def parse(self, source):
        assert source == SOURCE and self.timeout_micros == 100_000
        self.calls += 1
        if self.outcome in {"ValueError", "RuntimeError"}:
            raise {"ValueError": ValueError, "RuntimeError": RuntimeError}[self.outcome]("native trigger")
        return self.tree if self.outcome == "tree" else None

    def reset(self):
        self.resets += 1
        available = self.path is not None and self.path.is_file()
        self.raw_before_reset.append(available and any(
            r.get("kind") == "native" and r["native"].get("stage") == "parse"
            and r["native"].get("outcome") == self.outcome
            for r in rows(self.path)
        ))


@pytest.fixture
def fixture_case(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    (root / "source.ml").write_bytes(SOURCE)
    spec = {"id": "ocaml", "repo": "owner/fixture", "commit": "a" * 40,
            "language": "ocaml", "file": "source.ml", "source_sha256": hashlib.sha256(SOURCE).hexdigest()}
    path = tmp_path / "captures/ocaml/native-ocaml.jsonl"
    monkeypatch.setenv("ATTOCODE_EXPERIMENT_ENGINE", str(Path(package_file).parent))
    monkeypatch.delenv("QUALITY_GRAMMAR_CACHE", raising=False)
    return root, spec, path


def parse(native):
    proxy = ts_parser._get_parser("ocaml")
    if native.outcome == "RuntimeError":
        with pytest.raises(RuntimeError, match="^native trigger$"):
            ts_parser.bounded_parse(proxy, SOURCE)
    else:
        result = ts_parser.bounded_parse(proxy, SOURCE)
        assert result is (native.tree if native.outcome == "tree" else None)


def worker(fixture_case, monkeypatch, outcome, *, enabled=True, language="ocaml", wrong_engine=False):
    root, spec, path = fixture_case
    spec = {**spec, "language": language}
    native = Native(outcome, path)
    monkeypatch.setattr(ts_parser, "_get_parser", lambda language: native)
    if enabled:
        monkeypatch.setenv("ATTOCODE_CORPUS_EVIDENCE", str(path.parents[1]))
    else:
        monkeypatch.delenv("ATTOCODE_CORPUS_EVIDENCE", raising=False)
    if wrong_engine:
        monkeypatch.setenv("ATTOCODE_EXPERIMENT_ENGINE", str(root / "wrong-engine"))
    spec_path, output = root.parent / "spec.json", root.parent / "worker.json"
    spec_path.write_text(json.dumps(spec))

    async def evaluate(*args, **kwargs):
        proxy = ts_parser._get_parser("ocaml")
        value = ts_parser.bounded_parse(proxy, SOURCE)
        assert value is (native.tree if outcome == "tree" else None)
        return []

    monkeypatch.setattr(corpus, "evaluate", evaluate)
    monkeypatch.setattr(sys, "argv", ["corpus", "--worker", str(root), "--spec", str(spec_path), "--output", str(output)])
    if wrong_engine:
        with pytest.raises(ValueError, match="engine_origin"):
            corpus.main()
    elif outcome == "RuntimeError":
        with pytest.raises(RuntimeError, match="^native trigger$"):
            corpus.main()
    else:
        assert corpus.main() == 0
    return native, output, spec, path


@pytest.mark.parametrize("outcome", ["tree", "no_tree", "ValueError", "RuntimeError"])
def test_routine_worker_retains_native_outcome_before_fallback_reset(fixture_case, monkeypatch, outcome):
    native, output, spec, path = worker(fixture_case, monkeypatch, outcome)
    assert path.is_file(), "OCaml capture: routine worker lost raw native evidence"
    assert native.raw_before_reset == [True], "OCaml capture: raw result was not durable before reset"
    assert native.calls == native.resets == 1 and native.timeout_micros == 100_000
    data = rows(path)
    record = next(r["native"] for r in data if r.get("kind") == "native" and r["native"]["stage"] == "parse")
    assert record["source_sha256"] == spec["source_sha256"]
    assert record["parser_id"] == id(native) and record["thread_id"] == threading.get_ident()
    assert record["wall_ns"] >= 0 and record["thread_cpu_ns"] >= 0 and record["limit_micros"] == 100_000
    assert record["error"] == ({"type": outcome, "message": "native trigger"} if outcome in {"ValueError", "RuntimeError"} else None)
    assert data[-1]["kind"] == "trace_end" and data[-1]["status"] == "complete"
    result = json.loads(output.read_bytes())
    assert result["native_capture"]["parse_calls"] == 1
    if outcome == "RuntimeError":
        assert result["worker_error"] == {"type": "RuntimeError", "message": "native trigger"}


@pytest.mark.parametrize("mode", ["off", "other-language"])
def test_capture_off_or_unrelated_worker_preserves_existing_path(fixture_case, monkeypatch, mode):
    native, _output, _spec, path = worker(fixture_case, monkeypatch, "ValueError", enabled=mode != "off",
                                         language="python" if mode == "other-language" else "ocaml")
    assert native.calls == native.resets == 1 and not path.exists()


def test_worker_engine_guard_stops_before_capture_or_parse(fixture_case, monkeypatch):
    native, _output, _spec, path = worker(fixture_case, monkeypatch, "tree", wrong_engine=True)
    assert native.calls == 0 and not path.exists()


@pytest.mark.parametrize("fault,outcome", [
    ("write", "tree"), ("flush", "tree"), ("close", "tree"),
    ("write", "ValueError"), ("flush", "ValueError"), ("close", "ValueError"),
    ("write", "RuntimeError"), ("flush", "RuntimeError"), ("close", "RuntimeError"),
], ids=["tree-write", "tree-flush", "tree-close", "value-write", "value-flush", "value-close",
        "runtime-write", "runtime-flush", "runtime-close"])
def test_sink_fault_never_replaces_native_outcome(fixture_case, monkeypatch, fault, outcome):
    root, spec, path = fixture_case
    native = Native(outcome)
    monkeypatch.setattr(ts_parser, "_get_parser", lambda language: native)
    trace = capture_type()(path, root, spec)
    original = None

    class Fault:
        def __init__(self, stream):
            self.stream = stream
        def __getattr__(self, name):
            target = getattr(self.stream, name)
            if name == fault:
                def fail(*args, **kwargs):
                    raise OSError("capture sink fault")
                return fail
            return target

    try:
        with trace.capture():
            original = trace._file
            trace._file = Fault(original)
            parse(native)
    finally:
        if original is not None:
            original.close()
    assert native.calls == native.resets == 1
    assert trace.summary()["capture_errors"] > 0
    with pytest.raises(ValueError):
        trace.require_complete()
    from eval.quality.native_capture import read_capture
    with pytest.raises(ValueError):
        read_capture(path, root, spec, trace.summary())


@pytest.mark.parametrize("budget", [8192, 16384])
def test_bounded_tail_keeps_failure_before_reset_and_exposes_loss(fixture_case, monkeypatch, budget):
    root, spec, path = fixture_case
    native = Native("tree", path)
    monkeypatch.setattr(ts_parser, "_get_parser", lambda language: native)
    trace = capture_type()(path, root, spec, max_bytes=budget)
    with trace.capture():
        for _ in range(80):
            parse(native)
        native.outcome = "ValueError"
        parse(native)
        assert native.raw_before_reset[-1] is True
    assert native.calls == native.resets == 81 and path.stat().st_size <= budget
    assert rows(path)[-1]["dropped_events"] > 0
    with pytest.raises(ValueError):
        trace.require_complete()


def test_oversized_event_is_explicit_and_does_not_change_fallback(fixture_case, monkeypatch):
    root, spec, path = fixture_case
    class LargeError(Native):
        def parse(self, source):
            self.calls += 1
            raise ValueError("\u2603" * 2000)
    native = LargeError("ValueError")
    monkeypatch.setattr(ts_parser, "_get_parser", lambda language: native)
    trace = capture_type()(path, root, spec, event_bytes=2048)
    with trace.capture():
        assert ts_parser.bounded_parse(ts_parser._get_parser("ocaml"), SOURCE) is None
    assert native.calls == native.resets == 1 and trace.summary()["oversized_events"] > 0
    with pytest.raises(ValueError):
        trace.require_complete()


def test_abrupt_worker_exit_leaves_raw_native_error_without_footer(fixture_case):
    root, spec, path = fixture_case
    capture_type()
    code = """import json,os,sys
from pathlib import Path
from eval.quality.native_capture import NativeCapture
from attocode_intel._internal.integrations.context import ts_parser
class Native:
 timeout_micros=0
 def parse(self,source):raise ValueError('abrupt native trigger')
 def reset(self):os._exit(23)
ts_parser._get_parser=lambda language:Native()
with NativeCapture(Path(sys.argv[1]),Path(sys.argv[2]),json.loads(sys.argv[3])).capture():
 ts_parser.bounded_parse(ts_parser._get_parser('ocaml'),b'let value = 1\\n')
"""
    result = subprocess.run([sys.executable, "-c", code, str(path), str(root), json.dumps(spec)], check=False, timeout=20)
    assert result.returncode == 23
    data = rows(path)
    assert data[0]["kind"] == "trace_start" and data[-1]["kind"] != "trace_end"
    assert any(r.get("native", {}).get("error", {}).get("message") == "abrupt native trigger" for r in data if r.get("native", {}).get("error"))
    from eval.quality.native_capture import read_capture
    with pytest.raises(ValueError):
        read_capture(path, root, spec, {"status": "incomplete"})


def test_existing_capture_is_never_overwritten(fixture_case):
    root, spec, path = fixture_case
    path.parent.mkdir(parents=True)
    path.write_bytes(b"earlier attempt\n")
    with pytest.raises(FileExistsError), capture_type()(path, root, spec).capture():
        raise AssertionError("existing attempt was overwritten")
    assert path.read_bytes() == b"earlier attempt\n"


@pytest.mark.parametrize("fail_body", [False, True])
def test_parser_hook_restored_on_every_exit(fixture_case, monkeypatch, fail_body):
    root, spec, path = fixture_case
    native = Native()
    def original(language):
        return native
    monkeypatch.setattr(ts_parser, "_get_parser", original)
    trace = capture_type()(path, root, spec)
    try:
        with trace.capture():
            parse(native)
            if fail_body:
                raise RuntimeError("operator body failure")
    except RuntimeError as error:
        assert fail_body and str(error) == "operator body failure"
    assert ts_parser._get_parser is original
    trace.require_complete()


def test_disabled_capture_has_no_hook_or_file(fixture_case, monkeypatch):
    root, spec, path = fixture_case
    native = Native()
    def original(language):
        return native
    monkeypatch.setattr(ts_parser, "_get_parser", original)
    trace = capture_type()(None, root, spec)
    with trace.capture():
        assert ts_parser._get_parser is original
        parse(native)
    assert not path.exists() and trace.summary()["status"] == "disabled"


def test_other_language_keeps_its_original_parser(fixture_case, monkeypatch):
    root, spec, path = fixture_case
    native = Native()
    monkeypatch.setattr(ts_parser, "_get_parser", lambda language: native)
    trace = capture_type()(path, root, spec)
    with trace.capture():
        assert ts_parser._get_parser("python") is native
        assert ts_parser.bounded_parse(native, SOURCE) is native.tree
    assert trace.require_complete()["parse_calls"] == 0


def test_concurrent_native_records_remain_ordered_and_thread_bound(fixture_case, monkeypatch):
    root, spec, path = fixture_case
    local, natives, lock, barrier = threading.local(), [], threading.Lock(), threading.Barrier(4)
    def lookup(language):
        if not hasattr(local, "parser"):
            local.parser = Native("ValueError")
            with lock:
                natives.append(local.parser)
        return local.parser
    monkeypatch.setattr(ts_parser, "_get_parser", lookup)
    def work():
        barrier.wait(timeout=10)
        for _ in range(5):
            assert ts_parser.bounded_parse(ts_parser._get_parser("ocaml"), SOURCE) is None
    trace = capture_type()(path, root, spec)
    with trace.capture(), ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: work(), range(4)))
    assert len(natives) == 4 and all(n.calls == n.resets == 5 for n in natives)
    assert trace.require_complete()["parse_calls"] == 20
    data = rows(path)
    assert [r["index"] for r in data] == list(range(1, len(data) + 1))
    parsed = [r["native"] for r in data if r.get("native", {}).get("stage") == "parse"]
    assert len({r["thread_id"] for r in parsed}) == 4


def test_nested_active_capture_is_rejected_without_replacing_outer_hook(fixture_case, monkeypatch):
    root, spec, path = fixture_case
    native = Native()
    monkeypatch.setattr(ts_parser, "_get_parser", lambda language: native)
    cls = capture_type()
    with cls(path, root, spec).capture():
        original = ts_parser._get_parser
        with pytest.raises(ValueError), cls(path.with_name("second.jsonl"), root, spec).capture():
            raise AssertionError("nested capture replaced outer")
        assert ts_parser._get_parser is original
        parse(native)


@pytest.mark.parametrize("outcome", ["no_tree", "ValueError"])
def test_generic_ocaml_native_failure_is_retained_before_fallback(fixture_case, monkeypatch, outcome):
    import tree_sitter

    root, spec, path = fixture_case
    native = Native(outcome, path)
    monkeypatch.setattr(ts_parser._generic_extractor, "_get_language_obj", lambda *a, **k: object())
    monkeypatch.setattr(tree_sitter, "Parser", lambda language: native)
    trace = capture_type()(path, root, spec)
    with trace.capture():
        for _ in range(2):
            assert ts_parser._generic_extractor.parse("source.ml", SOURCE.decode(), "tree_sitter_ocaml", "ocaml") is None
    assert native.raw_before_reset == [True, True], "OCaml capture: generic parser lost raw failures before fallback"
    assert native.calls == native.resets == 2
    assert trace.require_complete()["parse_calls"] == 2
    parsed = [r["native"] for r in rows(path) if r.get("native", {}).get("stage") == "parse"]
    assert len({r["parser_generation"] for r in parsed}) == 2


def test_cross_thread_parser_handoff_is_observed_without_changing_outcome(fixture_case, monkeypatch):
    root, spec, path = fixture_case
    native = Native("ValueError", path)
    monkeypatch.setattr(ts_parser, "_get_parser", lambda language: native)
    trace = capture_type()(path, root, spec)
    with trace.capture(), ThreadPoolExecutor(max_workers=1) as pool:
        proxy = ts_parser._get_parser("ocaml")
        assert pool.submit(ts_parser.bounded_parse, proxy, SOURCE).result(timeout=10) is None
    error = None
    try:
        trace.require_complete()
    except Exception as caught:
        error = caught
    assert error is None, "OCaml capture: cross-thread handoff rejected otherwise lossless observation"
    assert native.calls == native.resets == 1 and native.raw_before_reset == [True]


@pytest.mark.parametrize("damage", [None, "footer", "source", "fixture", "root", "clock", "reset"])
def test_raw_native_capture_admission_checks_source_lifecycle_and_clocks(fixture_case, monkeypatch, damage):
    root, spec, path = fixture_case
    native = Native("ValueError")
    monkeypatch.setattr(ts_parser, "_get_parser", lambda language: native)
    trace = capture_type()(path, root, spec)
    with trace.capture():
        parse(native)
    from eval.quality.native_capture import read_capture
    data = rows(path)
    if damage == "footer":
        data.pop()
    elif damage == "source":
        data[0]["sources"]["eval/quality/native_capture.py"] = "0" * 64
    elif damage == "fixture":
        data[0]["fixture"]["source_sha256"] = "0" * 64
    elif damage == "root":
        data[0]["workspace"] = str(root.parent)
    elif damage == "clock":
        next(r["native"] for r in data if r.get("native", {}).get("stage") == "parse")["thread_cpu_ns"] = -1
    elif damage == "reset":
        data = [r for r in data if r.get("native", {}).get("stage") != "reset"]
        for number, row in enumerate(data, 1):
            row["index"] = number
    path.write_text("".join(json.dumps(r) + "\n" for r in data))
    if damage is None:
        result = read_capture(path, root, spec, trace.summary())
        assert result["status"] == "complete" and result["parse_calls"] == result["native_failures"] == 1
    else:
        with pytest.raises(ValueError):
            read_capture(path, root, spec, trace.summary())


@pytest.mark.parametrize("damage", [None, "missing", "footer", "source", "worker-failure"])
async def test_parent_admission_requires_complete_native_artifact(fixture_case, monkeypatch, damage):
    import os

    from eval.quality.corpus_capture import admit_worker, digest
    from eval.quality.experiment_evidence import Journal, assert_engine
    from eval.quality.fixture_identity import source_manifest

    cls = capture_type()
    root, original, _unused = fixture_case
    # A declared language pack can contain an auxiliary Python source; zero
    # OCaml calls must still have explicit, source-bound complete capture.
    (root / "source.ml").unlink()
    text = b"def helper(): return 1\nhelper()\n"
    (root / "main.py").write_bytes(text)
    spec = {**original, "file": "main.py", "source_sha256": hashlib.sha256(text).hexdigest(),
            "symbol": "helper", "anchor": "def helper(", "caller": "main.py",
            "importer": None, "test": None, "queries": []}
    evidence = root.parent / "evidence"
    path = evidence / "native-ocaml.jsonl"
    selected = Path(package_file).parent
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    fixture = Journal(evidence / "fixture", 2**20)
    ref = fixture.response({"event": "fixture_pinned", "repo": spec["repo"], "commit": spec["commit"],
                            "tree": "fixture-tree"}, source_manifest(root))
    journal = Journal(evidence / "journal", 2**20)
    journal.response({"event": "origin_start"}, {"pid": os.getpid(), "origins": assert_engine(selected)})
    journal.response({"event": "source_before"}, {"sha256": digest(source_manifest(root))})
    trace = cls(path, root, spec)
    try:
        with trace.capture():
            checks = await corpus.evaluate(root, spec, observations=[], journal=journal)
            if damage == "worker-failure":
                raise RuntimeError("worker failed after checks")
    except RuntimeError as error:
        assert damage == "worker-failure" and str(error) == "worker failed after checks"
    journal.response({"event": "source_after"}, {"sha256": digest(source_manifest(root))})
    journal.response({"event": "origin_end"}, {"pid": os.getpid(), "origins": assert_engine(selected)})
    summary = {"checks": checks, "retrieval": [], "tree": "fixture-tree", "fixture_ref": ref,
               "native_capture": trace.summary()}
    if damage == "missing":
        path.unlink()
    elif damage in {"footer", "source"}:
        data = rows(path)
        if damage == "footer":
            data.pop()
        else:
            data[0]["sources"]["eval/quality/native_capture.py"] = "0" * 64
        path.write_text("".join(json.dumps(r) + "\n" for r in data))
    if damage is None:
        assert admit_worker(root, spec, evidence, summary, selected)["native_capture"]["status"] == "complete"
    else:
        with pytest.raises(ValueError):
            admit_worker(root, spec, evidence, summary, selected)
