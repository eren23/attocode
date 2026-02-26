"""Tests for AoT (Atom-of-Thought) DAG graph scheduling."""

from __future__ import annotations

import pytest

from attoswarm.coordinator.aot_graph import AoTGraph, AoTNode


def _node(task_id: str, deps: list[str] | None = None, files: list[str] | None = None) -> AoTNode:
    return AoTNode(
        task_id=task_id,
        depends_on=deps or [],
        target_files=files or [],
    )


class TestAoTGraphBasics:
    def test_add_and_retrieve(self) -> None:
        g = AoTGraph()
        g.add_task(_node("t1"))
        assert "t1" in g.nodes

    def test_remove_task(self) -> None:
        g = AoTGraph()
        g.add_task(_node("t1"))
        g.remove_task("t1")
        assert "t1" not in g.nodes

    def test_remove_updates_reverse_edges(self) -> None:
        g = AoTGraph()
        g.add_task(_node("t1"))
        g.add_task(_node("t2", deps=["t1"]))
        g.remove_task("t2")
        assert "t2" not in g.nodes["t1"].depended_by


class TestLevelComputation:
    def test_no_deps_level_zero(self) -> None:
        g = AoTGraph()
        g.add_task(_node("t1"))
        g.add_task(_node("t2"))
        g.compute_levels()
        assert g.nodes["t1"].level == 0
        assert g.nodes["t2"].level == 0

    def test_linear_chain(self) -> None:
        g = AoTGraph()
        g.add_task(_node("t1"))
        g.add_task(_node("t2", deps=["t1"]))
        g.add_task(_node("t3", deps=["t2"]))
        g.compute_levels()
        assert g.nodes["t1"].level == 0
        assert g.nodes["t2"].level == 1
        assert g.nodes["t3"].level == 2

    def test_diamond_dependency(self) -> None:
        g = AoTGraph()
        g.add_task(_node("root"))
        g.add_task(_node("left", deps=["root"]))
        g.add_task(_node("right", deps=["root"]))
        g.add_task(_node("merge", deps=["left", "right"]))
        g.compute_levels()
        assert g.nodes["root"].level == 0
        assert g.nodes["left"].level == 1
        assert g.nodes["right"].level == 1
        assert g.nodes["merge"].level == 2

    def test_cycle_detection(self) -> None:
        g = AoTGraph()
        g.add_task(_node("a", deps=["b"]))
        g.add_task(_node("b", deps=["a"]))
        with pytest.raises(ValueError, match="[Cc]ycl"):
            g.compute_levels()


class TestExecutionOrder:
    def test_parallel_batch(self) -> None:
        g = AoTGraph()
        g.add_task(_node("a"))
        g.add_task(_node("b"))
        g.add_task(_node("c"))
        g.compute_levels()
        order = g.get_execution_order()
        assert len(order) == 1
        assert set(order[0]) == {"a", "b", "c"}

    def test_multi_level(self) -> None:
        g = AoTGraph()
        g.add_task(_node("t1"))
        g.add_task(_node("t2", deps=["t1"]))
        g.add_task(_node("t3", deps=["t1"]))
        g.add_task(_node("t4", deps=["t2", "t3"]))
        g.compute_levels()
        order = g.get_execution_order()
        assert len(order) == 3
        assert order[0] == ["t1"]
        assert set(order[1]) == {"t2", "t3"}
        assert order[2] == ["t4"]


class TestReadyBatch:
    def test_initial_ready(self) -> None:
        g = AoTGraph()
        g.add_task(_node("t1"))
        g.add_task(_node("t2", deps=["t1"]))
        g.compute_levels()
        ready = g.get_ready_batch()
        assert ready == ["t1"]

    def test_ready_after_complete(self) -> None:
        g = AoTGraph()
        g.add_task(_node("t1"))
        g.add_task(_node("t2", deps=["t1"]))
        g.compute_levels()
        g.mark_complete("t1")
        ready = g.get_ready_batch()
        assert ready == ["t2"]


class TestFailureCascade:
    def test_mark_failed_cascades(self) -> None:
        g = AoTGraph()
        g.add_task(_node("t1"))
        g.add_task(_node("t2", deps=["t1"]))
        g.add_task(_node("t3", deps=["t2"]))
        g.compute_levels()
        skipped = g.mark_failed("t1")
        assert "t2" in skipped
        assert "t3" in skipped
        assert g.nodes["t2"].status == "skipped"
        assert g.nodes["t3"].status == "skipped"


class TestCriticalPath:
    def test_critical_path_linear(self) -> None:
        g = AoTGraph()
        g.add_task(_node("t1"))
        g.add_task(_node("t2", deps=["t1"]))
        g.add_task(_node("t3", deps=["t2"]))
        g.compute_levels()
        path = g.get_critical_path()
        assert path == ["t1", "t2", "t3"]

    def test_critical_path_diamond(self) -> None:
        g = AoTGraph()
        g.add_task(_node("root"))
        g.add_task(_node("left", deps=["root"]))
        g.add_task(_node("right", deps=["root"]))
        g.add_task(_node("merge", deps=["left", "right"]))
        g.compute_levels()
        path = g.get_critical_path()
        assert len(path) == 3
        assert path[0] == "root"
        assert path[-1] == "merge"


class TestSummary:
    def test_summary_dict(self) -> None:
        g = AoTGraph()
        g.add_task(_node("t1"))
        g.compute_levels()
        s = g.summary()
        assert s["pending"] == 1

    def test_summary_after_complete(self) -> None:
        g = AoTGraph()
        g.add_task(_node("t1"))
        g.add_task(_node("t2"))
        g.compute_levels()
        g.mark_complete("t1")
        s = g.summary()
        assert s.get("done", 0) == 1
        assert s.get("pending", 0) == 1
