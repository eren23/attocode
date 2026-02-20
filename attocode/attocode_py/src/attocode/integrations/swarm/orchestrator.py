"""Swarm orchestrator — main coordinator for multi-agent task execution.

The orchestrator decomposes a task, schedules waves of subtasks across
workers, manages quality gates, recovery, and produces a final result.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from attocode.integrations.swarm.types import (
    BUILTIN_TASK_TYPE_CONFIGS,
    ArtifactInventory,
    ModelHealthRecord,
    OrchestratorDecision,
    SmartDecompositionResult,
    SwarmCheckpoint,
    SwarmConfig,
    SwarmError,
    SwarmEvent,
    SwarmEventListener,
    SwarmExecutionResult,
    SwarmExecutionStats,
    SwarmPhase,
    SwarmPlan,
    SwarmStatus,
    SwarmTask,
    SwarmTaskStatus,
    VerificationResult,
    swarm_event,
)

logger = logging.getLogger(__name__)


# =============================================================================
# OrchestratorInternals — shared context for cross-module delegation
# =============================================================================


@dataclass
class OrchestratorInternals:
    """Shared context object passed to execution/lifecycle/recovery modules.

    Holds all mutable state and bound callables so that extracted modules
    can operate on orchestrator state without circular imports.
    """

    config: SwarmConfig
    provider: Any  # LLMProvider
    task_queue: Any  # SwarmTaskQueue
    worker_pool: Any  # SwarmWorkerPool
    budget_pool: Any  # DynamicBudgetPool or similar
    health_tracker: Any  # ModelHealthTracker
    decomposer: Any  # SmartDecomposer or similar
    synthesizer: Any  # ResultSynthesizer
    shared_context_state: Any  # SharedContextState
    shared_economics_state: Any  # SharedEconomicsState
    shared_context_engine: Any  # SharedContextEngine
    blackboard: Any | None  # SharedBlackboard
    state_store: Any | None  # SwarmStateStore
    spawn_agent_fn: Any  # SpawnAgentFn
    codebase_context: Any | None  # CodebaseContextManager

    # Mutable orchestrator state
    cancelled: bool = False
    current_phase: SwarmPhase = SwarmPhase.IDLE
    total_tokens: int = 0
    total_cost: float = 0.0
    quality_rejections: int = 0
    retries: int = 0
    orchestrator_tokens: int = 0
    orchestrator_cost: float = 0.0
    orchestrator_calls: int = 0
    plan: SwarmPlan | None = None
    verification_result: VerificationResult | None = None
    artifact_inventory: ArtifactInventory | None = None
    hollow_streak: int = 0
    total_dispatches: int = 0
    total_hollows: int = 0
    original_prompt: str = ""
    has_replanned: bool = False

    # Collected data
    errors: list[SwarmError] = field(default_factory=list)
    wave_reviews: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[OrchestratorDecision] = field(default_factory=list)

    # Bound callables (set by orchestrator)
    emit: Any = None  # Callable[[SwarmEvent], None]
    log_decision: Any = None  # Callable[[str, str, str], None]
    track_orchestrator_usage: Any = None  # Callable
    execute_waves_delegate: Any = None  # Callable[[], Awaitable[None]]
    execute_wave_delegate: Any = None  # Callable[[list], Awaitable[None]]
    final_rescue_pass_delegate: Any = None  # Callable[[], Awaitable[None]]


# =============================================================================
# SwarmOrchestrator
# =============================================================================


class SwarmOrchestrator:
    """Main swarm orchestrator.

    Coordinates decomposition, scheduling, wave execution, quality gates,
    recovery, verification, and synthesis for multi-agent task completion.
    """

    def __init__(
        self,
        config: SwarmConfig,
        provider: Any,
        agent_registry: Any = None,
        spawn_agent_fn: Any = None,
        blackboard: Any = None,
    ) -> None:
        self._config = config
        self._provider = provider
        self._agent_registry = agent_registry
        self._spawn_agent_fn = spawn_agent_fn
        self._blackboard = blackboard
        self._listeners: list[SwarmEventListener] = []

        # These are created lazily or injected
        self._task_queue: Any = None
        self._worker_pool: Any = None
        self._budget_pool: Any = None
        self._health_tracker: Any = None
        self._decomposer: Any = None
        self._synthesizer: Any = None
        self._shared_context_state: Any = None
        self._shared_economics_state: Any = None
        self._shared_context_engine: Any = None
        self._state_store: Any = None
        self._event_bridge: Any = None

    def _initialize_subsystems(self) -> None:
        """Create all subsystems. Called before execute()."""
        from attocode.integrations.swarm.model_selector import ModelHealthTracker
        from attocode.integrations.swarm.task_queue import SwarmTaskQueue
        from attocode.integrations.swarm.worker_pool import SwarmWorkerPool

        self._health_tracker = ModelHealthTracker()

        self._task_queue = SwarmTaskQueue()
        self._task_queue.partial_dependency_threshold = self._config.partial_dependency_threshold
        self._task_queue.artifact_aware_skip = self._config.artifact_aware_skip

        self._budget_pool = _SimpleBudgetPool(self._config.total_budget)

        self._worker_pool = SwarmWorkerPool(
            config=self._config,
            spawn_agent_fn=self._spawn_agent_fn,
            budget_pool=self._budget_pool,
            health_tracker=self._health_tracker,
        )

    def _get_internals(self) -> OrchestratorInternals:
        """Create a snapshot of orchestrator internals for delegation."""
        ctx = OrchestratorInternals(
            config=self._config,
            provider=self._provider,
            task_queue=self._task_queue,
            worker_pool=self._worker_pool,
            budget_pool=self._budget_pool,
            health_tracker=self._health_tracker,
            decomposer=self._decomposer,
            synthesizer=self._synthesizer,
            shared_context_state=self._shared_context_state,
            shared_economics_state=self._shared_economics_state,
            shared_context_engine=self._shared_context_engine,
            blackboard=self._blackboard,
            state_store=self._state_store,
            spawn_agent_fn=self._spawn_agent_fn,
            codebase_context=self._config.codebase_context,
        )

        # Bind callables
        ctx.emit = self._emit
        ctx.log_decision = self._log_decision
        ctx.track_orchestrator_usage = self._track_orchestrator_usage

        return ctx

    def _sync_from_internals(self, ctx: OrchestratorInternals) -> None:
        """Copy mutable primitives back from internals."""
        self._cancelled = ctx.cancelled
        self._current_phase = ctx.current_phase
        self._total_tokens = ctx.total_tokens
        self._total_cost = ctx.total_cost
        self._quality_rejections = ctx.quality_rejections
        self._retries = ctx.retries
        self._orchestrator_tokens = ctx.orchestrator_tokens
        self._orchestrator_cost = ctx.orchestrator_cost
        self._orchestrator_calls = ctx.orchestrator_calls
        self._plan = ctx.plan
        self._verification_result = ctx.verification_result
        self._artifact_inventory = ctx.artifact_inventory
        self._hollow_streak = ctx.hollow_streak
        self._total_dispatches = ctx.total_dispatches
        self._total_hollows = ctx.total_hollows
        self._original_prompt = ctx.original_prompt
        self._has_replanned = ctx.has_replanned

    async def execute(self, task: str) -> SwarmExecutionResult:
        """Execute a full swarm pipeline for the given task.

        Pipeline:
        1. Decompose task into subtasks
        2. Schedule into waves
        3. Optionally probe models
        4. Optionally plan execution
        5. Execute waves with workers
        6. Final rescue pass
        7. Artifact audit
        8. Optional verification
        9. Synthesize outputs
        10. Return result
        """
        from attocode.integrations.swarm.execution import execute_waves
        from attocode.integrations.swarm.lifecycle import (
            build_artifact_inventory,
            build_error_result,
            build_stats,
            build_summary,
            decompose_task,
            detect_foundation_tasks,
            save_checkpoint,
            synthesize_outputs,
        )
        from attocode.integrations.swarm.recovery import (
            SwarmRecoveryState,
            final_rescue_pass,
        )

        self._initialize_subsystems()

        # Reset mutable state
        self._cancelled = False
        self._current_phase = SwarmPhase.IDLE
        self._total_tokens = 0
        self._total_cost = 0.0
        self._quality_rejections = 0
        self._retries = 0
        self._orchestrator_tokens = 0
        self._orchestrator_cost = 0.0
        self._orchestrator_calls = 0
        self._plan = None
        self._verification_result = None
        self._artifact_inventory = None
        self._hollow_streak = 0
        self._total_dispatches = 0
        self._total_hollows = 0
        self._original_prompt = task
        self._has_replanned = False

        ctx = self._get_internals()
        ctx.original_prompt = task
        recovery_state = SwarmRecoveryState(
            adaptive_stagger_ms=self._config.dispatch_stagger_ms,
        )

        try:
            # Phase 1: Decompose
            ctx.current_phase = SwarmPhase.DECOMPOSING
            decomp_result = await decompose_task(ctx, task)
            decomposition = decomp_result.get("result")
            if not decomposition or not decomposition.subtasks:
                self._sync_from_internals(ctx)
                return build_error_result(ctx, "Decomposition produced no subtasks")

            # Phase 2: Schedule
            ctx.current_phase = SwarmPhase.SCHEDULING
            self._task_queue.load_from_decomposition(decomposition, self._config)

            # Compute dynamic orchestrator reserve
            subtask_count = len(decomposition.subtasks)
            reserve = min(0.4, max(
                self._config.orchestrator_reserve_ratio,
                subtask_count * 0.05,
            ))
            logger.info(
                "Orchestrator reserve ratio: %.2f (subtasks=%d)",
                reserve, subtask_count,
            )

            detect_foundation_tasks(ctx)

            # Phase 3: Model probing (simplified)
            if self._config.probe_models is not False:
                logger.info("Skipping model probing in Python port (not yet implemented)")

            # Phase 4: Planning (concurrent, non-blocking)
            if self._config.enable_planning:
                ctx.current_phase = SwarmPhase.PLANNING
                # Planning runs concurrently — we don't await it here
                # In a full implementation this would be: asyncio.create_task(plan_execution(...))

            # Emit start
            total_tasks = len(self._task_queue.get_all_tasks())
            total_waves = self._task_queue.get_total_waves()
            self._emit(swarm_event("swarm.start", task_count=total_tasks, wave_count=total_waves))
            self._emit(swarm_event("swarm.tasks.loaded", tasks=self._task_queue.get_all_tasks()))

            # Phase 5: Execute waves
            ctx.current_phase = SwarmPhase.EXECUTING
            await execute_waves(ctx, recovery_state, self.get_status)
            self._sync_from_internals(ctx)

            # Phase 6: Final rescue pass
            async def exec_wave_fn(tasks: list[SwarmTask]) -> None:
                from attocode.integrations.swarm.execution import execute_wave
                await execute_wave(ctx, recovery_state, tasks, self.get_status)

            await final_rescue_pass(ctx, exec_wave_fn)
            self._sync_from_internals(ctx)

            # Phase 7: Artifact audit
            ctx.artifact_inventory = build_artifact_inventory(ctx)

            # Phase 8: Verification (simplified)
            if self._config.enable_verification and ctx.plan and ctx.plan.integration_test_plan:
                ctx.current_phase = SwarmPhase.VERIFYING
                # Full verification would call verify_integration here

            # Phase 9: Synthesis
            ctx.current_phase = SwarmPhase.SYNTHESIZING
            synthesis = await synthesize_outputs(ctx)

            # Phase 10: Complete
            ctx.current_phase = SwarmPhase.COMPLETED
            stats = build_stats(ctx)
            summary = build_summary(ctx, stats)
            save_checkpoint(ctx, "final")

            self._emit(swarm_event(
                "swarm.complete",
                stats=stats,
                errors=ctx.errors,
                artifact_inventory=ctx.artifact_inventory,
            ))

            self._sync_from_internals(ctx)

            # Success threshold: 70%
            success = (
                stats.completed_tasks / stats.total_tasks >= 0.7
                if stats.total_tasks > 0
                else False
            )

            return SwarmExecutionResult(
                success=success,
                summary=summary,
                stats=stats,
                errors=[{"phase": e.phase, "message": e.message, "task_id": e.task_id} for e in ctx.errors],
                plan=ctx.plan,
                verification=ctx.verification_result,
                artifact_inventory=ctx.artifact_inventory,
            )

        except Exception as exc:
            ctx.current_phase = SwarmPhase.FAILED
            self._sync_from_internals(ctx)
            self._emit(swarm_event("swarm.error", error=str(exc), phase=str(ctx.current_phase)))
            return build_error_result(ctx, str(exc))

    def get_status(self) -> SwarmStatus:
        """Get live swarm status snapshot for TUI."""
        from attocode.integrations.swarm.types import (
            SwarmBudgetStatus,
            SwarmOrchestratorStatus,
        )

        queue_stats = self._task_queue.get_stats() if self._task_queue else None

        return SwarmStatus(
            phase=getattr(self, "_current_phase", SwarmPhase.IDLE),
            current_wave=(self._task_queue.get_current_wave() + 1) if self._task_queue else 0,
            total_waves=self._task_queue.get_total_waves() if self._task_queue else 0,
            active_workers=self._worker_pool.get_active_worker_statuses() if self._worker_pool else [],
            queue=queue_stats if queue_stats else SwarmStatus().queue,
            budget=SwarmBudgetStatus(
                tokens_used=getattr(self, "_total_tokens", 0) + getattr(self, "_orchestrator_tokens", 0),
                tokens_total=self._config.total_budget,
                cost_used=getattr(self, "_total_cost", 0.0) + getattr(self, "_orchestrator_cost", 0.0),
                cost_total=self._config.max_cost,
            ),
            orchestrator=SwarmOrchestratorStatus(
                tokens=getattr(self, "_orchestrator_tokens", 0),
                cost=getattr(self, "_orchestrator_cost", 0.0),
                calls=getattr(self, "_orchestrator_calls", 0),
            ),
        )

    def subscribe(self, listener: SwarmEventListener) -> callable:
        """Register an event listener. Returns unsubscribe function."""
        self._listeners.append(listener)

        def unsubscribe() -> None:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass

        return unsubscribe

    async def cancel(self) -> None:
        """Cancel the swarm execution."""
        self._cancelled = True
        self._current_phase = SwarmPhase.FAILED
        if self._worker_pool:
            await self._worker_pool.cancel_all()

    def get_budget_pool(self) -> Any:
        """Expose budget pool for parent agent."""
        return self._budget_pool

    def get_shared_context_state(self) -> Any:
        return self._shared_context_state

    def get_shared_economics_state(self) -> Any:
        return self._shared_economics_state

    def get_shared_context_engine(self) -> Any:
        return self._shared_context_engine

    def _emit(self, event: SwarmEvent) -> None:
        """Emit event to all listeners."""
        for listener in self._listeners:
            try:
                listener(event)
            except Exception:
                pass

    def _log_decision(self, phase: str, decision: str, reasoning: str) -> None:
        """Record an orchestrator decision."""
        logger.info("Decision [%s]: %s — %s", phase, decision, reasoning)

    def _track_orchestrator_usage(self, response: Any, purpose: str) -> None:
        """Track token usage from an orchestrator LLM call."""
        if hasattr(response, "usage") and response.usage:
            tokens = getattr(response.usage, "total_tokens", 0)
            self._orchestrator_tokens = getattr(self, "_orchestrator_tokens", 0) + tokens
            self._orchestrator_calls = getattr(self, "_orchestrator_calls", 0) + 1


# =============================================================================
# Simple Budget Pool (placeholder until full DynamicBudgetPool)
# =============================================================================


class _SimpleBudgetPool:
    """Simple budget pool for token allocation."""

    def __init__(self, total_budget: int) -> None:
        self._total = total_budget
        self._used = 0

    def has_capacity(self, amount: int = 1000) -> bool:
        return self._used + amount < self._total

    def allocate(self, amount: int) -> bool:
        if not self.has_capacity(amount):
            return False
        self._used += amount
        return True

    def release(self, amount: int) -> None:
        self._used = max(0, self._used - amount)

    def reallocate_unused(self) -> None:
        pass

    @property
    def remaining(self) -> int:
        return max(0, self._total - self._used)

    @property
    def used(self) -> int:
        return self._used


# =============================================================================
# Factory
# =============================================================================


def create_swarm_orchestrator(
    config: SwarmConfig,
    provider: Any,
    agent_registry: Any = None,
    spawn_agent_fn: Any = None,
    blackboard: Any = None,
) -> SwarmOrchestrator:
    """Create a swarm orchestrator instance."""
    return SwarmOrchestrator(
        config=config,
        provider=provider,
        agent_registry=agent_registry,
        spawn_agent_fn=spawn_agent_fn,
        blackboard=blackboard,
    )
