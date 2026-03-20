"""Tests for SpeculativeExecutor."""

from __future__ import annotations

from attoswarm.coordinator.aot_graph import AoTGraph, AoTNode
from attoswarm.coordinator.health_monitor import HealthMonitor
from attoswarm.coordinator.speculative import SpeculativeExecutor


class TestSpeculativeExecutor:
    def _build_graph(self) -> AoTGraph:
        g = AoTGraph()
        g.add_task(AoTNode(task_id="a", target_files=["a.py"]))
        g.add_task(AoTNode(task_id="b", target_files=["b.py"]))
        g.add_task(AoTNode(task_id="c", depends_on=["a", "b"], target_files=["c.py"]))
        g.compute_levels()
        return g

    def test_no_candidates_when_deps_pending(self) -> None:
        g = self._build_graph()
        executor = SpeculativeExecutor(g, confidence_threshold=0.5)
        assert len(executor.get_candidates()) == 0

    def test_candidates_when_deps_running(self) -> None:
        g = self._build_graph()
        g.mark_running("a")
        g.mark_running("b")
        executor = SpeculativeExecutor(g, confidence_threshold=0.5)
        candidates = executor.get_candidates()
        assert len(candidates) == 1
        assert candidates[0].task_id == "c"

    def test_no_candidates_when_one_dep_pending(self) -> None:
        g = self._build_graph()
        g.mark_running("a")
        # b is still pending
        executor = SpeculativeExecutor(g, confidence_threshold=0.5)
        assert len(executor.get_candidates()) == 0

    def test_confidence_filter(self) -> None:
        g = self._build_graph()
        g.mark_running("a")
        g.mark_running("b")
        monitor = HealthMonitor()
        monitor.record_outcome("bad_model", "rate_limit")
        monitor.record_outcome("bad_model", "rate_limit")

        executor = SpeculativeExecutor(g, health_monitor=monitor, confidence_threshold=0.8)
        candidates = executor.get_candidates(running_models={"a": "bad_model", "b": "bad_model"})
        assert len(candidates) == 0  # low health = low confidence

    def test_on_dep_failed_cancels_speculative(self) -> None:
        g = self._build_graph()
        g.mark_running("a")
        g.mark_running("b")
        executor = SpeculativeExecutor(g, confidence_threshold=0.5)
        executor.mark_speculative("c")
        assert "c" in executor.speculative_tasks

        to_cancel = executor.on_dep_failed("a")
        assert "c" in to_cancel
        assert "c" not in executor.speculative_tasks

    def test_file_conflict_prevents_speculation(self) -> None:
        g = AoTGraph()
        g.add_task(AoTNode(task_id="a", target_files=["shared.py"]))
        g.add_task(AoTNode(task_id="b", depends_on=["a"], target_files=["shared.py"]))
        g.compute_levels()
        g.mark_running("a")

        executor = SpeculativeExecutor(g, confidence_threshold=0.5)
        # b targets same file as running a — should not be a candidate
        candidates = executor.get_candidates()
        assert len(candidates) == 0
