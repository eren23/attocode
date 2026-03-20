"""Tests for PostMortemGenerator and DecomposeMetrics."""

from __future__ import annotations

import tempfile
from pathlib import Path

from attoswarm.coordinator.decompose_metrics import DecomposeMetrics
from attoswarm.coordinator.postmortem import PostMortemGenerator, PostMortemReport
from attoswarm.coordinator.trace_query import TraceQueryEngine


class TestDecomposeMetrics:
    def test_granularity_good(self) -> None:
        metrics = DecomposeMetrics()
        task_data = {
            "t1": {"attempt_history": [{"duration_s": 30.0}]},
            "t2": {"attempt_history": [{"duration_s": 60.0}]},
            "t3": {"attempt_history": [{"duration_s": 120.0}]},
        }
        scorecard = metrics.score(task_data, wall_clock_s=120.0, max_concurrency=3)
        assert scorecard.granularity_score > 0.7

    def test_granularity_too_small(self) -> None:
        metrics = DecomposeMetrics()
        task_data = {
            "t1": {"attempt_history": [{"duration_s": 2.0}]},
            "t2": {"attempt_history": [{"duration_s": 3.0}]},
        }
        scorecard = metrics.score(task_data, wall_clock_s=5.0, max_concurrency=2)
        assert scorecard.granularity_score < 0.8

    def test_file_scope_accuracy(self) -> None:
        metrics = DecomposeMetrics()
        task_data = {
            "t1": {"target_files": ["a.py", "b.py"], "files_modified": ["a.py", "b.py"]},
        }
        scorecard = metrics.score(task_data)
        assert scorecard.file_scope_accuracy == 1.0

    def test_parallel_efficiency(self) -> None:
        metrics = DecomposeMetrics()
        task_data = {
            "t1": {"attempt_history": [{"duration_s": 10.0}]},
            "t2": {"attempt_history": [{"duration_s": 10.0}]},
        }
        # 20s of work in 10s wall clock with 2 workers = 100% efficiency
        scorecard = metrics.score(task_data, wall_clock_s=10.0, max_concurrency=2)
        assert scorecard.parallel_efficiency >= 0.9


class TestPostMortemGenerator:
    def test_generate_completed(self) -> None:
        gen = PostMortemGenerator()
        report = gen.generate(
            dag_summary={"done": 5, "failed": 0, "skipped": 0, "pending": 0},
            budget_data={"cost_used_usd": 2.5},
            wall_clock_s=120.0,
            critical_path=["t1", "t3"],
        )
        assert report.outcome == "completed"
        assert report.success_rate == 1.0
        assert report.total_cost_usd == 2.5

    def test_generate_partial(self) -> None:
        gen = PostMortemGenerator()
        report = gen.generate(
            dag_summary={"done": 3, "failed": 2, "skipped": 0, "pending": 0},
        )
        assert report.outcome == "partial"
        assert report.success_rate == 0.6

    def test_generate_recommendations(self) -> None:
        gen = PostMortemGenerator()
        report = gen.generate(
            dag_summary={"done": 1, "failed": 4, "skipped": 0, "pending": 0},
        )
        assert len(report.recommendations) > 0

    def test_to_markdown(self) -> None:
        gen = PostMortemGenerator()
        report = gen.generate(
            dag_summary={"done": 5, "failed": 0, "skipped": 0, "pending": 0},
            wall_clock_s=60.0,
        )
        md = gen.to_markdown(report)
        assert "# Swarm Post-Mortem Report" in md
        assert "completed" in md

    def test_persist(self) -> None:
        gen = PostMortemGenerator()
        report = gen.generate(
            dag_summary={"done": 3, "failed": 1, "skipped": 0, "pending": 0},
        )
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            gen.persist(report, run_dir)
            assert (run_dir / "postmortem.json").exists()
            assert (run_dir / "postmortem.md").exists()

    def test_to_dict(self) -> None:
        report = PostMortemReport(
            outcome="completed",
            total_tasks=5,
            completed_tasks=5,
            success_rate=1.0,
        )
        d = report.to_dict()
        assert d["summary"]["outcome"] == "completed"
        assert d["summary"]["success_rate"] == 1.0
