"""Failure handling logic extracted from HybridCoordinator."""

from __future__ import annotations

import asyncio
import random
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from attoswarm.coordinator.loop import HybridCoordinator
    from attoswarm.protocol.models import TaskSpec


async def handle_task_failed(
    coordinator: HybridCoordinator,
    agent_id: str,
    task_id: str,
    reason: str,
) -> None:
    """Handle a task failure: retry or mark as permanently failed."""
    from attoswarm.coordinator.output_harvester import capture_partial_output

    coordinator.running_task_by_agent.pop(agent_id, None)
    coordinator.running_task_last_progress.pop(task_id, None)
    coordinator.running_task_started_at.pop(task_id, None)
    coordinator.diminishing_tracker.clear_task(task_id)

    # Capture partial progress from agent outbox before it's lost
    partial_output = capture_partial_output(coordinator, agent_id)

    coordinator._append_event(
        "agent.task.exit",
        {"agent_id": agent_id, "task_id": task_id, "result": "task_failed"},
    )
    coordinator._append_event(
        "agent.task.classified",
        {
            "agent_id": agent_id,
            "task_id": task_id,
            "classification": "failure",
            "reason": reason,
            "partial_output": partial_output[:500] if partial_output else "",
        },
    )
    # Feed failure to health monitor for the model behind this agent
    role = coordinator.role_by_agent.get(agent_id)
    if role:
        outcome = "timeout" if "timeout" in reason.lower() else "failure"
        coordinator.health_monitor.record_outcome(role.model, outcome)

    task = coordinator._find_task(task_id)
    if task is None:
        return
    if coordinator.task_attempts.get(task_id, 0) < coordinator.config.retries.max_task_attempts:
        # For duration-exceeded failures, increase timeout on retry
        if "duration_exceeded" in reason and task.timeout_override is None:
            task.timeout_override = int(
                coordinator.config.watchdog.task_max_duration_seconds * 1.5
            )
            coordinator._task_timeout_overrides[task_id] = task.timeout_override

        # Exponential backoff with jitter before retrying
        attempt = coordinator.task_attempts.get(task_id, 0)
        base_delay = min(2.0 ** attempt, 60.0)  # 1s, 2s, 4s, 8s... capped at 60s
        jitter = random.uniform(0, base_delay * 0.3)
        delay = base_delay + jitter

        coordinator._append_event("retry_scheduled", {
            "task_id": task_id,
            "attempt": attempt + 1,
            "delay_s": round(delay, 2),
            "reason": reason,
        })

        # Schedule delayed retry as a background task so we don't block the
        # coordinator loop.  The task stays in its current state until the
        # delay elapses, then transitions to "ready".
        async def _delayed_retry(
            _coordinator: HybridCoordinator,
            _task_id: str,
            _task: TaskSpec,
            _reason: str,
            _delay: float,
        ) -> None:
            await asyncio.sleep(_delay)
            _coordinator._transition_task(_task_id, "ready", "coordinator", _reason)
            _coordinator._persist_task(_task, status="ready", last_error=_reason)

        asyncio.create_task(
            _delayed_retry(coordinator, task_id, task, reason, delay),
            name=f"retry-backoff-{task_id}",
        )
    else:
        coordinator._transition_task(task_id, "failed", "coordinator", reason)
        coordinator._persist_task(task, status="failed", last_error=reason)
        # Only cascade-skip tasks whose ALL deps are failed/skipped
        cascade_skip_blocked(coordinator)


async def mark_running_task_failed(
    coordinator: HybridCoordinator, agent_id: str, reason: str
) -> None:
    """Fail the task currently assigned to *agent_id*, if any."""
    task_id = coordinator.running_task_by_agent.get(agent_id)
    if task_id:
        await handle_task_failed(coordinator, agent_id, task_id, reason)


