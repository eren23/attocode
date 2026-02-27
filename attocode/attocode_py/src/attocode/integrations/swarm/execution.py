"""Swarm execution — wave dispatch, task completion handling.

Contains the core wave loop that dispatches tasks to workers,
processes completions, handles quality gates and failure recovery.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from attocode.integrations.swarm.helpers import (
    has_future_intent_language,
    is_hollow_completion,
)
from attocode.integrations.swarm.types import (
    BUILTIN_TASK_TYPE_CONFIGS,
    SpawnResult,
    SwarmError,
    SwarmEvent,
    SwarmPhase,
    SwarmStatus,
    SwarmTask,
    SwarmTaskResult,
    SwarmTaskStatus,
    TaskFailureMode,
    swarm_event,
)

if TYPE_CHECKING:
    from attocode.integrations.swarm.orchestrator import OrchestratorInternals
    from attocode.integrations.swarm.recovery import SwarmRecoveryState

logger = logging.getLogger(__name__)


# =============================================================================
# Wave Execution
# =============================================================================


async def execute_waves(
    ctx: OrchestratorInternals,
    recovery_state: SwarmRecoveryState,
    get_status: Any,
) -> None:
    """Main wave loop. Iterates through all waves dispatching and processing tasks."""
    from attocode.integrations.swarm.lifecycle import (
        emit_budget_update,
        save_checkpoint,
    )
    from attocode.integrations.swarm.recovery import (
        assess_and_adapt,
        is_circuit_breaker_active,
        rescue_cascade_skipped,
    )

    wave_index = ctx.task_queue.get_current_wave()
    total_waves = ctx.task_queue.get_total_waves()

    while wave_index < total_waves and not ctx.cancelled:
        # Reconcile stale dispatched tasks
        stale_ms = ctx.config.dispatch_lease_stale_ms
        active_ids = ctx.worker_pool.get_active_task_ids() if ctx.worker_pool else set()
        ctx.task_queue.reconcile_stale_dispatched(
            stale_after_ms=stale_ms,
            active_task_ids=active_ids,
        )

        # Get ready tasks for this wave
        ready_tasks = ctx.task_queue.get_ready_tasks()
        if not ready_tasks and ctx.worker_pool.active_count == 0:
            # Empty wave — skip
            if not ctx.task_queue.is_current_wave_complete():
                break
            ctx.task_queue.advance_wave()
            wave_index = ctx.task_queue.get_current_wave()
            total_waves = ctx.task_queue.get_total_waves()
            continue

        # Emit wave start
        ctx.emit(swarm_event(
            "swarm.wave.start",
            wave=wave_index + 1,
            total_waves=total_waves,
            task_count=len(ready_tasks),
        ))

        # Track pre-wave stats
        pre_stats = ctx.task_queue.get_stats()
        pre_completed = pre_stats.completed
        pre_failed = pre_stats.failed
        pre_skipped = pre_stats.skipped

        # Execute the wave
        await execute_wave(ctx, recovery_state, ready_tasks, get_status)

        # Compute wave deltas
        post_stats = ctx.task_queue.get_stats()
        wave_completed = post_stats.completed - pre_completed
        wave_failed = post_stats.failed - pre_failed
        wave_skipped = post_stats.skipped - pre_skipped

        ctx.emit(swarm_event(
            "swarm.wave.complete",
            wave=wave_index + 1,
            total_waves=total_waves,
            completed=wave_completed,
            failed=wave_failed,
            skipped=wave_skipped,
        ))

        # Wave review: run critic if configured
        if ctx.config.enable_wave_review:
            await _run_wave_review(ctx, wave_index)

        # ALL-FAILED recovery: re-queue retryable tasks
        if wave_completed == 0 and wave_failed > 0:
            ctx.emit(swarm_event("swarm.wave.allFailed", wave=wave_index + 1))
            # Re-queue tasks with remaining attempts
            requeued = []
            for task in ctx.task_queue.get_all_tasks():
                if (
                    task.wave == wave_index
                    and task.status == SwarmTaskStatus.FAILED
                    and task.attempts < ctx.config.worker_retries + 1
                ):
                    task.status = SwarmTaskStatus.READY
                    requeued.append(task)

            if requeued:
                await execute_wave(ctx, recovery_state, requeued, get_status)

        # Log wave success rate
        total_wave_tasks = wave_completed + wave_failed + wave_skipped
        if total_wave_tasks >= 2 and wave_completed / max(1, total_wave_tasks) < 0.5:
            logger.warning(
                "Wave %d success rate below 50%%: %d/%d",
                wave_index + 1, wave_completed, total_wave_tasks,
            )

        # Rescue cascade-skipped tasks
        rescued = rescue_cascade_skipped(ctx)
        if rescued:
            await execute_wave(ctx, recovery_state, rescued, get_status)

        # Budget reallocation
        if ctx.budget_pool:
            ctx.budget_pool.reallocate_unused()

        # Mid-swarm assessment
        await assess_and_adapt(ctx, recovery_state, wave_index)

        # Checkpoint
        save_checkpoint(ctx, f"wave-{wave_index + 1}")

        # Advance to next wave
        if not ctx.task_queue.advance_wave():
            break
        wave_index = ctx.task_queue.get_current_wave()
        total_waves = ctx.task_queue.get_total_waves()


# =============================================================================
# Single Wave Execution
# =============================================================================


async def execute_wave(
    ctx: OrchestratorInternals,
    recovery_state: SwarmRecoveryState,
    tasks: list[SwarmTask],
    get_status: Any,
) -> None:
    """Execute a single wave of tasks with concurrency control.

    Phase 1: Initial dispatch (fill slots with stagger)
    Phase 2: Completion processing + slot refilling
    Phase 3: Re-dispatch pass for remaining ready tasks
    """
    from attocode.integrations.swarm.recovery import (
        get_stagger_ms,
        is_circuit_breaker_active,
    )

    task_index = 0

    # Phase 1: Initial dispatch
    while (
        task_index < len(tasks)
        and ctx.worker_pool.available_slots > 0
        and not ctx.cancelled
    ):
        if is_circuit_breaker_active(recovery_state, ctx):
            wait_ms = recovery_state.circuit_breaker_until - time.time()
            if wait_ms > 0:
                await asyncio.sleep(wait_ms)

        task = tasks[task_index]
        if task.status == SwarmTaskStatus.READY:
            await dispatch_task(ctx, recovery_state, task, get_status)

        task_index += 1

        # Stagger between dispatches
        stagger = get_stagger_ms(recovery_state) / 1000.0
        if stagger > 0 and task_index < len(tasks):
            await asyncio.sleep(stagger)

    # Phase 2: Completion processing loop
    while ctx.worker_pool.active_count > 0 and not ctx.cancelled:
        completed = await ctx.worker_pool.wait_for_any()
        if completed is None:
            break

        task_id, spawn_result, started_at = completed
        await handle_task_completion(
            ctx, recovery_state, task_id, spawn_result, started_at, get_status,
        )

        from attocode.integrations.swarm.lifecycle import emit_budget_update
        emit_budget_update(ctx)
        ctx.emit(swarm_event("swarm.status", status=get_status()))

        # Fill freed slots with remaining tasks
        while (
            task_index < len(tasks)
            and ctx.worker_pool.available_slots > 0
            and not ctx.cancelled
        ):
            t = tasks[task_index]
            if t.status == SwarmTaskStatus.READY:
                await dispatch_task(ctx, recovery_state, t, get_status)
            task_index += 1

        # Pull cross-wave ready tasks to fill slots
        if ctx.worker_pool.available_slots > 0:
            active_ids = ctx.worker_pool.get_active_task_ids()
            more_ready = [
                t for t in ctx.task_queue.get_all_ready_tasks()
                if t.id not in active_ids
            ]
            for t in more_ready:
                if ctx.worker_pool.available_slots <= 0 or ctx.cancelled:
                    break
                await dispatch_task(ctx, recovery_state, t, get_status)

    # Phase 3: Re-dispatch pass
    if ctx.worker_pool.available_slots > 0 and not ctx.cancelled:
        active_ids = ctx.worker_pool.get_active_task_ids()
        still_ready = [
            t for t in ctx.task_queue.get_all_ready_tasks()
            if t.id not in active_ids
        ]
        for t in still_ready:
            if ctx.worker_pool.available_slots <= 0 or ctx.cancelled:
                break
            await dispatch_task(ctx, recovery_state, t, get_status)

        # Drain any remaining completions
        while ctx.worker_pool.active_count > 0 and not ctx.cancelled:
            completed = await ctx.worker_pool.wait_for_any()
            if completed is None:
                break
            task_id, spawn_result, started_at = completed
            await handle_task_completion(
                ctx, recovery_state, task_id, spawn_result, started_at, get_status,
            )


# =============================================================================
# Task Dispatch
# =============================================================================


async def dispatch_task(
    ctx: OrchestratorInternals,
    recovery_state: SwarmRecoveryState,
    task: SwarmTask,
    get_status: Any,
) -> None:
    """Dispatch a single task to a worker."""
    from attocode.integrations.swarm.recovery import (
        judge_split,
        should_auto_split,
    )

    # Pre-dispatch auto-split check
    if should_auto_split(ctx, task):
        split_result = await judge_split(ctx, task)
        if split_result.get("should_split") and split_result.get("subtasks"):
            ctx.task_queue.replace_with_subtasks(task.id, split_result["subtasks"])
            return

    # Pre-dispatch scout: if scout role is configured, gather codebase context
    # for implementation tasks on first attempt
    if task.attempts == 0 and task.type in ("code", "refactor", "test", "feature"):
        await _run_scout_for_task(ctx, task)

    # Select worker
    worker = ctx.worker_pool.select_worker(task)
    if worker is None:
        logger.warning("No worker available for task %s", task.id)
        ctx.task_queue.mark_failed(task.id, 0)
        return

    ctx.total_dispatches += 1
    ctx.task_queue.mark_dispatched(task.id, worker.model)

    try:
        await ctx.worker_pool.dispatch(task, worker)
    except Exception as exc:
        error_msg = str(exc)
        if "Budget pool exhausted" in error_msg:
            # Keep task ready for later
            task.status = SwarmTaskStatus.READY
        else:
            ctx.task_queue.mark_failed(task.id, 0)
            ctx.errors.append(
                SwarmError(
                    timestamp=time.time(),
                    phase="dispatch",
                    message=error_msg,
                    task_id=task.id,
                )
            )
        return

    ctx.emit(swarm_event(
        "swarm.task.dispatched",
        task_id=task.id,
        description=task.description,
        model=worker.model,
        worker_name=worker.name,
    ))


# =============================================================================
# Task Completion Handling
# =============================================================================


async def handle_task_completion(
    ctx: OrchestratorInternals,
    recovery_state: SwarmRecoveryState,
    task_id: str,
    spawn_result: SpawnResult,
    started_at: float,
    get_status: Any,
) -> None:
    """Handle a completed task — the most complex function in the swarm system.

    Routes to success, failure, or hollow handling paths.
    """
    from attocode.integrations.swarm.lifecycle import get_effective_retries
    from attocode.integrations.swarm.recovery import (
        decrease_stagger,
        record_rate_limit,
        try_resilience_recovery,
    )

    task = ctx.task_queue.get_task(task_id)
    if task is None:
        return

    # Guard: already terminal
    if task.status in (SwarmTaskStatus.SKIPPED, SwarmTaskStatus.FAILED):
        if not task.pending_cascade_skip:
            return

    duration_ms = int((time.time() - started_at) * 1000)

    # Build task result
    metrics = spawn_result.metrics or {}
    task_result = SwarmTaskResult(
        success=spawn_result.success,
        output=spawn_result.output,
        closure_report=spawn_result.closure_report,
        tokens_used=metrics.get("tokens", 0),
        cost_used=metrics.get("cost", 0.0),
        duration_ms=duration_ms,
        files_modified=spawn_result.files_modified,
        tool_calls=spawn_result.tool_calls,
        model=task.assigned_model or "",
    )

    # Max dispatch guard
    max_dispatches = ctx.config.max_dispatches_per_task
    if task.attempts >= max_dispatches:
        recovered = await try_resilience_recovery(
            ctx, recovery_state, task, task_id, task_result, spawn_result,
        )
        if not recovered:
            ctx.task_queue.mark_failed(task_id, 0)
            ctx.task_queue.trigger_cascade_skip(task_id)
        return

    # Accumulate stats
    ctx.total_tokens += task_result.tokens_used
    ctx.total_cost += task_result.cost_used

    # Emit attempt
    ctx.emit(swarm_event(
        "swarm.task.attempt",
        task_id=task_id,
        attempt=task.attempts,
        model=task_result.model,
        success=spawn_result.success,
        duration_ms=duration_ms,
        tool_calls=spawn_result.tool_calls,
    ))

    if spawn_result.success:
        await _handle_successful_completion(
            ctx, recovery_state, task, task_id, task_result, spawn_result, get_status,
        )
    else:
        await _handle_failed_completion(
            ctx, recovery_state, task, task_id, task_result, spawn_result, get_status,
        )


async def _handle_successful_completion(
    ctx: OrchestratorInternals,
    recovery_state: SwarmRecoveryState,
    task: SwarmTask,
    task_id: str,
    task_result: SwarmTaskResult,
    spawn_result: SpawnResult,
    get_status: Any,
) -> None:
    """Handle a task that completed successfully."""
    from attocode.integrations.swarm.recovery import (
        decrease_stagger,
        try_resilience_recovery,
    )

    # Check for hollow completion
    if is_hollow_completion(spawn_result, task.type, ctx.config):
        await _handle_hollow_completion(
            ctx, recovery_state, task, task_id, task_result, spawn_result,
        )
        return

    # Honor pending cascade skip
    if task.pending_cascade_skip:
        task.pending_cascade_skip = False
        # If result is good, override the cascade skip

    # Record health success
    if ctx.health_tracker and task.assigned_model:
        ctx.health_tracker.record_success(task.assigned_model, task_result.duration_ms)

    decrease_stagger(recovery_state)

    # Completion guards
    output = spawn_result.output or ""

    # Future intent guard
    if ctx.config.completion_guard.reject_future_intent_outputs:
        if has_future_intent_language(output):
            task_result.success = False
            task_result.quality_feedback = "Output describes future work rather than completed work"
            max_retries = ctx.config.worker_retries
            ctx.task_queue.mark_failed_without_cascade(task_id, max_retries)
            ctx.emit(swarm_event(
                "swarm.quality.rejected",
                task_id=task_id,
                score=1,
                feedback="Future intent language detected",
            ))
            return

    # Concrete artifact guard for action tasks
    if ctx.config.completion_guard.require_concrete_artifacts_for_action_tasks:
        type_config = BUILTIN_TASK_TYPE_CONFIGS.get(task.type, None)
        if type_config and type_config.requires_tool_calls and spawn_result.tool_calls == 0:
            task_result.success = False
            max_retries = ctx.config.worker_retries
            ctx.task_queue.mark_failed_without_cascade(task_id, max_retries)
            return

    # Quality gate — run pre-flight + LLM judge if enabled
    if ctx.config.quality_gates:
        from attocode.integrations.swarm.quality_gate import (
            QualityGateConfig,
            evaluate_worker_output,
        )
        from attocode.integrations.swarm.roles import get_judge_model

        # Determine judge model from roles
        roles = _get_role_map(ctx)
        judge_model = get_judge_model(roles, ctx.config.orchestrator_model)

        judge_cfg = QualityGateConfig(model=judge_model)

        # Determine quality threshold (foundation tasks get relaxed threshold)
        threshold = ctx.config.quality_threshold
        if task.is_foundation and threshold > 2:
            threshold -= 1

        gate_result = await evaluate_worker_output(
            provider=ctx.provider,
            orchestrator_model=ctx.config.orchestrator_model,
            task=task,
            result=task_result,
            judge_config=judge_cfg,
            quality_threshold=threshold,
            on_usage=lambda u: _track_judge_usage(ctx, u),
            swarm_config=ctx.config,
            emit=ctx.emit,
        )

        if not gate_result.passed:
            # Quality rejection — retry or fail
            task_result.quality_score = gate_result.score
            task_result.quality_feedback = gate_result.feedback
            ctx.quality_rejections += 1
            max_retries = ctx.config.worker_retries
            retried = ctx.task_queue.mark_failed_without_cascade(task_id, max_retries)

            # Set retry context with judge feedback
            from attocode.integrations.swarm.types import RetryContext
            task.retry_context = RetryContext(
                previous_feedback=gate_result.feedback,
                previous_score=gate_result.score,
                attempt=task.attempts,
                previous_model=task.assigned_model,
            )
            task.failure_mode = TaskFailureMode.QUALITY

            ctx.emit(swarm_event(
                "swarm.quality.rejected",
                task_id=task_id,
                score=gate_result.score,
                feedback=gate_result.feedback,
            ))

            if not retried:
                from attocode.integrations.swarm.recovery import try_resilience_recovery
                recovered = await try_resilience_recovery(
                    ctx, recovery_state, task, task_id, task_result, spawn_result,
                )
                if not recovered:
                    ctx.task_queue.trigger_cascade_skip(task_id)
            return

        # Store quality score on result
        task_result.quality_score = gate_result.score

    # Mark completed
    ctx.task_queue.mark_completed(task_id, task_result)
    ctx.hollow_streak = 0

    ctx.emit(swarm_event(
        "swarm.task.completed",
        task_id=task_id,
        success=True,
        tokens_used=task_result.tokens_used,
        cost_used=task_result.cost_used,
        duration_ms=task_result.duration_ms,
        quality_score=task_result.quality_score,
        output=(spawn_result.output or "")[:1000],
        files_modified=spawn_result.files_modified,
        tool_calls=spawn_result.tool_calls,
        session_id=spawn_result.session_id,
        num_turns=spawn_result.num_turns,
        stderr=(spawn_result.stderr or "")[:500],
    ))


async def _handle_failed_completion(
    ctx: OrchestratorInternals,
    recovery_state: SwarmRecoveryState,
    task: SwarmTask,
    task_id: str,
    task_result: SwarmTaskResult,
    spawn_result: SpawnResult,
    get_status: Any,
) -> None:
    """Handle a task that failed."""
    from attocode.integrations.swarm.recovery import (
        record_rate_limit,
        try_resilience_recovery,
    )

    # Classify failure
    failure_class = _classify_failure(spawn_result.output)
    task.failure_mode = TaskFailureMode(failure_class) if failure_class in TaskFailureMode.__members__.values() else TaskFailureMode.ERROR

    # Record health failure
    if ctx.health_tracker and task.assigned_model:
        error_type = "429" if task.failure_mode == TaskFailureMode.RATE_LIMIT else "error"
        ctx.health_tracker.record_failure(task.assigned_model, error_type)

    # Rate limit handling
    if task.failure_mode == TaskFailureMode.RATE_LIMIT:
        record_rate_limit(recovery_state, ctx)

    # Consecutive timeout tracking
    if task.failure_mode == TaskFailureMode.TIMEOUT:
        count = recovery_state.task_timeout_counts.get(task_id, 0) + 1
        recovery_state.task_timeout_counts[task_id] = count
        if count >= ctx.config.consecutive_timeout_limit:
            # Try resilience recovery
            recovered = await try_resilience_recovery(
                ctx, recovery_state, task, task_id, task_result, spawn_result,
            )
            if not recovered:
                ctx.task_queue.mark_failed(task_id, 0)
            return

    # Model failover: on consecutive timeouts or rate limits, try an alternative model
    if (
        ctx.config.enable_model_failover
        and task.failure_mode in (TaskFailureMode.TIMEOUT, TaskFailureMode.RATE_LIMIT)
        and task.attempts >= 2
    ):
        from attocode.integrations.swarm.model_selector import select_alternative_model
        from attocode.integrations.swarm.types import WorkerCapability

        capability = WorkerCapability.CODE
        type_config = BUILTIN_TASK_TYPE_CONFIGS.get(
            task.type.value if hasattr(task.type, "value") else str(task.type)
        )
        if type_config:
            capability = type_config.capability

        alt_worker = select_alternative_model(
            ctx.config.workers,
            task.assigned_model or "",
            capability,
            ctx.health_tracker,
        )
        if alt_worker:
            old_model = task.assigned_model or ""
            logger.info(
                "Model failover for task %s: %s -> %s",
                task_id, old_model, alt_worker.model,
            )
            task.assigned_model = alt_worker.model
            ctx.emit(swarm_event(
                "swarm.model.failover",
                task_id=task_id,
                from_model=old_model,
                to_model=alt_worker.model,
                reason=str(task.failure_mode),
            ))

    # Set retry context
    from attocode.integrations.swarm.types import RetryContext
    task.retry_context = RetryContext(
        previous_feedback=spawn_result.output[:2000] if spawn_result.output else "",
        previous_score=0,
        attempt=task.attempts,
        previous_model=task.assigned_model,
    )

    # Compute retry limit
    base_retries = ctx.config.worker_retries
    if task.failure_mode == TaskFailureMode.RATE_LIMIT:
        retry_limit = min(ctx.config.rate_limit_retries, base_retries + 1)
    else:
        retry_limit = base_retries

    # Try retry or fail
    retried = ctx.task_queue.mark_failed_without_cascade(task_id, retry_limit)
    if retried:
        ctx.retries += 1
        # Set cooldown for rate limits
        if task.failure_mode == TaskFailureMode.RATE_LIMIT:
            ctx.task_queue.set_retry_after(task_id, ctx.config.retry_base_delay_ms)
    else:
        # Try resilience recovery before hard fail
        recovered = await try_resilience_recovery(
            ctx, recovery_state, task, task_id, task_result, spawn_result,
        )
        if not recovered:
            ctx.task_queue.trigger_cascade_skip(task_id)

    ctx.emit(swarm_event(
        "swarm.task.failed",
        task_id=task_id,
        error=spawn_result.output[:500] if spawn_result.output else "Unknown error",
        attempt=task.attempts,
        max_attempts=retry_limit + 1,
        will_retry=retried,
        failure_mode=str(task.failure_mode),
        output=(spawn_result.output or "")[:1000],
        files_modified=spawn_result.files_modified,
        tool_calls=spawn_result.tool_calls,
        session_id=spawn_result.session_id,
        num_turns=spawn_result.num_turns,
        stderr=(spawn_result.stderr or "")[:500],
    ))


async def _handle_hollow_completion(
    ctx: OrchestratorInternals,
    recovery_state: SwarmRecoveryState,
    task: SwarmTask,
    task_id: str,
    task_result: SwarmTaskResult,
    spawn_result: SpawnResult,
) -> None:
    """Handle a hollow (empty/boilerplate) completion."""
    from attocode.integrations.swarm.lifecycle import skip_remaining_tasks
    from attocode.integrations.swarm.recovery import try_resilience_recovery

    # Honor pending cascade skip
    if task.pending_cascade_skip:
        task.pending_cascade_skip = False
        ctx.task_queue.mark_failed(task_id, 0)
        return

    task.failure_mode = TaskFailureMode.HOLLOW

    # Record hollow on health tracker
    if ctx.health_tracker and task.assigned_model:
        ctx.health_tracker.record_hollow(task.assigned_model)

    # Set retry context
    from attocode.integrations.swarm.types import RetryContext
    task.retry_context = RetryContext(
        previous_feedback="Previous attempt produced no meaningful output",
        previous_score=0,
        attempt=task.attempts,
        previous_model=task.assigned_model,
    )

    # Try retry
    retry_limit = ctx.config.worker_retries
    retried = ctx.task_queue.mark_failed_without_cascade(task_id, retry_limit)

    if not retried:
        recovered = await try_resilience_recovery(
            ctx, recovery_state, task, task_id, task_result, spawn_result,
        )
        if not recovered:
            ctx.task_queue.trigger_cascade_skip(task_id)

    # Increment hollow counters
    ctx.hollow_streak += 1
    ctx.total_hollows += 1

    # Emit hollow detected event
    ctx.emit(swarm_event(
        "swarm.hollow_detected",
        task_id=task_id,
        hollow_streak=ctx.hollow_streak,
        total_hollows=ctx.total_hollows,
        model=task.assigned_model,
    ))

    # Hollow streak termination
    if ctx.config.enable_hollow_termination:
        # Single model + 3+ hollow streak + unhealthy
        if (
            ctx.hollow_streak >= 3
            and task.assigned_model
            and ctx.health_tracker
            and not ctx.health_tracker.is_healthy(task.assigned_model)
        ):
            # Check if only one model
            models = {w.model for w in ctx.config.workers}
            if len(models) <= 1:
                skip_remaining_tasks(ctx, "Hollow streak termination")
                return

        # Hollow ratio termination
        if (
            ctx.total_dispatches >= ctx.config.hollow_termination_min_dispatches
            and ctx.total_hollows / max(1, ctx.total_dispatches) > ctx.config.hollow_termination_ratio
        ):
            skip_remaining_tasks(ctx, "Hollow ratio exceeded")


# =============================================================================
# Helpers
# =============================================================================


def _classify_failure(output: str) -> str:
    """Classify a failure from the output text."""
    lower = output.lower() if output else ""

    if "429" in lower or "rate limit" in lower or "too many requests" in lower:
        return "rate-limit"
    if "402" in lower or "payment required" in lower or "insufficient" in lower:
        return "rate-limit"
    if "timeout" in lower or "timed out" in lower:
        return "timeout"

    return "error"


def _get_role_map(ctx: OrchestratorInternals) -> dict[str, Any]:
    """Build role map from config, caching on ctx."""
    if not hasattr(ctx, "_role_map_cache"):
        from attocode.integrations.swarm.roles import build_role_map
        ctx._role_map_cache = build_role_map(ctx.config.roles or None)  # type: ignore[attr-defined]
    return ctx._role_map_cache  # type: ignore[attr-defined]


def _track_judge_usage(ctx: OrchestratorInternals, usage: dict[str, Any]) -> None:
    """Track judge LLM usage on orchestrator stats."""
    tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
    ctx.orchestrator_tokens += tokens
    ctx.orchestrator_calls += 1


async def _run_wave_review(ctx: OrchestratorInternals, wave_index: int) -> None:
    """Run critic wave review if the critic role is configured."""
    from attocode.integrations.swarm.roles import get_critic_config

    roles = _get_role_map(ctx)
    critic_config = get_critic_config(roles)

    if critic_config is None:
        # No critic configured — emit a basic summary event
        stats = ctx.task_queue.get_stats()
        ctx.emit(swarm_event(
            "swarm.wave.review",
            wave=wave_index + 1,
            assessment="good",
            task_assessments=[],
            fixup_count=0,
        ))
        return

    # Gather wave tasks
    wave_tasks = [
        t for t in ctx.task_queue.get_all_tasks()
        if t.wave == wave_index
    ]

    if not wave_tasks:
        return

    from attocode.integrations.swarm.critic import build_fixup_tasks, review_wave

    review_result = await review_wave(ctx, critic_config, wave_index, wave_tasks)

    # Store the review
    ctx.wave_reviews.append({
        "wave": wave_index + 1,
        "assessment": review_result.assessment,
        "task_assessments": review_result.task_assessments,
        "fixup_count": len(review_result.fixup_instructions),
    })

    # Build fixup tasks and enqueue them
    if review_result.assessment != "good":
        fixups = build_fixup_tasks(review_result, wave_index)
        if fixups:
            ctx.task_queue.add_fixup_tasks(fixups)
            logger.info(
                "Critic created %d fixup tasks for wave %d",
                len(fixups), wave_index + 1,
            )


# =============================================================================
# Scout Pre-Execution
# =============================================================================


async def _run_scout_for_task(
    ctx: OrchestratorInternals,
    task: SwarmTask,
) -> None:
    """Run a read-only scout agent before dispatching an implementation task.

    If the scout role is configured, spawns a lightweight agent to explore
    relevant files and gathers findings that are injected into the task's
    ``dependency_context`` to give the builder better situational awareness.

    No-ops if scout is not configured or if the spawn fails.
    """
    from attocode.integrations.swarm.roles import get_scout_config

    roles = _get_role_map(ctx)
    scout_config = get_scout_config(roles)
    if scout_config is None:
        return

    # Build a focused scout prompt from the task
    target_files = ", ".join(task.target_files[:5]) if task.target_files else "N/A"
    read_files = ", ".join(task.read_files[:5]) if task.read_files else "N/A"
    scout_prompt = (
        f"Explore the codebase to gather context for this task:\n\n"
        f"Task: {task.description}\n"
        f"Target files: {target_files}\n"
        f"Reference files: {read_files}\n\n"
        f"Read the target and reference files. Report:\n"
        f"1. Key functions/classes in those files\n"
        f"2. Import dependencies\n"
        f"3. Any patterns or conventions to follow\n"
        f"4. Potential gotchas or edge cases\n\n"
        f"Be concise. Output only findings, no code changes."
    )

    # Use scout's model (falls back to orchestrator model)
    scout_model = scout_config.model or ctx.config.orchestrator_model

    try:
        scout_result = await asyncio.wait_for(
            ctx.spawn_agent_fn(
                task=SwarmTask(
                    id=f"scout-{task.id}",
                    description=scout_prompt,
                    type="research",
                    target_files=task.target_files,
                    read_files=task.read_files,
                ),
                worker=None,
                system_prompt=scout_config.persona or "You are a read-only codebase explorer.",
                max_tokens=20_000,
                timeout_ms=30_000,
            ),
            timeout=35.0,
        )

        if scout_result.success and scout_result.output:
            # Inject scout findings into the task's dependency context
            existing = task.dependency_context or ""
            scout_section = f"\n\n## Scout Findings\n\n{scout_result.output[:3000]}"
            task.dependency_context = existing + scout_section

            ctx.emit(swarm_event(
                "swarm.scout.complete",
                task_id=task.id,
                findings_length=len(scout_result.output),
            ))
            logger.info("Scout gathered %d chars of context for task %s",
                        len(scout_result.output), task.id)

    except (asyncio.TimeoutError, Exception) as exc:
        # Scout is best-effort — don't block dispatch on failure
        logger.debug("Scout for task %s failed: %s", task.id, exc)
