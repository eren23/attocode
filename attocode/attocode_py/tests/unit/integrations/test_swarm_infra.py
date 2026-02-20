"""Tests for swarm infrastructure: task_queue, quality_gate, worker_pool, model_selector."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from attocode.integrations.swarm.model_selector import (
    FALLBACK_WORKERS,
    ModelHealthTracker,
    get_fallback_workers,
    select_alternative_model,
    select_worker_for_capability,
)
from attocode.integrations.swarm.quality_gate import (
    ArtifactReport,
    ConcreteCheckResult,
    QualityGateResult,
    check_artifacts,
    check_artifacts_enhanced,
    run_concrete_checks,
    run_pre_flight_checks,
)
from attocode.integrations.swarm.task_queue import (
    SwarmTaskQueue,
    get_effective_threshold,
)
from attocode.integrations.swarm.types import (
    BUILTIN_TASK_TYPE_CONFIGS,
    FAILURE_MODE_THRESHOLDS,
    DependencyGraph,
    FileConflictStrategy,
    FixupTask,
    ModelHealthRecord,
    PartialContext,
    ResourceConflict,
    SmartDecompositionResult,
    SmartSubtask,
    SpawnResult,
    SubtaskType,
    SwarmConfig,
    SwarmTask,
    SwarmTaskResult,
    SwarmTaskStatus,
    SwarmWorkerSpec,
    TaskFailureMode,
    WorkerCapability,
    WorkerRole,
)
from attocode.integrations.swarm.worker_pool import SwarmWorkerPool


# =============================================================================
# Helpers
# =============================================================================


def _make_task(
    task_id: str = "t1",
    description: str = "Test task",
    task_type: SubtaskType = SubtaskType.IMPLEMENT,
    dependencies: list[str] | None = None,
    status: SwarmTaskStatus = SwarmTaskStatus.PENDING,
    complexity: int = 5,
    wave: int = 0,
    target_files: list[str] | None = None,
    read_files: list[str] | None = None,
    attempts: int = 0,
    is_foundation: bool = False,
    failure_mode: TaskFailureMode | None = None,
    dispatched_at: float | None = None,
) -> SwarmTask:
    return SwarmTask(
        id=task_id,
        description=description,
        type=task_type,
        dependencies=dependencies or [],
        status=status,
        complexity=complexity,
        wave=wave,
        target_files=target_files,
        read_files=read_files,
        attempts=attempts,
        is_foundation=is_foundation,
        failure_mode=failure_mode,
        dispatched_at=dispatched_at,
    )


def _make_result(
    success: bool = True,
    output: str = "Done",
    tool_calls: int | None = 5,
    files_modified: list[str] | None = None,
    closure_report: dict[str, Any] | None = None,
    tokens_used: int = 1000,
    duration_ms: int = 5000,
) -> SwarmTaskResult:
    return SwarmTaskResult(
        success=success,
        output=output,
        tool_calls=tool_calls,
        files_modified=files_modified,
        tokens_used=tokens_used,
        duration_ms=duration_ms,
        closure_report=closure_report,
    )


def _make_decomposition(
    subtasks: list[SmartSubtask] | None = None,
    parallel_groups: list[list[str]] | None = None,
    conflicts: list[ResourceConflict] | None = None,
) -> SmartDecompositionResult:
    return SmartDecompositionResult(
        subtasks=subtasks or [],
        dependency_graph=DependencyGraph(
            parallel_groups=parallel_groups or [],
            conflicts=conflicts or [],
        ),
    )


def _make_config(**overrides: Any) -> SwarmConfig:
    defaults: dict[str, Any] = {
        "partial_dependency_threshold": 0.5,
        "artifact_aware_skip": True,
        "file_conflict_strategy": FileConflictStrategy.CLAIM_BASED,
    }
    defaults.update(overrides)
    return SwarmConfig(**defaults)


def _make_worker(
    name: str = "coder",
    model: str = "test-model",
    capabilities: list[WorkerCapability] | None = None,
    max_tokens: int = 50_000,
    prompt_tier: str = "full",
    persona: str = "",
) -> SwarmWorkerSpec:
    return SwarmWorkerSpec(
        name=name,
        model=model,
        capabilities=capabilities or [WorkerCapability.CODE],
        max_tokens=max_tokens,
        prompt_tier=prompt_tier,
        persona=persona,
    )


# =============================================================================
# TaskQueue: get_effective_threshold
# =============================================================================


class TestGetEffectiveThreshold:
    """Tests for the free function get_effective_threshold."""

    def test_no_failed_deps_returns_configured(self) -> None:
        assert get_effective_threshold([], 0.5) == 0.5

    def test_no_failure_modes_returns_configured(self) -> None:
        dep = _make_task(failure_mode=None)
        assert get_effective_threshold([dep], 0.5) == 0.5

    def test_timeout_mode_uses_threshold_from_map(self) -> None:
        dep = _make_task(failure_mode=TaskFailureMode.TIMEOUT)
        result = get_effective_threshold([dep], 0.5)
        assert result == FAILURE_MODE_THRESHOLDS["timeout"]  # 0.3

    def test_quality_mode(self) -> None:
        dep = _make_task(failure_mode=TaskFailureMode.QUALITY)
        result = get_effective_threshold([dep], 0.5)
        assert result == 0.5  # min(0.7, 0.5) = 0.5

    def test_quality_mode_with_high_configured(self) -> None:
        dep = _make_task(failure_mode=TaskFailureMode.QUALITY)
        result = get_effective_threshold([dep], 0.9)
        assert result == 0.7  # min(0.7, 0.9) = 0.7

    def test_multiple_modes_uses_minimum(self) -> None:
        dep1 = _make_task(task_id="d1", failure_mode=TaskFailureMode.TIMEOUT)
        dep2 = _make_task(task_id="d2", failure_mode=TaskFailureMode.QUALITY)
        result = get_effective_threshold([dep1, dep2], 0.8)
        assert result == 0.3  # min(0.3, 0.7, 0.8)

    def test_cascade_mode(self) -> None:
        dep = _make_task(failure_mode=TaskFailureMode.CASCADE)
        result = get_effective_threshold([dep], 0.9)
        assert result == 0.8  # min(0.8, 0.9)

    def test_error_mode(self) -> None:
        dep = _make_task(failure_mode=TaskFailureMode.ERROR)
        result = get_effective_threshold([dep], 0.6)
        assert result == 0.5  # min(0.5, 0.6)

    def test_rate_limit_mode(self) -> None:
        dep = _make_task(failure_mode=TaskFailureMode.RATE_LIMIT)
        result = get_effective_threshold([dep], 0.5)
        assert result == 0.3

    def test_hollow_mode(self) -> None:
        dep = _make_task(failure_mode=TaskFailureMode.HOLLOW)
        result = get_effective_threshold([dep], 0.5)
        assert result == 0.5  # min(0.7, 0.5) = 0.5

    def test_configured_lower_than_all_modes(self) -> None:
        dep = _make_task(failure_mode=TaskFailureMode.CASCADE)
        result = get_effective_threshold([dep], 0.1)
        assert result == 0.1  # 0.1 < 0.8


# =============================================================================
# TaskQueue: load_from_decomposition
# =============================================================================


class TestLoadFromDecomposition:
    """Tests for SwarmTaskQueue.load_from_decomposition."""

    def test_creates_tasks_from_subtasks(self) -> None:
        q = SwarmTaskQueue()
        sub = SmartSubtask(id="s1", description="Do it", type="implement", complexity=5)
        result = _make_decomposition(subtasks=[sub], parallel_groups=[["s1"]])
        q.load_from_decomposition(result, _make_config())
        assert "s1" in q.tasks
        assert q.tasks["s1"].description == "Do it"

    def test_assigns_waves(self) -> None:
        q = SwarmTaskQueue()
        s1 = SmartSubtask(id="s1", description="First", complexity=3)
        s2 = SmartSubtask(id="s2", description="Second", complexity=5, dependencies=["s1"])
        result = _make_decomposition(
            subtasks=[s1, s2],
            parallel_groups=[["s1"], ["s2"]],
        )
        q.load_from_decomposition(result, _make_config())
        assert q.tasks["s1"].wave == 0
        assert q.tasks["s2"].wave == 1

    def test_sets_foundation_flag(self) -> None:
        q = SwarmTaskQueue()
        s1 = SmartSubtask(id="s1", description="Foundation")
        s2 = SmartSubtask(id="s2", description="D1", dependencies=["s1"])
        s3 = SmartSubtask(id="s3", description="D2", dependencies=["s1"])
        s4 = SmartSubtask(id="s4", description="D3", dependencies=["s1"])
        result = _make_decomposition(
            subtasks=[s1, s2, s3, s4],
            parallel_groups=[["s1"], ["s2", "s3", "s4"]],
        )
        q.load_from_decomposition(result, _make_config())
        assert q.tasks["s1"].is_foundation is True
        assert q.tasks["s2"].is_foundation is False

    def test_tasks_with_no_deps_become_ready(self) -> None:
        q = SwarmTaskQueue()
        s1 = SmartSubtask(id="s1", description="Ready task")
        result = _make_decomposition(subtasks=[s1], parallel_groups=[["s1"]])
        q.load_from_decomposition(result, _make_config())
        assert q.tasks["s1"].status == SwarmTaskStatus.READY

    def test_tasks_with_deps_stay_pending(self) -> None:
        q = SwarmTaskQueue()
        s1 = SmartSubtask(id="s1", description="First")
        s2 = SmartSubtask(id="s2", description="Depends", dependencies=["s1"])
        result = _make_decomposition(
            subtasks=[s1, s2], parallel_groups=[["s1"], ["s2"]]
        )
        q.load_from_decomposition(result, _make_config())
        assert q.tasks["s2"].status == SwarmTaskStatus.PENDING

    def test_builds_waves_list(self) -> None:
        q = SwarmTaskQueue()
        s1 = SmartSubtask(id="s1", description="W0")
        s2 = SmartSubtask(id="s2", description="W1")
        result = _make_decomposition(
            subtasks=[s1, s2], parallel_groups=[["s1"], ["s2"]]
        )
        q.load_from_decomposition(result, _make_config())
        assert len(q.waves) == 2
        assert "s1" in q.waves[0]
        assert "s2" in q.waves[1]

    def test_clears_previous_state(self) -> None:
        q = SwarmTaskQueue()
        # Load once
        s1 = SmartSubtask(id="s1", description="First load")
        r1 = _make_decomposition(subtasks=[s1], parallel_groups=[["s1"]])
        q.load_from_decomposition(r1, _make_config())

        # Load again
        s2 = SmartSubtask(id="s2", description="Second load")
        r2 = _make_decomposition(subtasks=[s2], parallel_groups=[["s2"]])
        q.load_from_decomposition(r2, _make_config())

        assert "s1" not in q.tasks
        assert "s2" in q.tasks

    def test_fallback_wave_zero(self) -> None:
        q = SwarmTaskQueue()
        s1 = SmartSubtask(id="s1", description="No group")
        result = _make_decomposition(subtasks=[s1], parallel_groups=[])
        q.load_from_decomposition(result, _make_config())
        assert q.tasks["s1"].wave == 0

    def test_sets_partial_dependency_threshold(self) -> None:
        q = SwarmTaskQueue()
        s1 = SmartSubtask(id="s1", description="A")
        result = _make_decomposition(subtasks=[s1], parallel_groups=[["s1"]])
        q.load_from_decomposition(result, _make_config(partial_dependency_threshold=0.7))
        assert q.partial_dependency_threshold == 0.7

    def test_serialize_conflicts(self) -> None:
        q = SwarmTaskQueue()
        s1 = SmartSubtask(id="s1", description="Writer 1")
        s2 = SmartSubtask(id="s2", description="Writer 2")
        conflict = ResourceConflict(file_path="shared.py", task_ids=["s1", "s2"])
        result = _make_decomposition(
            subtasks=[s1, s2],
            parallel_groups=[["s1", "s2"]],
            conflicts=[conflict],
        )
        config = _make_config(file_conflict_strategy=FileConflictStrategy.SERIALIZE)
        q.load_from_decomposition(result, config)
        # After serialization, s2 should be in a later wave
        assert q.tasks["s1"].wave != q.tasks["s2"].wave or len(q.waves) >= 2


# =============================================================================
# TaskQueue: get_ready_tasks
# =============================================================================


class TestGetReadyTasks:
    def test_returns_current_wave_ready(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.READY, wave=0)
        q.waves = [["t1"]]
        q.current_wave = 0
        ready = q.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].id == "t1"

    def test_skips_non_ready(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.DISPATCHED, wave=0)
        q.waves = [["t1"]]
        ready = q.get_ready_tasks()
        assert len(ready) == 0

    def test_skips_future_waves(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.READY, wave=1)
        q.waves = [[], ["t1"]]
        q.current_wave = 0
        ready = q.get_ready_tasks()
        assert len(ready) == 0

    def test_respects_retry_after(self) -> None:
        q = SwarmTaskQueue()
        t = _make_task("t1", status=SwarmTaskStatus.READY, wave=0)
        t.retry_after = time.time() + 1000  # far in the future
        q.tasks["t1"] = t
        q.waves = [["t1"]]
        ready = q.get_ready_tasks()
        assert len(ready) == 0

    def test_expired_retry_after_returns(self) -> None:
        q = SwarmTaskQueue()
        t = _make_task("t1", status=SwarmTaskStatus.READY, wave=0)
        t.retry_after = time.time() - 10  # in the past
        q.tasks["t1"] = t
        q.waves = [["t1"]]
        ready = q.get_ready_tasks()
        assert len(ready) == 1

    def test_empty_when_past_last_wave(self) -> None:
        q = SwarmTaskQueue()
        q.waves = [["t1"]]
        q.current_wave = 5
        assert q.get_ready_tasks() == []


# =============================================================================
# TaskQueue: get_all_ready_tasks
# =============================================================================


class TestGetAllReadyTasks:
    def test_sorts_by_wave_then_complexity_desc(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.READY, wave=0, complexity=3)
        q.tasks["t2"] = _make_task("t2", status=SwarmTaskStatus.READY, wave=0, complexity=8)
        q.tasks["t3"] = _make_task("t3", status=SwarmTaskStatus.READY, wave=1, complexity=5)
        result = q.get_all_ready_tasks()
        assert result[0].id == "t2"  # wave 0, complexity 8
        assert result[1].id == "t1"  # wave 0, complexity 3
        assert result[2].id == "t3"  # wave 1, complexity 5

    def test_excludes_non_ready(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.READY, wave=0)
        q.tasks["t2"] = _make_task("t2", status=SwarmTaskStatus.COMPLETED, wave=0)
        result = q.get_all_ready_tasks()
        assert len(result) == 1

    def test_respects_retry_after(self) -> None:
        q = SwarmTaskQueue()
        t = _make_task("t1", status=SwarmTaskStatus.READY, wave=0)
        t.retry_after = time.time() + 1000
        q.tasks["t1"] = t
        assert len(q.get_all_ready_tasks()) == 0

    def test_empty_queue(self) -> None:
        q = SwarmTaskQueue()
        assert q.get_all_ready_tasks() == []


# =============================================================================
# TaskQueue: mark_dispatched
# =============================================================================


class TestMarkDispatched:
    def test_transitions_to_dispatched(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.READY)
        q.mark_dispatched("t1", "model-a")
        assert q.tasks["t1"].status == SwarmTaskStatus.DISPATCHED
        assert q.tasks["t1"].assigned_model == "model-a"
        assert q.tasks["t1"].attempts == 1

    def test_sets_dispatched_at(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.READY)
        before = time.time()
        q.mark_dispatched("t1", "m")
        assert q.tasks["t1"].dispatched_at is not None
        assert q.tasks["t1"].dispatched_at >= before

    def test_nonexistent_task_is_noop(self) -> None:
        q = SwarmTaskQueue()
        q.mark_dispatched("ghost", "m")  # should not raise

    def test_increments_attempts(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.READY, attempts=2)
        q.mark_dispatched("t1", "m")
        assert q.tasks["t1"].attempts == 3


# =============================================================================
# TaskQueue: mark_completed
# =============================================================================


class TestMarkCompleted:
    def test_transitions_to_completed(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.DISPATCHED)
        result = _make_result()
        q.mark_completed("t1", result)
        assert q.tasks["t1"].status == SwarmTaskStatus.COMPLETED
        assert q.tasks["t1"].result is result

    def test_clears_pending_cascade_skip(self) -> None:
        q = SwarmTaskQueue()
        t = _make_task("t1", status=SwarmTaskStatus.DISPATCHED)
        t.pending_cascade_skip = True
        q.tasks["t1"] = t
        q.mark_completed("t1", _make_result())
        assert q.tasks["t1"].pending_cascade_skip is False

    def test_unlocks_dependents(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.DISPATCHED)
        q.tasks["t2"] = _make_task("t2", status=SwarmTaskStatus.PENDING, dependencies=["t1"])
        q.waves = [["t1"], ["t2"]]
        q.mark_completed("t1", _make_result())
        assert q.tasks["t2"].status == SwarmTaskStatus.READY

    def test_nonexistent_task_is_noop(self) -> None:
        q = SwarmTaskQueue()
        q.mark_completed("ghost", _make_result())  # no raise


# =============================================================================
# TaskQueue: mark_failed (with retries and cascade)
# =============================================================================


class TestMarkFailed:
    def test_retry_when_attempts_within_budget(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.DISPATCHED, attempts=1)
        retried = q.mark_failed("t1", max_retries=2)
        assert retried is True
        assert q.tasks["t1"].status == SwarmTaskStatus.READY

    def test_failed_when_retries_exhausted(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.DISPATCHED, attempts=3)
        retried = q.mark_failed("t1", max_retries=2)
        assert retried is False
        assert q.tasks["t1"].status == SwarmTaskStatus.FAILED

    def test_cascade_on_failure(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.DISPATCHED, attempts=3)
        q.tasks["t2"] = _make_task("t2", status=SwarmTaskStatus.PENDING, dependencies=["t1"])
        q.waves = [["t1"], ["t2"]]
        q.mark_failed("t1", max_retries=2)
        assert q.tasks["t2"].status == SwarmTaskStatus.SKIPPED

    def test_nonexistent_task_returns_false(self) -> None:
        q = SwarmTaskQueue()
        assert q.mark_failed("ghost", max_retries=2) is False


# =============================================================================
# TaskQueue: mark_failed_without_cascade
# =============================================================================


class TestMarkFailedWithoutCascade:
    def test_retry(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", attempts=1)
        retried = q.mark_failed_without_cascade("t1", max_retries=2)
        assert retried is True
        assert q.tasks["t1"].status == SwarmTaskStatus.READY

    def test_fail_no_cascade(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", attempts=3)
        q.tasks["t2"] = _make_task("t2", dependencies=["t1"], status=SwarmTaskStatus.PENDING)
        q.waves = [["t1"], ["t2"]]
        retried = q.mark_failed_without_cascade("t1", max_retries=2)
        assert retried is False
        assert q.tasks["t1"].status == SwarmTaskStatus.FAILED
        # t2 should NOT be skipped
        assert q.tasks["t2"].status == SwarmTaskStatus.PENDING

    def test_nonexistent_returns_false(self) -> None:
        q = SwarmTaskQueue()
        assert q.mark_failed_without_cascade("ghost", max_retries=2) is False


# =============================================================================
# TaskQueue: trigger_cascade_skip
# =============================================================================


class TestTriggerCascadeSkip:
    def test_manually_triggers(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.FAILED)
        q.tasks["t2"] = _make_task("t2", dependencies=["t1"], status=SwarmTaskStatus.PENDING)
        q.waves = [["t1"], ["t2"]]
        q.trigger_cascade_skip("t1")
        assert q.tasks["t2"].status == SwarmTaskStatus.SKIPPED

    def test_cascade_callback_invoked(self) -> None:
        q = SwarmTaskQueue()
        callback = MagicMock()
        q.set_on_cascade_skip(callback)
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.FAILED)
        q.tasks["t2"] = _make_task("t2", dependencies=["t1"], status=SwarmTaskStatus.PENDING)
        q.waves = [["t1"], ["t2"]]
        q.trigger_cascade_skip("t1")
        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == "t1"
        assert "t2" in args[1]


# =============================================================================
# TaskQueue: cascade_skip with partial threshold
# =============================================================================


class TestCascadeSkipPartialThreshold:
    def test_partial_threshold_keeps_task_ready(self) -> None:
        q = SwarmTaskQueue()
        q.partial_dependency_threshold = 0.5
        q.artifact_aware_skip = False

        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.COMPLETED)
        q.tasks["t1"].result = _make_result()
        q.tasks["t2"] = _make_task("t2", status=SwarmTaskStatus.FAILED)
        q.tasks["t3"] = _make_task(
            "t3", dependencies=["t1", "t2"], status=SwarmTaskStatus.PENDING
        )
        q.waves = [["t1", "t2"], ["t3"]]
        q.trigger_cascade_skip("t2")
        # 1/2 = 0.5 >= threshold 0.5 -> not skipped, gets partial context
        assert q.tasks["t3"].status == SwarmTaskStatus.READY
        assert q.tasks["t3"].partial_context is not None

    def test_below_threshold_skips(self) -> None:
        q = SwarmTaskQueue()
        q.partial_dependency_threshold = 0.8
        q.artifact_aware_skip = False

        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.COMPLETED)
        q.tasks["t1"].result = _make_result()
        q.tasks["t2"] = _make_task("t2", status=SwarmTaskStatus.FAILED)
        q.tasks["t3"] = _make_task(
            "t3", dependencies=["t1", "t2"], status=SwarmTaskStatus.PENDING
        )
        q.waves = [["t1", "t2"], ["t3"]]
        q.trigger_cascade_skip("t2")
        # 1/2 = 0.5 < 0.8 -> skipped
        assert q.tasks["t3"].status == SwarmTaskStatus.SKIPPED


# =============================================================================
# TaskQueue: cascade_skip with timeout lenience
# =============================================================================


class TestCascadeSkipTimeoutLenience:
    def test_timeout_keeps_dependent_ready(self) -> None:
        q = SwarmTaskQueue()
        q.artifact_aware_skip = False

        t1 = _make_task("t1", status=SwarmTaskStatus.FAILED, failure_mode=TaskFailureMode.TIMEOUT)
        q.tasks["t1"] = t1
        q.tasks["t2"] = _make_task("t2", dependencies=["t1"], status=SwarmTaskStatus.PENDING)
        q.waves = [["t1"], ["t2"]]
        q.trigger_cascade_skip("t1")
        assert q.tasks["t2"].status == SwarmTaskStatus.READY
        assert q.tasks["t2"].partial_context is not None


# =============================================================================
# TaskQueue: cascade_skip pending_cascade_skip for dispatched tasks
# =============================================================================


class TestCascadeSkipPendingForDispatched:
    def test_dispatched_task_gets_pending_flag(self) -> None:
        q = SwarmTaskQueue()
        q.artifact_aware_skip = False

        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.FAILED)
        q.tasks["t2"] = _make_task(
            "t2", dependencies=["t1"], status=SwarmTaskStatus.DISPATCHED
        )
        q.waves = [["t1"], ["t2"]]
        q.trigger_cascade_skip("t1")
        assert q.tasks["t2"].pending_cascade_skip is True
        # Should NOT be skipped (still dispatched)
        assert q.tasks["t2"].status == SwarmTaskStatus.DISPATCHED


# =============================================================================
# TaskQueue: rescue_task
# =============================================================================


class TestRescueTask:
    def test_rescue_skipped_task(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.SKIPPED)
        q.rescue_task("t1", "Manual rescue context")
        assert q.tasks["t1"].status == SwarmTaskStatus.READY
        assert q.tasks["t1"].rescue_context == "Manual rescue context"

    def test_rescue_non_skipped_returns_false(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.FAILED)
        assert q.rescue_task("t1", "ctx") is False

    def test_rescue_nonexistent_returns_false(self) -> None:
        q = SwarmTaskQueue()
        assert q.rescue_task("ghost", "ctx") is False


# =============================================================================
# TaskQueue: replace_with_subtasks
# =============================================================================


class TestReplaceWithSubtasks:
    def test_marks_original_decomposed(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.DISPATCHED, wave=0)
        q.waves = [["t1"]]
        sub_a = _make_task("sub-a", status=SwarmTaskStatus.PENDING)
        sub_b = _make_task("sub-b", status=SwarmTaskStatus.PENDING)
        q.replace_with_subtasks("t1", [sub_a, sub_b])
        assert q.tasks["t1"].status == SwarmTaskStatus.DECOMPOSED

    def test_adds_subtasks(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", wave=0)
        q.waves = [["t1"]]
        sub_a = _make_task("sub-a")
        sub_b = _make_task("sub-b")
        q.replace_with_subtasks("t1", [sub_a, sub_b])
        assert "sub-a" in q.tasks
        assert "sub-b" in q.tasks

    def test_rewires_dependencies(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", wave=0)
        q.tasks["t2"] = _make_task("t2", dependencies=["t1"], wave=1)
        q.waves = [["t1"], ["t2"]]
        sub_a = _make_task("sub-a")
        q.replace_with_subtasks("t1", [sub_a])
        # t2 should now depend on sub-a, not t1
        assert "t1" not in q.tasks["t2"].dependencies
        assert "sub-a" in q.tasks["t2"].dependencies

    def test_subtasks_get_parent_wave(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", wave=2)
        q.waves = [[], [], ["t1"]]
        sub = _make_task("sub-1", wave=99)  # will be overridden
        q.replace_with_subtasks("t1", [sub])
        assert q.tasks["sub-1"].wave == 2

    def test_nonexistent_original_is_noop(self) -> None:
        q = SwarmTaskQueue()
        q.replace_with_subtasks("ghost", [_make_task("s1")])  # no raise


# =============================================================================
# TaskQueue: advance_wave
# =============================================================================


class TestAdvanceWave:
    def test_increments_wave(self) -> None:
        q = SwarmTaskQueue()
        q.waves = [["t1"], ["t2"]]
        q.current_wave = 0
        has_more = q.advance_wave()
        assert q.current_wave == 1
        assert has_more is True

    def test_returns_false_at_end(self) -> None:
        q = SwarmTaskQueue()
        q.waves = [["t1"]]
        q.current_wave = 0
        has_more = q.advance_wave()
        assert has_more is False
        assert q.current_wave == 1

    def test_promotes_pending_to_ready(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.COMPLETED, wave=0)
        q.tasks["t2"] = _make_task("t2", status=SwarmTaskStatus.PENDING, dependencies=["t1"], wave=1)
        q.tasks["t1"].result = _make_result()
        q.waves = [["t1"], ["t2"]]
        q.current_wave = 0
        q.advance_wave()
        assert q.tasks["t2"].status == SwarmTaskStatus.READY


# =============================================================================
# TaskQueue: is_complete
# =============================================================================


class TestIsComplete:
    def test_all_terminal(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.COMPLETED)
        q.tasks["t2"] = _make_task("t2", status=SwarmTaskStatus.FAILED)
        q.tasks["t3"] = _make_task("t3", status=SwarmTaskStatus.SKIPPED)
        assert q.is_complete() is True

    def test_decomposed_is_terminal(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.DECOMPOSED)
        assert q.is_complete() is True

    def test_not_complete_with_pending(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.COMPLETED)
        q.tasks["t2"] = _make_task("t2", status=SwarmTaskStatus.PENDING)
        assert q.is_complete() is False

    def test_not_complete_with_dispatched(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.DISPATCHED)
        assert q.is_complete() is False

    def test_empty_queue_is_complete(self) -> None:
        q = SwarmTaskQueue()
        assert q.is_complete() is True


# =============================================================================
# TaskQueue: get_stats
# =============================================================================


class TestGetStats:
    def test_counts_correctly(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["r1"] = _make_task("r1", status=SwarmTaskStatus.READY)
        q.tasks["r2"] = _make_task("r2", status=SwarmTaskStatus.READY)
        q.tasks["d1"] = _make_task("d1", status=SwarmTaskStatus.DISPATCHED)
        q.tasks["c1"] = _make_task("c1", status=SwarmTaskStatus.COMPLETED)
        q.tasks["f1"] = _make_task("f1", status=SwarmTaskStatus.FAILED)
        q.tasks["s1"] = _make_task("s1", status=SwarmTaskStatus.SKIPPED)
        stats = q.get_stats()
        assert stats.total == 6
        assert stats.ready == 2
        assert stats.running == 1
        assert stats.completed == 1
        assert stats.failed == 1
        assert stats.skipped == 1

    def test_decomposed_counts_as_completed(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["d1"] = _make_task("d1", status=SwarmTaskStatus.DECOMPOSED)
        stats = q.get_stats()
        assert stats.completed == 1

    def test_empty_stats(self) -> None:
        q = SwarmTaskQueue()
        stats = q.get_stats()
        assert stats.total == 0


# =============================================================================
# TaskQueue: reconcile_stale_dispatched
# =============================================================================


class TestReconcileStaleDispatched:
    def test_resets_stale_to_ready(self) -> None:
        q = SwarmTaskQueue()
        now = time.time()
        t = _make_task("t1", status=SwarmTaskStatus.DISPATCHED, dispatched_at=now - 600)
        q.tasks["t1"] = t
        recovered = q.reconcile_stale_dispatched(
            stale_after_ms=300_000, now=now
        )
        assert "t1" in recovered
        assert q.tasks["t1"].status == SwarmTaskStatus.READY

    def test_keeps_fresh_dispatched(self) -> None:
        q = SwarmTaskQueue()
        now = time.time()
        t = _make_task("t1", status=SwarmTaskStatus.DISPATCHED, dispatched_at=now - 10)
        q.tasks["t1"] = t
        recovered = q.reconcile_stale_dispatched(
            stale_after_ms=300_000, now=now
        )
        assert len(recovered) == 0
        assert q.tasks["t1"].status == SwarmTaskStatus.DISPATCHED

    def test_skips_active_tasks(self) -> None:
        q = SwarmTaskQueue()
        now = time.time()
        t = _make_task("t1", status=SwarmTaskStatus.DISPATCHED, dispatched_at=now - 600)
        q.tasks["t1"] = t
        recovered = q.reconcile_stale_dispatched(
            stale_after_ms=300_000, now=now, active_task_ids={"t1"}
        )
        assert len(recovered) == 0

    def test_ignores_non_dispatched(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.READY)
        recovered = q.reconcile_stale_dispatched(stale_after_ms=1000)
        assert len(recovered) == 0


# =============================================================================
# TaskQueue: add_replan_tasks / add_fixup_tasks
# =============================================================================


class TestAddReplanFixupTasks:
    def test_add_replan_tasks(self) -> None:
        q = SwarmTaskQueue()
        sub = SmartSubtask(id="rp1", description="Replan task", complexity=4)
        added = q.add_replan_tasks([sub], wave=2)
        assert len(added) == 1
        assert q.tasks["rp1"].status == SwarmTaskStatus.READY
        assert q.tasks["rp1"].attempts == 1
        assert q.tasks["rp1"].rescue_context is not None

    def test_add_fixup_tasks(self) -> None:
        q = SwarmTaskQueue()
        q.current_wave = 1
        q.waves = [[], []]
        ft = FixupTask(
            id="fix1",
            description="Fix something",
            fixes_task_id="t1",
            fix_instructions="Redo the widget",
        )
        q.add_fixup_tasks([ft])
        assert q.tasks["fix1"].status == SwarmTaskStatus.READY
        assert q.tasks["fix1"].wave == 1  # set to current_wave


# =============================================================================
# TaskQueue: checkpoint / restore
# =============================================================================


class TestCheckpointRestore:
    def test_roundtrip(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.COMPLETED, wave=0)
        q.tasks["t1"].result = _make_result(output="hello")
        q.tasks["t2"] = _make_task("t2", status=SwarmTaskStatus.PENDING, wave=1, dependencies=["t1"])
        q.waves = [["t1"], ["t2"]]
        q.current_wave = 1
        q.partial_dependency_threshold = 0.7
        q.artifact_aware_skip = False

        state = q.get_checkpoint_state()

        q2 = SwarmTaskQueue()
        q2.restore_from_checkpoint(state)

        assert q2.current_wave == 1
        assert q2.partial_dependency_threshold == 0.7
        assert q2.artifact_aware_skip is False
        assert "t1" in q2.tasks
        assert q2.tasks["t1"].status == SwarmTaskStatus.COMPLETED
        assert q2.tasks["t1"].result is not None
        assert q2.tasks["t1"].result.output == "hello"
        # t2 should become READY after restore (deps satisfied)
        assert q2.tasks["t2"].status == SwarmTaskStatus.READY

    def test_restore_with_result(self) -> None:
        state = {
            "tasks": [
                {
                    "id": "t1",
                    "status": "completed",
                    "result": {
                        "success": True,
                        "output": "done",
                        "tokens_used": 500,
                        "cost_used": 0.01,
                        "duration_ms": 2000,
                    },
                    "attempts": 1,
                    "wave": 0,
                    "description": "Test",
                    "type": "implement",
                    "complexity": 5,
                    "dependencies": [],
                }
            ],
            "waves": [["t1"]],
            "current_wave": 0,
        }
        q = SwarmTaskQueue()
        q.restore_from_checkpoint(state)
        assert q.tasks["t1"].result is not None
        assert q.tasks["t1"].result.tokens_used == 500

    def test_restore_unknown_type_defaults_to_implement(self) -> None:
        state = {
            "tasks": [
                {
                    "id": "t1",
                    "status": "pending",
                    "type": "unknown_type",
                    "description": "x",
                    "dependencies": [],
                }
            ],
            "waves": [["t1"]],
            "current_wave": 0,
        }
        q = SwarmTaskQueue()
        q.restore_from_checkpoint(state)
        assert q.tasks["t1"].type == SubtaskType.IMPLEMENT


# =============================================================================
# TaskQueue: is_current_wave_complete
# =============================================================================


class TestIsCurrentWaveComplete:
    def test_complete_when_all_terminal(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.COMPLETED)
        q.waves = [["t1"]]
        assert q.is_current_wave_complete() is True

    def test_incomplete_when_dispatched(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.DISPATCHED)
        q.waves = [["t1"]]
        assert q.is_current_wave_complete() is False

    def test_complete_past_all_waves(self) -> None:
        q = SwarmTaskQueue()
        q.waves = []
        q.current_wave = 5
        assert q.is_current_wave_complete() is True


# =============================================================================
# TaskQueue: set_retry_after
# =============================================================================


class TestSetRetryAfter:
    def test_sets_timestamp(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1")
        before = time.time()
        q.set_retry_after("t1", 5000)
        assert q.tasks["t1"].retry_after is not None
        assert q.tasks["t1"].retry_after >= before + 4.9

    def test_nonexistent_is_noop(self) -> None:
        q = SwarmTaskQueue()
        q.set_retry_after("ghost", 5000)  # no raise


# =============================================================================
# TaskQueue: un_skip_dependents
# =============================================================================


class TestUnSkipDependents:
    def test_unskip_when_deps_satisfied(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.COMPLETED)
        q.tasks["t1"].result = _make_result()
        t2 = _make_task("t2", status=SwarmTaskStatus.SKIPPED, dependencies=["t1"])
        q.tasks["t2"] = t2
        q.un_skip_dependents("t1")
        assert q.tasks["t2"].status == SwarmTaskStatus.READY

    def test_no_unskip_when_deps_not_satisfied(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.COMPLETED)
        q.tasks["t_other"] = _make_task("t_other", status=SwarmTaskStatus.FAILED)
        t2 = _make_task("t2", status=SwarmTaskStatus.SKIPPED, dependencies=["t1", "t_other"])
        q.tasks["t2"] = t2
        q.un_skip_dependents("t1")
        assert q.tasks["t2"].status == SwarmTaskStatus.SKIPPED


# =============================================================================
# TaskQueue: get_skipped_tasks / get_conflicts
# =============================================================================


class TestAccessors:
    def test_get_skipped_tasks(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.SKIPPED)
        q.tasks["t2"] = _make_task("t2", status=SwarmTaskStatus.COMPLETED)
        assert len(q.get_skipped_tasks()) == 1

    def test_get_conflicts(self) -> None:
        q = SwarmTaskQueue()
        q._conflicts = [ResourceConflict(file_path="a.py", task_ids=["t1", "t2"])]
        conflicts = q.get_conflicts()
        assert len(conflicts) == 1
        assert conflicts[0].file_path == "a.py"

    def test_get_task(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1")
        assert q.get_task("t1") is not None
        assert q.get_task("ghost") is None

    def test_get_all_tasks(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1")
        q.tasks["t2"] = _make_task("t2")
        assert len(q.get_all_tasks()) == 2

    def test_get_current_wave(self) -> None:
        q = SwarmTaskQueue()
        q.current_wave = 3
        assert q.get_current_wave() == 3

    def test_get_total_waves(self) -> None:
        q = SwarmTaskQueue()
        q.waves = [["t1"], ["t2"], ["t3"]]
        assert q.get_total_waves() == 3


# =============================================================================
# QualityGate: run_pre_flight_checks
# =============================================================================


class TestRunPreFlightChecks:
    def test_v4_all_target_files_empty_fails(self, tmp_path: Path) -> None:
        task = _make_task(target_files=[str(tmp_path / "ghost.py")])
        result = _make_result(tool_calls=5)
        artifact = ArtifactReport(all_empty=True, summary="ALL EMPTY")
        gate = run_pre_flight_checks(task, result, cached_artifacts=artifact)
        assert gate is not None
        assert gate.passed is False
        assert gate.artifact_auto_fail is True
        assert gate.score == 1

    def test_v7_requires_tool_calls_zero_fails(self) -> None:
        task = _make_task(task_type=SubtaskType.IMPLEMENT)
        result = _make_result(tool_calls=0)
        gate = run_pre_flight_checks(task, result)
        assert gate is not None
        assert gate.passed is False
        assert gate.pre_flight_reject is True

    def test_passes_when_ok(self) -> None:
        task = _make_task(task_type=SubtaskType.IMPLEMENT)
        result = _make_result(tool_calls=10, files_modified=["a.py"])
        gate = run_pre_flight_checks(task, result)
        assert gate is None  # None means all checks passed

    def test_v7_research_no_tool_calls_ok(self) -> None:
        task = _make_task(task_type=SubtaskType.RESEARCH)
        result = _make_result(tool_calls=0)
        gate = run_pre_flight_checks(task, result)
        # Research does NOT require tool calls
        assert gate is None

    def test_v10_file_creation_no_tool_calls(self) -> None:
        # Use a type that does NOT require tool calls so V7 doesn't fire first
        task = _make_task(
            description="Create a new module for authentication",
            task_type=SubtaskType.RESEARCH,
        )
        result = _make_result(tool_calls=0, files_modified=[])
        gate = run_pre_flight_checks(task, result)
        assert gate is not None
        assert gate.artifact_auto_fail is True

    def test_v6_budget_excuse_findings(self) -> None:
        task = _make_task()
        result = _make_result(
            tool_calls=5,
            closure_report={
                "findings": [
                    "Ran out of budget before completing the task",
                    "Budget limit exceeded",
                ]
            },
        )
        gate = run_pre_flight_checks(task, result)
        assert gate is not None
        assert gate.pre_flight_reject is True

    def test_no_target_files_skips_v4(self) -> None:
        task = _make_task(target_files=None)
        result = _make_result(tool_calls=5)
        gate = run_pre_flight_checks(task, result)
        assert gate is None

    def test_tool_calls_none_skips_v7(self) -> None:
        task = _make_task(task_type=SubtaskType.IMPLEMENT)
        result = _make_result(tool_calls=None)
        gate = run_pre_flight_checks(task, result)
        assert gate is None

    def test_non_empty_artifacts_pass_v4(self) -> None:
        task = _make_task(target_files=["src/main.py"])
        result = _make_result(tool_calls=5)
        artifact = ArtifactReport(all_empty=False, summary="1/1 files exist")
        gate = run_pre_flight_checks(task, result, cached_artifacts=artifact)
        assert gate is None


# =============================================================================
# QualityGate: run_concrete_checks
# =============================================================================


class TestRunConcreteChecks:
    def test_missing_files_issue(self, tmp_path: Path) -> None:
        result = _make_result(files_modified=[str(tmp_path / "nonexistent.py")])
        task = _make_task()
        check = run_concrete_checks(task, result)
        assert check.passed is False
        assert any("does not exist" in i for i in check.issues)

    def test_valid_files_pass(self, tmp_path: Path) -> None:
        f = tmp_path / "valid.py"
        f.write_text("print('hello')\n")
        result = _make_result(files_modified=[str(f)])
        task = _make_task()
        check = run_concrete_checks(task, result)
        assert check.passed is True
        assert len(check.issues) == 0

    def test_empty_file_issue(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.py"
        f.write_text("")
        result = _make_result(files_modified=[str(f)])
        task = _make_task()
        check = run_concrete_checks(task, result)
        assert check.passed is False
        assert any("empty" in i for i in check.issues)

    def test_no_files_modified_passes(self) -> None:
        result = _make_result(files_modified=None)
        task = _make_task()
        check = run_concrete_checks(task, result)
        assert check.passed is True

    def test_json_parse_error(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text("{invalid json")
        result = _make_result(files_modified=[str(f)])
        task = _make_task()
        check = run_concrete_checks(task, result)
        assert check.passed is False
        assert any("JSON parse error" in i for i in check.issues)

    def test_valid_json_passes(self, tmp_path: Path) -> None:
        f = tmp_path / "good.json"
        f.write_text('{"key": "value"}')
        result = _make_result(files_modified=[str(f)])
        task = _make_task()
        check = run_concrete_checks(task, result)
        assert check.passed is True

    def test_brace_imbalance_issue(self, tmp_path: Path) -> None:
        f = tmp_path / "imbalanced.py"
        f.write_text("{ { { { }")  # 4 open, 1 close -> diff=3, but check is >3
        result = _make_result(files_modified=[str(f)])
        task = _make_task()
        check = run_concrete_checks(task, result)
        # imbalance of 3, threshold is >3, so it should pass
        assert check.passed is True

    def test_severe_brace_imbalance(self, tmp_path: Path) -> None:
        f = tmp_path / "severe.ts"
        f.write_text("{ { { { {")  # 5 open, 0 close -> diff=5
        result = _make_result(files_modified=[str(f)])
        task = _make_task()
        check = run_concrete_checks(task, result)
        assert check.passed is False
        assert any("Brace imbalance" in i for i in check.issues)


# =============================================================================
# QualityGate: check_artifacts
# =============================================================================


class TestCheckArtifacts:
    def test_with_existing_files(self, tmp_path: Path) -> None:
        f = tmp_path / "module.py"
        f.write_text("class Foo: pass\n")
        task = _make_task(target_files=[str(f)])
        report = check_artifacts(task)
        assert report.all_empty is False
        assert len(report.files) == 1
        assert report.files[0]["exists"] is True
        assert report.files[0]["size"] > 0

    def test_with_missing_files(self) -> None:
        task = _make_task(target_files=["/nonexistent/path/x.py"])
        report = check_artifacts(task)
        assert report.all_empty is True
        assert report.files[0]["exists"] is False

    def test_no_target_files(self) -> None:
        task = _make_task(target_files=None)
        report = check_artifacts(task)
        assert report.all_empty is False
        assert "No target files" in report.summary

    def test_empty_file_counts_as_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.py"
        f.write_text("")
        task = _make_task(target_files=[str(f)])
        report = check_artifacts(task)
        assert report.all_empty is True

    def test_mixed_existing_missing(self, tmp_path: Path) -> None:
        existing = tmp_path / "exists.py"
        existing.write_text("x = 1\n")
        task = _make_task(target_files=[str(existing), "/no/such/file.py"])
        report = check_artifacts(task)
        assert report.all_empty is False
        assert len(report.files) == 2


# =============================================================================
# QualityGate: check_artifacts_enhanced
# =============================================================================


class TestCheckArtifactsEnhanced:
    def test_searches_output_for_file_paths(self, tmp_path: Path) -> None:
        f = tmp_path / "found.py"
        f.write_text("hello = True\n")
        result = _make_result(
            output=f"I created {f}\n",
            files_modified=None,
        )
        task = _make_task(target_files=None)
        report = check_artifacts_enhanced(task, result, base_dir=str(tmp_path))
        # The absolute path should be found in the output
        assert len(report.files) >= 1

    def test_combines_target_and_modified(self, tmp_path: Path) -> None:
        f1 = tmp_path / "target.py"
        f1.write_text("a")
        f2 = tmp_path / "modified.py"
        f2.write_text("b")
        result = _make_result(files_modified=[str(f2)])
        task = _make_task(target_files=[str(f1)])
        report = check_artifacts_enhanced(task, result)
        assert len(report.files) == 2
        assert report.all_empty is False

    def test_no_paths_at_all(self) -> None:
        result = _make_result(output="Some text with no file paths", files_modified=None)
        task = _make_task(target_files=None)
        report = check_artifacts_enhanced(task, result)
        assert "No artifact files" in report.summary

    def test_relative_paths_resolved(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        f = tmp_path / "src" / "app.py"
        f.write_text("main()")
        result = _make_result(output="Created src/app.py\n", files_modified=None)
        task = _make_task(target_files=None)
        report = check_artifacts_enhanced(task, result, base_dir=str(tmp_path))
        found = [e for e in report.files if e["path"] == "src/app.py"]
        assert len(found) == 1
        assert found[0]["exists"] is True


# =============================================================================
# WorkerPool: select_worker
# =============================================================================


class TestWorkerPoolSelectWorker:
    def _make_pool(
        self,
        workers: list[SwarmWorkerSpec] | None = None,
        health_tracker: Any = None,
    ) -> SwarmWorkerPool:
        config = _make_config(
            workers=workers or [_make_worker()],
            max_concurrency=3,
        )
        return SwarmWorkerPool(
            config=config,
            spawn_agent_fn=AsyncMock(),
            budget_pool=None,
            health_tracker=health_tracker,
        )

    def test_matches_code_capability(self) -> None:
        pool = self._make_pool(
            workers=[
                _make_worker("coder", "m1", [WorkerCapability.CODE]),
                _make_worker("researcher", "m2", [WorkerCapability.RESEARCH]),
            ]
        )
        task = _make_task(task_type=SubtaskType.IMPLEMENT)
        selected = pool.select_worker(task)
        assert selected is not None
        assert selected.name == "coder"

    def test_matches_research_capability(self) -> None:
        pool = self._make_pool(
            workers=[
                _make_worker("coder", "m1", [WorkerCapability.CODE]),
                _make_worker("researcher", "m2", [WorkerCapability.RESEARCH]),
            ]
        )
        task = _make_task(task_type=SubtaskType.RESEARCH)
        selected = pool.select_worker(task)
        assert selected is not None
        assert selected.name == "researcher"

    def test_fallback_test_to_code(self) -> None:
        pool = self._make_pool(
            workers=[_make_worker("coder", "m1", [WorkerCapability.CODE])]
        )
        task = _make_task(task_type=SubtaskType.TEST)
        selected = pool.select_worker(task)
        assert selected is not None
        assert WorkerCapability.CODE in selected.capabilities

    def test_fallback_to_first_worker(self) -> None:
        pool = self._make_pool(
            workers=[_make_worker("default", "m1", [WorkerCapability.CODE])]
        )
        # DOCUMENT fallback -> CODE workers
        task = _make_task(task_type=SubtaskType.DOCUMENT)
        selected = pool.select_worker(task)
        assert selected is not None

    def test_no_workers_returns_none(self) -> None:
        config = _make_config(workers=[], max_concurrency=1)
        pool = SwarmWorkerPool(
            config=config, spawn_agent_fn=AsyncMock(), budget_pool=None
        )
        task = _make_task()
        assert pool.select_worker(task) is None

    def test_prefers_healthy_with_tracker(self) -> None:
        @dataclass
        class _HealthRecord:
            healthy: bool
            success_rate: float

        tracker = MagicMock()
        tracker.get.side_effect = lambda model: (
            _HealthRecord(healthy=True, success_rate=0.9) if model == "healthy-m"
            else _HealthRecord(healthy=False, success_rate=0.3)
        )
        pool = self._make_pool(
            workers=[
                _make_worker("bad", "unhealthy-m", [WorkerCapability.CODE]),
                _make_worker("good", "healthy-m", [WorkerCapability.CODE]),
            ],
            health_tracker=tracker,
        )
        task = _make_task(task_type=SubtaskType.IMPLEMENT)
        selected = pool.select_worker(task)
        assert selected is not None
        assert selected.name == "good"


# =============================================================================
# WorkerPool: dispatch
# =============================================================================


class TestWorkerPoolDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_creates_task(self) -> None:
        spawn_fn = AsyncMock(return_value=SpawnResult(success=True, output="ok"))
        worker = _make_worker()
        config = _make_config(workers=[worker], max_concurrency=3)
        pool = SwarmWorkerPool(
            config=config,
            spawn_agent_fn=spawn_fn,
            budget_pool=MagicMock(),
        )
        task = _make_task("t1", status=SwarmTaskStatus.READY)
        await pool.dispatch(task, worker)
        assert pool.active_count == 1
        assert "t1" in pool.get_active_task_ids()

    @pytest.mark.asyncio
    async def test_dispatch_raises_no_worker(self) -> None:
        config = _make_config(workers=[], max_concurrency=1)
        pool = SwarmWorkerPool(
            config=config, spawn_agent_fn=AsyncMock(), budget_pool=None
        )
        with pytest.raises(RuntimeError, match="No worker"):
            await pool.dispatch(_make_task())


# =============================================================================
# WorkerPool: wait_for_any
# =============================================================================


class TestWorkerPoolWaitForAny:
    @pytest.mark.asyncio
    async def test_returns_completed_result(self) -> None:
        spawn_fn = AsyncMock(
            return_value=SpawnResult(success=True, output="done", tool_calls=3)
        )
        worker = _make_worker()
        config = _make_config(workers=[worker], max_concurrency=3)
        pool = SwarmWorkerPool(
            config=config,
            spawn_agent_fn=spawn_fn,
            budget_pool=MagicMock(),
        )
        task = _make_task("t1")
        await pool.dispatch(task, worker)
        result = await pool.wait_for_any()
        assert result is not None
        task_id, spawn_result, started_at = result
        assert task_id == "t1"
        assert spawn_result.success is True

    @pytest.mark.asyncio
    async def test_returns_none_when_empty(self) -> None:
        config = _make_config(workers=[_make_worker()], max_concurrency=1)
        pool = SwarmWorkerPool(
            config=config, spawn_agent_fn=AsyncMock(), budget_pool=None
        )
        result = await pool.wait_for_any()
        assert result is None


# =============================================================================
# WorkerPool: available_slots / active_count
# =============================================================================


class TestWorkerPoolSlots:
    def test_available_slots_initial(self) -> None:
        config = _make_config(workers=[_make_worker()], max_concurrency=5)
        pool = SwarmWorkerPool(
            config=config, spawn_agent_fn=AsyncMock(), budget_pool=None
        )
        assert pool.available_slots == 5
        assert pool.active_count == 0

    @pytest.mark.asyncio
    async def test_slots_decrease_on_dispatch(self) -> None:
        spawn_fn = AsyncMock(return_value=SpawnResult(success=True, output="ok"))
        worker = _make_worker()
        config = _make_config(workers=[worker], max_concurrency=3)
        pool = SwarmWorkerPool(
            config=config, spawn_agent_fn=spawn_fn, budget_pool=MagicMock()
        )
        await pool.dispatch(_make_task("t1"), worker)
        assert pool.available_slots == 2
        assert pool.active_count == 1


# =============================================================================
# WorkerPool: cancel_all
# =============================================================================


class TestWorkerPoolCancelAll:
    @pytest.mark.asyncio
    async def test_cancel_all_clears_active(self) -> None:
        # Spawn function that never returns
        async def slow_spawn(**kwargs: Any) -> SpawnResult:
            await asyncio.sleep(999)
            return SpawnResult(success=False, output="unreachable")

        worker = _make_worker()
        config = _make_config(workers=[worker], max_concurrency=3, worker_timeout=120_000)
        pool = SwarmWorkerPool(
            config=config,
            spawn_agent_fn=slow_spawn,
            budget_pool=MagicMock(),
        )
        await pool.dispatch(_make_task("t1"), worker)
        assert pool.active_count == 1

        await pool.cancel_all()
        assert pool.active_count == 0


# =============================================================================
# WorkerPool: _compute_worker_budget
# =============================================================================


class TestComputeWorkerBudget:
    def _make_pool_for_budget(self, max_tokens_per_worker: int = 100_000) -> SwarmWorkerPool:
        config = _make_config(
            workers=[_make_worker()],
            max_concurrency=1,
            max_tokens_per_worker=max_tokens_per_worker,
        )
        return SwarmWorkerPool(
            config=config, spawn_agent_fn=AsyncMock(), budget_pool=None
        )

    def test_scales_by_complexity(self) -> None:
        pool = self._make_pool_for_budget(max_tokens_per_worker=200_000)
        worker = _make_worker(max_tokens=200_000)
        # implement: min=40_000, max=150_000
        task_low = _make_task(complexity=1, task_type=SubtaskType.IMPLEMENT)
        task_high = _make_task(complexity=10, task_type=SubtaskType.IMPLEMENT)
        budget_low = pool._compute_worker_budget(task_low, worker)
        budget_high = pool._compute_worker_budget(task_high, worker)
        assert budget_low["max_tokens"] < budget_high["max_tokens"]

    def test_capped_at_worker_max(self) -> None:
        pool = self._make_pool_for_budget(max_tokens_per_worker=200_000)
        worker = _make_worker(max_tokens=10_000)
        task = _make_task(complexity=10, task_type=SubtaskType.IMPLEMENT)
        budget = pool._compute_worker_budget(task, worker)
        assert budget["max_tokens"] <= 10_000

    def test_capped_at_config_max(self) -> None:
        pool = self._make_pool_for_budget(max_tokens_per_worker=5_000)
        worker = _make_worker(max_tokens=200_000)
        task = _make_task(complexity=10, task_type=SubtaskType.IMPLEMENT)
        budget = pool._compute_worker_budget(task, worker)
        assert budget["max_tokens"] <= 5_000

    def test_unknown_type_uses_defaults(self) -> None:
        pool = self._make_pool_for_budget(max_tokens_per_worker=200_000)
        worker = _make_worker(max_tokens=200_000)
        task = _make_task(complexity=5)
        # Manually set a type that is not in BUILTIN or custom
        task.type = "nonexistent_type"  # type: ignore[assignment]
        budget = pool._compute_worker_budget(task, worker)
        # Should use defaults: min=20_000, max=80_000
        expected = int(20_000 + (80_000 - 20_000) * 5 / 10)
        assert budget["max_tokens"] == expected

    def test_includes_timeout(self) -> None:
        pool = self._make_pool_for_budget()
        worker = _make_worker()
        task = _make_task(task_type=SubtaskType.IMPLEMENT)
        budget = pool._compute_worker_budget(task, worker)
        assert "timeout_ms" in budget
        assert budget["timeout_ms"] > 0


# =============================================================================
# WorkerPool: _build_worker_system_prompt
# =============================================================================


class TestBuildWorkerSystemPrompt:
    def _make_pool(self) -> SwarmWorkerPool:
        config = _make_config(workers=[_make_worker()], max_concurrency=1)
        return SwarmWorkerPool(
            config=config, spawn_agent_fn=AsyncMock(), budget_pool=None
        )

    def test_minimal_tier(self) -> None:
        pool = self._make_pool()
        worker = _make_worker(prompt_tier="minimal")
        task = _make_task(description="Fix the bug")
        prompt = pool._build_worker_system_prompt(task, worker, attempt=0)
        assert "Fix the bug" in prompt
        # Minimal should NOT include quality self-assessment or environment
        assert "Quality Self-Assessment" not in prompt
        assert "Environment" not in prompt

    def test_reduced_tier(self) -> None:
        pool = self._make_pool()
        worker = _make_worker(prompt_tier="full")
        task = _make_task(description="Refactor module")
        # attempt > 0 forces reduced tier
        prompt = pool._build_worker_system_prompt(task, worker, attempt=1)
        assert "Refactor module" in prompt
        assert "Environment" in prompt
        # Should NOT have quality self-assessment (that's full only)
        assert "Quality Self-Assessment" not in prompt

    def test_full_tier(self) -> None:
        pool = self._make_pool()
        worker = _make_worker(prompt_tier="full")
        task = _make_task(description="Build feature X")
        prompt = pool._build_worker_system_prompt(task, worker, attempt=0)
        assert "Build feature X" in prompt
        assert "Quality Self-Assessment" in prompt
        assert "Goal Recitation" in prompt

    def test_includes_target_files(self) -> None:
        pool = self._make_pool()
        worker = _make_worker()
        task = _make_task(target_files=["src/foo.py", "src/bar.py"])
        prompt = pool._build_worker_system_prompt(task, worker, attempt=0)
        assert "src/foo.py" in prompt
        assert "src/bar.py" in prompt

    def test_includes_dependency_context(self) -> None:
        pool = self._make_pool()
        worker = _make_worker()
        task = _make_task()
        task.dependency_context = "Dep output: data model is ready"
        prompt = pool._build_worker_system_prompt(task, worker, attempt=0)
        assert "Dep output: data model is ready" in prompt

    def test_includes_partial_context(self) -> None:
        pool = self._make_pool()
        worker = _make_worker()
        task = _make_task()
        task.partial_context = PartialContext(
            succeeded=["Task A done"],
            failed=["Task B failed"],
            ratio=0.5,
        )
        prompt = pool._build_worker_system_prompt(task, worker, attempt=0)
        assert "Task A done" in prompt
        assert "Task B failed" in prompt

    def test_research_template_no_delegation_spec(self) -> None:
        pool = self._make_pool()
        worker = _make_worker()
        task = _make_task(task_type=SubtaskType.RESEARCH)
        prompt = pool._build_worker_system_prompt(task, worker, attempt=0)
        assert "Delegation Spec" not in prompt


# =============================================================================
# ModelSelector: ModelHealthTracker.record_success
# =============================================================================


class TestModelHealthTrackerRecordSuccess:
    def test_increments_successes(self) -> None:
        t = ModelHealthTracker()
        t.record_success("m1", 100.0)
        record = t._records["m1"]
        assert record.successes == 1
        assert record.healthy is True

    def test_updates_ema_latency(self) -> None:
        t = ModelHealthTracker()
        t.record_success("m1", 100.0)
        assert t._records["m1"].average_latency_ms == 100.0
        t.record_success("m1", 200.0)
        # EMA: 0.7 * 100 + 0.3 * 200 = 130
        assert abs(t._records["m1"].average_latency_ms - 130.0) < 0.01

    def test_recomputes_success_rate(self) -> None:
        t = ModelHealthTracker()
        t.record_success("m1", 50.0)
        assert t._records["m1"].success_rate == 1.0

    def test_multiple_successes(self) -> None:
        t = ModelHealthTracker()
        for _ in range(5):
            t.record_success("m1", 100.0)
        assert t._records["m1"].successes == 5
        assert t._records["m1"].success_rate == 1.0


# =============================================================================
# ModelSelector: ModelHealthTracker.record_failure
# =============================================================================


class TestModelHealthTrackerRecordFailure:
    def test_increments_failures(self) -> None:
        t = ModelHealthTracker()
        t.record_failure("m1", "error")
        assert t._records["m1"].failures == 1

    def test_marks_unhealthy_at_threshold(self) -> None:
        t = ModelHealthTracker()
        # Need 3+ total with >50% failure
        t.record_failure("m1", "error")
        t.record_failure("m1", "error")
        t.record_failure("m1", "error")
        assert t._records["m1"].healthy is False

    def test_rate_limit_burst_detection(self) -> None:
        t = ModelHealthTracker()
        t.record_failure("m1", "429")
        t.record_failure("m1", "429")
        assert t._records["m1"].healthy is False
        assert t._records["m1"].rate_limits == 2

    def test_single_rate_limit_stays_healthy(self) -> None:
        t = ModelHealthTracker()
        # One rate limit + some successes
        t.record_success("m1", 100)
        t.record_success("m1", 100)
        t.record_failure("m1", "429")
        # 1 failure / 3 total = 33% < 50%, only 1 rate limit < burst threshold
        assert t._records["m1"].healthy is True

    def test_recomputes_success_rate_on_failure(self) -> None:
        t = ModelHealthTracker()
        t.record_success("m1", 100)
        t.record_failure("m1", "error")
        assert t._records["m1"].success_rate == 0.5


# =============================================================================
# ModelSelector: ModelHealthTracker.record_quality_rejection
# =============================================================================


class TestModelHealthTrackerRecordQualityRejection:
    def test_undoes_premature_success(self) -> None:
        t = ModelHealthTracker()
        t.record_success("m1", 100.0)
        assert t._records["m1"].successes == 1
        t.record_quality_rejection("m1", 2)
        assert t._records["m1"].successes == 0
        assert t._records["m1"].failures == 1
        assert t._records["m1"].quality_rejections == 1

    def test_unhealthy_at_3_rejections(self) -> None:
        t = ModelHealthTracker()
        for _ in range(3):
            t.record_success("m1", 100.0)
            t.record_quality_rejection("m1", 2)
        assert t._records["m1"].healthy is False

    def test_no_negative_successes(self) -> None:
        t = ModelHealthTracker()
        t.record_quality_rejection("m1", 1)
        # Should not go below 0
        assert t._records["m1"].successes == 0


# =============================================================================
# ModelSelector: ModelHealthTracker.record_hollow
# =============================================================================


class TestModelHealthTrackerRecordHollow:
    def test_increments_hollow_count(self) -> None:
        t = ModelHealthTracker()
        t.record_hollow("m1")
        assert t._hollow_counts["m1"] == 1
        t.record_hollow("m1")
        assert t._hollow_counts["m1"] == 2

    def test_also_records_failure(self) -> None:
        t = ModelHealthTracker()
        t.record_hollow("m1")
        assert t._records["m1"].failures == 1

    def test_get_hollow_rate(self) -> None:
        t = ModelHealthTracker()
        t.record_success("m1", 100)
        t.record_hollow("m1")
        # 1 hollow / (1 success + 1 failure) = 0.5
        assert abs(t.get_hollow_rate("m1") - 0.5) < 0.01

    def test_get_hollow_count(self) -> None:
        t = ModelHealthTracker()
        assert t.get_hollow_count("m1") == 0
        t.record_hollow("m1")
        assert t.get_hollow_count("m1") == 1


# =============================================================================
# ModelSelector: ModelHealthTracker.is_healthy
# =============================================================================


class TestModelHealthTrackerIsHealthy:
    def test_unknown_model_is_healthy(self) -> None:
        t = ModelHealthTracker()
        assert t.is_healthy("unknown-model") is True

    def test_after_success_is_healthy(self) -> None:
        t = ModelHealthTracker()
        t.record_success("m1", 100)
        assert t.is_healthy("m1") is True

    def test_after_forced_unhealthy(self) -> None:
        t = ModelHealthTracker()
        t.mark_unhealthy("m1")
        assert t.is_healthy("m1") is False


# =============================================================================
# ModelSelector: ModelHealthTracker.get_success_rate
# =============================================================================


class TestModelHealthTrackerGetSuccessRate:
    def test_unknown_returns_1(self) -> None:
        t = ModelHealthTracker()
        assert t.get_success_rate("unknown") == 1.0

    def test_all_successes(self) -> None:
        t = ModelHealthTracker()
        t.record_success("m1", 100)
        t.record_success("m1", 100)
        assert t.get_success_rate("m1") == 1.0

    def test_mixed(self) -> None:
        t = ModelHealthTracker()
        t.record_success("m1", 100)
        t.record_failure("m1", "error")
        assert t.get_success_rate("m1") == 0.5


# =============================================================================
# ModelSelector: ModelHealthTracker.restore
# =============================================================================


class TestModelHealthTrackerRestore:
    def test_clears_state(self) -> None:
        t = ModelHealthTracker()
        t.record_success("m1", 100)
        t.record_hollow("m1")
        t.restore([])
        assert len(t._records) == 0
        assert len(t._hollow_counts) == 0

    def test_restores_records(self) -> None:
        t = ModelHealthTracker()
        record = ModelHealthRecord(
            model="m1", successes=5, failures=2, healthy=True, success_rate=0.714
        )
        t.restore([record])
        assert "m1" in t._records
        assert t._records["m1"].successes == 5
        assert t._records["m1"].failures == 2

    def test_get_all_records(self) -> None:
        t = ModelHealthTracker()
        t.record_success("m1", 100)
        t.record_success("m2", 200)
        records = t.get_all_records()
        assert len(records) == 2

    def test_get_healthy_filters(self) -> None:
        t = ModelHealthTracker()
        t.record_success("m1", 100)
        t.mark_unhealthy("m2")
        healthy = t.get_healthy(["m1", "m2", "m3"])
        assert "m1" in healthy
        assert "m3" in healthy  # unknown = healthy
        assert "m2" not in healthy


# =============================================================================
# ModelSelector: select_worker_for_capability
# =============================================================================


class TestSelectWorkerForCapability:
    def test_basic_matching(self) -> None:
        workers = [
            _make_worker("coder", "m1", [WorkerCapability.CODE]),
            _make_worker("researcher", "m2", [WorkerCapability.RESEARCH]),
        ]
        selected = select_worker_for_capability(workers, WorkerCapability.CODE)
        assert selected is not None
        assert selected.name == "coder"

    def test_round_robin(self) -> None:
        workers = [
            _make_worker("coder1", "m1", [WorkerCapability.CODE]),
            _make_worker("coder2", "m2", [WorkerCapability.CODE]),
        ]
        s0 = select_worker_for_capability(workers, WorkerCapability.CODE, task_index=0)
        s1 = select_worker_for_capability(workers, WorkerCapability.CODE, task_index=1)
        assert s0 is not None and s1 is not None
        assert s0.name != s1.name

    def test_fallback_test_to_code(self) -> None:
        workers = [_make_worker("coder", "m1", [WorkerCapability.CODE])]
        selected = select_worker_for_capability(workers, WorkerCapability.TEST)
        assert selected is not None
        assert WorkerCapability.CODE in selected.capabilities

    def test_fallback_write_to_code(self) -> None:
        workers = [_make_worker("coder", "m1", [WorkerCapability.CODE])]
        selected = select_worker_for_capability(workers, WorkerCapability.WRITE)
        assert selected is not None

    def test_no_match_falls_to_first(self) -> None:
        workers = [_make_worker("coder", "m1", [WorkerCapability.CODE])]
        selected = select_worker_for_capability(workers, WorkerCapability.DOCUMENT)
        assert selected is not None
        assert selected.name == "coder"

    def test_empty_returns_none(self) -> None:
        assert select_worker_for_capability([], WorkerCapability.CODE) is None

    def test_with_health_ranking(self) -> None:
        tracker = ModelHealthTracker()
        tracker.record_success("healthy-m", 100)
        tracker.record_failure("unhealthy-m", "error")
        tracker.record_failure("unhealthy-m", "error")
        tracker.record_failure("unhealthy-m", "error")

        workers = [
            _make_worker("bad", "unhealthy-m", [WorkerCapability.CODE]),
            _make_worker("good", "healthy-m", [WorkerCapability.CODE]),
        ]
        selected = select_worker_for_capability(
            workers, WorkerCapability.CODE, health_tracker=tracker
        )
        assert selected is not None
        assert selected.name == "good"

    def test_single_match_returns_it(self) -> None:
        workers = [
            _make_worker("coder", "m1", [WorkerCapability.CODE]),
            _make_worker("researcher", "m2", [WorkerCapability.RESEARCH]),
        ]
        selected = select_worker_for_capability(workers, WorkerCapability.RESEARCH)
        assert selected is not None
        assert selected.name == "researcher"


# =============================================================================
# ModelSelector: select_alternative_model
# =============================================================================


class TestSelectAlternativeModel:
    def test_finds_different_model(self) -> None:
        workers = [
            _make_worker("c1", "m1", [WorkerCapability.CODE]),
            _make_worker("c2", "m2", [WorkerCapability.CODE]),
        ]
        alt = select_alternative_model(workers, "m1", WorkerCapability.CODE)
        assert alt is not None
        assert alt.model == "m2"

    def test_no_alternative_returns_none(self) -> None:
        workers = [_make_worker("c1", "m1", [WorkerCapability.CODE])]
        alt = select_alternative_model(workers, "m1", WorkerCapability.CODE)
        assert alt is None

    def test_write_falls_back_to_code(self) -> None:
        workers = [
            _make_worker("writer", "m1", [WorkerCapability.WRITE]),
            _make_worker("coder", "m2", [WorkerCapability.CODE]),
        ]
        alt = select_alternative_model(workers, "m1", WorkerCapability.WRITE)
        assert alt is not None
        assert alt.model == "m2"

    def test_prefers_healthy(self) -> None:
        tracker = ModelHealthTracker()
        tracker.mark_unhealthy("m2")
        tracker.record_success("m3", 100)

        workers = [
            _make_worker("c1", "m1", [WorkerCapability.CODE]),
            _make_worker("c2", "m2", [WorkerCapability.CODE]),
            _make_worker("c3", "m3", [WorkerCapability.CODE]),
        ]
        alt = select_alternative_model(
            workers, "m1", WorkerCapability.CODE, health_tracker=tracker
        )
        assert alt is not None
        assert alt.model == "m3"

    def test_empty_workers(self) -> None:
        assert select_alternative_model([], "m1", WorkerCapability.CODE) is None

    def test_any_worker_fallback(self) -> None:
        workers = [
            _make_worker("c1", "m1", [WorkerCapability.CODE]),
            _make_worker("r1", "m2", [WorkerCapability.RESEARCH]),
        ]
        # Looking for DOCUMENT but c1 is the failed model, so fallback to any different model
        alt = select_alternative_model(workers, "m1", WorkerCapability.DOCUMENT)
        assert alt is not None
        assert alt.model == "m2"


# =============================================================================
# ModelSelector: get_fallback_workers
# =============================================================================


class TestGetFallbackWorkers:
    def test_has_5_entries(self) -> None:
        assert len(FALLBACK_WORKERS) == 5

    def test_appends_reviewer(self) -> None:
        workers = get_fallback_workers("my-orch-model")
        assert len(workers) == 6  # 5 + reviewer
        reviewer = workers[-1]
        assert reviewer.name == "reviewer"
        assert reviewer.model == "my-orch-model"
        assert WorkerCapability.REVIEW in reviewer.capabilities

    def test_does_not_modify_global(self) -> None:
        get_fallback_workers("model-a")
        assert len(FALLBACK_WORKERS) == 5  # unchanged

    def test_fallback_worker_capabilities(self) -> None:
        # Verify coder has CODE + TEST
        coder = FALLBACK_WORKERS[0]
        assert WorkerCapability.CODE in coder.capabilities
        assert WorkerCapability.TEST in coder.capabilities

    def test_fallback_researcher_capabilities(self) -> None:
        researcher = FALLBACK_WORKERS[3]
        assert WorkerCapability.RESEARCH in researcher.capabilities
        assert WorkerCapability.REVIEW in researcher.capabilities

    def test_fallback_documenter_capabilities(self) -> None:
        documenter = FALLBACK_WORKERS[4]
        assert WorkerCapability.DOCUMENT in documenter.capabilities


# =============================================================================
# ModelSelector: ModelHealthTracker.get_hollow_rate edge cases
# =============================================================================


class TestModelHealthTrackerHollowRate:
    def test_zero_for_unknown(self) -> None:
        t = ModelHealthTracker()
        assert t.get_hollow_rate("unknown") == 0.0

    def test_zero_when_no_hollows(self) -> None:
        t = ModelHealthTracker()
        t.record_success("m1", 100)
        assert t.get_hollow_rate("m1") == 0.0

    def test_hollow_rate_calculation(self) -> None:
        t = ModelHealthTracker()
        t.record_success("m1", 100)
        t.record_success("m1", 100)
        t.record_hollow("m1")
        # 1 hollow / (2 success + 1 failure) = 1/3
        assert abs(t.get_hollow_rate("m1") - 1 / 3) < 0.01


# =============================================================================
# FAILURE_MODE_THRESHOLDS verification
# =============================================================================


class TestFailureModeThresholds:
    def test_all_modes_present(self) -> None:
        expected_modes = {"timeout", "rate-limit", "error", "quality", "hollow", "cascade"}
        assert set(FAILURE_MODE_THRESHOLDS.keys()) == expected_modes

    def test_values_between_0_and_1(self) -> None:
        for mode, threshold in FAILURE_MODE_THRESHOLDS.items():
            assert 0.0 <= threshold <= 1.0, f"Threshold for {mode} out of range: {threshold}"

    def test_specific_values(self) -> None:
        assert FAILURE_MODE_THRESHOLDS["timeout"] == 0.3
        assert FAILURE_MODE_THRESHOLDS["rate-limit"] == 0.3
        assert FAILURE_MODE_THRESHOLDS["error"] == 0.5
        assert FAILURE_MODE_THRESHOLDS["quality"] == 0.7
        assert FAILURE_MODE_THRESHOLDS["hollow"] == 0.7
        assert FAILURE_MODE_THRESHOLDS["cascade"] == 0.8


# =============================================================================
# TaskQueue: artifact_aware_skip
# =============================================================================


class TestArtifactAwareSkip:
    def test_keeps_dependent_when_artifacts_exist(self, tmp_path: Path) -> None:
        q = SwarmTaskQueue(working_directory=str(tmp_path))
        q.artifact_aware_skip = True

        # Create the target file on disk
        target = tmp_path / "output.py"
        target.write_text("result = 42\n")

        t1 = _make_task("t1", status=SwarmTaskStatus.FAILED, target_files=["output.py"])
        q.tasks["t1"] = t1
        q.tasks["t2"] = _make_task("t2", dependencies=["t1"], status=SwarmTaskStatus.PENDING)
        q.waves = [["t1"], ["t2"]]
        q.trigger_cascade_skip("t1")
        # t2 should NOT be skipped because artifact exists
        assert q.tasks["t2"].status != SwarmTaskStatus.SKIPPED

    def test_skips_when_no_artifacts(self) -> None:
        q = SwarmTaskQueue(working_directory="/nonexistent/dir")
        q.artifact_aware_skip = True

        t1 = _make_task("t1", status=SwarmTaskStatus.FAILED, target_files=["missing.py"])
        q.tasks["t1"] = t1
        q.tasks["t2"] = _make_task("t2", dependencies=["t1"], status=SwarmTaskStatus.PENDING)
        q.waves = [["t1"], ["t2"]]
        q.trigger_cascade_skip("t1")
        assert q.tasks["t2"].status == SwarmTaskStatus.SKIPPED


# =============================================================================
# WorkerPool: _get_prompt_tier
# =============================================================================


class TestGetPromptTier:
    def _make_pool(self) -> SwarmWorkerPool:
        config = _make_config(workers=[_make_worker()], max_concurrency=1)
        return SwarmWorkerPool(
            config=config, spawn_agent_fn=AsyncMock(), budget_pool=None
        )

    def test_minimal_worker(self) -> None:
        pool = self._make_pool()
        worker = _make_worker(prompt_tier="minimal")
        assert pool._get_prompt_tier(worker, attempt=0) == "minimal"

    def test_retry_forces_reduced(self) -> None:
        pool = self._make_pool()
        worker = _make_worker(prompt_tier="full")
        assert pool._get_prompt_tier(worker, attempt=1) == "reduced"

    def test_first_attempt_full(self) -> None:
        pool = self._make_pool()
        worker = _make_worker(prompt_tier="full")
        assert pool._get_prompt_tier(worker, attempt=0) == "full"

    def test_minimal_overrides_retry(self) -> None:
        pool = self._make_pool()
        worker = _make_worker(prompt_tier="minimal")
        assert pool._get_prompt_tier(worker, attempt=1) == "minimal"


# =============================================================================
# WorkerPool: cleanup
# =============================================================================


class TestWorkerPoolCleanup:
    def test_cleanup_clears_state(self) -> None:
        config = _make_config(workers=[_make_worker()], max_concurrency=1)
        pool = SwarmWorkerPool(
            config=config, spawn_agent_fn=AsyncMock(), budget_pool=None
        )
        pool._completed_results["t1"] = (SpawnResult(success=True, output=""), 0.0)
        pool.cleanup()
        assert len(pool._completed_results) == 0
        assert len(pool._active_workers) == 0


# =============================================================================
# WorkerPool: _match_capability
# =============================================================================


class TestMatchCapability:
    def _make_pool(self, task_types: dict | None = None) -> SwarmWorkerPool:
        config = _make_config(
            workers=[_make_worker()],
            max_concurrency=1,
            task_types=task_types or {},
        )
        return SwarmWorkerPool(
            config=config, spawn_agent_fn=AsyncMock(), budget_pool=None
        )

    def test_builtin_implement(self) -> None:
        pool = self._make_pool()
        assert pool._match_capability("implement") == WorkerCapability.CODE

    def test_builtin_research(self) -> None:
        pool = self._make_pool()
        assert pool._match_capability("research") == WorkerCapability.RESEARCH

    def test_builtin_test(self) -> None:
        pool = self._make_pool()
        assert pool._match_capability("test") == WorkerCapability.TEST

    def test_builtin_review(self) -> None:
        pool = self._make_pool()
        assert pool._match_capability("review") == WorkerCapability.REVIEW

    def test_builtin_document(self) -> None:
        pool = self._make_pool()
        assert pool._match_capability("document") == WorkerCapability.DOCUMENT

    def test_unknown_defaults_to_code(self) -> None:
        pool = self._make_pool()
        assert pool._match_capability("totally_unknown") == WorkerCapability.CODE

    def test_custom_task_type(self) -> None:
        from attocode.integrations.swarm.types import TaskTypeConfig
        custom = {
            "my_custom": TaskTypeConfig(
                capability=WorkerCapability.WRITE,
                requires_tool_calls=False,
                prompt_template="code",
                timeout=120,
            )
        }
        pool = self._make_pool(task_types=custom)
        assert pool._match_capability("my_custom") == WorkerCapability.WRITE


# =============================================================================
# Quality gate: _parse_quality_response (indirect test via evaluate_worker_output)
# =============================================================================


class TestParseQualityResponse:
    def test_parse_score_and_feedback(self) -> None:
        from attocode.integrations.swarm.quality_gate import _parse_quality_response
        score, feedback = _parse_quality_response("SCORE: 4\nFEEDBACK: Good work")
        assert score == 4
        assert feedback == "Good work"

    def test_fallback_on_missing_score(self) -> None:
        from attocode.integrations.swarm.quality_gate import _parse_quality_response
        score, feedback = _parse_quality_response("Some random text")
        assert score == 3  # safe default

    def test_score_out_of_range_uses_default(self) -> None:
        from attocode.integrations.swarm.quality_gate import _parse_quality_response
        score, _ = _parse_quality_response("SCORE: 9\nFEEDBACK: wow")
        assert score == 3  # 9 is outside 1-5

    def test_score_zero_uses_default(self) -> None:
        from attocode.integrations.swarm.quality_gate import _parse_quality_response
        score, _ = _parse_quality_response("SCORE: 0\nFEEDBACK: bad")
        assert score == 3  # 0 is outside 1-5

    def test_case_insensitive(self) -> None:
        from attocode.integrations.swarm.quality_gate import _parse_quality_response
        score, feedback = _parse_quality_response("score: 5\nfeedback: Excellent")
        assert score == 5
        assert feedback == "Excellent"


# =============================================================================
# Quality gate: evaluate_worker_output
# =============================================================================


class TestEvaluateWorkerOutput:
    @pytest.mark.asyncio
    async def test_pre_flight_rejection_short_circuits(self) -> None:
        from attocode.integrations.swarm.quality_gate import evaluate_worker_output
        task = _make_task(task_type=SubtaskType.IMPLEMENT)
        result = _make_result(tool_calls=0)
        provider = AsyncMock()
        gate = await evaluate_worker_output(
            provider=provider,
            orchestrator_model="orch-model",
            task=task,
            result=result,
        )
        assert gate.passed is False
        # Provider should NOT have been called (pre-flight rejected)
        provider.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_error_returns_safe_default(self) -> None:
        from attocode.integrations.swarm.quality_gate import evaluate_worker_output
        task = _make_task(task_type=SubtaskType.RESEARCH)
        result = _make_result(tool_calls=3)
        provider = AsyncMock()
        provider.chat.side_effect = Exception("LLM down")
        gate = await evaluate_worker_output(
            provider=provider,
            orchestrator_model="m",
            task=task,
            result=result,
        )
        assert gate.score == 3
        assert gate.gate_error is True

    @pytest.mark.asyncio
    async def test_llm_success(self) -> None:
        from attocode.integrations.swarm.quality_gate import evaluate_worker_output
        task = _make_task(task_type=SubtaskType.RESEARCH)
        result = _make_result(tool_calls=3)
        provider = AsyncMock()
        provider.chat.return_value = {
            "content": "SCORE: 4\nFEEDBACK: Good implementation"
        }
        gate = await evaluate_worker_output(
            provider=provider,
            orchestrator_model="m",
            task=task,
            result=result,
        )
        assert gate.score == 4
        assert gate.passed is True
        assert "Good implementation" in gate.feedback

    @pytest.mark.asyncio
    async def test_empty_response_gate_error(self) -> None:
        from attocode.integrations.swarm.quality_gate import evaluate_worker_output
        task = _make_task(task_type=SubtaskType.RESEARCH)
        result = _make_result(tool_calls=3)
        provider = AsyncMock()
        provider.chat.return_value = {"content": ""}
        gate = await evaluate_worker_output(
            provider=provider,
            orchestrator_model="m",
            task=task,
            result=result,
        )
        assert gate.gate_error is True
        assert gate.score == 3


# =============================================================================
# Quality gate: _is_budget_excuse
# =============================================================================


class TestIsBudgetExcuse:
    def test_budget_excuse_detected(self) -> None:
        from attocode.integrations.swarm.quality_gate import _is_budget_excuse
        assert _is_budget_excuse("Ran out of budget before completion") is True
        assert _is_budget_excuse("Budget limit exceeded") is True
        assert _is_budget_excuse("Insufficient tokens") is True
        assert _is_budget_excuse("Token limit reached") is True
        assert _is_budget_excuse("Context window exceeded") is True

    def test_non_excuse(self) -> None:
        from attocode.integrations.swarm.quality_gate import _is_budget_excuse
        assert _is_budget_excuse("Implemented the feature successfully") is False
        assert _is_budget_excuse("Fixed the bug in the parser") is False


# =============================================================================
# WorkerPool: _select_prompt_template
# =============================================================================


class TestSelectPromptTemplate:
    def _make_pool(self) -> SwarmWorkerPool:
        config = _make_config(workers=[_make_worker()], max_concurrency=1)
        return SwarmWorkerPool(
            config=config, spawn_agent_fn=AsyncMock(), budget_pool=None
        )

    def test_research_type(self) -> None:
        pool = self._make_pool()
        assert pool._select_prompt_template("research") == "research"

    def test_implement_type(self) -> None:
        pool = self._make_pool()
        assert pool._select_prompt_template("implement") == "code"

    def test_unknown_type_defaults_to_code(self) -> None:
        pool = self._make_pool()
        assert pool._select_prompt_template("totally_unknown") == "code"

    def test_document_type(self) -> None:
        pool = self._make_pool()
        assert pool._select_prompt_template("document") == "document"

    def test_merge_type(self) -> None:
        pool = self._make_pool()
        assert pool._select_prompt_template("merge") == "synthesis"


# =============================================================================
# BUILTIN_TASK_TYPE_CONFIGS verification
# =============================================================================


class TestBuiltinTaskTypeConfigs:
    def test_has_all_subtask_types(self) -> None:
        expected = {
            "research", "analysis", "design", "implement", "test",
            "refactor", "review", "document", "integrate", "deploy", "merge"
        }
        assert set(BUILTIN_TASK_TYPE_CONFIGS.keys()) == expected

    def test_implement_requires_tool_calls(self) -> None:
        assert BUILTIN_TASK_TYPE_CONFIGS["implement"].requires_tool_calls is True

    def test_research_no_tool_calls_required(self) -> None:
        assert BUILTIN_TASK_TYPE_CONFIGS["research"].requires_tool_calls is False

    def test_review_no_tool_calls_required(self) -> None:
        assert BUILTIN_TASK_TYPE_CONFIGS["review"].requires_tool_calls is False

    def test_test_requires_tool_calls(self) -> None:
        assert BUILTIN_TASK_TYPE_CONFIGS["test"].requires_tool_calls is True


# =============================================================================
# TaskQueue: transitive cascade skip
# =============================================================================


class TestTransitiveCascadeSkip:
    def test_cascades_transitively(self) -> None:
        q = SwarmTaskQueue()
        q.artifact_aware_skip = False

        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.FAILED)
        q.tasks["t2"] = _make_task("t2", dependencies=["t1"], status=SwarmTaskStatus.PENDING)
        q.tasks["t3"] = _make_task("t3", dependencies=["t2"], status=SwarmTaskStatus.PENDING)
        q.waves = [["t1"], ["t2"], ["t3"]]

        q.trigger_cascade_skip("t1")
        assert q.tasks["t2"].status == SwarmTaskStatus.SKIPPED
        assert q.tasks["t3"].status == SwarmTaskStatus.SKIPPED

    def test_does_not_cascade_to_completed(self) -> None:
        q = SwarmTaskQueue()
        q.artifact_aware_skip = False

        q.tasks["t1"] = _make_task("t1", status=SwarmTaskStatus.FAILED)
        q.tasks["t2"] = _make_task("t2", dependencies=["t1"], status=SwarmTaskStatus.COMPLETED)
        q.waves = [["t1"], ["t2"]]

        q.trigger_cascade_skip("t1")
        assert q.tasks["t2"].status == SwarmTaskStatus.COMPLETED


# =============================================================================
# TaskQueue: _depends_on
# =============================================================================


class TestDependsOn:
    def test_direct_dependency(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1")
        q.tasks["t2"] = _make_task("t2", dependencies=["t1"])
        assert q._depends_on("t2", "t1") is True

    def test_transitive_dependency(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1")
        q.tasks["t2"] = _make_task("t2", dependencies=["t1"])
        q.tasks["t3"] = _make_task("t3", dependencies=["t2"])
        assert q._depends_on("t3", "t1") is True

    def test_no_dependency(self) -> None:
        q = SwarmTaskQueue()
        q.tasks["t1"] = _make_task("t1")
        q.tasks["t2"] = _make_task("t2")
        assert q._depends_on("t2", "t1") is False
