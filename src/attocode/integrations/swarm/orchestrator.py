"""Swarm orchestrator — main coordinator for multi-agent task execution.

The orchestrator decomposes a task, schedules waves of subtasks across
workers, manages quality gates, recovery, and produces a final result.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from attocode.integrations.swarm.types import (
    ArtifactInventory,
    OrchestratorDecision,
    SpawnResult,
    SwarmCheckpoint,
    SwarmConfig,
    SwarmError,
    SwarmEvent,
    SwarmEventListener,
    SwarmExecutionResult,
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
    message_bus: Any | None  # SwarmMessageBus
    state_store: Any | None  # SwarmStateStore
    spawn_agent_fn: Any  # SpawnAgentFn
    codebase_context: Any | None  # CodebaseContextManager

    # Mutable orchestrator state
    cancelled: bool = False
    paused: bool = False
    pause_event: asyncio.Event = field(default_factory=lambda: asyncio.Event())
    _role_map_cache: dict[str, Any] | None = None
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
    replan_count: int = 0
    scout_tokens: int = 0

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
        self._paused: bool = False
        self._cancelled: bool = False

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
        self._message_bus: Any = None
        self._active_ctx: OrchestratorInternals | None = None  # Set during execute()

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

        # Auto-select OpenShell spawn function when sandbox_mode=openshell
        # and no explicit spawn function was provided
        effective_spawn_fn = self._spawn_agent_fn
        if self._config.sandbox_mode == "openshell" and effective_spawn_fn is None:
            try:
                import os

                from attocode.integrations.swarm.openshell_spawner import (
                    create_openshell_spawn_fn,
                )

                effective_spawn_fn = create_openshell_spawn_fn(
                    working_dir=os.getcwd(),
                    config=self._config,
                )
                logger.info("Auto-selected OpenShell spawn function (sandbox_mode=openshell)")
            except Exception as exc:
                logger.warning("Failed to create OpenShell spawn function: %s", exc)

        self._worker_pool = SwarmWorkerPool(
            config=self._config,
            spawn_agent_fn=effective_spawn_fn or self._spawn_agent_fn,
            budget_pool=self._budget_pool,
            health_tracker=self._health_tracker,
        )

        # Initialize message bus for inter-worker communication
        try:
            import os

            from attocode.integrations.swarm.message_bus import SwarmMessageBus
            bus_path = os.path.join(self._config.state_dir, "message_bus.db")
            os.makedirs(os.path.dirname(bus_path), exist_ok=True)
            self._message_bus = SwarmMessageBus(bus_path)
        except Exception:
            logger.debug("Message bus initialization failed; using in-memory fallback")
            try:
                from attocode.integrations.swarm.message_bus import SwarmMessageBus
                self._message_bus = SwarmMessageBus(":memory:")
            except Exception:
                self._message_bus = None
                logger.warning(
                    "Message bus initialization failed completely; "
                    "inter-worker communication will be unavailable"
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
            message_bus=self._message_bus,
            state_store=self._state_store,
            spawn_agent_fn=self._spawn_agent_fn,
            codebase_context=self._config.codebase_context,
        )

        ctx.pause_event.set()  # Start unpaused

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
        self._replan_count = ctx.replan_count

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
            save_checkpoint,
            synthesize_outputs,
        )
        from attocode.integrations.swarm.recovery import (
            SwarmRecoveryState,
            final_rescue_pass,
        )

        self._initialize_subsystems()

        # Reset mutable state
        self._paused = False
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
        self._replan_count = 0

        ctx = self._get_internals()
        ctx.original_prompt = task
        self._active_ctx = ctx
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

            self._detect_foundation_tasks(ctx)

            # Phase 3: Model probing
            if self._config.probe_models is not False:
                try:
                    from attocode.integrations.swarm.model_selector import probe_worker_models

                    probe_results = await probe_worker_models(
                        provider=self._provider,
                        workers=self._config.workers,
                        health_tracker=self._health_tracker,
                        timeout_ms=self._config.probe_timeout_ms,
                        failure_strategy=self._config.probe_failure_strategy.value,
                    )
                    failed_count = sum(1 for r in probe_results if not r.success)
                    if failed_count > 0:
                        logger.warning(
                            "Model probing: %d/%d models failed",
                            failed_count, len(probe_results),
                        )
                except RuntimeError as probe_err:
                    # abort strategy raises RuntimeError
                    self._sync_from_internals(ctx)
                    return build_error_result(ctx, f"Model probing failed: {probe_err}")
                except Exception as probe_err:
                    logger.warning("Model probing failed: %s", probe_err)

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

            # Post-wave review
            completed_tasks = [t for t in ctx.task_queue.get_all_tasks().values() if t.status == SwarmTaskStatus.COMPLETED]
            fix_ups = await self._review_wave_results(completed_tasks, ctx)
            if fix_ups:
                for fix_task in fix_ups:
                    ctx.task_queue.add_task(fix_task)

            # Phase 6: Final rescue pass
            async def exec_wave_fn(tasks: list[SwarmTask]) -> None:
                from attocode.integrations.swarm.execution import execute_wave
                await execute_wave(ctx, recovery_state, tasks, self.get_status)

            await final_rescue_pass(ctx, exec_wave_fn)
            self._sync_from_internals(ctx)

            # Phase 7: Artifact audit
            ctx.artifact_inventory = build_artifact_inventory(ctx)

            # Phase 8: Verification
            if self._config.enable_verification:
                ctx.current_phase = SwarmPhase.VERIFYING
                ctx.verification_result = await self._verify_integration(ctx)

            # Phase 9: Synthesis
            ctx.current_phase = SwarmPhase.SYNTHESIZING
            _synthesis = await synthesize_outputs(ctx)

            # Save final state
            await self._save_state(ctx, "final")

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

    async def pause(self) -> None:
        """Pause dispatching new tasks. Running tasks continue."""
        self._paused = True
        if self._active_ctx:
            self._active_ctx.paused = True
            self._active_ctx.pause_event.clear()
        self._emit(swarm_event("swarm.paused", message="Dispatch paused by user"))

    async def resume(self) -> None:
        """Resume dispatching after a pause."""
        self._paused = False
        if self._active_ctx:
            self._active_ctx.paused = False
            self._active_ctx.pause_event.set()
        self._emit(swarm_event("swarm.resumed", message="Dispatch resumed"))

    @property
    def paused(self) -> bool:
        """Whether dispatching is paused."""
        return self._paused

    async def skip_task(self, task_id: str) -> bool:
        """Skip a pending/ready task and cascade-skip dependents. Returns True if skipped."""
        if not self._task_queue:
            return False
        task = self._task_queue.get_task(task_id)
        if not task or task.status not in (SwarmTaskStatus.PENDING, SwarmTaskStatus.READY):
            return False
        task.status = SwarmTaskStatus.SKIPPED
        self._emit(swarm_event(
            "swarm.task.skipped",
            task_id=task_id,
            description=task.description,
            reason="skipped_by_user",
        ))
        # Cascade-skip dependents so they don't hang waiting
        self._task_queue.trigger_cascade_skip(task_id)
        return True

    async def retry_task(self, task_id: str) -> bool:
        """Re-queue a failed task for retry. Returns True if re-queued."""
        if not self._task_queue:
            return False
        task = self._task_queue.get_task(task_id)
        if not task or task.status != SwarmTaskStatus.FAILED:
            return False
        task.attempts = max(0, task.attempts - 1)
        task.status = SwarmTaskStatus.READY
        task.failure_mode = None
        self._emit(swarm_event(
            "swarm.task.retry_queued",
            task_id=task_id,
            description=task.description,
            message="Task re-queued by user",
        ))
        return True

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

    async def _review_wave_results(
        self,
        wave_tasks: list[SwarmTask],
        ctx: OrchestratorInternals,
    ) -> list[SwarmTask]:
        """Post-wave review: analyze results and generate fix-up tasks.

        After each wave completes, reviews the results to identify:
        - Hollow completions that need re-execution
        - Integration issues between completed tasks
        - Missing acceptance criteria

        Returns a list of fix-up tasks to add to the queue.
        """
        from attocode.integrations.swarm.helpers import is_hollow_completion as check_hollow
        from attocode.integrations.swarm.types import FixupTask

        fix_ups: list[SwarmTask] = []
        hollow_count = 0

        for task in wave_tasks:
            if task.status != SwarmTaskStatus.COMPLETED:
                continue

            result = task.result
            if result is None:
                continue

            # Check for hollow completions using the helpers module
            spawn_like = SpawnResult(
                output=result.output,
                files_modified=result.files_modified or [],
                tool_calls=result.tool_calls or 0,
                success=result.success if hasattr(result, "success") else True,
            )
            task_type_str = task.type.value if hasattr(task.type, "value") else str(task.type)
            if check_hollow(spawn_like, task_type_str, self._config):
                hollow_count += 1
                ctx.total_hollows += 1
                ctx.hollow_streak += 1

                self._emit(swarm_event(
                    "swarm.hollow_detected",
                    task_id=task.id,
                    task_description=task.description,
                ))

                # If streak is short, retry the task
                if ctx.hollow_streak <= 3:
                    retry_task = FixupTask(
                        id=f"{task.id}_retry",
                        description=(
                            f"[RETRY - be concrete] {task.description}. "
                            "You MUST produce actual code/file changes, not just explanations."
                        ),
                        type=task.type,
                        dependencies=task.dependencies,
                        fixes_task_id=task.id,
                        fix_instructions="Previous attempt was hollow - produce real artifacts",
                    )
                    fix_ups.append(retry_task)
                    ctx.retries += 1
            else:
                ctx.hollow_streak = 0  # Reset streak on real completion

        # Log wave review
        review = {
            "wave_tasks": len(wave_tasks),
            "completed": sum(1 for t in wave_tasks if t.status == SwarmTaskStatus.COMPLETED),
            "hollow": hollow_count,
            "fix_ups_generated": len(fix_ups),
        }
        ctx.wave_reviews.append(review)

        self._emit(swarm_event("swarm.wave_review", review=review))

        return fix_ups

    async def _verify_integration(
        self,
        ctx: OrchestratorInternals,
    ) -> VerificationResult:
        """Verify integration of completed work.

        Runs basic validation:
        1. Check that all artifact files exist
        2. Run integration test plan steps if available

        Returns VerificationResult.
        """
        import subprocess

        from attocode.integrations.swarm.types import VerificationStepResult

        steps: list[VerificationStepResult] = []
        step_index = 0

        # Check artifact inventory files
        if ctx.artifact_inventory and ctx.artifact_inventory.files:
            import os

            for artifact in ctx.artifact_inventory.files:
                exists = os.path.isfile(artifact.path)
                steps.append(VerificationStepResult(
                    step_index=step_index,
                    description=f"Artifact exists: {artifact.path}",
                    passed=exists,
                    output="" if exists else f"File not found: {artifact.path}",
                ))
                step_index += 1

        # Run integration test plan steps if available
        if ctx.plan and ctx.plan.integration_test_plan:
            test_plan = ctx.plan.integration_test_plan
            for test_step in test_plan.steps:
                if not test_step.command:
                    continue
                try:
                    import shlex
                    # Use shlex.split for proper shell-like argument parsing
                    cmd_parts = shlex.split(test_step.command)
                    proc = subprocess.run(
                        cmd_parts,
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    passed = proc.returncode == 0
                    steps.append(VerificationStepResult(
                        step_index=step_index,
                        description=test_step.description,
                        passed=passed,
                        output=proc.stdout[:500] if passed else proc.stderr[:500],
                    ))
                except Exception as e:
                    steps.append(VerificationStepResult(
                        step_index=step_index,
                        description=test_step.description,
                        passed=False,
                        output=f"Execution error: {e}",
                    ))
                step_index += 1

        total = len(steps)
        passed_count = sum(1 for s in steps if s.passed)
        overall_passed = total == 0 or (passed_count / max(1, total) >= 0.7)

        return VerificationResult(
            passed=overall_passed,
            steps=steps,
            summary=f"{passed_count}/{total} checks passed",
        )

    async def _save_state(
        self,
        ctx: OrchestratorInternals,
        label: str = "",
    ) -> bool:
        """Save orchestrator state for checkpoint/resume.

        Persists current swarm state to the state store so execution
        can be resumed later.
        """
        if ctx.state_store is None:
            return False

        try:
            import time as _time

            checkpoint = SwarmCheckpoint(
                session_id=ctx.config.resume_session_id or "",
                timestamp=_time.time(),
                phase=str(ctx.current_phase),
                stats={
                    "total_tokens": ctx.total_tokens,
                    "total_cost": ctx.total_cost,
                    "orchestrator_tokens": ctx.orchestrator_tokens,
                    "quality_rejections": ctx.quality_rejections,
                    "retries": ctx.retries,
                },
                errors=[
                    SwarmError(
                        timestamp=e.timestamp,
                        phase=e.phase,
                        message=e.message,
                        task_id=e.task_id,
                    )
                    for e in ctx.errors
                ],
                original_prompt=ctx.original_prompt,
            )
            await ctx.state_store.save_checkpoint(checkpoint)

            self._emit(swarm_event("swarm.checkpoint_saved", label=label))
            return True
        except Exception as e:
            logger.warning("Failed to save swarm state: %s", e)
            return False

    def _detect_foundation_tasks(self, ctx: OrchestratorInternals) -> None:
        """Mark tasks that are depended on by 3+ other tasks as foundation tasks.

        Foundation tasks get:
        - is_foundation flag
        - Extra retries (+1)
        - Relaxed quality threshold (-1)
        """
        all_tasks = ctx.task_queue.get_all_tasks()

        # Count dependents for each task
        dependent_count: dict[str, int] = {}
        for task in all_tasks.values():
            for dep_id in task.dependencies or []:
                dependent_count[dep_id] = dependent_count.get(dep_id, 0) + 1

        # Mark foundation tasks
        for task in all_tasks.values():
            if dependent_count.get(task.id, 0) >= 3:
                task.is_foundation = True

                self._emit(swarm_event(
                    "swarm.foundation_task",
                    task_id=task.id,
                    dependents=dependent_count[task.id],
                ))


class _SimpleBudgetPool:
    """Simple budget pool for token allocation.

    Supports both the legacy ``allocate(amount)``/``release(amount)`` API
    and the per-task ``acquire(task_id, amount)``/``release(task_id)`` API
    used by :class:`SwarmWorkerPool`.
    """

    def __init__(self, total_budget: int) -> None:
        self._total = total_budget
        self._used = 0
        self._task_allocations: dict[str, int] = {}

    def has_capacity(self, amount: int = 1000) -> bool:
        return self._used + amount < self._total

    def allocate(self, amount: int) -> bool:
        if not self.has_capacity(amount):
            return False
        self._used += amount
        return True

    def acquire(self, task_id: str, amount: int) -> bool:
        """Acquire *amount* tokens for *task_id* with per-task tracking."""
        if not self.has_capacity(amount):
            return False
        self._used += amount
        self._task_allocations[task_id] = amount
        return True

    def release(self, task_id_or_amount: str | int) -> None:
        """Release budget — accepts either a task_id (str) or raw amount (int)."""
        if isinstance(task_id_or_amount, str):
            amount = self._task_allocations.pop(task_id_or_amount, 0)
            self._used = max(0, self._used - amount)
        else:
            self._used = max(0, self._used - task_id_or_amount)

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
