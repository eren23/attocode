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
    format_sweep_comparison,
)


def test_to_dict_roundtrips_provenance():
    rr = RepoResult(repo="gh-cli", total_queries=5)
    rr.avg_mrr = 0.4123
    rr.model_name = "local:bge-base-en-v1.5"
    rr.body_budget = "400"
    rr.embedded_chunks = 1234
    rr.index_ready = True
    d = rr.to_dict()
    assert d["repo"] == "gh-cli"
    assert d["avg_mrr"] == 0.4123
    assert d["model_name"] == "local:bge-base-en-v1.5"
    assert d["body_budget"] == "400"
    assert d["embedded_chunks"] == 1234
    assert d["index_ready"] is True
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