def cascade_skip_blocked(coordinator: HybridCoordinator) -> list[str]:
    """Skip tasks whose ALL dependencies are failed/skipped (no viable path).

    Unlike immediate cascade, this only skips when there is truly no
    possibility of the task running (all deps terminal and none succeeded).
    """
    if coordinator.manifest is None:
        return []
    skipped: list[str] = []
    changed = True
    while changed:
        changed = False
        for task in coordinator.manifest.tasks:
            status = coordinator.task_state.get(task.task_id, task.status)
            if status not in ("pending", "ready"):
                continue
            if not task.deps:
                continue
            # Check if ANY dependency can still succeed
            has_viable = any(
                coordinator.task_state.get(d, "pending")
                in ("pending", "ready", "running", "reviewing")
                for d in task.deps
            )
            if not has_viable:
                # All deps are terminal -- check if enough succeeded for partial execution
                done_count = sum(
                    1 for d in task.deps if coordinator.task_state.get(d) == "done"
                )
                if task.deps and done_count / len(task.deps) >= 0.5:
                    continue  # 50%+ deps succeeded -- let it run with partial context
                coordinator._transition_task(
                    task.task_id, "skipped", "coordinator", "all_deps_failed"
                )
                coordinator._persist_task(task, status="skipped", last_error="all_deps_failed")
                skipped.append(task.task_id)
                changed = True
    if skipped:
        coordinator._append_event(
            "task.cascade_skip",
            {
                "skipped": skipped,
                "reason": "all_deps_failed",
            },
        )
    return skipped


async def enforce_task_silence_timeouts(coordinator: HybridCoordinator) -> None:
    """Fail tasks that have been silent (no output) beyond the configured threshold."""
    timeout = max(5.0, float(coordinator.config.watchdog.task_silence_timeout_seconds))
    now = time.monotonic()
    for agent_id, task_id in list(coordinator.running_task_by_agent.items()):
        last = coordinator.running_task_last_progress.get(task_id, now)
        elapsed = now - last
        if coordinator.config.run.debug:
            coordinator._append_event(
                "debug.watchdog.silence_check",
                {
                    "agent_id": agent_id,
                    "task_id": task_id,
                    "elapsed_seconds": round(elapsed, 1),
                    "threshold_seconds": timeout,
                },
            )
        if elapsed <= timeout:
            continue
        await coordinator._handle_task_failed(
            agent_id, task_id, reason=f"silent_timeout>{timeout}s"
        )
        coordinator._append_event(
            "agent.task.classified",
            {
                "agent_id": agent_id,
                "task_id": task_id,
                "classification": "silent_timeout",
                "timeout_seconds": timeout,
            },
        )


async def enforce_task_duration_limits(coordinator: HybridCoordinator) -> None:
    """Fail tasks that have exceeded their maximum allowed duration."""
    default_max = max(300.0, float(coordinator.config.watchdog.task_max_duration_seconds))
    now = time.monotonic()
    for agent_id, task_id in list(coordinator.running_task_by_agent.items()):
        started = coordinator.running_task_started_at.get(task_id)
        if started is None:
            continue
        # Respect per-task timeout_override (set on retry for timed-out tasks)
        override = coordinator._task_timeout_overrides.get(task_id)
        max_duration = float(override) if override is not None else default_max
        elapsed = now - started
        if coordinator.config.run.debug:
            coordinator._append_event(
                "debug.watchdog.duration_check",
                {
                    "agent_id": agent_id,
                    "task_id": task_id,
                    "elapsed_seconds": round(elapsed, 1),
                    "threshold_seconds": max_duration,
                },
            )
        if elapsed > max_duration:
            await coordinator._handle_task_failed(
                agent_id,
                task_id,
                reason=f"task_duration_exceeded>{max_duration}s",
            )
            coordinator._append_event(
                "agent.task.classified",
                {
                    "agent_id": agent_id,
                    "task_id": task_id,
                    "classification": "duration_exceeded",
                    "duration_seconds": now - started,
                    "max_duration_seconds": max_duration,
                },
            )
