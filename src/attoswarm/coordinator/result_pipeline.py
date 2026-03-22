"""Async result pipeline for concurrent post-task processing.

Replaces the sequential ``for result in results: _handle_result(result)``
loop with a staged pipeline that processes independent work concurrently
while keeping shared-state updates sequential.

Pipeline stages:
1. Budget update (sequential — shared mutable BudgetCounter)
2. Concurrent fan-out: test verification, learning, diff capture, projection
3. DAG state update (sequential — shared AoTGraph)
4. State persistence (batched — one persist per batch, not per result)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from attoswarm.coordinator.subagent_manager import TaskResult

logger = logging.getLogger(__name__)


@runtime_checkable
class PipelineHandlers(Protocol):
    """Protocol for orchestrator methods the pipeline delegates to.

    Decouples the pipeline from the full SwarmOrchestrator for testability.
    """

    async def pipeline_update_budget(self, result: TaskResult) -> None: ...
    async def pipeline_test_verify(self, result: TaskResult) -> bool: ...
    async def pipeline_syntax_verify(self, result: TaskResult) -> bool: ...
    async def pipeline_record_learning(self, result: TaskResult) -> None: ...
    async def pipeline_capture_diff(self, result: TaskResult) -> None: ...
    async def pipeline_run_projection(self) -> None: ...
    async def pipeline_update_dag(self, result: TaskResult, success: bool) -> int: ...

    async def pipeline_git_commit(self, result: TaskResult) -> str | None:
        """Create an atomic git commit for a completed task.

        Returns the commit hash on success, or None if nothing was committed.
        Default implementation is a no-op.
        """
        return None


@dataclass(slots=True)
class PipelineResult:
    """Aggregated result of processing a batch through the pipeline."""

    completed: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    commits: dict[str, str] = field(default_factory=dict)
    """Mapping of task_id → commit hash for tasks that were auto-committed."""


class ResultPipeline:
    """Concurrent result processing pipeline.

    Usage::

        pipeline = ResultPipeline()
        result = await pipeline.process_batch(results, handlers)
        total_completed = result.completed
    """

    def __init__(self, max_concurrent: int = 8) -> None:
        self._max_concurrent = max_concurrent

    async def process_batch(
        self,
        results: list[TaskResult],
        handlers: PipelineHandlers,
    ) -> PipelineResult:
        """Process a batch of task results through the pipeline.

        Stages:
        1. Sequential budget updates (shared mutable state)
        2. Concurrent independent operations per result
        3. Sequential DAG updates (shared mutable state)
        4. Single batched projection at the end
        """
        pipeline_result = PipelineResult()

        if not results:
            return pipeline_result

        # Stage 1: Sequential budget updates
        for result in results:
            try:
                await handlers.pipeline_update_budget(result)
            except Exception as exc:
                logger.warning("Budget update failed for %s: %s", result.task_id, exc)
                pipeline_result.errors.append(f"budget:{result.task_id}:{exc}")

        # Stage 2: Concurrent fan-out per result
        semaphore = asyncio.Semaphore(self._max_concurrent)
        verification_results: dict[str, bool] = {}
        syntax_results: dict[str, bool] = {}
        commit_results: dict[str, str] = {}

        async def _process_one(result: TaskResult) -> None:
            async with semaphore:
                tasks: list[asyncio.Task[Any]] = []

                # Test verification (only for successful results)
                if result.success:
                    async def _verify() -> None:
                        try:
                            passed = await handlers.pipeline_test_verify(result)
                            verification_results[result.task_id] = passed
                        except Exception as exc:
                            logger.debug("Test verify failed for %s: %s", result.task_id, exc)
                            verification_results[result.task_id] = result.success

                    tasks.append(asyncio.create_task(_verify()))

                # Syntax verification (only for successful results with modified files)
                if result.success and result.files_modified:
                    async def _syntax() -> None:
                        try:
                            passed = await handlers.pipeline_syntax_verify(result)
                            syntax_results[result.task_id] = passed
                        except Exception:
                            syntax_results[result.task_id] = True  # fail-open

                    tasks.append(asyncio.create_task(_syntax()))

                # Learning recording (always)
                async def _learn() -> None:
                    try:
                        await handlers.pipeline_record_learning(result)
                    except Exception as exc:
                        logger.debug("Learning record failed for %s: %s", result.task_id, exc)

                tasks.append(asyncio.create_task(_learn()))

                # Diff capture (only for successful results with modified files)
                if result.success and result.files_modified:
                    async def _diff() -> None:
                        try:
                            await handlers.pipeline_capture_diff(result)
                        except Exception as exc:
                            logger.debug("Diff capture failed for %s: %s", result.task_id, exc)

                    tasks.append(asyncio.create_task(_diff()))

                # Atomic git commit (only for successful results with modified files)
                if result.success and result.files_modified:
                    async def _git_commit() -> None:
                        try:
                            commit_hash = await handlers.pipeline_git_commit(result)
                            if commit_hash:
                                commit_results[result.task_id] = commit_hash
                        except Exception as exc:
                            logger.debug("Git commit failed for %s: %s", result.task_id, exc)

                    tasks.append(asyncio.create_task(_git_commit()))

                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

        fan_out_tasks = [_process_one(r) for r in results]
        await asyncio.gather(*fan_out_tasks, return_exceptions=True)

        # Collect commit results from fan-out
        pipeline_result.commits.update(commit_results)

        # Stage 3: Sequential DAG updates
        for result in results:
            # Check if test verification changed success status
            if result.task_id in verification_results:
                if not verification_results[result.task_id]:
                    result.success = False
            # Check if syntax verification changed success status
            if result.task_id in syntax_results:
                if not syntax_results[result.task_id]:
                    result.success = False

            try:
                completed = await handlers.pipeline_update_dag(result, result.success)
                pipeline_result.completed += completed
                if not result.success:
                    pipeline_result.failed += 1
            except Exception as exc:
                logger.warning("DAG update failed for %s: %s", result.task_id, exc)
                pipeline_result.errors.append(f"dag:{result.task_id}:{exc}")

        # Stage 4: Single batched projection
        try:
            await handlers.pipeline_run_projection()
        except Exception as exc:
            logger.debug("Batched projection failed: %s", exc)

        return pipeline_result
