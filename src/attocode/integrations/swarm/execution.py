"""Swarm execution — wave dispatch, task completion handling.

Contains the core wave loop that dispatches tasks to workers,
processes completions, handles quality gates and failure recovery.
"""

from __future__ import annotations

import asyncio
import logging
import os
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
        save_checkpoint,
    )
    from attocode.integrations.swarm.recovery import (
        assess_and_adapt,
        rescue_cascade_skipped,
    )

    wave_index = ctx.task_queue.get_current_wave()
    total_waves = ctx.task_queue.get_total_waves()

    while wave_index < total_waves and not ctx.cancelled:
        # Reconcile stale dispatched tasks
        stale_ms = ctx.config.dispatch_lease_stale_ms
        active_ids = ctx.worker_pool.get_active_task_ids() if ctx.worker_pool else set()
        stale_recovered = ctx.task_queue.reconcile_stale_dispatched(
            stale_after_ms=stale_ms,
            active_task_ids=active_ids,
        )
        for stale_id, stale_elapsed in stale_recovered:
            ctx.emit(swarm_event(
                "swarm.task.stale_recovered",
                task_id=stale_id,
                elapsed_s=stale_elapsed,
            ))

        # Release stale budget allocations from crashed children
        if ctx.budget_pool and hasattr(ctx.budget_pool, "release_stale"):
            timeout = ctx.config.worker_timeout / 1000.0
            freed = ctx.budget_pool.release_stale(timeout * 2)
            if freed:
                logger.info("Released %d stale budget allocations: %s", len(freed), freed)

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

        # Process escalations from message bus
        if ctx.message_bus is not None:
            try:
                escalations = ctx.message_bus.get_escalations()
                for esc in escalations:
                    ctx.emit(swarm_event(
                        "swarm.escalation",
                        sender=esc.sender,
                        issue=esc.payload.get("issue", ""),
                        severity=esc.payload.get("severity", "medium"),
                    ))
            except Exception:
                logger.warning("Failed to process message bus escalations", exc_info=True)

        # Wave review: run critic if configured
        if ctx.config.enable_wave_review:
            await _run_wave_review(ctx, wave_index)

        # MAJORITY-FAILED recovery: re-queue retryable tasks when success rate < 50%
        total_wave_attempted = wave_completed + wave_failed
        wave_success_rate = wave_completed / max(1, total_wave_attempted)
        if wave_success_rate < 0.5 and wave_failed > 0:
            if wave_completed == 0:
                ctx.emit(swarm_event("swarm.wave.allFailed", wave=wave_index + 1))
            # Re-queue tasks with remaining attempts
            requeued = []
            all_tasks = ctx.task_queue.get_all_tasks()
            for task in (all_tasks.values() if isinstance(all_tasks, dict) else all_tasks):
                if (
                    task.wave == wave_index
                    and task.status == SwarmTaskStatus.FAILED
                    and task.attempts <= ctx.config.worker_retries + 1
                ):
                    task.status = SwarmTaskStatus.READY
                    task.attempts = max(0, task.attempts - 1)  # Grant one bonus retry
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
            # Wave not complete — check stuck timeout
            wave_stuck_timeout_s = ctx.config.wave_stuck_timeout_ms / 1000.0
            wave_start = time.time()
            advanced = False
            while not ctx.cancelled:
                # If all non-terminal tasks are DISPATCHED, they'll finish async — ok to advance
                all_non_terminal_dispatched = all(
                    t.status == SwarmTaskStatus.DISPATCHED
                    for tid in ctx.task_queue.waves[ctx.task_queue.current_wave]
                    for t in [ctx.task_queue.get_task(tid)]
                    if t is not None and t.status not in (
                        SwarmTaskStatus.COMPLETED, SwarmTaskStatus.FAILED,
                        SwarmTaskStatus.SKIPPED, SwarmTaskStatus.DECOMPOSED,
                    )
                )
                if all_non_terminal_dispatched:
                    ctx.task_queue.current_wave += 1
                    advanced = True
                    break
                # Stuck timeout: if ready tasks exist in later waves, advance
                elapsed = time.time() - wave_start
                if elapsed > wave_stuck_timeout_s:
                    later_ready = any(
                        t.status == SwarmTaskStatus.READY
                        for t in ctx.task_queue.get_all_tasks().values()
                        if t.wave > ctx.task_queue.current_wave
                    )
                    if later_ready:
                        logger.warning(
                            "Wave %d stuck for %.0fs, advancing to unblock ready tasks",
                            wave_index + 1, elapsed,
                        )
                        ctx.task_queue.current_wave += 1
                        advanced = True
                    break
                break  # Don't loop — just check once per wave cycle
            if not advanced:
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
        # Pause check: wait until unpaused
        if getattr(ctx, "paused", False):
            await ctx.pause_event.wait()

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

        # Pause check before slot re-fill
        if getattr(ctx, "paused", False):
            await ctx.pause_event.wait()

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
    if task.attempts == 0 and task.type in ("implement", "refactor", "test", "integrate"):
        await _run_scout_for_task(ctx, task)

    # Select worker
    worker = ctx.worker_pool.select_worker(task)
    if worker is None:
        logger.warning("No worker available for task %s", task.id)
        ctx.task_queue.mark_failed(task.id, 0)
        return

    ctx.total_dispatches += 1
    ctx.task_queue.mark_dispatched(task.id, worker.model)

    # Message bus: lock target files before dispatch
    if ctx.message_bus is not None and task.target_files:
        try:
            for fpath in task.target_files[:20]:
                ctx.message_bus.lock_file(fpath, task.id)
        except Exception:
            logger.warning("Failed to lock files for task %s", task.id, exc_info=True)

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
    from attocode.integrations.swarm.recovery import (
        try_resilience_recovery,
    )

    task = ctx.task_queue.get_task(task_id)
    if task is None:
        return

    # Guard: already terminal
    if task.status in (SwarmTaskStatus.SKIPPED, SwarmTaskStatus.FAILED) and not task.pending_cascade_skip:
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
        test_output=spawn_result.test_output,
        tool_actions_summary=[
            {
                "tool": a.tool_name,
                "args": a.arguments_summary[:100],
                "output": a.output_summary[:200],
                "exit_code": a.exit_code,
                "is_test": a.is_test_execution,
            }
            for a in (spawn_result.tool_actions or [])[:15]
        ] or None,
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
    if ctx.config.completion_guard.reject_future_intent_outputs and has_future_intent_language(output):
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

    # Mandatory compilation check — runs for ALL action tasks that modify files,
    # regardless of quality_gates setting. Catches syntax/compilation errors early.
    if _is_action_task(task) and spawn_result.files_modified:
        try:
            from attocode.integrations.swarm.compilation_check import run_compilation_checks

            working_dir = getattr(ctx, "working_dir", None) or "."
            check_result = run_compilation_checks(
                files_modified=spawn_result.files_modified,
                working_dir=working_dir,
            )

            if not check_result.passed:
                # Build structured RetryContext with compilation errors
                from attocode.integrations.swarm.types import RetryContext

                error_dicts = [
                    {"file": e.file_path, "line": e.line, "message": e.message}
                    for e in check_result.errors
                    if e.severity == "error"
                ]

                task.retry_context = RetryContext(
                    previous_feedback=_format_compilation_errors(check_result.errors),
                    previous_score=0,
                    attempt=task.attempts,
                    previous_model=task.assigned_model,
                    compilation_errors=error_dicts,
                    verification_suggestions=[
                        f"Fix {e.file_path}:{e.line}: {e.message}"
                        for e in check_result.errors
                        if e.severity == "error" and e.line is not None
                    ],
                )
                task.failure_mode = TaskFailureMode.QUALITY
                task_result.success = False
                task_result.quality_feedback = _format_compilation_errors(check_result.errors)
                max_retries = ctx.config.worker_retries
                retried = ctx.task_queue.mark_failed_without_cascade(task_id, max_retries)

                ctx.emit(swarm_event(
                    "swarm.compilation.failed",
                    task_id=task_id,
                    errors=[
                        {"file": e.file_path, "line": e.line, "message": e.message}
                        for e in check_result.errors
                        if e.severity == "error"
                    ],
                    files_checked=check_result.files_checked,
                    duration_ms=check_result.duration_ms,
                ))

                if not retried:
                    ctx.task_queue.trigger_cascade_skip(task_id)
                return
        except Exception as exc:
            logger.warning("Compilation check error for task %s: %s", task_id, exc)
            # Non-fatal: continue to quality gate if compilation check itself errors

    # For test tasks: run verification gate BEFORE the quality gate so the
    # judge can see actual test pass/fail data.
    task_type_val = task.type.value if hasattr(task.type, "value") else str(task.type)
    _is_test = task_type_val == "test"
    _verification_evidence_for_judge: dict[str, Any] | None = None

    _vg_type_config_early = BUILTIN_TASK_TYPE_CONFIGS.get(task.type, None)
    _should_verify_early = bool(
        _is_test
        and ctx.config.enable_verification
        and _vg_type_config_early and _vg_type_config_early.requires_tool_calls
    )
    if _should_verify_early:
        try:
            from attocode.integrations.tasks.task_splitter import SubTask as _SubTask
            from attocode.integrations.tasks.verification_gate import (
                VerificationGate as _VG,
            )

            _wd = getattr(ctx, "working_dir", None) or "."
            _gate = _VG(
                provider=ctx.provider if ctx.config.enable_wave_review else None,
                model=ctx.config.orchestrator_model,
                working_dir=_wd,
            )
            _sub = _SubTask(id=task.id, description=task.description)
            _verif = await _gate.verify(
                _sub,
                spawn_result.output or "",
                run_tests=True,
                run_types=True,
                run_lint=True,
                run_llm=False,
                is_test_task=True,
            )
            # Package verification results for the judge prompt
            _verification_evidence_for_judge = {
                "passed": _verif.passed,
                "checks": [
                    {"name": c.name, "passed": c.passed, "message": c.message[:200]}
                    for c in _verif.checks
                ],
            }

            if not _verif.passed:
                # Verification failed — retry immediately, skip judge
                from attocode.integrations.swarm.types import RetryContext
                _verif_suggestions = _verif.suggestions[:3]
                _test_failures: list[str] = []
                _comp_errors: list[dict[str, Any]] = []
                for c in _verif.checks:
                    if not c.passed:
                        if c.name == "tests":
                            _test_failures.append(c.message[:300])
                        else:
                            _comp_errors.append({
                                "file": "", "line": None,
                                "message": c.message[:300], "check": c.name,
                            })
                task.retry_context = RetryContext(
                    previous_feedback="; ".join(_verif_suggestions),
                    previous_score=task_result.quality_score or 0,
                    attempt=task.attempts,
                    previous_model=task.assigned_model,
                    compilation_errors=_comp_errors or None,
                    test_failures=_test_failures or None,
                    verification_suggestions=_verif_suggestions or None,
                )
                task_result.quality_feedback = "; ".join(_verif_suggestions)
                max_retries = ctx.config.worker_retries
                retried = ctx.task_queue.mark_failed_without_cascade(task_id, max_retries)
                ctx.emit(swarm_event(
                    "swarm.verification.failed",
                    task_id=task_id,
                    checks=[
                        {"name": c.name, "passed": c.passed, "message": c.message[:200]}
                        for c in _verif.checks
                    ],
                ))
                if not retried:
                    ctx.task_queue.trigger_cascade_skip(task_id)
                return
        except Exception as exc:
            logger.warning("Early verification gate error for test task %s: %s", task_id, exc)

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
            verification_evidence=_verification_evidence_for_judge if _is_test else None,
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

    # Verification gate — run automated checks (tests, types, lint)
    # Decoupled from quality_gates: runs independently for action tasks
    # that modify files, controlled by enable_verification flag.
    # Skip for test tasks — already ran verification before judge above.
    _vg_type_config = BUILTIN_TASK_TYPE_CONFIGS.get(task.type, None)
    _should_verify = bool(
        not _is_test  # test tasks already verified before quality gate
        and ctx.config.enable_verification
        and _vg_type_config and _vg_type_config.requires_tool_calls
        and spawn_result.files_modified
    )
    if _should_verify:
        try:
            from attocode.integrations.tasks.task_splitter import SubTask
            from attocode.integrations.tasks.verification_gate import (
                VerificationGate,
                check_modified_files_compile,
            )

            working_dir = getattr(ctx, "working_dir", None) or "."

            # Run targeted compilation check on modified files first
            compile_result = check_modified_files_compile(
                spawn_result.files_modified, working_dir,
            )
            if not compile_result.passed:
                # Emit compilation failure event
                ctx.emit(swarm_event(
                    "swarm.compilation.failed",
                    task_id=task_id,
                    errors=[
                        {"file": e.get("file", ""), "message": e.get("message", "")}
                        for e in (compile_result.errors or [])[:10]
                    ],
                ))
                # Build structured retry context with compilation errors
                from attocode.integrations.swarm.types import RetryContext
                task.retry_context = RetryContext(
                    previous_feedback=compile_result.message,
                    previous_score=task_result.quality_score or 0,
                    attempt=task.attempts,
                    previous_model=task.assigned_model,
                    compilation_errors=compile_result.errors[:10] if compile_result.errors else None,
                    verification_suggestions=[
                        f"Fix compilation error in {e.get('file', 'unknown')}: {e.get('message', '')}"
                        for e in (compile_result.errors or [])[:5]
                    ] or None,
                )
                task_result.quality_feedback = compile_result.message
                max_retries = ctx.config.worker_retries
                retried = ctx.task_queue.mark_failed_without_cascade(task_id, max_retries)
                if not retried:
                    ctx.task_queue.trigger_cascade_skip(task_id)
                return

            # Full verification gate: tests, types, lint
            gate = VerificationGate(
                provider=ctx.provider if ctx.config.enable_wave_review else None,
                model=ctx.config.orchestrator_model,
                working_dir=working_dir,
            )
            # Adapt SwarmTask → SubTask for the verification gate interface
            sub_task = SubTask(id=task.id, description=task.description)
            verification = await gate.verify(
                sub_task,
                spawn_result.output or "",
                run_tests=True,
                run_types=True,
                run_lint=True,
                run_llm=False,  # Quality gate LLM judge already ran above (if enabled)
            )
            if not verification.passed:
                # Build structured retry context with verification details
                _verif_suggestions = verification.suggestions[:3]
                task_result.quality_feedback = "; ".join(_verif_suggestions)

                # Populate structured error fields on retry context
                from attocode.integrations.swarm.types import RetryContext
                _comp_errors: list[dict[str, Any]] = []
                _test_failures: list[str] = []
                for c in verification.checks:
                    if not c.passed:
                        if c.name in ("tests",):
                            _test_failures.append(c.message[:300])
                        else:
                            _comp_errors.append({
                                "file": "",
                                "line": None,
                                "message": c.message[:300],
                                "check": c.name,
                            })
                task.retry_context = RetryContext(
                    previous_feedback=task_result.quality_feedback,
                    previous_score=task_result.quality_score or 0,
                    attempt=task.attempts,
                    previous_model=task.assigned_model,
                    compilation_errors=_comp_errors or None,
                    test_failures=_test_failures or None,
                    verification_suggestions=_verif_suggestions or None,
                )

                max_retries = ctx.config.worker_retries
                retried = ctx.task_queue.mark_failed_without_cascade(task_id, max_retries)
                ctx.emit(swarm_event(
                    "swarm.verification.failed",
                    task_id=task_id,
                    checks=[
                        {"name": c.name, "passed": c.passed, "message": c.message[:200]}
                        for c in verification.checks
                    ],
                ))
                if not retried:
                    ctx.task_queue.trigger_cascade_skip(task_id)
                return
        except Exception as exc:
            logger.warning("Verification gate error for task %s: %s", task_id, exc)
            task_result.quality_feedback = "Verification skipped due to error"
            ctx.emit(swarm_event(
                "swarm.verification.skipped",
                task_id=task_id,
                reason=str(exc)[:200],
            ))

    # File conflict detection via blackboard
    blackboard = getattr(ctx, "blackboard", None)
    if blackboard is not None and spawn_result.files_modified:
        try:
            conflicts = blackboard.register_file_modifications(
                task_id, spawn_result.files_modified,
            )
            if conflicts:
                ctx.emit(swarm_event(
                    "swarm.file_conflict",
                    task_id=task_id,
                    conflicting_files=conflicts,
                    worker_id=task_id,
                ))
                logger.warning(
                    "File conflict detected: task %s modified files also "
                    "modified by other workers: %s",
                    task_id, conflicts,
                )
        except Exception:
            logger.warning(
                "Blackboard conflict detection failed for task %s", task_id, exc_info=True,
            )

    # Mark completed
    ctx.task_queue.mark_completed(task_id, task_result)
    ctx.hollow_streak = 0

    # Message bus: broadcast worker_done and release file locks
    if ctx.message_bus is not None:
        try:
            ctx.message_bus.broadcast_done(
                task_id,
                summary=(spawn_result.output or "")[:1000],
                files_modified=spawn_result.files_modified,
            )
            ctx.message_bus.release_all_locks(task_id)
        except Exception:
            logger.warning(
                "Message bus broadcast_done/release failed for task %s", task_id, exc_info=True,
            )

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
        tool_actions_summary=task_result.tool_actions_summary,
        test_output=(task_result.test_output or "")[:500] if task_result.test_output else None,
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

    # Classify failure using comprehensive classifier
    failure_class = _classify_failure(spawn_result.output, spawn_result.tool_calls)
    task.failure_mode = TaskFailureMode(failure_class) if failure_class in TaskFailureMode.__members__.values() else TaskFailureMode.ERROR

    # Skip retries for terminal failures (auth, spend limit, etc.)
    try:
        from attocode.integrations.swarm.failure_classifier import classify_swarm_failure
        full_classification = classify_swarm_failure(spawn_result.output, spawn_result.tool_calls)
        if not full_classification.retryable:
            ctx.task_queue.mark_failed(task_id, 0)  # Zero retries for terminal failures
            ctx.task_queue.trigger_cascade_skip(task_id)
            logger.warning(
                "Terminal failure for task %s: %s", task_id, full_classification.reason,
            )
            # Still emit the event below, but skip retry logic
            ctx.emit(swarm_event(
                "swarm.task.failed",
                task_id=task_id,
                error=spawn_result.output[:500] if spawn_result.output else "Unknown error",
                attempt=task.attempts,
                max_attempts=1,
                will_retry=False,
                failure_mode=str(task.failure_mode),
                output=(spawn_result.output or "")[:1000],
                files_modified=spawn_result.files_modified,
                tool_calls=spawn_result.tool_calls,
                tool_actions_summary=task_result.tool_actions_summary,
                test_output=(task_result.test_output or "")[:500] if task_result.test_output else None,
                session_id=spawn_result.session_id,
                num_turns=spawn_result.num_turns,
                stderr=(spawn_result.stderr or "")[:500],
            ))
            # Release locks
            if ctx.message_bus is not None:
                try:
                    ctx.message_bus.release_all_locks(task_id)
                except Exception:
                    logger.warning("Message bus release failed for task %s", task_id)
            return
    except ImportError:
        pass

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

    # User intervention hook: if enabled and task has failed N times,
    # emit an intervention event instead of cascade-skipping immediately.
    if (
        ctx.config.enable_user_intervention
        and task.attempts >= ctx.config.user_intervention_threshold
    ):
        _last_error = spawn_result.output[:500] if spawn_result.output else "Unknown error"
        _comp_errors = None
        if task.retry_context and task.retry_context.compilation_errors:
            _comp_errors = task.retry_context.compilation_errors[:5]
        ctx.emit(swarm_event(
            "swarm.task.intervention_needed",
            task_id=task_id,
            description=task.description,
            attempts=task.attempts,
            last_error=_last_error,
            compilation_errors=_comp_errors,
            failure_mode=str(task.failure_mode),
            model=task.assigned_model,
        ))
        # Task stays in its current state (DISPATCHED/FAILED) — does not
        # cascade-skip yet. The TUI/dashboard should show the intervention
        # prompt. Normal retry/fail logic still runs below so the task can
        # be retried if the user provides guidance, but cascade skip is
        # deferred.

    # Try retry or fail
    retried = ctx.task_queue.mark_failed_without_cascade(task_id, retry_limit)
    if retried:
        ctx.retries += 1
        # Set cooldown for rate limits
        if task.failure_mode == TaskFailureMode.RATE_LIMIT:
            ctx.task_queue.set_retry_after(task_id, ctx.config.retry_base_delay_ms)
    else:
        # If user intervention is active, skip cascade-skip to give user a chance
        if (
            ctx.config.enable_user_intervention
            and task.attempts >= ctx.config.user_intervention_threshold
        ):
            logger.info(
                "Task %s needs user intervention (attempt %d/%d). "
                "Cascade skip deferred.",
                task_id, task.attempts, ctx.config.user_intervention_threshold,
            )
        else:
            # Try resilience recovery before hard fail
            recovered = await try_resilience_recovery(
                ctx, recovery_state, task, task_id, task_result, spawn_result,
            )
            if not recovered:
                ctx.task_queue.trigger_cascade_skip(task_id)

    # Message bus: release file locks on failure
    if ctx.message_bus is not None:
        try:
            ctx.message_bus.release_all_locks(task_id)
        except Exception:
            logger.warning(
                "Message bus release_all_locks failed for task %s", task_id, exc_info=True,
            )

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
        tool_actions_summary=task_result.tool_actions_summary,
        test_output=(task_result.test_output or "")[:500] if task_result.test_output else None,
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
        # Safety valve: don't terminate if >60% tasks already completed
        stats = ctx.task_queue.get_stats()
        completion_ratio = stats.completed / max(1, stats.total) if stats.total else 0.0
        if completion_ratio > 0.6:
            logger.info(
                "Hollow termination suppressed: %.0f%% tasks completed",
                completion_ratio * 100,
            )
        else:
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


