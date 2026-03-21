"""Tests for ResultPipeline."""

from __future__ import annotations

import pytest

from attoswarm.coordinator.result_pipeline import ResultPipeline
from attoswarm.coordinator.subagent_manager import TaskResult


class MockHandlers:
    """Mock PipelineHandlers for testing."""

    def __init__(self) -> None:
        self.budget_updates: list[str] = []
        self.verifications: dict[str, bool] = {}
        self.learnings: list[str] = []
        self.diffs: list[str] = []
        self.projections: int = 0
        self.dag_updates: list[tuple[str, bool]] = []

    async def pipeline_update_budget(self, result: TaskResult) -> None:
        self.budget_updates.append(result.task_id)

    async def pipeline_test_verify(self, result: TaskResult) -> bool:
        return self.verifications.get(result.task_id, True)

    async def pipeline_record_learning(self, result: TaskResult) -> None:
        self.learnings.append(result.task_id)

    async def pipeline_capture_diff(self, result: TaskResult) -> None:
        self.diffs.append(result.task_id)

    async def pipeline_run_projection(self) -> None:
        self.projections += 1

    async def pipeline_update_dag(self, result: TaskResult, success: bool) -> int:
        self.dag_updates.append((result.task_id, success))
        return 1 if success else 0


class TestResultPipeline:
    @pytest.mark.asyncio
    async def test_empty_batch(self) -> None:
        pipeline = ResultPipeline()
        handlers = MockHandlers()
        result = await pipeline.process_batch([], handlers)
        assert result.completed == 0
        assert result.failed == 0

    @pytest.mark.asyncio
    async def test_successful_batch(self) -> None:
        pipeline = ResultPipeline()
        handlers = MockHandlers()
        results = [
            TaskResult(task_id="t1", success=True, files_modified=["a.py"]),
            TaskResult(task_id="t2", success=True, files_modified=["b.py"]),
        ]
        pr = await pipeline.process_batch(results, handlers)
        assert pr.completed == 2
        assert pr.failed == 0
        assert len(handlers.budget_updates) == 2
        assert len(handlers.learnings) == 2
        assert len(handlers.diffs) == 2
        assert handlers.projections == 1

    @pytest.mark.asyncio
    async def test_mixed_batch(self) -> None:
        pipeline = ResultPipeline()
        handlers = MockHandlers()
        results = [
            TaskResult(task_id="t1", success=True),
            TaskResult(task_id="t2", success=False, error="timeout"),
        ]
        pr = await pipeline.process_batch(results, handlers)
        assert pr.completed == 1
        assert pr.failed == 1

    @pytest.mark.asyncio
    async def test_verification_can_fail_task(self) -> None:
        pipeline = ResultPipeline()
        handlers = MockHandlers()
        handlers.verifications["t1"] = False  # verification will fail

        results = [
            TaskResult(task_id="t1", success=True, files_modified=["a.py"]),
        ]
        pr = await pipeline.process_batch(results, handlers)
        # Verification changed success to False
        assert pr.completed == 0
        assert pr.failed == 1
