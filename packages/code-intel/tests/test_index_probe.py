"""Instrumentation must remain bounded and preserve indexing, ranking and rollback."""

import json
import os
import threading
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from attocode_intel._internal.integrations.context import index_probe as probe
from attocode_intel._internal.integrations.context.semantic_search import SemanticSearchManager


def test_disabled_probe_never_reads_clocks_or_wraps_hot_calls(monkeypatch):
    def forbidden():
        raise AssertionError("disabled clock")

    monkeypatch.setattr(probe, "time", SimpleNamespace(monotonic=forbidden, thread_time=forbidden))

    def f(x):
        return x + 1

    assert probe.instrument("body.tokenize", f) is f
    with probe.measure("body.files"):
        probe.count("body.files_started")
        assert probe.measured_call("body.sql", f, 2) == 3


def test_inclusive_clocks_exception_and_live_snapshot_semantics(monkeypatch):
    clocks = [10.0, 2.0]
    monkeypatch.setattr(
        probe, "time", SimpleNamespace(monotonic=lambda: clocks[0], thread_time=lambda: clocks[1])
    )
    p = probe.IndexProbe()
    with pytest.raises(RuntimeError), probe.activate(p), probe.measure("body.files"):
        clocks[:] = [12.0, 3.0]
        with probe.measure("body.sql"):
            clocks[:] = [15.0, 4.0]
            active = p.snapshot()["active"]
            assert active == [
                {"phase": "body.files", "wall_seconds": 5.0},
                {"phase": "body.sql", "wall_seconds": 3.0},
            ]
        probe.count("body.files_completed")
        clocks[:] = [20.0, 5.0]
        raise RuntimeError("injected")
    s = p.snapshot()
    assert not s["active"]
    assert s["phases"]["body.files"] == {
        "calls": 1,
        "wall_seconds": 10.0,
        "thread_cpu_seconds": 3.0,
    }
    assert s["phases"]["body.sql"] == {"calls": 1, "wall_seconds": 3.0, "thread_cpu_seconds": 1.0}
    assert s["counts"] == {"body.files_completed": 1}


def test_probe_retention_is_fixed_and_rejects_dynamic_labels():
    p = probe.IndexProbe()
    with probe.activate(p):
        for _ in range(300):
            with probe.measure("body.document", "x" * 10000):
                probe.count("body.files_started")
    s = p.snapshot()
    assert len(s["slow_files"]) == 8 and all(len(r["file"]) == 160 for r in s["slow_files"])
    assert len(s["phases"]) == 1 and len(json.dumps(s)) < 4000
    with pytest.raises(ValueError), p.measure("arbitrary file as phase"):
        pass
    with pytest.raises(ValueError):
        p.count("arbitrary key")
    with pytest.raises(ValueError):
        p.sample_call("arbitrary key")


def rows(manager):
    conn = manager._open_body_db()
    try:
        return {
            t: conn.execute(f"SELECT rowid,* FROM {t} ORDER BY rowid").fetchall()
            for t in ("kw_files", "kw_docs", "body_files", "body_fts", "body_file_fts")
        }
    finally:
        conn.close()


def fixture(root):
    root.mkdir()
    for i in range(12):
        p = root / f"helper{i}.py"
        p.write_text(
            f'class Catalog{i}:\n    def find(self, key):\n        return "NeedleValue" + key\n'
        )
        os.utime(p, ns=(1700000000000000000, 1700000000000000000))


def test_opt_in_warmup_has_exact_cache_fts_and_ranking_parity(tmp_path, monkeypatch):
    monkeypatch.delenv("ATTOCODE_INTEL_INDEX_PROBE", raising=False)
    fixture(tmp_path / "plain")
    fixture(tmp_path / "measured")
    plain = SemanticSearchManager(str(tmp_path / "plain"))
    measured = SemanticSearchManager(str(tmp_path / "measured"), index_probe=probe.IndexProbe())
    try:
        plain._warm_candidate_indexes()
        measured._warm_candidate_indexes()
        assert plain.index_probe is None and plain._body_index_built and measured._body_index_built
        assert rows(plain) == rows(measured)
        assert [asdict(d) for d in plain._kw_docs] == [asdict(d) for d in measured._kw_docs]
        for query in ("NeedleValue", "find catalog", "missing"):
            assert plain._keyword_search(query, 24, "") == measured._keyword_search(query, 24, "")
        s = measured.index_probe.snapshot()
        assert s["counts"]["body.files_completed"] == 12
        assert s["counts"]["keyword.files_completed"] == 12
        assert s["counts"]["body.commits"] == s["counts"]["keyword.commits"] == 1
        assert s["sampling"]["observed_calls"]["keyword.serialize"] > 12
        assert s["phases"]["keyword.serialize"]["calls"] < 12
        assert {"body.sql", "body.tokenize", "keyword.frequencies", "keyword.discovery"} <= s[
            "phases"
        ].keys()
        assert len(s["slow_files"]) == 8 and not s["active"]
        previous = measured.index_probe
        measured._warm_candidate_indexes()
        assert measured.index_probe is not previous
        assert measured.index_probe.snapshot()["counts"] == {}
    finally:
        plain.close()
        measured.close()


