import pytest

from eval.graded_score import score

PACK = {"repos": {"r": [{"query": "q", "relevant_files": {"good.py": 3, "ok.py": 1}}]}}


def _pool(files):
    return {"repos": [{"repo": "r", "queries": [
        {"query": "q", "intent": "source", "arms": {"prior": {"files": files}}}]}]}


def _trial(ranked, pool_sha256="x", rows=1):
    return {"pool_sha256": pool_sha256, "summary": {"median_inference_ms": 1, "p95_inference_ms": 1, "failures": 0},
            "cases": [{"repo": "r", "query": "q", "ranked_files": ranked}] * rows}


def test_unjudged_files_block_every_metric_and_are_listed_arm_blind():
    report = score(PACK, _pool(["good.py", "ok.py"]), {"model": _trial(["new.py", "good.py"])}, "x")
    assert report["unjudged"] == {"r::q": ["new.py"]}
    assert all(report["arms"]["model"][m] is None for m in ("gndcg5", "mrr5_primary", "recall5"))
    assert report["arms"]["baseline"]["mrr5_primary"]["mean"] == 1.0
    assert report["known_primary_capture"]["primary@5"] == 1.0


def test_trials_must_match_the_pool_and_cover_it_once():
    pool = _pool(["good.py", "ok.py"])
    with pytest.raises(ValueError, match="another pool"):
        score(PACK, pool, {"model": _trial(["good.py"], pool_sha256="y")}, "x")
    assert score(PACK, pool, {"model": _trial(["good.py"], "y")}, "x", frozenset({"model"}))["arms"]["model"]
    for rows in (0, 2):
        with pytest.raises(ValueError, match="exactly once"):
            score(PACK, pool, {"model": _trial(["good.py"], rows=rows)}, "x")


def test_binary_packs_and_zero_grades_score():
    pack = {"repos": {"r": [{"query": "q", "relevant_files": {"good.py": 2, "bad.py": 0}}]}}
    report = score(pack, _pool(["bad.py", "good.py"]), {})
    assert report["arms"]["baseline"]["gndcg5"]["mean"] < 1.0
    assert report["arms"]["baseline"]["mrr5_primary"]["mean"] == 0.5
    binary = {"repos": {"r": [{"query": "q", "relevant_files": ["good.py"]}]}}
    assert score(binary, _pool(["good.py"]), {})["arms"]["baseline"]["recall5"]["mean"] == 1.0
