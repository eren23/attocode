"""Tests for swarm orchestrator, execution, lifecycle, recovery, and event_bridge modules.

Covers the five core swarm modules with ~150 tests:
- SwarmOrchestrator: construction, subscribe/unsubscribe, get_status, cancel, _emit, _log_decision, _SimpleBudgetPool
- Lifecycle: classify_decomposition_failure, build_emergency_decomposition, decompose_task,
  parse_json, build_stats, build_summary, build_error_result, detect_foundation_tasks,
  skip_remaining_tasks, emit_budget_update, get_effective_retries, get_swarm_progress_summary,
  _build_parallel_groups
- Recovery: SwarmRecoveryState, record_rate_limit, is_circuit_breaker_active,
  get_stagger_ms, increase_stagger, decrease_stagger, should_auto_split, rescue_cascade_skipped
- EventBridge: construction, set_tasks, get_live_state, _handle_event, close
- Execution: _classify_failure
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# --- Types ---
from attocode.integrations.swarm.types import (
    AutoSplitConfig,
    CompletionGuardConfig,
    DependencyGraph,
    FixupTask,
    SmartDecompositionResult,
    SmartSubtask,
    SpawnResult,
    SubtaskType,
    SwarmConfig,
    SwarmEvent,
    SwarmExecutionStats,
    SwarmPhase,
    SwarmQueueStats,
    SwarmStatus,
    SwarmTask,
    SwarmTaskResult,
    SwarmTaskStatus,
    SwarmWorkerStatus,
    TaskFailureMode,
    swarm_event,
)

# --- Orchestrator ---
from attocode.integrations.swarm.orchestrator import (
    OrchestratorInternals,
    SwarmOrchestrator,
    _SimpleBudgetPool,
    create_swarm_orchestrator,
)

# --- Lifecycle ---
from attocode.integrations.swarm.lifecycle import (
    _build_parallel_groups,
    build_emergency_decomposition,
    build_error_result,
    build_stats,
    build_summary,
    classify_decomposition_failure,
    detect_foundation_tasks,
    emit_budget_update,
    get_effective_retries,
    get_swarm_progress_summary,
    parse_json,
    skip_remaining_tasks,
)

# --- Recovery ---
from attocode.integrations.swarm.recovery import (
    CIRCUIT_BREAKER_PAUSE_MS,
    CIRCUIT_BREAKER_THRESHOLD,
    CIRCUIT_BREAKER_WINDOW_MS,
    SwarmRecoveryState,
    decrease_stagger,
    get_stagger_ms,
    increase_stagger,
    is_circuit_breaker_active,
    record_rate_limit,
    rescue_cascade_skipped,
    should_auto_split,
)

# --- Event bridge ---
from attocode.integrations.swarm.event_bridge import SwarmEventBridge

# --- Execution ---
from attocode.integrations.swarm.execution import _classify_failure


# =============================================================================
# Shared Fixtures / Helpers
# =============================================================================


class FakeQueueStats:
    """Fake queue stats object matching SwarmTaskQueue.get_stats() return."""

    def __init__(
        self,
        ready: int = 0,
        running: int = 0,
        completed: int = 0,
        failed: int = 0,
        skipped: int = 0,
        total: int = 0,
    ) -> None:
        self.ready = ready
        self.running = running
        self.completed = completed
        self.failed = failed
        self.skipped = skipped
        self.total = total


class FakeTaskQueue:
    """Minimal mock of SwarmTaskQueue for OrchestratorInternals.

    NOTE: The real SwarmTaskQueue.get_all_tasks() returns list[SwarmTask].
    However, recovery.py annotates/uses it as dict[str, SwarmTask] with .items().
    We return list by default (matching real impl). Tests for recovery modules
    that need dict access use FakeTaskQueueDict instead.
    """

    def __init__(self, tasks: dict[str, SwarmTask] | None = None) -> None:
        self._tasks = tasks or {}
        self._current_wave = 0
        self._total_waves = 1

    def get_all_tasks(self) -> list[SwarmTask]:
        return list(self._tasks.values())

    def get_stats(self) -> FakeQueueStats:
        completed = sum(1 for t in self._tasks.values() if t.status == SwarmTaskStatus.COMPLETED)
        failed = sum(1 for t in self._tasks.values() if t.status == SwarmTaskStatus.FAILED)
        skipped = sum(1 for t in self._tasks.values() if t.status == SwarmTaskStatus.SKIPPED)
        ready = sum(1 for t in self._tasks.values() if t.status == SwarmTaskStatus.READY)
        running = sum(1 for t in self._tasks.values() if t.status == SwarmTaskStatus.DISPATCHED)
        return FakeQueueStats(
            ready=ready,
            running=running,
            completed=completed,
            failed=failed,
            skipped=skipped,
            total=len(self._tasks),
        )

    def get_current_wave(self) -> int:
        return self._current_wave

    def get_total_waves(self) -> int:
        return self._total_waves

    def get_task(self, task_id: str) -> SwarmTask | None:
        return self._tasks.get(task_id)

    def rescue_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and task.status == SwarmTaskStatus.SKIPPED:
            task.status = SwarmTaskStatus.READY
            return True
        return False

    def mark_completed(self, task_id: str, result: SwarmTaskResult) -> None:
        task = self._tasks.get(task_id)
        if task:
            task.status = SwarmTaskStatus.COMPLETED
            task.result = result

    def mark_failed(self, task_id: str, max_retries: int) -> bool:
        task = self._tasks.get(task_id)
        if task:
            task.status = SwarmTaskStatus.FAILED
            return False
        return False

    def mark_failed_without_cascade(self, task_id: str, max_retries: int) -> bool:
        task = self._tasks.get(task_id)
        if task:
            if task.attempts <= max_retries:
                task.status = SwarmTaskStatus.READY
                return True
            task.status = SwarmTaskStatus.FAILED
            return False
        return False

    def mark_dispatched(self, task_id: str, model: str) -> None:
        task = self._tasks.get(task_id)
        if task:
            task.status = SwarmTaskStatus.DISPATCHED
            task.assigned_model = model
            task.attempts += 1

    def trigger_cascade_skip(self, task_id: str) -> None:
        pass

    def get_checkpoint_state(self) -> list[dict[str, Any]]:
        return []

    def set_retry_after(self, task_id: str, delay_ms: int) -> None:
        pass


class FakeTaskQueueDict(FakeTaskQueue):
    """Variant of FakeTaskQueue that returns dict from get_all_tasks().

    This matches the interface expected by recovery.py which calls .items()
    and .values() on the result.
    """

    def get_all_tasks(self) -> dict[str, SwarmTask]:  # type: ignore[override]
        return self._tasks


def _make_ctx(
    tasks: dict[str, SwarmTask] | None = None,
    config: SwarmConfig | None = None,
    use_dict_queue: bool = False,
) -> OrchestratorInternals:
    """Build a minimal OrchestratorInternals for testing."""
    cfg = config or SwarmConfig()
    queue_cls = FakeTaskQueueDict if use_dict_queue else FakeTaskQueue
    tq = queue_cls(tasks or {})
    ctx = OrchestratorInternals(
        config=cfg,
        provider=MagicMock(),
        task_queue=tq,
        worker_pool=MagicMock(),
        budget_pool=MagicMock(),
        health_tracker=MagicMock(),
        decomposer=None,
        synthesizer=None,
        shared_context_state=None,
        shared_economics_state=None,
        shared_context_engine=None,
        blackboard=None,
        state_store=None,
        spawn_agent_fn=AsyncMock(),
        codebase_context=None,
    )
    ctx.emit = MagicMock()
    ctx.log_decision = MagicMock()
    ctx.track_orchestrator_usage = MagicMock()
    return ctx


# =============================================================================
# Orchestrator Tests
# =============================================================================


class TestSwarmOrchestratorConstruction:
    """SwarmOrchestrator constructor and factory."""

    def test_basic_construction(self) -> None:
        config = SwarmConfig()
        provider = MagicMock()
        orch = SwarmOrchestrator(config, provider)
        assert orch._config is config
        assert orch._provider is provider
        assert orch._listeners == []

    def test_construction_with_all_kwargs(self) -> None:
        config = SwarmConfig()
        provider = MagicMock()
        registry = MagicMock()
        spawn_fn = AsyncMock()
        bb = MagicMock()
        orch = SwarmOrchestrator(config, provider, registry, spawn_fn, bb)
        assert orch._agent_registry is registry
        assert orch._spawn_agent_fn is spawn_fn
        assert orch._blackboard is bb

    def test_factory_function(self) -> None:
        config = SwarmConfig()
        provider = MagicMock()
        orch = create_swarm_orchestrator(config, provider)
        assert isinstance(orch, SwarmOrchestrator)

    def test_factory_with_kwargs(self) -> None:
        config = SwarmConfig()
        provider = MagicMock()
        bb = MagicMock()
        orch = create_swarm_orchestrator(config, provider, blackboard=bb)
        assert orch._blackboard is bb

    def test_subsystems_initially_none(self) -> None:
        orch = SwarmOrchestrator(SwarmConfig(), MagicMock())
        assert orch._task_queue is None
        assert orch._worker_pool is None
        assert orch._budget_pool is None
        assert orch._health_tracker is None


class TestSwarmOrchestratorSubscribe:
    """subscribe / unsubscribe mechanism."""

    def test_subscribe_adds_listener(self) -> None:
        orch = SwarmOrchestrator(SwarmConfig(), MagicMock())
        listener = MagicMock()
        orch.subscribe(listener)
        assert listener in orch._listeners

    def test_subscribe_returns_unsubscribe_fn(self) -> None:
        orch = SwarmOrchestrator(SwarmConfig(), MagicMock())
        listener = MagicMock()
        unsub = orch.subscribe(listener)
        assert callable(unsub)

    def test_unsubscribe_removes_listener(self) -> None:
        orch = SwarmOrchestrator(SwarmConfig(), MagicMock())
        listener = MagicMock()
        unsub = orch.subscribe(listener)
        unsub()
        assert listener not in orch._listeners

    def test_unsubscribe_idempotent(self) -> None:
        orch = SwarmOrchestrator(SwarmConfig(), MagicMock())
        listener = MagicMock()
        unsub = orch.subscribe(listener)
        unsub()
        unsub()  # No error on double-unsubscribe
        assert listener not in orch._listeners

    def test_multiple_listeners(self) -> None:
        orch = SwarmOrchestrator(SwarmConfig(), MagicMock())
        l1, l2 = MagicMock(), MagicMock()
        orch.subscribe(l1)
        orch.subscribe(l2)
        assert len(orch._listeners) == 2


class TestSwarmOrchestratorGetStatus:
    """get_status returns a valid SwarmStatus."""

    def test_get_status_idle_no_subsystems(self) -> None:
        orch = SwarmOrchestrator(SwarmConfig(), MagicMock())
        status = orch.get_status()
        assert isinstance(status, SwarmStatus)
        assert status.phase == SwarmPhase.IDLE

    def test_get_status_budget_reflects_config(self) -> None:
        config = SwarmConfig(total_budget=1_000_000, max_cost=5.0)
        orch = SwarmOrchestrator(config, MagicMock())
        status = orch.get_status()
        assert status.budget.tokens_total == 1_000_000
        assert status.budget.cost_total == 5.0

    def test_get_status_orchestrator_initially_zero(self) -> None:
        orch = SwarmOrchestrator(SwarmConfig(), MagicMock())
        status = orch.get_status()
        assert status.orchestrator.tokens == 0
        assert status.orchestrator.cost == 0.0
        assert status.orchestrator.calls == 0


class TestSwarmOrchestratorCancel:
    """cancel sets phase to FAILED."""

    @pytest.mark.asyncio
    async def test_cancel_sets_phase(self) -> None:
        orch = SwarmOrchestrator(SwarmConfig(), MagicMock())
        orch._cancelled = False
        orch._current_phase = SwarmPhase.EXECUTING
        # No worker pool => set to avoid AttributeError
        orch._worker_pool = None
        await orch.cancel()
        assert orch._cancelled is True
        assert orch._current_phase == SwarmPhase.FAILED

    @pytest.mark.asyncio
    async def test_cancel_calls_worker_pool_cancel_all(self) -> None:
        orch = SwarmOrchestrator(SwarmConfig(), MagicMock())
        orch._cancelled = False
        orch._current_phase = SwarmPhase.EXECUTING
        mock_pool = AsyncMock()
        orch._worker_pool = mock_pool
        await orch.cancel()
        mock_pool.cancel_all.assert_awaited_once()


class TestSwarmOrchestratorEmit:
    """_emit dispatches to all listeners."""

    def test_emit_calls_all_listeners(self) -> None:
        orch = SwarmOrchestrator(SwarmConfig(), MagicMock())
        l1, l2 = MagicMock(), MagicMock()
        orch.subscribe(l1)
        orch.subscribe(l2)
        event = swarm_event("test.event", foo="bar")
        orch._emit(event)
        l1.assert_called_once_with(event)
        l2.assert_called_once_with(event)

    def test_emit_swallows_listener_exceptions(self) -> None:
        orch = SwarmOrchestrator(SwarmConfig(), MagicMock())
        bad_listener = MagicMock(side_effect=RuntimeError("boom"))
        good_listener = MagicMock()
        orch.subscribe(bad_listener)
        orch.subscribe(good_listener)
        event = swarm_event("test.event")
        orch._emit(event)
        good_listener.assert_called_once_with(event)

    def test_emit_no_listeners(self) -> None:
        orch = SwarmOrchestrator(SwarmConfig(), MagicMock())
        orch._emit(swarm_event("no.listeners"))  # Should not raise


class TestSwarmOrchestratorLogDecision:
    """_log_decision records decision."""

    def test_log_decision_does_not_raise(self) -> None:
        orch = SwarmOrchestrator(SwarmConfig(), MagicMock())
        orch._log_decision("phase", "decision", "reasoning")


class TestSwarmOrchestratorTrackUsage:
    """_track_orchestrator_usage tracks tokens from LLM response."""

    def test_tracks_usage_from_response(self) -> None:
        orch = SwarmOrchestrator(SwarmConfig(), MagicMock())
        orch._orchestrator_tokens = 0
        orch._orchestrator_calls = 0
        response = MagicMock()
        response.usage.total_tokens = 500
        orch._track_orchestrator_usage(response, "test")
        assert orch._orchestrator_tokens == 500
        assert orch._orchestrator_calls == 1

    def test_tracks_cumulative_usage(self) -> None:
        orch = SwarmOrchestrator(SwarmConfig(), MagicMock())
        orch._orchestrator_tokens = 100
        orch._orchestrator_calls = 1
        response = MagicMock()
        response.usage.total_tokens = 200
        orch._track_orchestrator_usage(response, "test")
        assert orch._orchestrator_tokens == 300
        assert orch._orchestrator_calls == 2

    def test_no_usage_attribute(self) -> None:
        orch = SwarmOrchestrator(SwarmConfig(), MagicMock())
        orch._orchestrator_tokens = 0
        orch._orchestrator_calls = 0
        response = MagicMock(spec=[])  # no attributes
        orch._track_orchestrator_usage(response, "test")
        assert orch._orchestrator_tokens == 0


class TestOrchestratorInternals:
    """OrchestratorInternals dataclass has expected fields."""

    def test_all_fields_present(self) -> None:
        ctx = _make_ctx()
        assert hasattr(ctx, "config")
        assert hasattr(ctx, "provider")
        assert hasattr(ctx, "task_queue")
        assert hasattr(ctx, "worker_pool")
        assert hasattr(ctx, "budget_pool")
        assert hasattr(ctx, "health_tracker")
        assert hasattr(ctx, "decomposer")
        assert hasattr(ctx, "synthesizer")
        assert hasattr(ctx, "shared_context_state")
        assert hasattr(ctx, "shared_economics_state")
        assert hasattr(ctx, "shared_context_engine")
        assert hasattr(ctx, "blackboard")
        assert hasattr(ctx, "state_store")
        assert hasattr(ctx, "spawn_agent_fn")
        assert hasattr(ctx, "codebase_context")

    def test_mutable_state_defaults(self) -> None:
        ctx = _make_ctx()
        assert ctx.cancelled is False
        assert ctx.current_phase == SwarmPhase.IDLE
        assert ctx.total_tokens == 0
        assert ctx.total_cost == 0.0
        assert ctx.quality_rejections == 0
        assert ctx.retries == 0
        assert ctx.orchestrator_tokens == 0
        assert ctx.orchestrator_cost == 0.0
        assert ctx.orchestrator_calls == 0
        assert ctx.plan is None
        assert ctx.verification_result is None
        assert ctx.artifact_inventory is None
        assert ctx.hollow_streak == 0
        assert ctx.total_dispatches == 0
        assert ctx.total_hollows == 0
        assert ctx.original_prompt == ""
        assert ctx.has_replanned is False

    def test_collected_data_defaults(self) -> None:
        ctx = _make_ctx()
        assert ctx.errors == []
        assert ctx.wave_reviews == []
        assert ctx.decisions == []


# =============================================================================
# _SimpleBudgetPool Tests
# =============================================================================


class TestSimpleBudgetPool:
    """_SimpleBudgetPool allocation, release, and capacity."""

    def test_initial_capacity(self) -> None:
        pool = _SimpleBudgetPool(100_000)
        assert pool.remaining == 100_000
        assert pool.used == 0

    def test_allocate_success(self) -> None:
        pool = _SimpleBudgetPool(100_000)
        assert pool.allocate(50_000) is True
        assert pool.used == 50_000
        assert pool.remaining == 50_000

    def test_allocate_failure_insufficient(self) -> None:
        pool = _SimpleBudgetPool(100)
        assert pool.allocate(200) is False
        assert pool.used == 0

    def test_has_capacity_true(self) -> None:
        pool = _SimpleBudgetPool(100_000)
        assert pool.has_capacity(50_000) is True

    def test_has_capacity_false(self) -> None:
        pool = _SimpleBudgetPool(100)
        assert pool.has_capacity(200) is False

    def test_has_capacity_default(self) -> None:
        pool = _SimpleBudgetPool(5000)
        assert pool.has_capacity() is True

    def test_release(self) -> None:
        pool = _SimpleBudgetPool(100_000)
        pool.allocate(30_000)
        pool.release(10_000)
        assert pool.used == 20_000
        assert pool.remaining == 80_000

    def test_release_floors_at_zero(self) -> None:
        pool = _SimpleBudgetPool(100_000)
        pool.release(50_000)  # release more than used
        assert pool.used == 0
        assert pool.remaining == 100_000

    def test_reallocate_unused_noop(self) -> None:
        pool = _SimpleBudgetPool(100_000)
        pool.reallocate_unused()  # should not raise

    def test_multiple_allocations(self) -> None:
        pool = _SimpleBudgetPool(100_000)
        pool.allocate(20_000)
        pool.allocate(30_000)
        assert pool.used == 50_000
        assert pool.remaining == 50_000

    def test_allocate_exact_boundary(self) -> None:
        pool = _SimpleBudgetPool(1000)
        # has_capacity checks strict less than, so exact = total is False
        assert pool.allocate(1000) is False


# =============================================================================
# Lifecycle Tests
# =============================================================================


class TestClassifyDecompositionFailure:
    """classify_decomposition_failure recognizes failure types."""

    def test_rate_limit_429(self) -> None:
        assert classify_decomposition_failure("Error 429 from API") == "rate_limit"

    def test_rate_limit_text(self) -> None:
        assert classify_decomposition_failure("rate limit exceeded") == "rate_limit"

    def test_provider_budget_402(self) -> None:
        assert classify_decomposition_failure("402 Payment Required") == "provider_budget_limit"

    def test_provider_budget_text(self) -> None:
        assert classify_decomposition_failure("budget exceeded") == "provider_budget_limit"

    def test_parse_failure_json(self) -> None:
        assert classify_decomposition_failure("JSON decode error") == "parse_failure"

    def test_parse_failure_parse(self) -> None:
        assert classify_decomposition_failure("Failed to parse response") == "parse_failure"

    def test_validation_failure(self) -> None:
        assert classify_decomposition_failure("validation failed: invalid schema") == "validation_failure"

    def test_other_fallback(self) -> None:
        assert classify_decomposition_failure("Something went wrong") == "other"

    def test_empty_message(self) -> None:
        assert classify_decomposition_failure("") == "other"

    def test_case_insensitive(self) -> None:
        assert classify_decomposition_failure("RATE LIMIT HIT") == "rate_limit"


class TestBuildEmergencyDecomposition:
    """build_emergency_decomposition creates 4 tasks."""

    def test_creates_four_subtasks(self) -> None:
        ctx = _make_ctx()
        result = build_emergency_decomposition(ctx, "Build a parser")
        assert len(result.subtasks) == 4

    def test_subtask_ids_are_sequential(self) -> None:
        ctx = _make_ctx()
        result = build_emergency_decomposition(ctx, "task")
        ids = [s.id for s in result.subtasks]
        assert ids == ["task-fb-0", "task-fb-1", "task-fb-2", "task-fb-3"]

    def test_subtask_types(self) -> None:
        ctx = _make_ctx()
        result = build_emergency_decomposition(ctx, "task")
        types = [s.type for s in result.subtasks]
        assert types == ["design", "implement", "test", "integrate"]

    def test_dependencies_chain(self) -> None:
        ctx = _make_ctx()
        result = build_emergency_decomposition(ctx, "task")
        assert result.subtasks[0].dependencies == []
        assert result.subtasks[1].dependencies == ["task-fb-0"]
        assert result.subtasks[2].dependencies == ["task-fb-1"]
        assert result.subtasks[3].dependencies == ["task-fb-1", "task-fb-2"]

    def test_strategy_is_emergency(self) -> None:
        ctx = _make_ctx()
        result = build_emergency_decomposition(ctx, "task", "test reason")
        assert result.strategy == "emergency-fallback"
        assert "test reason" in result.reasoning

    def test_llm_assisted_is_false(self) -> None:
        ctx = _make_ctx()
        result = build_emergency_decomposition(ctx, "task")
        assert result.llm_assisted is False

    def test_has_parallel_groups(self) -> None:
        ctx = _make_ctx()
        result = build_emergency_decomposition(ctx, "task")
        assert len(result.dependency_graph.parallel_groups) == 4


class TestParseJson:
    """parse_json handles various JSON formats."""

    def test_direct_json(self) -> None:
        result = parse_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_markdown_code_block(self) -> None:
        content = '```json\n{"key": "value"}\n```'
        result = parse_json(content)
        assert result == {"key": "value"}

    def test_markdown_code_block_no_lang(self) -> None:
        content = '```\n{"key": "value"}\n```'
        result = parse_json(content)
        assert result == {"key": "value"}

    def test_json_in_text(self) -> None:
        content = 'Here is the result: {"key": "value"} hope this helps'
        result = parse_json(content)
        assert result == {"key": "value"}

    def test_empty_string(self) -> None:
        assert parse_json("") is None

    def test_none_like(self) -> None:
        assert parse_json("") is None

    def test_invalid_json(self) -> None:
        assert parse_json("not json at all") is None

    def test_nested_json(self) -> None:
        result = parse_json('{"subtasks": [{"id": "st-0", "type": "implement"}]}')
        assert result is not None
        assert len(result["subtasks"]) == 1


class TestBuildStats:
    """build_stats computes execution statistics."""

    def test_empty_queue(self) -> None:
        ctx = _make_ctx()
        stats = build_stats(ctx)
        assert stats.total_tasks == 0
        assert stats.completed_tasks == 0

    def test_with_tasks(self) -> None:
        tasks = {
            "t1": SwarmTask(id="t1", description="A", status=SwarmTaskStatus.COMPLETED,
                            result=SwarmTaskResult(success=True, output="ok", duration_ms=100)),
            "t2": SwarmTask(id="t2", description="B", status=SwarmTaskStatus.FAILED),
            "t3": SwarmTask(id="t3", description="C", status=SwarmTaskStatus.SKIPPED),
        }
        ctx = _make_ctx(tasks)
        ctx.total_tokens = 5000
        ctx.total_cost = 0.5
        ctx.quality_rejections = 1
        ctx.retries = 2
        ctx.orchestrator_tokens = 200
        ctx.orchestrator_cost = 0.01

        stats = build_stats(ctx)
        assert stats.total_tasks == 3
        assert stats.completed_tasks == 1
        assert stats.failed_tasks == 1
        assert stats.skipped_tasks == 1
        assert stats.total_tokens == 5000
        assert stats.total_cost == 0.5
        assert stats.quality_rejections == 1
        assert stats.retries == 2
        assert stats.orchestrator_tokens == 200
        assert stats.orchestrator_cost == 0.01
        assert stats.total_duration_ms == 100

    def test_duration_sums_all_results(self) -> None:
        tasks = {
            "t1": SwarmTask(id="t1", description="A", status=SwarmTaskStatus.COMPLETED,
                            result=SwarmTaskResult(success=True, output="ok", duration_ms=100)),
            "t2": SwarmTask(id="t2", description="B", status=SwarmTaskStatus.COMPLETED,
                            result=SwarmTaskResult(success=True, output="ok", duration_ms=200)),
        }
        ctx = _make_ctx(tasks)
        stats = build_stats(ctx)
        assert stats.total_duration_ms == 300


class TestBuildSummary:
    """build_summary includes key fields in output."""

    def test_includes_task_counts(self) -> None:
        ctx = _make_ctx()
        stats = SwarmExecutionStats(total_tasks=10, completed_tasks=8, failed_tasks=1, skipped_tasks=1)
        summary = build_summary(ctx, stats)
        assert "8/10" in summary
        assert "Failed: 1" in summary
        assert "Skipped: 1" in summary

    def test_includes_tokens_and_cost(self) -> None:
        ctx = _make_ctx()
        stats = SwarmExecutionStats(total_tokens=100_000, total_cost=1.5, orchestrator_tokens=5000, orchestrator_cost=0.1)
        summary = build_summary(ctx, stats)
        assert "100,000" in summary
        assert "$1.5" in summary

    def test_includes_header(self) -> None:
        ctx = _make_ctx()
        stats = SwarmExecutionStats()
        summary = build_summary(ctx, stats)
        assert "Swarm Execution Summary" in summary


class TestBuildErrorResult:
    """build_error_result returns failed result."""

    def test_returns_failed(self) -> None:
        ctx = _make_ctx()
        ctx.current_phase = SwarmPhase.DECOMPOSING
        result = build_error_result(ctx, "something broke")
        assert result.success is False
        assert "something broke" in result.summary

    def test_includes_phase_in_errors(self) -> None:
        ctx = _make_ctx()
        ctx.current_phase = SwarmPhase.EXECUTING
        result = build_error_result(ctx, "fail")
        assert len(result.errors) == 1
        assert result.errors[0]["phase"] == "executing"

    def test_empty_message(self) -> None:
        ctx = _make_ctx()
        ctx.current_phase = SwarmPhase.IDLE
        result = build_error_result(ctx, "")
        assert result.success is False


class TestDetectFoundationTasks:
    """detect_foundation_tasks marks high-dep tasks."""

    def test_marks_tasks_with_two_plus_dependents(self) -> None:
        tasks = {
            "t1": SwarmTask(id="t1", description="base"),
            "t2": SwarmTask(id="t2", description="A", dependencies=["t1"]),
            "t3": SwarmTask(id="t3", description="B", dependencies=["t1"]),
        }
        ctx = _make_ctx(tasks)
        detect_foundation_tasks(ctx)
        assert tasks["t1"].is_foundation is True
        assert tasks["t2"].is_foundation is False
        assert tasks["t3"].is_foundation is False

    def test_does_not_mark_with_single_dependent(self) -> None:
        tasks = {
            "t1": SwarmTask(id="t1", description="base"),
            "t2": SwarmTask(id="t2", description="A", dependencies=["t1"]),
        }
        ctx = _make_ctx(tasks)
        detect_foundation_tasks(ctx)
        assert tasks["t1"].is_foundation is False

    def test_multiple_foundations(self) -> None:
        tasks = {
            "t1": SwarmTask(id="t1", description="base1"),
            "t2": SwarmTask(id="t2", description="base2"),
            "t3": SwarmTask(id="t3", description="A", dependencies=["t1", "t2"]),
            "t4": SwarmTask(id="t4", description="B", dependencies=["t1", "t2"]),
        }
        ctx = _make_ctx(tasks)
        detect_foundation_tasks(ctx)
        assert tasks["t1"].is_foundation is True
        assert tasks["t2"].is_foundation is True

    def test_no_tasks(self) -> None:
        ctx = _make_ctx()
        detect_foundation_tasks(ctx)  # should not raise


class TestSkipRemainingTasks:
    """skip_remaining_tasks skips pending and ready tasks."""

    def test_skips_pending_and_ready(self) -> None:
        tasks = {
            "t1": SwarmTask(id="t1", description="A", status=SwarmTaskStatus.PENDING),
            "t2": SwarmTask(id="t2", description="B", status=SwarmTaskStatus.READY),
            "t3": SwarmTask(id="t3", description="C", status=SwarmTaskStatus.COMPLETED),
            "t4": SwarmTask(id="t4", description="D", status=SwarmTaskStatus.DISPATCHED),
        }
        ctx = _make_ctx(tasks)
        skip_remaining_tasks(ctx, "test reason")
        assert tasks["t1"].status == SwarmTaskStatus.SKIPPED
        assert tasks["t2"].status == SwarmTaskStatus.SKIPPED
        assert tasks["t3"].status == SwarmTaskStatus.COMPLETED
        assert tasks["t4"].status == SwarmTaskStatus.DISPATCHED

    def test_emits_events_for_each_skipped(self) -> None:
        tasks = {
            "t1": SwarmTask(id="t1", description="A", status=SwarmTaskStatus.PENDING),
            "t2": SwarmTask(id="t2", description="B", status=SwarmTaskStatus.READY),
        }
        ctx = _make_ctx(tasks)
        skip_remaining_tasks(ctx, "budget")
        assert ctx.emit.call_count == 2


class TestEmitBudgetUpdate:
    """emit_budget_update emits event with budget data."""

    def test_emits_budget_event(self) -> None:
        ctx = _make_ctx()
        ctx.total_tokens = 1000
        ctx.orchestrator_tokens = 200
        ctx.total_cost = 0.1
        ctx.orchestrator_cost = 0.05
        emit_budget_update(ctx)
        ctx.emit.assert_called_once()
        event = ctx.emit.call_args[0][0]
        assert event.type == "swarm.budget.update"
        assert event.data["tokens_used"] == 1200
        assert event.data["cost_used"] == pytest.approx(0.15)


class TestGetEffectiveRetries:
    """get_effective_retries: foundation +1, fixup 2, normal base."""

    def test_normal_task(self) -> None:
        ctx = _make_ctx(config=SwarmConfig(worker_retries=3))
        task = SwarmTask(id="t1", description="test")
        assert get_effective_retries(ctx, task) == 3

    def test_foundation_task_gets_plus_one(self) -> None:
        ctx = _make_ctx(config=SwarmConfig(worker_retries=3))
        task = SwarmTask(id="t1", description="test", is_foundation=True)
        assert get_effective_retries(ctx, task) == 4

    def test_fixup_task_returns_two(self) -> None:
        ctx = _make_ctx(config=SwarmConfig(worker_retries=3))
        task = FixupTask(id="fix1", description="fix", fixes_task_id="t1")
        assert get_effective_retries(ctx, task) == 2


class TestGetSwarmProgressSummary:
    """get_swarm_progress_summary lists completed tasks."""

    def test_no_completed_tasks(self) -> None:
        ctx = _make_ctx()
        summary = get_swarm_progress_summary(ctx)
        assert "No tasks completed" in summary

    def test_with_completed_tasks(self) -> None:
        tasks = {
            "t1": SwarmTask(id="t1", description="Implement auth", status=SwarmTaskStatus.COMPLETED,
                            result=SwarmTaskResult(success=True, output="done", quality_score=4,
                                                   files_modified=["auth.py"])),
            "t2": SwarmTask(id="t2", description="Write tests", status=SwarmTaskStatus.PENDING),
        }
        ctx = _make_ctx(tasks)
        summary = get_swarm_progress_summary(ctx)
        assert "Completed 1 tasks" in summary
        assert "Implement auth" in summary
        assert "quality: 4" in summary
        assert "auth.py" in summary


class TestBuildParallelGroups:
    """_build_parallel_groups from subtask dependencies."""

    def test_no_deps_single_group(self) -> None:
        subtasks = [
            SmartSubtask(id="a", description="A"),
            SmartSubtask(id="b", description="B"),
        ]
        groups = _build_parallel_groups(subtasks)
        assert len(groups) == 1
        assert set(groups[0]) == {"a", "b"}

    def test_sequential_chain(self) -> None:
        subtasks = [
            SmartSubtask(id="a", description="A"),
            SmartSubtask(id="b", description="B", dependencies=["a"]),
            SmartSubtask(id="c", description="C", dependencies=["b"]),
        ]
        groups = _build_parallel_groups(subtasks)
        assert len(groups) == 3
        assert groups[0] == ["a"]
        assert groups[1] == ["b"]
        assert groups[2] == ["c"]

    def test_diamond_pattern(self) -> None:
        subtasks = [
            SmartSubtask(id="a", description="A"),
            SmartSubtask(id="b", description="B", dependencies=["a"]),
            SmartSubtask(id="c", description="C", dependencies=["a"]),
            SmartSubtask(id="d", description="D", dependencies=["b", "c"]),
        ]
        groups = _build_parallel_groups(subtasks)
        assert len(groups) == 3
        assert groups[0] == ["a"]
        assert set(groups[1]) == {"b", "c"}
        assert groups[2] == ["d"]

    def test_empty_subtasks(self) -> None:
        groups = _build_parallel_groups([])
        assert groups == []

    def test_ignores_external_deps(self) -> None:
        subtasks = [
            SmartSubtask(id="a", description="A", dependencies=["external-id"]),
        ]
        groups = _build_parallel_groups(subtasks)
        assert len(groups) == 1
        assert groups[0] == ["a"]


class TestDecomposeTask:
    """decompose_task fallback chain."""

    @pytest.mark.asyncio
    async def test_emergency_fallback_when_no_decomposer(self) -> None:
        ctx = _make_ctx()
        ctx.decomposer = None
        # Mock last_resort_decompose to also fail
        with patch("attocode.integrations.swarm.lifecycle.last_resort_decompose", new_callable=AsyncMock) as mock_lr:
            mock_lr.return_value = None
            from attocode.integrations.swarm.lifecycle import decompose_task
            result = await decompose_task(ctx, "Build a CLI")
        decomp = result["result"]
        assert decomp is not None
        assert len(decomp.subtasks) == 4
        assert decomp.strategy == "emergency-fallback"

    @pytest.mark.asyncio
    async def test_primary_decomposer_success(self) -> None:
        ctx = _make_ctx()
        decomposer = AsyncMock()
        expected = SmartDecompositionResult(
            subtasks=[
                SmartSubtask(id="s1", description="task1"),
                SmartSubtask(id="s2", description="task2"),
            ],
            strategy="primary",
        )
        decomposer.decompose.return_value = expected
        ctx.decomposer = decomposer

        from attocode.integrations.swarm.lifecycle import decompose_task
        result = await decompose_task(ctx, "Build a CLI")
        assert result["result"] is expected

    @pytest.mark.asyncio
    async def test_last_resort_fallback(self) -> None:
        ctx = _make_ctx()
        ctx.decomposer = AsyncMock()
        ctx.decomposer.decompose.side_effect = RuntimeError("primary fail")

        last_resort_result = SmartDecompositionResult(
            subtasks=[
                SmartSubtask(id="lr-0", description="task1"),
                SmartSubtask(id="lr-1", description="task2"),
            ],
            strategy="last-resort",
        )
        with patch("attocode.integrations.swarm.lifecycle.last_resort_decompose", new_callable=AsyncMock) as mock_lr:
            mock_lr.return_value = last_resort_result
            from attocode.integrations.swarm.lifecycle import decompose_task
            result = await decompose_task(ctx, "Build a CLI")
        assert result["result"] is last_resort_result


# =============================================================================
# Recovery Tests
# =============================================================================


class TestSwarmRecoveryStateDefaults:
    """SwarmRecoveryState defaults."""

    def test_defaults(self) -> None:
        state = SwarmRecoveryState()
        assert state.recent_rate_limits == []
        assert state.circuit_breaker_until == 0.0
        assert state.per_model_quality_rejections == {}
        assert state.quality_gate_disabled_models == set()
        assert state.adaptive_stagger_ms == 1500.0
        assert state.task_timeout_counts == {}
        assert state.hollow_ratio_warned is False

    def test_custom_stagger(self) -> None:
        state = SwarmRecoveryState(adaptive_stagger_ms=3000.0)
        assert state.adaptive_stagger_ms == 3000.0


class TestRecordRateLimit:
    """record_rate_limit pushes timestamp, increases stagger, trips breaker."""

    def test_pushes_timestamp(self) -> None:
        state = SwarmRecoveryState()
        ctx = _make_ctx()
        record_rate_limit(state, ctx)
        assert len(state.recent_rate_limits) == 1

    def test_increases_stagger(self) -> None:
        state = SwarmRecoveryState(adaptive_stagger_ms=1000.0)
        ctx = _make_ctx()
        initial = state.adaptive_stagger_ms
        record_rate_limit(state, ctx)
        assert state.adaptive_stagger_ms > initial

    def test_trips_circuit_breaker_at_threshold(self) -> None:
        state = SwarmRecoveryState()
        ctx = _make_ctx()
        for _ in range(CIRCUIT_BREAKER_THRESHOLD):
            record_rate_limit(state, ctx)
        assert state.circuit_breaker_until > 0.0

    def test_does_not_trip_below_threshold(self) -> None:
        state = SwarmRecoveryState()
        ctx = _make_ctx()
        for _ in range(CIRCUIT_BREAKER_THRESHOLD - 1):
            record_rate_limit(state, ctx)
        assert state.circuit_breaker_until == 0.0

    def test_emits_circuit_open_event(self) -> None:
        state = SwarmRecoveryState()
        ctx = _make_ctx()
        for _ in range(CIRCUIT_BREAKER_THRESHOLD):
            record_rate_limit(state, ctx)
        # Find the circuit open event
        found = False
        for call in ctx.emit.call_args_list:
            event = call[0][0]
            if event.type == "swarm.circuit.open":
                found = True
                break
        assert found, "Expected swarm.circuit.open event"

    def test_prunes_old_timestamps(self) -> None:
        state = SwarmRecoveryState()
        ctx = _make_ctx()
        # Add old timestamps outside window
        old_time = time.time() - (CIRCUIT_BREAKER_WINDOW_MS / 1000.0) - 10
        state.recent_rate_limits = [old_time, old_time]
        record_rate_limit(state, ctx)
        # Old timestamps should be pruned
        assert len(state.recent_rate_limits) == 1


class TestIsCircuitBreakerActive:
    """is_circuit_breaker_active returns True during pause, False after expiry."""

    def test_returns_false_when_not_set(self) -> None:
        state = SwarmRecoveryState()
        ctx = _make_ctx()
        assert is_circuit_breaker_active(state, ctx) is False

    def test_returns_true_during_pause(self) -> None:
        state = SwarmRecoveryState(circuit_breaker_until=time.time() + 100)
        ctx = _make_ctx()
        assert is_circuit_breaker_active(state, ctx) is True

    def test_resets_after_expiry(self) -> None:
        state = SwarmRecoveryState(circuit_breaker_until=time.time() - 1)
        state.recent_rate_limits = [time.time()]
        ctx = _make_ctx()
        result = is_circuit_breaker_active(state, ctx)
        assert result is False
        assert state.circuit_breaker_until == 0.0
        assert state.recent_rate_limits == []

    def test_emits_circuit_closed_on_expiry(self) -> None:
        state = SwarmRecoveryState(circuit_breaker_until=time.time() - 1)
        ctx = _make_ctx()
        is_circuit_breaker_active(state, ctx)
        ctx.emit.assert_called_once()
        event = ctx.emit.call_args[0][0]
        assert event.type == "swarm.circuit.closed"


class TestStaggerControl:
    """get_stagger_ms, increase_stagger, decrease_stagger."""

    def test_get_stagger_ms_returns_current(self) -> None:
        state = SwarmRecoveryState(adaptive_stagger_ms=2000.0)
        assert get_stagger_ms(state) == 2000.0

    def test_increase_stagger(self) -> None:
        state = SwarmRecoveryState(adaptive_stagger_ms=1000.0)
        increase_stagger(state)
        assert state.adaptive_stagger_ms == 1500.0  # 1000 * 1.5

    def test_increase_stagger_caps_at_10000(self) -> None:
        state = SwarmRecoveryState(adaptive_stagger_ms=9000.0)
        increase_stagger(state)
        assert state.adaptive_stagger_ms == 10_000.0

    def test_increase_stagger_already_at_cap(self) -> None:
        state = SwarmRecoveryState(adaptive_stagger_ms=10_000.0)
        increase_stagger(state)
        assert state.adaptive_stagger_ms == 10_000.0

    def test_decrease_stagger(self) -> None:
        state = SwarmRecoveryState(adaptive_stagger_ms=1000.0)
        decrease_stagger(state)
        assert state.adaptive_stagger_ms == 900.0  # 1000 * 0.9

    def test_decrease_stagger_floors_at_200(self) -> None:
        state = SwarmRecoveryState(adaptive_stagger_ms=200.0)
        decrease_stagger(state)
        assert state.adaptive_stagger_ms == 200.0

    def test_decrease_stagger_below_floor(self) -> None:
        state = SwarmRecoveryState(adaptive_stagger_ms=100.0)
        decrease_stagger(state)
        assert state.adaptive_stagger_ms == 200.0

    def test_repeated_increase(self) -> None:
        state = SwarmRecoveryState(adaptive_stagger_ms=200.0)
        for _ in range(20):
            increase_stagger(state)
        assert state.adaptive_stagger_ms == 10_000.0

    def test_repeated_decrease(self) -> None:
        state = SwarmRecoveryState(adaptive_stagger_ms=5000.0)
        for _ in range(50):
            decrease_stagger(state)
        assert state.adaptive_stagger_ms == 200.0


class TestShouldAutoSplit:
    """should_auto_split checks conditions."""

    def _make_split_ctx(self, **config_overrides: Any) -> Any:
        config = SwarmConfig(
            auto_split=AutoSplitConfig(
                enabled=True,
                complexity_floor=6,
                splittable_types=["implement", "refactor", "test"],
                max_subtasks=4,
            ),
            total_budget=1_000_000,
            **config_overrides,
        )
        return _make_ctx(config=config)

    def test_all_conditions_met(self) -> None:
        ctx = self._make_split_ctx()
        task = SwarmTask(
            id="t1", description="complex task",
            type=SubtaskType.IMPLEMENT, complexity=8,
            attempts=0, is_foundation=True,
        )
        assert should_auto_split(ctx, task) is True

    def test_disabled_config(self) -> None:
        config = SwarmConfig(auto_split=AutoSplitConfig(enabled=False))
        ctx = _make_ctx(config=config)
        task = SwarmTask(
            id="t1", description="task",
            type=SubtaskType.IMPLEMENT, complexity=8,
            attempts=0, is_foundation=True,
        )
        assert should_auto_split(ctx, task) is False

    def test_low_complexity(self) -> None:
        ctx = self._make_split_ctx()
        task = SwarmTask(
            id="t1", description="simple task",
            type=SubtaskType.IMPLEMENT, complexity=3,
            attempts=0, is_foundation=True,
        )
        assert should_auto_split(ctx, task) is False

    def test_not_splittable_type(self) -> None:
        ctx = self._make_split_ctx()
        task = SwarmTask(
            id="t1", description="review task",
            type=SubtaskType.REVIEW, complexity=8,
            attempts=0, is_foundation=True,
        )
        assert should_auto_split(ctx, task) is False

    def test_already_attempted(self) -> None:
        ctx = self._make_split_ctx()
        task = SwarmTask(
            id="t1", description="task",
            type=SubtaskType.IMPLEMENT, complexity=8,
            attempts=1, is_foundation=True,
        )
        assert should_auto_split(ctx, task) is False

    def test_not_foundation(self) -> None:
        ctx = self._make_split_ctx()
        task = SwarmTask(
            id="t1", description="task",
            type=SubtaskType.IMPLEMENT, complexity=8,
            attempts=0, is_foundation=False,
        )
        assert should_auto_split(ctx, task) is False


class TestRescueCascadeSkipped:
    """rescue_cascade_skipped rescues qualified tasks."""

    def test_rescues_task_with_no_dependencies(self) -> None:
        tasks = {
            "t1": SwarmTask(id="t1", description="orphan", status=SwarmTaskStatus.SKIPPED,
                            dependencies=[]),
        }
        ctx = _make_ctx(tasks, use_dict_queue=True)
        rescued = rescue_cascade_skipped(ctx)
        assert len(rescued) == 1
        assert tasks["t1"].status == SwarmTaskStatus.READY

    def test_rescues_task_with_majority_completed_deps(self) -> None:
        tasks = {
            "t1": SwarmTask(id="t1", description="dep1", status=SwarmTaskStatus.COMPLETED),
            "t2": SwarmTask(id="t2", description="dep2", status=SwarmTaskStatus.COMPLETED),
            "t3": SwarmTask(id="t3", description="dep3", status=SwarmTaskStatus.FAILED),
            "t4": SwarmTask(id="t4", description="target", status=SwarmTaskStatus.SKIPPED,
                            dependencies=["t1", "t2", "t3"]),
        }
        ctx = _make_ctx(tasks, use_dict_queue=True)
        rescued = rescue_cascade_skipped(ctx)
        assert len(rescued) == 1
        assert tasks["t4"].status == SwarmTaskStatus.READY
        assert "2/3" in (tasks["t4"].rescue_context or "")

    def test_does_not_rescue_with_low_completion(self) -> None:
        tasks = {
            "t1": SwarmTask(id="t1", description="dep1", status=SwarmTaskStatus.FAILED),
            "t2": SwarmTask(id="t2", description="dep2", status=SwarmTaskStatus.FAILED),
            "t3": SwarmTask(id="t3", description="target", status=SwarmTaskStatus.SKIPPED,
                            dependencies=["t1", "t2"]),
        }
        ctx = _make_ctx(tasks, use_dict_queue=True)
        rescued = rescue_cascade_skipped(ctx)
        assert len(rescued) == 0

    def test_lenient_mode_rescues_with_one_dep(self) -> None:
        tasks = {
            "t1": SwarmTask(id="t1", description="dep1", status=SwarmTaskStatus.COMPLETED),
            "t2": SwarmTask(id="t2", description="dep2", status=SwarmTaskStatus.FAILED),
            "t3": SwarmTask(id="t3", description="dep3", status=SwarmTaskStatus.FAILED),
            "t4": SwarmTask(id="t4", description="target", status=SwarmTaskStatus.SKIPPED,
                            dependencies=["t1", "t2", "t3"]),
        }
        ctx = _make_ctx(tasks, use_dict_queue=True)
        rescued = rescue_cascade_skipped(ctx, lenient=True)
        assert len(rescued) == 1

    def test_ignores_non_skipped_tasks(self) -> None:
        tasks = {
            "t1": SwarmTask(id="t1", description="pending", status=SwarmTaskStatus.PENDING),
            "t2": SwarmTask(id="t2", description="failed", status=SwarmTaskStatus.FAILED),
        }
        ctx = _make_ctx(tasks, use_dict_queue=True)
        rescued = rescue_cascade_skipped(ctx)
        assert len(rescued) == 0

    def test_sets_rescue_context(self) -> None:
        tasks = {
            "t1": SwarmTask(id="t1", description="dep", status=SwarmTaskStatus.COMPLETED),
            "t2": SwarmTask(id="t2", description="target", status=SwarmTaskStatus.SKIPPED,
                            dependencies=["t1"]),
        }
        ctx = _make_ctx(tasks, use_dict_queue=True)
        rescued = rescue_cascade_skipped(ctx)
        assert len(rescued) == 1
        assert tasks["t2"].rescue_context is not None
        assert "Rescued" in tasks["t2"].rescue_context


# =============================================================================
# Event Bridge Tests
# =============================================================================


class TestSwarmEventBridgeConstruction:
    """SwarmEventBridge construction."""

    def test_basic_construction(self) -> None:
        bridge = SwarmEventBridge()
        assert bridge._output_dir == ".agent/swarm-live"
        assert bridge._max_lines == 5000
        assert bridge._seq == 0

    def test_custom_output_dir(self) -> None:
        bridge = SwarmEventBridge(output_dir="/tmp/test-swarm")
        assert bridge._output_dir == "/tmp/test-swarm"

    def test_custom_max_lines(self) -> None:
        bridge = SwarmEventBridge(max_lines=1000)
        assert bridge._max_lines == 1000

    def test_initial_state_empty(self) -> None:
        bridge = SwarmEventBridge()
        assert bridge._tasks == {}
        assert bridge._edges == []
        assert bridge._timeline == []
        assert bridge._errors == []


class TestSwarmEventBridgeSetTasks:
    """set_tasks populates task map."""

    def test_populates_task_map(self) -> None:
        bridge = SwarmEventBridge()
        tasks = [
            SwarmTask(id="t1", description="A", dependencies=[]),
            SwarmTask(id="t2", description="B", dependencies=["t1"]),
        ]
        bridge.set_tasks(tasks)
        assert "t1" in bridge._tasks
        assert "t2" in bridge._tasks

    def test_populates_edges(self) -> None:
        bridge = SwarmEventBridge()
        tasks = [
            SwarmTask(id="t1", description="A"),
            SwarmTask(id="t2", description="B", dependencies=["t1"]),
        ]
        bridge.set_tasks(tasks)
        assert ("t1", "t2") in bridge._edges

    def test_clears_previous_data(self) -> None:
        bridge = SwarmEventBridge()
        bridge._tasks["old"] = SwarmTask(id="old", description="old")
        bridge._edges.append(("a", "b"))
        tasks = [SwarmTask(id="t1", description="new")]
        bridge.set_tasks(tasks)
        assert "old" not in bridge._tasks
        assert ("a", "b") not in bridge._edges

    def test_multiple_dependencies(self) -> None:
        bridge = SwarmEventBridge()
        tasks = [
            SwarmTask(id="t1", description="A"),
            SwarmTask(id="t2", description="B"),
            SwarmTask(id="t3", description="C", dependencies=["t1", "t2"]),
        ]
        bridge.set_tasks(tasks)
        assert ("t1", "t3") in bridge._edges
        assert ("t2", "t3") in bridge._edges


class TestSwarmEventBridgeGetLiveState:
    """get_live_state returns dict with expected keys."""

    def test_returns_dict(self) -> None:
        bridge = SwarmEventBridge()
        state = bridge.get_live_state()
        assert isinstance(state, dict)

    def test_has_expected_keys(self) -> None:
        bridge = SwarmEventBridge()
        state = bridge.get_live_state()
        expected_keys = {
            "seq", "timestamp", "status", "tasks", "edges",
            "timeline", "errors", "decisions", "model_health",
            "config", "plan", "verification", "artifact_inventory",
            "worker_log_files",
        }
        assert expected_keys.issubset(set(state.keys()))

    def test_tasks_reflect_set_tasks(self) -> None:
        bridge = SwarmEventBridge()
        bridge.set_tasks([SwarmTask(id="t1", description="A")])
        state = bridge.get_live_state()
        assert "t1" in state["tasks"]
        assert state["tasks"]["t1"]["description"] == "A"

    def test_edges_reflect_dependencies(self) -> None:
        bridge = SwarmEventBridge()
        bridge.set_tasks([
            SwarmTask(id="t1", description="A"),
            SwarmTask(id="t2", description="B", dependencies=["t1"]),
        ])
        state = bridge.get_live_state()
        assert {"source": "t1", "target": "t2"} in state["edges"]


class TestSwarmEventBridgeHandleEvent:
    """_handle_event for various event types."""

    def test_swarm_start_resets_state(self) -> None:
        bridge = SwarmEventBridge()
        bridge._tasks["old"] = SwarmTask(id="old", description="old")
        bridge._errors.append({"msg": "old error"})
        bridge._timeline.append({"msg": "old"})
        event = SwarmEvent(type="swarm.start", data={})
        bridge._handle_event(event)
        assert bridge._tasks == {}
        assert bridge._errors == []
        assert bridge._timeline == []
        assert bridge._seq == 1

    def test_swarm_start_sets_phase_to_decomposing(self) -> None:
        bridge = SwarmEventBridge()
        event = SwarmEvent(type="swarm.start", data={})
        bridge._handle_event(event)
        assert bridge._last_status is not None
        assert bridge._last_status.phase == SwarmPhase.DECOMPOSING

    def test_task_dispatched_updates_task(self) -> None:
        bridge = SwarmEventBridge()
        bridge._tasks["t1"] = SwarmTask(id="t1", description="A", status=SwarmTaskStatus.READY)
        bridge._last_status = SwarmStatus(phase=SwarmPhase.EXECUTING)
        event = SwarmEvent(type="swarm.task.dispatched", data={
            "task_id": "t1", "model": "gpt-4",
        })
        bridge._handle_event(event)
        assert bridge._tasks["t1"].status == SwarmTaskStatus.DISPATCHED
        assert bridge._tasks["t1"].assigned_model == "gpt-4"

    def test_task_completed_updates_task(self) -> None:
        bridge = SwarmEventBridge()
        bridge._tasks["t1"] = SwarmTask(id="t1", description="A", status=SwarmTaskStatus.DISPATCHED)
        bridge._last_status = SwarmStatus(
            phase=SwarmPhase.EXECUTING,
            active_workers=[SwarmWorkerStatus(task_id="t1", task_description="A", model="m", worker_name="w")],
        )
        event = SwarmEvent(type="swarm.task.completed", data={"task_id": "t1"})
        bridge._handle_event(event)
        assert bridge._tasks["t1"].status == SwarmTaskStatus.COMPLETED
        assert bridge._last_status.active_workers == []

    def test_task_failed_updates_task(self) -> None:
        bridge = SwarmEventBridge()
        bridge._tasks["t1"] = SwarmTask(id="t1", description="A", status=SwarmTaskStatus.DISPATCHED)
        bridge._last_status = SwarmStatus(
            phase=SwarmPhase.EXECUTING,
            active_workers=[SwarmWorkerStatus(task_id="t1", task_description="A", model="m", worker_name="w")],
        )
        event = SwarmEvent(type="swarm.task.failed", data={
            "task_id": "t1", "error": "timeout", "failure_mode": "timeout",
        })
        bridge._handle_event(event)
        assert bridge._tasks["t1"].status == SwarmTaskStatus.FAILED
        assert bridge._last_status.active_workers == []

    def test_task_failed_records_error(self) -> None:
        bridge = SwarmEventBridge()
        bridge._tasks["t1"] = SwarmTask(id="t1", description="A", status=SwarmTaskStatus.DISPATCHED)
        bridge._last_status = SwarmStatus(
            phase=SwarmPhase.EXECUTING,
            active_workers=[SwarmWorkerStatus(task_id="t1", task_description="A", model="m", worker_name="w")],
        )
        event = SwarmEvent(type="swarm.task.failed", data={
            "task_id": "t1", "error": "boom",
        })
        bridge._handle_event(event)
        assert len(bridge._errors) == 1
        assert bridge._errors[0]["task_id"] == "t1"

    def test_task_skipped_updates_task(self) -> None:
        bridge = SwarmEventBridge()
        bridge._tasks["t1"] = SwarmTask(id="t1", description="A", status=SwarmTaskStatus.PENDING)
        bridge._last_status = SwarmStatus(phase=SwarmPhase.EXECUTING)
        event = SwarmEvent(type="swarm.task.skipped", data={"task_id": "t1"})
        bridge._handle_event(event)
        assert bridge._tasks["t1"].status == SwarmTaskStatus.SKIPPED

    def test_swarm_complete_sets_phase(self) -> None:
        bridge = SwarmEventBridge()
        bridge._last_status = SwarmStatus(
            phase=SwarmPhase.EXECUTING,
            active_workers=[
                SwarmWorkerStatus(task_id="t1", task_description="A", model="m", worker_name="w1"),
                SwarmWorkerStatus(task_id="t2", task_description="B", model="m", worker_name="w2"),
            ],
        )
        event = SwarmEvent(type="swarm.complete", data={})
        bridge._handle_event(event)
        assert bridge._last_status.phase == SwarmPhase.COMPLETED
        assert bridge._last_status.active_workers == []

    def test_swarm_complete_cancels_pending_write(self) -> None:
        bridge = SwarmEventBridge()
        bridge._last_status = SwarmStatus(phase=SwarmPhase.EXECUTING)
        mock_handle = MagicMock()
        bridge._pending_write = mock_handle
        event = SwarmEvent(type="swarm.complete", data={})
        bridge._handle_event(event)
        mock_handle.cancel.assert_called_once()
        assert bridge._pending_write is None

    def test_swarm_error_records_error(self) -> None:
        bridge = SwarmEventBridge()
        event = SwarmEvent(type="swarm.error", data={
            "phase": "executing", "message": "something broke",
        })
        bridge._handle_event(event)
        assert len(bridge._errors) == 1
        assert bridge._errors[0]["message"] == "something broke"

    def test_seq_increments(self) -> None:
        bridge = SwarmEventBridge()
        bridge._handle_event(SwarmEvent(type="swarm.start", data={}))
        # swarm.start resets seq to 1
        assert bridge._seq == 1
        bridge._handle_event(SwarmEvent(type="swarm.budget.update", data={}))
        assert bridge._seq == 2

    def test_model_health_upsert_creates(self) -> None:
        bridge = SwarmEventBridge()
        event = SwarmEvent(type="swarm.model.health", data={
            "model": "gpt-4", "successes": 5, "failures": 1, "healthy": True,
        })
        bridge._handle_event(event)
        assert len(bridge._model_health) == 1
        assert bridge._model_health[0].model == "gpt-4"
        assert bridge._model_health[0].successes == 5

    def test_model_health_upsert_updates(self) -> None:
        bridge = SwarmEventBridge()
        event1 = SwarmEvent(type="swarm.model.health", data={
            "model": "gpt-4", "successes": 5, "failures": 1,
        })
        bridge._handle_event(event1)
        event2 = SwarmEvent(type="swarm.model.health", data={
            "model": "gpt-4", "successes": 10,
        })
        bridge._handle_event(event2)
        assert len(bridge._model_health) == 1
        assert bridge._model_health[0].successes == 10

    def test_decision_event(self) -> None:
        bridge = SwarmEventBridge()
        event = SwarmEvent(type="swarm.orchestrator.decision", data={
            "phase": "recovery", "decision": "micro-decompose", "reasoning": "complex task",
        })
        bridge._handle_event(event)
        assert len(bridge._decisions) == 1
        assert bridge._decisions[0].decision == "micro-decompose"

    def test_error_list_capped_at_100(self) -> None:
        bridge = SwarmEventBridge()
        bridge._last_status = SwarmStatus(phase=SwarmPhase.EXECUTING, active_workers=[])
        for i in range(110):
            bridge._tasks[f"t{i}"] = SwarmTask(id=f"t{i}", description=f"task-{i}", status=SwarmTaskStatus.DISPATCHED)
            event = SwarmEvent(type="swarm.task.failed", data={
                "task_id": f"t{i}", "error": f"error-{i}",
            })
            bridge._handle_event(event)
        assert len(bridge._errors) <= 100

    def test_unknown_event_goes_to_timeline(self) -> None:
        bridge = SwarmEventBridge()
        event = SwarmEvent(type="swarm.custom.event", data={"task_id": "t1"})
        bridge._handle_event(event)
        assert len(bridge._timeline) == 1
        assert bridge._timeline[0]["type"] == "swarm.custom.event"


class TestSwarmEventBridgeClose:
    """close method works without error."""

    def test_close_without_events_file(self) -> None:
        bridge = SwarmEventBridge()
        bridge.close()  # Should not raise

    def test_close_with_events_file(self) -> None:
        bridge = SwarmEventBridge()
        mock_file = MagicMock()
        bridge._events_file = mock_file
        bridge.close()
        mock_file.close.assert_called_once()
        assert bridge._events_file is None

    def test_close_cancels_pending_write(self) -> None:
        bridge = SwarmEventBridge()
        mock_handle = MagicMock()
        bridge._pending_write = mock_handle
        bridge.close()
        mock_handle.cancel.assert_called_once()
        assert bridge._pending_write is None

    def test_close_idempotent(self) -> None:
        bridge = SwarmEventBridge()
        bridge.close()
        bridge.close()  # Should not raise


class TestSwarmEventBridgeQueueStats:
    """_update_queue_stats recalculates correctly."""

    def test_queue_stats_after_task_changes(self) -> None:
        bridge = SwarmEventBridge()
        bridge._last_status = SwarmStatus(phase=SwarmPhase.EXECUTING)
        bridge._tasks = {
            "t1": SwarmTask(id="t1", description="A", status=SwarmTaskStatus.PENDING),
            "t2": SwarmTask(id="t2", description="B", status=SwarmTaskStatus.DISPATCHED),
            "t3": SwarmTask(id="t3", description="C", status=SwarmTaskStatus.COMPLETED),
            "t4": SwarmTask(id="t4", description="D", status=SwarmTaskStatus.FAILED),
            "t5": SwarmTask(id="t5", description="E", status=SwarmTaskStatus.SKIPPED),
        }
        bridge._update_queue_stats()
        q = bridge._last_status.queue
        assert q.ready == 1  # PENDING counts as ready
        assert q.running == 1
        assert q.completed == 1
        assert q.failed == 1
        assert q.skipped == 1
        assert q.total == 5


# =============================================================================
# Execution Tests
# =============================================================================


class TestClassifyFailure:
    """_classify_failure recognizes failure types."""

    def test_rate_limit_429(self) -> None:
        assert _classify_failure("Error 429 Too Many Requests") == "rate-limit"

    def test_rate_limit_text(self) -> None:
        assert _classify_failure("rate limit exceeded") == "rate-limit"

    def test_rate_limit_too_many_requests(self) -> None:
        assert _classify_failure("too many requests") == "rate-limit"

    def test_payment_required_402(self) -> None:
        assert _classify_failure("Error 402 Payment Required") == "rate-limit"

    def test_payment_required_text(self) -> None:
        assert _classify_failure("payment required") == "rate-limit"

    def test_insufficient_funds(self) -> None:
        assert _classify_failure("insufficient balance") == "rate-limit"

    def test_timeout_text(self) -> None:
        assert _classify_failure("request timeout") == "timeout"

    def test_timed_out(self) -> None:
        assert _classify_failure("connection timed out") == "timeout"

    def test_generic_error(self) -> None:
        assert _classify_failure("something went wrong") == "error"

    def test_empty_string(self) -> None:
        assert _classify_failure("") == "error"

    def test_none_like_empty(self) -> None:
        assert _classify_failure("") == "error"

    def test_case_insensitive(self) -> None:
        assert _classify_failure("RATE LIMIT") == "rate-limit"
        assert _classify_failure("TIMEOUT") == "timeout"

    def test_mixed_content_rate_limit(self) -> None:
        assert _classify_failure("The API returned a 429 status code due to rate limit") == "rate-limit"

    def test_mixed_content_timeout(self) -> None:
        assert _classify_failure("The request timed out after 30 seconds") == "timeout"