def test_partial_snapshot_survives_cancel_without_claiming_commit(tmp_path, monkeypatch):
    fixture(tmp_path / "project")
    monkeypatch.setenv("ATTOCODE_INTEL_INDEX_PROBE", "1")
    m = SemanticSearchManager(str(tmp_path / "project"))
    entered, release = threading.Event(), threading.Event()
    original = SemanticSearchManager._body_document

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(SemanticSearchManager, "_body_document", staticmethod(blocked))
    try:
        m.warm()
        assert entered.wait(5)
        s = m.index_probe.snapshot()
        assert s["counts"]["body.files_started"] == 1
        assert "body.commits" not in s["counts"]
        assert any(a["phase"] == "body.document" for a in s["active"])
        assert all("thread_cpu_seconds" not in a for a in s["active"])
        m._closed = True
        release.set()
        m._body_thread.join(5)
        assert not m._body_thread.is_alive() and not m._body_index_built
        assert not m.index_probe.snapshot()["active"]
        assert "body.commits" not in m.index_probe.snapshot()["counts"]
        assert rows(m)["body_files"] == []
    finally:
        release.set()
        m.close()


@pytest.mark.parametrize("mode", ["concurrent", "prehydrated"])
def test_probe_arm_waits_for_structural_hydration_only_when_selected(tmp_path, mode):
    from attocode_intel.request_context import RequestContext

    from eval.quality.index_probe import ProbeGateway

    calls = []
    ast = SimpleNamespace(
        _hydration_thread=SimpleNamespace(
            join=lambda timeout: calls.append("join"), is_alive=lambda: False
        ),
        hydration_snapshot=lambda: {"phase": "ready"},
    )
    service = SimpleNamespace(
        _get_ast_service=lambda: ast,
        _get_semantic_search=lambda: SimpleNamespace(warm=lambda: calls.append("warm")),
    )
    context = RequestContext(str(tmp_path), str(tmp_path), stores={"service": service})
    gateway = ProbeGateway(tmp_path, mode)
    gateway._warm_search(context)
    gateway._warm_search(context)
    assert calls == (["join", "warm", "warm"] if mode == "prehydrated" else ["warm", "warm"])


def test_probe_pack_requires_explicit_worker_before_workspace_creation(tmp_path, monkeypatch):
    from eval.quality.index_probe import run

    monkeypatch.delenv("QUALITY_ALLOW_DOWNLOADS", raising=False)
    root = tmp_path / "not-created"
    with pytest.raises(ValueError, match="Linux worker"):
        run(root, "cockroach")
    assert not root.exists()


def test_hot_calls_count_all_but_time_only_fixed_samples(monkeypatch):
    reads = []
    def clock():
        reads.append(1)
        return float(len(reads))
    monkeypatch.setattr(probe, "time", SimpleNamespace(monotonic=clock, thread_time=clock))
    p = probe.IndexProbe()
    with probe.activate(p):
        f = probe.instrument("body.tokenize", lambda value: value + 1)
        assert [f(i) for i in range(130)] == list(range(1, 131))
        # Rewrapping for another file must not restart sampling/counts.
        f = probe.instrument("body.tokenize", lambda value: value + 1)
        assert f(130) == 131
    assert len(reads) == 3 * 4  # calls 1, 65, 129; two clocks at entry/exit
    s = p.snapshot()
    assert s["schema"] == 2 and s["sampling"]["observed_calls"] == {"body.tokenize": 131}
    assert s["phases"]["body.tokenize"]["calls"] == 3
    assert "no extrapolation" in s["sampling"]["timing"]
    assert not s["active"]


def test_sampled_and_unsampled_exceptions_keep_their_behavior():
    p = probe.IndexProbe()
    def fail():
        raise LookupError("unchanged")
    with probe.activate(p):
        f = probe.instrument("body.tokenize", fail)
        for _ in range(2):
            with pytest.raises(LookupError, match="unchanged"):
                f()
    s = p.snapshot()
    assert s["sampling"]["observed_calls"]["body.tokenize"] == 2
    assert s["phases"]["body.tokenize"]["calls"] == 1
    assert not s["active"]