_ACTION_TASK_TYPES: frozenset[str] = frozenset({
    "implement", "test", "refactor", "integrate", "deploy",
})


def _is_action_task(task: SwarmTask) -> bool:
    """Return True if *task* is an action task (produces code artifacts)."""
    return task.type in _ACTION_TASK_TYPES


def _format_compilation_errors(errors: list[Any]) -> str:
    """Format a list of :class:`CompilationError` objects into a human-readable string."""
    if not errors:
        return "No compilation errors."
    lines: list[str] = ["COMPILATION ERRORS:"]
    for err in errors:
        loc = f"{err.file_path}"
        if err.line is not None:
            loc += f":{err.line}"
        lines.append(f"  - `{loc}`: {err.message}")
    return "\n".join(lines)


def _classify_failure(output: str, tool_calls: int | None = None) -> str:
    """Classify a failure from the output text.

    Returns a ``TaskFailureMode``-compatible string (``"rate-limit"``,
    ``"timeout"``, ``"error"``, ``"terminal"`` etc.).

    Delegates to the comprehensive ``classify_swarm_failure`` classifier
    when available, mapping its structured result back to the simple
    string expected by the rest of the execution layer.
    """
    try:
        from attocode.integrations.swarm.failure_classifier import (
            SwarmFailureClass,
            classify_swarm_failure,
        )
        classification = classify_swarm_failure(output, tool_calls)
        # Map failure classes back to TaskFailureMode-compatible strings
        _CLASS_TO_MODE: dict[SwarmFailureClass, str] = {
            SwarmFailureClass.RATE_LIMITED: "rate-limit",
            SwarmFailureClass.TIMEOUT: "timeout",
            SwarmFailureClass.PROVIDER_SPEND_LIMIT: "terminal",
            SwarmFailureClass.PROVIDER_AUTH: "terminal",
            SwarmFailureClass.POLICY_BLOCKED: "terminal",
            SwarmFailureClass.INVALID_TOOL_ARGS: "terminal",
            SwarmFailureClass.MISSING_TARGET_PATH: "terminal",
            SwarmFailureClass.PERMISSION_REQUIRED: "terminal",
            SwarmFailureClass.PROVIDER_TRANSIENT: "recoverable",
        }
        return _CLASS_TO_MODE.get(classification.failure_class, "error")
    except Exception:
        pass

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
    if ctx._role_map_cache is None:
        from attocode.integrations.swarm.roles import build_role_map
        ctx._role_map_cache = build_role_map(ctx.config.roles or None)
    return ctx._role_map_cache


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
        _stats = ctx.task_queue.get_stats()
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
        t for t in ctx.task_queue.get_all_tasks().values()
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
    # Fast mechanical scout: recursively gather context from target + ref files
    # If sufficient context is gathered, skip the expensive LLM scout entirely
    try:
        from attocode.tricks.recursive_context import RecursiveContextRetriever

        class _FileContentProvider:
            def __init__(self, root: str) -> None:
                self._root = os.path.realpath(root) if root else ""

            def get_content(self, path: str) -> str | None:
                try:
                    if self._root:
                        candidate = os.path.normpath(os.path.join(self._root, path))
                        if not candidate.startswith(self._root):
                            return None  # Path traversal rejected
                        path = candidate
                    with open(path, encoding="utf-8", errors="replace") as f:
                        return f.read()
                except (OSError, UnicodeDecodeError):
                    return None

        working_dir = getattr(ctx, "working_dir", None) or "."
        retriever = RecursiveContextRetriever(
            _FileContentProvider(working_dir),
            max_depth=2,
            token_budget=15_000,
            max_files=10,
        )
        seed_files = list((task.target_files or [])[:5]) + list((task.read_files or [])[:5])
        if seed_files:
            result = retriever.retrieve(seed_files)
            if result.nodes and result.total_tokens > 500:
                existing = task.dependency_context or ""
                scout_section = "\n\n## File Context (auto-gathered)\n\n" + result.content[:5000]
                task.dependency_context = existing + scout_section
                logger.info(
                    "Mechanical scout gathered %d files (%d tokens) for task %s",
                    result.files_visited, result.total_tokens, task.id,
                )
                return  # Skip LLM scout — mechanical context is sufficient
    except Exception:
        pass  # Fall through to LLM scout

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
    _scout_model = scout_config.model or ctx.config.orchestrator_model

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

            # Track scout token usage
            scout_tokens = getattr(scout_result, "metrics", {})
            if isinstance(scout_tokens, dict):
                tokens = scout_tokens.get("tokens", 0)
            else:
                tokens = getattr(scout_tokens, "tokens", 0)
            if tokens:
                ctx.orchestrator_tokens += tokens
                if not hasattr(ctx, "scout_tokens"):
                    ctx.scout_tokens = 0
                ctx.scout_tokens += tokens

            ctx.emit(swarm_event(
                "swarm.scout.complete",
                task_id=task.id,
                findings_length=len(scout_result.output),
                tokens=tokens,
            ))
            logger.info("Scout gathered %d chars of context for task %s",
                        len(scout_result.output), task.id)

    except (TimeoutError, Exception) as exc:
        # Scout is best-effort — don't block dispatch on failure
        logger.debug("Scout for task %s failed: %s", task.id, exc)
