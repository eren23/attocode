"""Tests for parallel background agents."""

from __future__ import annotations

import pytest

from attocode.core.parallel_agents import (
    ParallelAgentManager,
    ParallelConfig,
    ParallelResult,
    ParallelTask,
    ParallelTaskStatus,
)


class TestParallelTask:
    def test_defaults(self) -> None:
        task = ParallelTask(id="t1", description="Do thing")
        assert task.status == ParallelTaskStatus.PENDING
        assert task.duration == 0.0

    def test_duration(self) -> None:
        task = ParallelTask(id="t1", description="d", start_time=10.0, end_time=15.0)
        assert task.duration == 5.0


class TestParallelResult:
    def test_all_succeeded(self) -> None:
        result = ParallelResult(tasks=[
            ParallelTask(id="t1", description="a", status=ParallelTaskStatus.COMPLETED),
            ParallelTask(id="t2", description="b", status=ParallelTaskStatus.COMPLETED),
        ])
        assert result.all_succeeded is True

    def test_not_all_succeeded(self) -> None:
        result = ParallelResult(tasks=[
            ParallelTask(id="t1", description="a", status=ParallelTaskStatus.COMPLETED),
            ParallelTask(id="t2", description="b", status=ParallelTaskStatus.FAILED),
        ])
        assert result.all_succeeded is False
        assert result.completed_count == 1
        assert result.failed_count == 1

    def test_format_summary(self) -> None:
        result = ParallelResult(tasks=[
            ParallelTask(id="t1", description="Build login", status=ParallelTaskStatus.COMPLETED),
            ParallelTask(id="t2", description="Fix bug", status=ParallelTaskStatus.FAILED, error="Broke"),
        ])
        text = result.format_summary()
        assert "1/2 completed" in text
        assert "Build login" in text
        assert "Broke" in text

    def test_format_summary_conflicts(self) -> None:
        result = ParallelResult(
            tasks=[],
            merge_conflicts=["src/main.py"],
        )
        text = result.format_summary()
        assert "main.py" in text


class TestParallelAgentManager:
    def test_parse_tasks(self) -> None:
        mgr = ParallelAgentManager()
        tasks = mgr.parse_tasks("build login | fix auth | add tests")
        assert len(tasks) == 3
        assert tasks[0].description == "build login"
        assert tasks[1].description == "fix auth"
        assert tasks[2].description == "add tests"

    def test_parse_tasks_caps_at_max(self) -> None:
        mgr = ParallelAgentManager(ParallelConfig(max_agents=2))
        tasks = mgr.parse_tasks("a | b | c | d")
        assert len(tasks) == 2

    def test_parse_tasks_empty_segments(self) -> None:
        mgr = ParallelAgentManager()
        tasks = mgr.parse_tasks("a | | b |")
        assert len(tasks) == 2

    def test_get_task(self) -> None:
        mgr = ParallelAgentManager()
        mgr.parse_tasks("task A | task B")
        assert mgr.get_task("p0") is not None
        assert mgr.get_task("p0").description == "task A"
        assert mgr.get_task("nonexistent") is None

    def test_start_task(self) -> None:
        mgr = ParallelAgentManager()
        mgr.parse_tasks("task")
        assert mgr.start_task("p0", worktree_path="/tmp/wt") is True
        task = mgr.get_task("p0")
        assert task.status == ParallelTaskStatus.RUNNING
        assert task.worktree_path == "/tmp/wt"

    def test_start_task_unknown(self) -> None:
        mgr = ParallelAgentManager()
        assert mgr.start_task("nonexistent") is False

    def test_complete_task(self) -> None:
        mgr = ParallelAgentManager()
        mgr.parse_tasks("task")
        mgr.start_task("p0")
        assert mgr.complete_task(
            "p0", success=True, summary="Done", files_modified=["a.py"]
        ) is True
        task = mgr.get_task("p0")
        assert task.status == ParallelTaskStatus.COMPLETED
        assert task.files_modified == ["a.py"]

    def test_complete_task_failure(self) -> None:
        mgr = ParallelAgentManager()
        mgr.parse_tasks("task")
        mgr.complete_task("p0", success=False, error="Broke")
        task = mgr.get_task("p0")
        assert task.status == ParallelTaskStatus.FAILED
        assert task.error == "Broke"

    def test_get_result_detects_conflicts(self) -> None:
        mgr = ParallelAgentManager()
        mgr.parse_tasks("a | b")
        mgr.complete_task("p0", files_modified=["shared.py", "a.py"])
        mgr.complete_task("p1", files_modified=["shared.py", "b.py"])
        result = mgr.get_result()
        assert "shared.py" in result.merge_conflicts

    def test_get_result_no_conflicts(self) -> None:
        mgr = ParallelAgentManager()
        mgr.parse_tasks("a | b")
        mgr.complete_task("p0", files_modified=["a.py"])
        mgr.complete_task("p1", files_modified=["b.py"])
        result = mgr.get_result()
        assert result.merge_conflicts == []

    def test_get_status(self) -> None:
        mgr = ParallelAgentManager()
        mgr.parse_tasks("a | b | c")
        mgr.start_task("p0")
        mgr.complete_task("p1", success=True)
        status = mgr.get_status()
        assert status["total"] == 3
        assert status["running"] == 1
        assert status["completed"] == 1
        assert status["pending"] == 1
