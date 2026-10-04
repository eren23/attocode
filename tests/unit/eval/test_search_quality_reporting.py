"""Pure-function tests for search-quality reporting helpers (no I/O, no search)."""
from __future__ import annotations

import sys
from pathlib import Path

# eval/ is a top-level package alongside src; ensure repo root importable.
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from eval.search_quality import (  # noqa: E402
    RepoResult,
    _overall_from_results,
    evaluate_repo,
    format_sweep_comparison,
    parse_search_results,
)


def test_to_dict_roundtrips_provenance():
    rr = RepoResult(repo="gh-cli", total_queries=5)
    rr.avg_mrr = 0.4123
    rr.model_name = "local:bge-base-en-v1.5"
    rr.body_budget = "400"
    rr.embedded_chunks = 1234
    rr.index_ready = True
    rr.search_cold_start_ms = 17.5
    d = rr.to_dict()
    assert d["repo"] == "gh-cli"
    assert d["avg_mrr"] == 0.4123
    assert d["model_name"] == "local:bge-base-en-v1.5"
    assert d["body_budget"] == "400"
    assert d["embedded_chunks"] == 1234
    assert d["index_ready"] is True
    assert d["search_cold_start_ms"] == 17.5
    assert d["error"] == ""


def test_overall_is_query_weighted_and_skips_errored():
    a = RepoResult(repo="a", total_queries=10)
    a.avg_mrr, a.avg_ndcg = 0.6, 0.4
    b = RepoResult(repo="b", total_queries=5)
    b.avg_mrr, b.avg_ndcg = 0.3, 0.2
    err = RepoResult(repo="c", total_queries=5)
    err.avg_mrr = 0.99  # should be excluded
    err.error = "no_embeddings_built"

    ov = _overall_from_results([a, b, err])
    # query-weighted over a+b only: (0.6*10 + 0.3*5) / 15 = 0.5
    assert ov["total_queries"] == 15
    assert abs(ov["avg_mrr"] - 0.5) < 1e-9
    assert abs(ov["avg_ndcg"] - (0.4 * 10 + 0.2 * 5) / 15) < 1e-9


def test_overall_empty_is_zero():
    ov = _overall_from_results([])
    assert ov == {"avg_mrr": 0.0, "avg_ndcg": 0.0, "total_queries": 0}


def test_sweep_comparison_marks_best_mrr():
    runs = [
        {"label": "200", "overall": {"avg_mrr": 0.50, "avg_ndcg": 0.30, "total_queries": 15}},
        {"label": "400", "overall": {"avg_mrr": 0.58, "avg_ndcg": 0.34, "total_queries": 15}},
        {"label": "800", "overall": {"avg_mrr": 0.55, "avg_ndcg": 0.33, "total_queries": 15}},
    ]
    out = format_sweep_comparison(runs)
    assert "Sweep Comparison" in out
    # winner row (400) carries the star, the others do not
    star_lines = [ln for ln in out.splitlines() if "⭐" in ln]
    assert len(star_lines) == 1
    assert "400" in star_lines[0]
    assert "0.580" in star_lines[0]


def test_recall_at_20_requests_twenty_results(monkeypatch):
    import eval.search_quality as search_quality

    class FakeManager:
        provider_name = "fixture"

        def is_index_ready(self):
            return True

    class FakeService:
        calls: list[int] = []

        def __init__(self, repo_path):
            self.repo_path = repo_path

        def _get_semantic_search(self):
            return FakeManager()

        def semantic_search(self, query, top_k=10):
            self.calls.append(top_k)
            return "\n".join(
                f"{rank}. [file] file{rank}.py — symbol{rank} (score: 1.000)"
                for rank in range(1, top_k + 1)
            )

    monkeypatch.setattr(search_quality, "CodeIntelService", FakeService)
    monkeypatch.setattr(search_quality, "load_ground_truth", lambda repo: [
        {"query": "query", "relevant_files": ["file15.py"]}
    ])
    monkeypatch.setitem(search_quality.REPO_CONFIGS, "fixture", "/unused")
    result = evaluate_repo("fixture")
    assert FakeService.calls == [20, 20]  # discarded readiness probe, then timed query
    assert len(result.query_results[0].retrieved_files) == 20
    assert result.query_results[0].recall_at_k == 1.0


def test_cold_index_is_waited_for_and_measured_separately(monkeypatch):
    import time

    import eval.search_quality as search_quality

    class FakeManager:
        provider_name = "fixture"
        ready = False

        def is_index_ready(self):
            return False

        def candidate_diagnostics(self):
            return {"status": "ready" if self.ready else "warming"}

        def wait_for_body_index(self, timeout):
            time.sleep(0.01)
            self.ready = True
            return True

    class FakeService:
        calls = 0

        def __init__(self, repo_path):
            self.manager = FakeManager()

        def _get_semantic_search(self):
            return self.manager

        def semantic_search(self, query, top_k=10):
            FakeService.calls += 1
            if not self.manager.ready:
                return "Search index warming; retry shortly. Missing results do not prove absence."
            return "1. [function] handler.py:1-3 — handler (score: 1.000)"

    monkeypatch.setattr(search_quality, "CodeIntelService", FakeService)
    monkeypatch.setattr(search_quality, "load_ground_truth", lambda _repo: [
        {"query": "handler", "relevant_files": ["handler.py"]},
    ])
    monkeypatch.setitem(search_quality.REPO_CONFIGS, "fixture", "/unused")
    result = evaluate_repo("fixture")
    assert result.error == ""
    assert result.avg_mrr == 1.0
    assert result.search_cold_start_ms >= 10
    assert result.total_time_ms == result.query_results[0].search_time_ms
    assert FakeService.calls == 3  # cold probe, ready probe, timed query


def test_index_timeout_is_not_scored_as_zero_relevance(monkeypatch):
    import eval.search_quality as search_quality

    class FakeManager:
        provider_name = "fixture"

        def is_index_ready(self):
            return False

        def candidate_diagnostics(self):
            return {"status": "warming"}

    class FakeService:
        def __init__(self, repo_path):
            self.manager = FakeManager()

        def _get_semantic_search(self):
            return self.manager

        def semantic_search(self, query, top_k=10):
            return "Search index warming; retry shortly. Missing results do not prove absence."

    monkeypatch.setattr(search_quality, "CodeIntelService", FakeService)
    monkeypatch.setattr(search_quality, "load_ground_truth", lambda _repo: [
        {"query": "handler", "relevant_files": ["handler.py"]},
    ])
    monkeypatch.setitem(search_quality.REPO_CONFIGS, "fixture", "/unused")
    result = evaluate_repo("fixture", search_ready_timeout_seconds=0.01)
    assert result.error.startswith("search_index_not_ready:")
    assert result.query_results == []


def test_evaluators_strip_source_spans_without_damaging_windows_paths():
    from eval.competitive.__main__ import parse_search_results as parse_competitive

    output = (
        "  1. [function] src/bootstrap.py:3-12 — bootstrap (score: 1.000)\n"
        "  2. [file] C:\\src\\helper.py:10-14 — helper (score: 0.800)"
    )
    expected = ["src/bootstrap.py", "C:\\src\\helper.py"]
    assert parse_search_results(output) == expected
    assert parse_competitive(output) == expected
