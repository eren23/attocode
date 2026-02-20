"""Swarm recovery -- circuit breaker, micro-decomposition, degraded acceptance, re-planning.

Provides resilience strategies for the swarm orchestrator:
- Circuit breaker: pauses dispatching when rate limits pile up
- Micro-decomposition: LLM-driven task splitting on repeated failures
- Degraded acceptance: partial-credit rescue for tasks that produced artifacts
- Mid-swarm re-planning: single-shot replanning when execution stalls
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from attocode.integrations.swarm.helpers import is_hollow_completion
from attocode.integrations.swarm.types import (
    BUILTIN_TASK_TYPE_CONFIGS,
    OrchestratorDecision,
    SpawnResult,
    SubtaskType,
    SwarmConfig,
    SwarmEvent,
    SwarmTask,
    SwarmTaskResult,
    SwarmTaskStatus,
    swarm_event,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Recovery State
# =============================================================================


@dataclass
class SwarmRecoveryState:
    """Mutable state tracked across the swarm session for recovery decisions."""

    recent_rate_limits: list[float] = field(default_factory=list)  # timestamps
    circuit_breaker_until: float = 0.0  # unix timestamp
    per_model_quality_rejections: dict[str, int] = field(default_factory=dict)
    quality_gate_disabled_models: set[str] = field(default_factory=set)
    adaptive_stagger_ms: float = 1500.0
    task_timeout_counts: dict[str, int] = field(default_factory=dict)
    hollow_ratio_warned: bool = False


# =============================================================================
# Constants
# =============================================================================

CIRCUIT_BREAKER_WINDOW_MS = 30_000
CIRCUIT_BREAKER_THRESHOLD = 3
CIRCUIT_BREAKER_PAUSE_MS = 15_000


# =============================================================================
# Circuit Breaker
# =============================================================================


def record_rate_limit(state: SwarmRecoveryState, ctx: Any) -> None:
    """Record a rate-limit event and potentially trip the circuit breaker.

    Pushes the current timestamp into the rolling window, increases the
    adaptive stagger, prunes entries outside the window, and trips the
    breaker if the threshold is reached.
    """
    now = time.time()
    state.recent_rate_limits.append(now)
    increase_stagger(state)

    # Prune entries outside the window
    window_start = now - (CIRCUIT_BREAKER_WINDOW_MS / 1000.0)
    state.recent_rate_limits = [
        ts for ts in state.recent_rate_limits if ts >= window_start
    ]

    # Trip breaker if threshold reached
    if len(state.recent_rate_limits) >= CIRCUIT_BREAKER_THRESHOLD:
        pause_until = now + (CIRCUIT_BREAKER_PAUSE_MS / 1000.0)
        state.circuit_breaker_until = pause_until
        ctx.emit(
            swarm_event(
                "swarm.circuit.open",
                pause_ms=CIRCUIT_BREAKER_PAUSE_MS,
                rate_limit_count=len(state.recent_rate_limits),
            )
        )
        logger.warning(
            "Circuit breaker OPEN: %d rate limits in %dms window, pausing for %dms",
            len(state.recent_rate_limits),
            CIRCUIT_BREAKER_WINDOW_MS,
            CIRCUIT_BREAKER_PAUSE_MS,
        )


def is_circuit_breaker_active(state: SwarmRecoveryState, ctx: Any) -> bool:
    """Check whether the circuit breaker is currently engaged.

    Returns True if we are within the pause window.  On expiry, resets state
    and emits a ``swarm.circuit.closed`` event.
    """
    if state.circuit_breaker_until <= 0.0:
        return False

    now = time.time()
    if now < state.circuit_breaker_until:
        return True

    # Breaker expired -- reset
    state.circuit_breaker_until = 0.0
    state.recent_rate_limits.clear()
    decrease_stagger(state)
    ctx.emit(swarm_event("swarm.circuit.closed"))
    logger.info("Circuit breaker CLOSED")
    return False


# =============================================================================
# Stagger Control
# =============================================================================


def get_stagger_ms(state: SwarmRecoveryState) -> float:
    """Return the current adaptive stagger between dispatches (ms)."""
    return state.adaptive_stagger_ms


def increase_stagger(state: SwarmRecoveryState) -> None:
    """Increase stagger multiplicatively, capped at 10 000 ms."""
    state.adaptive_stagger_ms = min(state.adaptive_stagger_ms * 1.5, 10_000.0)


def decrease_stagger(state: SwarmRecoveryState) -> None:
    """Decrease stagger multiplicatively, floored at 200 ms."""
    state.adaptive_stagger_ms = max(state.adaptive_stagger_ms * 0.9, 200.0)


# =============================================================================
# Primary Resilience Recovery
# =============================================================================


async def try_resilience_recovery(
    ctx: Any,
    recovery_state: SwarmRecoveryState,
    task: SwarmTask,
    task_id: str,
    task_result: SwarmTaskResult,
    spawn_result: SpawnResult,
) -> bool:
    """Attempt two recovery strategies for a failed task.

    Strategy 1 -- Micro-Decomposition:
        If the task is complex enough (>=4) and has been attempted at least
        twice, ask an LLM to split it into 2-3 simpler subtasks.

    Strategy 2 -- Degraded Acceptance:
        If the task produced artifacts or met certain heuristic criteria,
        accept it with a degraded quality score.

    Returns True if recovery succeeded (task should not be retried normally).
    """
    # Strategy 1: Micro-decomposition
    config: SwarmConfig = ctx.config
    if (
        task.complexity >= 4
        and task.attempts >= 2
        and _budget_has_capacity(ctx)
    ):
        try:
            subtasks = await _micro_decompose(ctx, task)
            if len(subtasks) >= 2:
                ctx.task_queue.replace_with_subtasks(task_id, subtasks)
                ctx.emit(
                    swarm_event(
                        "swarm.task.decomposed",
                        task_id=task_id,
                        subtask_count=len(subtasks),
                        strategy="micro-decompose",
                    )
                )
                ctx.log_decision(
                    "recovery",
                    f"micro-decomposed {task_id} into {len(subtasks)} subtasks",
                    f"complexity={task.complexity}, attempts={task.attempts}",
                )
                logger.info(
                    "Micro-decomposed task %s into %d subtasks",
                    task_id,
                    len(subtasks),
                )
                return True
        except Exception:
            logger.debug("Micro-decomposition failed for %s", task_id, exc_info=True)

    # Strategy 2: Degraded acceptance
    if _should_accept_degraded(task, spawn_result, config):
        task_result.success = True
        task_result.degraded = True
        task_result.quality_score = 2
        task.degraded = True
        task.status = SwarmTaskStatus.COMPLETED
        task.result = task_result
        ctx.emit(
            swarm_event(
                "swarm.task.completed",
                task_id=task_id,
                degraded=True,
                quality_score=2,
            )
        )
        ctx.log_decision(
            "recovery",
            f"degraded-accept {task_id}",
            "task produced partial artifacts or met heuristic criteria",
        )
        logger.info("Accepted task %s in degraded mode", task_id)
        return True

    return False


def _should_accept_degraded(
    task: SwarmTask,
    spawn_result: SpawnResult,
    config: SwarmConfig,
) -> bool:
    """Decide whether a failed task qualifies for degraded acceptance."""
    has_artifacts = bool(
        spawn_result.files_modified and len(spawn_result.files_modified) > 0
    )
    if has_artifacts:
        return True

    # Non-action task with tool calls and non-narrative output
    type_config = BUILTIN_TASK_TYPE_CONFIGS.get(task.type.value if isinstance(task.type, SubtaskType) else str(task.type))
    is_action = type_config.requires_tool_calls if type_config else True
    had_tool_calls = spawn_result.tool_calls > 0
    narrative_only = is_hollow_completion(spawn_result, task.type.value if isinstance(task.type, SubtaskType) else str(task.type), config)

    if not is_action and had_tool_calls and not narrative_only:
        return True

    return False


# =============================================================================
# Auto-Split
# =============================================================================


def should_auto_split(ctx: Any, task: SwarmTask) -> bool:
    """Heuristic: should this task be auto-split before first dispatch?

    Checks:
    - auto_split is enabled in config
    - complexity >= configured floor
    - task type is in the splittable list
    - task has not been attempted yet
    - task is a foundation task (3+ dependents)
    - budget has remaining capacity
    """
    config: SwarmConfig = ctx.config
    auto_split_cfg = config.auto_split
    if not auto_split_cfg.enabled:
        return False
    if task.complexity < auto_split_cfg.complexity_floor:
        return False

    task_type_str = task.type.value if isinstance(task.type, SubtaskType) else str(task.type)
    if task_type_str not in auto_split_cfg.splittable_types:
        return False
    if task.attempts != 0:
        return False
    if not task.is_foundation:
        return False
    if not _budget_has_capacity(ctx):
        return False

    return True


async def judge_split(ctx: Any, task: SwarmTask) -> dict[str, Any]:
    """Ask an LLM whether a task should be split and into what subtasks.

    Returns a dict with ``should_split: bool`` and ``subtasks: list[dict]``.
    """
    config: SwarmConfig = ctx.config
    model = config.orchestrator_model

    prompt = (
        "You are a task decomposition expert. Given the following task, "
        "decide whether it should be split into smaller subtasks.\n\n"
        f"Task: {task.description}\n"
        f"Type: {task.type}\n"
        f"Complexity: {task.complexity}/10\n"
        f"Target files: {task.target_files or 'none'}\n\n"
        "If it should be split, provide 2-4 subtasks. Each subtask needs: "
        "id, description, type (implement/test/refactor/research/review), "
        "complexity (1-10), and dependencies (list of sibling subtask ids).\n\n"
        "Respond in JSON: {\"should_split\": bool, \"subtasks\": [...]}"
    )

    try:
        response = await ctx.provider.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.3,
        )
        ctx.track_orchestrator_usage(response, "judge_split")
        text = _extract_text(response)
        return _parse_json_response(text, {"should_split": False, "subtasks": []})
    except Exception:
        logger.debug("judge_split LLM call failed for %s", task.id, exc_info=True)
        return {"should_split": False, "subtasks": []}


# =============================================================================
# Rescue / Cascade Recovery
# =============================================================================


def rescue_cascade_skipped(ctx: Any, *, lenient: bool = False) -> list[SwarmTask]:
    """Rescue tasks that were skipped due to dependency cascading.

    Iterates over all tasks with status SKIPPED and evaluates whether
    their dependencies have enough completed results to proceed.

    Args:
        ctx: Orchestrator context with task_queue access.
        lenient: If True, use relaxed rescue conditions (e.g. accept
            if at least one dependency succeeded).

    Returns:
        List of tasks that were rescued and moved back to READY.
    """
    rescued: list[SwarmTask] = []
    all_tasks: dict[str, SwarmTask] = ctx.task_queue.get_all_tasks()

    for task_id, task in all_tasks.items():
        if task.status != SwarmTaskStatus.SKIPPED:
            continue

        deps = task.dependencies or []
        if not deps:
            # No dependencies -- should never have been skipped, rescue it
            if ctx.task_queue.rescue_task(task_id):
                rescued.append(task)
            continue

        # Examine dependency outcomes
        dep_completed = 0
        dep_failed = 0
        dep_total = len(deps)

        for dep_id in deps:
            dep_task = all_tasks.get(dep_id)
            if dep_task is None:
                continue
            if dep_task.status == SwarmTaskStatus.COMPLETED:
                dep_completed += 1
            elif dep_task.status in (SwarmTaskStatus.FAILED, SwarmTaskStatus.SKIPPED):
                dep_failed += 1

        # Rescue conditions
        should_rescue = False
        if lenient:
            # Lenient: rescue if at least one dep completed
            should_rescue = dep_completed >= 1
        else:
            # Strict: rescue if majority completed
            should_rescue = dep_total > 0 and dep_completed / dep_total >= 0.5

        if should_rescue:
            if ctx.task_queue.rescue_task(task_id):
                task.rescue_context = (
                    f"Rescued: {dep_completed}/{dep_total} deps completed"
                )
                rescued.append(task)

    if rescued:
        logger.info(
            "Rescued %d cascade-skipped tasks (lenient=%s)",
            len(rescued),
            lenient,
        )

    return rescued


async def final_rescue_pass(
    ctx: Any,
    execute_wave_fn: Callable[..., Coroutine[Any, Any, Any]],
) -> None:
    """Final pass: rescue cascade-skipped tasks with lenient criteria and execute.

    Called near the end of swarm execution to maximize useful output.
    """
    rescued = rescue_cascade_skipped(ctx, lenient=True)
    if not rescued:
        return

    ctx.log_decision(
        "recovery",
        f"final-rescue: {len(rescued)} tasks",
        "lenient cascade rescue at end of swarm",
    )
    ctx.emit(
        swarm_event(
            "swarm.rescue.final",
            rescued_count=len(rescued),
            task_ids=[t.id for t in rescued],
        )
    )

    await execute_wave_fn(rescued)


# =============================================================================
# Adaptive Assessment
# =============================================================================


async def assess_and_adapt(
    ctx: Any,
    recovery_state: SwarmRecoveryState,
    wave_index: int,
) -> None:
    """Assess swarm progress and adapt strategy if needed.

    Called after each wave completes. Two checks:
    1. Budget sufficiency: skip low-priority leaf tasks if budget is tight.
    2. Stall detection: if progress is below threshold, trigger re-planning.
    """
    all_tasks = ctx.task_queue.get_all_tasks()
    total = len(all_tasks)
    if total == 0:
        return

    completed = sum(
        1 for t in all_tasks.values() if t.status == SwarmTaskStatus.COMPLETED
    )
    attempted = sum(
        1 for t in all_tasks.values()
        if t.status
        in (
            SwarmTaskStatus.COMPLETED,
            SwarmTaskStatus.FAILED,
            SwarmTaskStatus.SKIPPED,
        )
    )
    progress = completed / total

    # Budget sufficiency: skip remaining low-priority leaf tasks if budget < 20%
    budget_ratio = _get_budget_ratio(ctx)
    if budget_ratio < 0.2 and attempted >= 5:
        _skip_low_priority_leaves(ctx, all_tasks)

    # Stall detection
    if attempted >= 5 and progress < 0.4:
        logger.warning(
            "Stall detected: progress=%.1f%% after %d attempted tasks",
            progress * 100,
            attempted,
        )
        ctx.log_decision(
            "recovery",
            f"stall-detected at wave {wave_index}",
            f"progress={progress:.2f}, attempted={attempted}",
        )
        await mid_swarm_replan(ctx)


async def mid_swarm_replan(ctx: Any) -> None:
    """Perform a mid-swarm re-plan to recover from stall.

    Guards: runs at most once per session (ctx.has_replanned).
    Uses an LLM call to analyze completed/failed tasks and propose
    replacement subtasks for the stalled remainder.
    """
    if getattr(ctx, "has_replanned", False):
        logger.debug("Re-plan skipped: already replanned this session")
        return

    config: SwarmConfig = ctx.config
    model = config.orchestrator_model
    all_tasks = ctx.task_queue.get_all_tasks()

    # Build a summary of current state
    completed_summaries: list[str] = []
    failed_summaries: list[str] = []
    pending_summaries: list[str] = []

    for tid, t in all_tasks.items():
        desc = f"[{tid}] {t.description} (type={t.type}, complexity={t.complexity})"
        if t.status == SwarmTaskStatus.COMPLETED:
            completed_summaries.append(desc)
        elif t.status in (SwarmTaskStatus.FAILED, SwarmTaskStatus.SKIPPED):
            failed_summaries.append(desc)
        elif t.status in (SwarmTaskStatus.PENDING, SwarmTaskStatus.READY):
            pending_summaries.append(desc)

    prompt = (
        "You are a swarm orchestrator performing mid-execution re-planning.\n\n"
        "COMPLETED tasks:\n" + "\n".join(completed_summaries or ["(none)"]) + "\n\n"
        "FAILED/SKIPPED tasks:\n" + "\n".join(failed_summaries or ["(none)"]) + "\n\n"
        "PENDING tasks:\n" + "\n".join(pending_summaries or ["(none)"]) + "\n\n"
        "Analyze what has stalled and propose replacement subtasks for the "
        "failed/pending work. Keep it practical -- 2-5 subtasks max.\n\n"
        "Respond in JSON: {\"subtasks\": [{\"id\": str, \"description\": str, "
        "\"type\": str, \"complexity\": int, \"dependencies\": [str]}]}"
    )

    try:
        response = await ctx.provider.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3000,
            temperature=0.4,
        )
        ctx.track_orchestrator_usage(response, "mid_swarm_replan")
        text = _extract_text(response)
        parsed = _parse_json_response(text, {"subtasks": []})
        subtasks = parsed.get("subtasks", [])

        if subtasks:
            ctx.task_queue.add_replan_tasks(subtasks)
            ctx.emit(
                swarm_event(
                    "swarm.replan",
                    new_task_count=len(subtasks),
                )
            )
            ctx.log_decision(
                "recovery",
                f"mid-swarm replan: {len(subtasks)} new tasks",
                "stall recovery",
            )
            logger.info("Mid-swarm replan added %d tasks", len(subtasks))
    except Exception:
        logger.warning("Mid-swarm replan LLM call failed", exc_info=True)
    finally:
        ctx.has_replanned = True


# =============================================================================
# Private Helpers
# =============================================================================


async def _micro_decompose(ctx: Any, task: SwarmTask) -> list[dict[str, Any]]:
    """Use an LLM to break a task into 2-3 simpler subtasks.

    Returns a list of dicts suitable for ``task_queue.replace_with_subtasks``.
    """
    config: SwarmConfig = ctx.config
    model = config.orchestrator_model

    prompt = (
        "You are a task decomposition expert. This task has failed multiple "
        "times and needs to be broken into simpler pieces.\n\n"
        f"Task ID: {task.id}\n"
        f"Description: {task.description}\n"
        f"Type: {task.type}\n"
        f"Complexity: {task.complexity}/10\n"
        f"Target files: {task.target_files or 'none'}\n"
        f"Attempts so far: {task.attempts}\n\n"
        "Break this into 2-3 simpler subtasks. Each subtask MUST have:\n"
        "- id: string (e.g. 'sub-1')\n"
        "- description: string\n"
        "- type: 'implement' | 'test' | 'refactor' | 'research'\n"
        "- complexity: int (1-10, must be lower than parent)\n"
        "- dependencies: list of sibling subtask IDs (or empty)\n"
        "- target_files: list of file paths (or empty)\n\n"
        "Respond in JSON: {\"subtasks\": [...]}"
    )

    response = await ctx.provider.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000,
        temperature=0.3,
    )
    ctx.track_orchestrator_usage(response, "micro_decompose")
    text = _extract_text(response)
    parsed = _parse_json_response(text, {"subtasks": []})
    return parsed.get("subtasks", [])


def _budget_has_capacity(ctx: Any) -> bool:
    """Check if the swarm budget pool has remaining capacity (>10%)."""
    try:
        total = ctx.config.total_budget
        used = getattr(ctx, "total_tokens", 0)
        if total <= 0:
            return True
        return (used / total) < 0.9
    except Exception:
        return True


def _get_budget_ratio(ctx: Any) -> float:
    """Return fraction of budget remaining (0.0 to 1.0)."""
    try:
        total = ctx.config.total_budget
        used = getattr(ctx, "total_tokens", 0)
        if total <= 0:
            return 1.0
        return max(0.0, 1.0 - (used / total))
    except Exception:
        return 1.0


def _skip_low_priority_leaves(ctx: Any, all_tasks: dict[str, SwarmTask]) -> None:
    """Skip low-priority leaf tasks to conserve budget.

    A leaf task has no other tasks depending on it.
    Low-priority: complexity <= 3 and type is 'document' or 'review'.
    """
    # Build reverse dependency map
    dependents: dict[str, int] = {}
    for t in all_tasks.values():
        for dep_id in t.dependencies or []:
            dependents[dep_id] = dependents.get(dep_id, 0) + 1

    for task_id, task in all_tasks.items():
        if task.status not in (SwarmTaskStatus.PENDING, SwarmTaskStatus.READY):
            continue
        # Leaf: no one depends on it
        if dependents.get(task_id, 0) > 0:
            continue
        task_type_str = (
            task.type.value if isinstance(task.type, SubtaskType) else str(task.type)
        )
        if task.complexity <= 3 and task_type_str in ("document", "review"):
            task.status = SwarmTaskStatus.SKIPPED
            ctx.emit(
                swarm_event(
                    "swarm.task.skipped",
                    task_id=task_id,
                    reason="budget-conservation",
                )
            )
            logger.debug("Skipped low-priority leaf task %s to conserve budget", task_id)


def _extract_text(response: Any) -> str:
    """Extract text content from an LLM response object."""
    if isinstance(response, str):
        return response
    if hasattr(response, "content"):
        content = response.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if hasattr(block, "text"):
                    parts.append(block.text)
                elif isinstance(block, dict) and "text" in block:
                    parts.append(block["text"])
            return "\n".join(parts)
    if hasattr(response, "text"):
        return response.text
    return str(response)


def _parse_json_response(text: str, default: dict[str, Any]) -> dict[str, Any]:
    """Parse a JSON response from LLM output, handling markdown fences."""
    text = text.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last fence lines
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # Try to find JSON object in the text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    # Fallback
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        logger.debug("Failed to parse JSON from LLM response: %s", text[:200])
        return default
