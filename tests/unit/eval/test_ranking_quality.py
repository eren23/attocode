"""Synthetic proof tests for judged candidate/ranking evaluation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from eval.metrics import compute_graded_ndcg  # noqa: E402
from eval.ranking_quality import (  # noqa: E402
    Judgment,
    Observation,
    compare_runs,
    evaluate_run,
    load_judgments,
    load_run,
    main,
    score_query,
)


def _fixture():
    judgments = {
        ("python", "q1"): Judgment(
            "python", "q1", {"impl": 3, "test": 2, "docs": 1, "swarm": 0}, "broad"
        ),
        ("go", "q2"): Judgment(
            "go", "q2", {"impl2": 3, "other": 0}, "exact"
        ),
        ("go", "q3"): Judgment("go", "q3", {"decoy": 0}, "no_answer"),
    }
    baseline = {
        ("python", "q1"): Observation(
            "python", "q1", ("swarm", "test", "impl", "docs"),
            ("swarm", "test", "impl"), 100.0,
        ),
        ("go", "q2"): Observation(
            "go", "q2", ("other", "impl2"), ("other",), 200.0,
        ),
        ("go", "q3"): Observation("go", "q3", ("decoy",), ("decoy",), 300.0),
    }
    proposed = {
        ("python", "q1"): Observation(
            "python", "q1", baseline[("python", "q1")].candidates,
            ("impl", "test"), 120.0,
        ),
        ("go", "q2"): Observation(
            "go", "q2", baseline[("go", "q2")].candidates,
            ("impl2",), 220.0,
        ),
        ("go", "q3"): Observation("go", "q3", ("decoy",), (), 320.0),
    }
    return judgments, baseline, proposed


def test_graded_ndcg_uses_entire_judged_pool_as_ideal():
    grades = {"impl": 3, "test": 2, "swarm": 0}
    assert compute_graded_ndcg(["impl", "test"], grades, 2) == pytest.approx(1.0)
    assert compute_graded_ndcg(["test", "impl"], grades, 2) < 1.0
    assert compute_graded_ndcg(["swarm"], grades, 2) == 0.0
    with pytest.raises(ValueError, match="judgments"):
        compute_graded_ndcg(["unjudged"], grades, 2)


def test_candidate_recall_separate_from_final_direct_success():
    judgments, baseline, proposed = _fixture()
    result = evaluate_run(judgments, baseline)
    assert result["overall"]["candidate_direct_recall_at_50"] == 1.0
    assert result["overall"]["direct_success_at_3"] == 0.5
    assert result["overall"]["no_answer_false_positive_rate"] == 1.0
    assert result["overall"]["latency_p50_ms"] == 200.0
    assert result["overall"]["latency_p95_ms"] == pytest.approx(290.0)
    assert result["by_category"]["no_answer"]["no_answer_queries"] == 1

    improved = evaluate_run(judgments, proposed)
    assert improved["overall"]["candidate_direct_recall_at_50"] == 1.0
    assert improved["overall"]["direct_success_at_3"] == 1.0
    assert improved["overall"]["no_answer_false_positive_rate"] == 0.0
    assert improved["overall"]["graded_ndcg_at_5"] > result["overall"]["graded_ndcg_at_5"]


def test_no_answer_and_unjudged_are_not_conflated():
    judgment = Judgment("r", "q", {"background": 1, "decoy": 0})
    good = Observation("r", "q", ("decoy",), (), 3.0)
    assert score_query(judgment, good)["no_answer_false_positive"] is False
    with pytest.raises(ValueError, match="unjudged"):
        score_query(judgment, Observation("r", "q", ("unknown",), (), 3.0))


def test_paired_repository_bootstrap_is_deterministic():
    judgments, baseline, proposed = _fixture()
    a = evaluate_run(judgments, baseline)
    b = evaluate_run(judgments, proposed)
    result = compare_runs(a, b, samples=100, seed=8)
    assert result == compare_runs(a, b, samples=100, seed=8)
    assert result["cluster_repositories"] == 2
    assert result["delta_proposed_minus_baseline"]["direct_success_at_3"] == 0.5
    assert result["delta_proposed_minus_baseline"]["no_answer_false_positive_rate"] == -1.0
    assert result["ci95"]["graded_ndcg_at_5"][0] > 0


def test_jsonl_input_rejects_missing_or_duplicate_judgments(tmp_path):
    labels = tmp_path / "labels.jsonl"
    run = tmp_path / "run.jsonl"
    labels.write_text(json.dumps({
        "repo": "r", "query_id": "q", "grades": {"impl": 3},
    }) + "\n")
    run.write_text(json.dumps({
        "repo": "r", "query_id": "q", "candidates": ["impl", "unknown"],
        "ranked": ["impl"], "latency_ms": 10,
    }) + "\n")
    with pytest.raises(ValueError, match="unjudged"):
        evaluate_run(load_judgments(labels), load_run(run))
    labels.write_text(labels.read_text() * 2)
    with pytest.raises(ValueError, match="duplicate judgment"):
        load_judgments(labels)


def test_jsonl_run_requires_ranked_subset_and_valid_latency(tmp_path):
    run = tmp_path / "run.jsonl"
    row = {"repo": "r", "query_id": "q", "candidates": ["one"],
           "ranked": ["two"], "latency_ms": 1}
    run.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="ranked IDs"):
        load_run(run)
    row["ranked"] = ["one"]
    row["latency_ms"] = float("nan")
    run.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="latency_ms"):
        load_run(run)


def test_cli_compares_frozen_candidates_without_running_models(tmp_path, monkeypatch, capsys):
    judgments, baseline, proposed = _fixture()
    labels_path = tmp_path / "labels.jsonl"
    baseline_path = tmp_path / "baseline.jsonl"
    proposed_path = tmp_path / "proposed.jsonl"
    labels_path.write_text("".join(json.dumps({
        "repo": j.repo, "query_id": j.query_id, "grades": j.grades,
        "category": j.category,
    }) + "\n" for j in judgments.values()))
    for path, run in ((baseline_path, baseline), (proposed_path, proposed)):
        path.write_text("".join(json.dumps({
            "repo": row.repo, "query_id": row.query_id,
            "candidates": row.candidates, "ranked": row.ranked,
            "latency_ms": row.latency_ms,
        }) + "\n" for row in run.values()))
    monkeypatch.setattr(sys, "argv", [
        "ranking_quality", "--judgments", str(labels_path),
        "--run", str(baseline_path), "--compare-run", str(proposed_path),
        "--require-same-candidates", "--bootstrap-samples", "20",
    ])
    main()
    report = json.loads(capsys.readouterr().out)
    assert report["comparison"]["delta_proposed_minus_baseline"]["direct_success_at_3"] == 0.5
