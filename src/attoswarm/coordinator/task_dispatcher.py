"""Task dispatch logic extracted from HybridCoordinator."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from attoswarm.adapters.base import AgentMessage
from attoswarm.coordinator.scheduler import (
    AgentSlot,
    assign_tasks,
    compute_ready_tasks,
    find_unschedulable_tasks,
)
from attoswarm.protocol.io import read_json, write_json_atomic
from attoswarm.protocol.locks import locked_file
from attoswarm.protocol.models import (
    AgentInbox,
    InboxMessage,
    TaskSpec,
    utc_now_iso,
)

if TYPE_CHECKING:
    from attoswarm.coordinator.loop import HybridCoordinator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Async code-intel enrichment (side-query pattern)
# ---------------------------------------------------------------------------

async def enrich_task_context_async(
    task: TaskSpec,
    code_intel: Any,
    *,
    timeout: float = 5.0,
) -> dict[str, str]:
    """Fire-and-forget code-intel enrichment for a task.

    Queries code-intel for impact analysis, symbols, and dependencies
    relevant to the task's target files.  Returns whatever completes
    within the timeout -- never blocks task dispatch.

    The code-intel service methods are synchronous, so each query is
    dispatched via ``asyncio.to_thread`` to avoid blocking the event
    loop.

    Args:
        task: Task to enrich.
        code_intel: Code intelligence service instance.
        timeout: Maximum seconds to wait for enrichment.

    Returns:
        Dict with keys like ``"impact"``, ``"symbols"``, ``"dependencies"``
        containing markdown-formatted context strings.
    """
    if not task.target_files or not code_intel:
        return {}

    enrichments: dict[str, str] = {}

    try:
        async with asyncio.timeout(timeout):
            # Build parallel coroutines for each code-intel query.
            # All service methods are sync -- wrap with to_thread.
            coros: list[Any] = []
            labels: list[str] = []

            if hasattr(code_intel, "impact_analysis_data"):
                coros.append(
                    asyncio.to_thread(
                        code_intel.impact_analysis_data, task.target_files
                    )
                )
                labels.append("impact")

            if hasattr(code_intel, "symbols_data"):
                # symbols_data takes a single path -- aggregate over target files
                async def _gather_symbols() -> list[dict]:
                    results: list[dict] = []
                    for tf in task.target_files[:3]:
                        r = await asyncio.to_thread(code_intel.symbols_data, tf)
                        if isinstance(r, list):
                            results.extend(r)
                    return results

                coros.append(_gather_symbols())
                labels.append("symbols")

            if hasattr(code_intel, "dependencies_data"):
                # dependencies_data takes a single path -- aggregate
                async def _gather_deps() -> list[dict]:
                    results: list[dict] = []
                    for tf in task.target_files[:3]:
                        r = await asyncio.to_thread(
                            code_intel.dependencies_data, tf
                        )
                        if isinstance(r, dict):
                            results.append(r)
                    return results

                coros.append(_gather_deps())
                labels.append("dependencies")

            if not coros:
                return {}

            results = await asyncio.gather(*coros, return_exceptions=True)

            for label, result in zip(labels, results):
                if isinstance(result, Exception) or not result:
                    continue
                enrichments[label] = _format_enrichment(label, result)

    except (TimeoutError, asyncio.TimeoutError):
        pass  # Use whatever completed in time
    except Exception:
        pass  # Don't let enrichment failures block dispatch

    return enrichments


def _format_enrichment(label: str, data: Any) -> str:
    """Convert raw code-intel result into a compact markdown snippet."""
    if label == "impact" and isinstance(data, dict):
        impacted = data.get("impacted_files", [])
        if not impacted:
            return ""
        lines = [f"- `{f}`" if isinstance(f, str) else f"- `{f.get('file', '?')}`"
                 for f in impacted[:10]]
        total = data.get("total_impacted", len(impacted))
        header = f"**{total}** file(s) potentially impacted by changes:"
        return f"{header}\n" + "\n".join(lines)

    if label == "symbols" and isinstance(data, list):
        if not data:
            return ""
        lines = []
        for s in data[:15]:
            name = s.get("name", "?") if isinstance(s, dict) else str(s)
            kind = s.get("kind", "") if isinstance(s, dict) else ""
            lines.append(f"- `{name}`" + (f" ({kind})" if kind else ""))
        return "Key symbols in scope:\n" + "\n".join(lines)

    if label == "dependencies" and isinstance(data, list):
        if not data:
            return ""
        all_imports: list[str] = []
        all_imported_by: list[str] = []
        for entry in data:
            if isinstance(entry, dict):
                all_imports.extend(entry.get("imports", []))
                all_imported_by.extend(entry.get("imported_by", []))
        parts: list[str] = []
        if all_imports:
            parts.append("Imports: " + ", ".join(f"`{i}`" for i in sorted(set(all_imports))[:10]))
        if all_imported_by:
            parts.append("Imported by: " + ", ".join(f"`{i}`" for i in sorted(set(all_imported_by))[:10]))
        return "\n".join(parts) if parts else ""

    # Fallback: stringify
    return str(data)[:500] if data else ""


async def dispatch_ready_tasks(coordinator: HybridCoordinator) -> None:
    """Find ready tasks, assign them to free agents, and send assignments."""
    if coordinator.manifest is None:
        raise RuntimeError("Manifest not initialized — cannot dispatch tasks")
    tasks = [
        replace(t, status=coordinator.task_state.get(t.task_id, t.status))
        for t in coordinator.manifest.tasks
    ]
    ready = compute_ready_tasks(tasks, coordinator.task_state)
    all_agents = [
        AgentSlot(
            agent_id=aid,
            role_id=coordinator.role_by_agent[aid].role_id,
            backend=coordinator.role_by_agent[aid].backend,
            busy=aid in coordinator.running_task_by_agent,
        )
        for aid in coordinator.handles
    ]
    unschedulable = find_unschedulable_tasks(ready, all_agents, coordinator.manifest.roles)
    unschedulable_ids = {item.task_id for item in unschedulable}
    for item in unschedulable:
        task = coordinator._find_task(item.task_id)
        if task is None:
            continue
        coordinator._transition_task(task.task_id, "failed", "scheduler", item.reason)
        coordinator._persist_task(task, status="failed", last_error=item.reason)
        coordinator._append_event(
            "task.unschedulable",
            {
                "task_id": item.task_id,
                "task_kind": item.task_kind,
                "role_hint": item.role_hint,
                "reason": item.reason,
                "eligible_role_ids": item.eligible_role_ids,
                "available_role_ids": item.available_role_ids,
            },
        )
        coordinator._error(
            "scheduler_unschedulable",
            (
                f"{item.task_id} ({item.task_kind}) cannot be scheduled: {item.reason}; "
                f"eligible_roles={item.eligible_role_ids or '[]'} "
                f"available_roles={item.available_role_ids or '[]'}"
            ),
        )

    schedulable_ready = [task for task in ready if task.task_id not in unschedulable_ids]
    assignments = assign_tasks(schedulable_ready, all_agents, coordinator.manifest.roles)

    # --- Side-query: fire code-intel enrichment concurrently (non-blocking) ---
    enrichment_futures: dict[str, asyncio.Task[dict[str, str]]] = {}
    code_intel = getattr(coordinator, "_code_intel", None)
    ci_cfg = getattr(getattr(coordinator, "config", None), "code_intel", None)
    enrichment_enabled = bool(
        code_intel and (not ci_cfg or getattr(ci_cfg, "impact_enrichment", True))
    )

    if enrichment_enabled:
        # Build a task_id -> TaskSpec lookup for assigned tasks
        task_by_id: dict[str, TaskSpec] = {}
        for assignment in assignments:
            t = coordinator._find_task(assignment.task_id)
            if t and t.target_files:
                task_by_id[t.task_id] = t
        for tid, t in task_by_id.items():
            enrichment_futures[tid] = asyncio.create_task(
                enrich_task_context_async(t, code_intel, timeout=3.0)
            )

    for assignment in assignments:
        task = coordinator._find_task(assignment.task_id)
        if task is None:
            continue
        attempts = coordinator.task_attempts.get(task.task_id, 0)
        max_attempts = coordinator.config.retries.max_task_attempts
        if attempts >= max_attempts:
            coordinator._transition_task(
                task.task_id, "failed", "coordinator",
                "max_task_attempts_exceeded",
            )
            coordinator._persist_task(
                task, status="failed",
                last_error="max_task_attempts_exceeded",
            )
            # Cancel any pending enrichment for this task
            fut = enrichment_futures.pop(task.task_id, None)
            if fut and not fut.done():
                fut.cancel()
            continue

        # Circuit breaker: skip dispatch if the assigned model is tripped
        role = coordinator.role_by_agent.get(assignment.agent_id)
        if role and coordinator.health_monitor.check_circuit_breaker(role.model):
            logger.warning(
                "Circuit breaker open for model %s — deferring task %s",
                role.model,
                task.task_id,
            )
            coordinator._append_event(
                "circuit_breaker.skip",
                {
                    "task_id": task.task_id,
                    "agent_id": assignment.agent_id,
                    "model": role.model,
                    "reason": "circuit_breaker_open",
                },
            )
            # Cancel any pending enrichment for this task
            fut = enrichment_futures.pop(task.task_id, None)
            if fut and not fut.done():
                fut.cancel()
            continue

        # Collect enrichment if ready (short timeout so dispatch is never blocked)
        enrichment: dict[str, str] = {}
        if task.task_id in enrichment_futures:
            try:
                enrichment = await asyncio.wait_for(
                    enrichment_futures.pop(task.task_id), timeout=2.0,
                )
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                enrichment = {}

        coordinator.task_attempts[task.task_id] = coordinator.task_attempts.get(task.task_id, 0) + 1
        coordinator.running_task_by_agent[assignment.agent_id] = task.task_id
        coordinator.running_task_last_progress[task.task_id] = time.monotonic()
        coordinator.running_task_started_at[task.task_id] = time.monotonic()
        coordinator._transition_task(task.task_id, "running", "coordinator", "assigned")
        coordinator._persist_task(task, status="running", assigned_agent_id=assignment.agent_id)
        await send_task_assignment(
            coordinator, assignment.agent_id, task, enrichment=enrichment,
        )

    # Cancel any remaining enrichment futures that were not consumed
    for fut in enrichment_futures.values():
        if not fut.done():
            fut.cancel()


def build_task_prompt(
    coordinator: HybridCoordinator,
    task: TaskSpec,
    *,
    enrichment: dict[str, str] | None = None,
) -> str:
    """Build an actionable prompt for the agent based on task kind.

    The prompt gives the agent coding context and instructions appropriate
    for its task type.  It intentionally does NOT include protocol markers
    like ``[TASK_DONE]`` / ``[TASK_FAILED]`` -- those are emitted by the
    heartbeat wrapper based on exit code.

    If *enrichment* is provided (from :func:`enrich_task_context_async`),
    a ``## Code Intelligence Context`` section is appended with impact
    analysis, symbol, and dependency information.
    """
    desc = task.description.replace(chr(10), " ").strip()
    goal_ctx = f"Project goal: {coordinator.goal}\n\n" if coordinator.goal else ""

    acceptance_block = ""
    if task.acceptance:
        items = "\n".join(f"  - {a}" for a in task.acceptance)
        acceptance_block = f"\nAcceptance criteria:\n{items}\n"

    if task.task_kind in ("implement", "test", "integrate"):
        prompt = (
            f"{goal_ctx}"
            f"Task {task.task_id}: {task.title}\n\n"
            f"{desc}\n"
            f"{acceptance_block}\n"
            "You are a coding agent. Read the existing code in this working directory, "
            "then create or modify the necessary files to complete this task. "
            "Write clean, working code. Run any available tests to verify correctness."
        )
    elif task.task_kind in ("analysis", "design"):
        prompt = (
            f"{goal_ctx}"
            f"Task {task.task_id}: {task.title}\n\n"
            f"{desc}\n"
            f"{acceptance_block}\n"
            "Analyze the codebase in this working directory and produce a concrete "
            "written plan or analysis. Include specific file paths, function names, "
            "and implementation details."
        )
    elif task.task_kind in ("judge", "critic"):
        prompt = (
            f"{goal_ctx}"
            f"Task {task.task_id}: {task.title}\n\n"
            f"{desc}\n"
            f"{acceptance_block}\n"
            "Evaluate the work in this working directory. Check for correctness, "
            "completeness, and adherence to the acceptance criteria. Report any issues found."
        )
    else:
        # Fallback for merge or unknown kinds
        prompt = (
            f"{goal_ctx}"
            f"Task {task.task_id}: {task.title}\n\n"
            f"{desc}\n"
            f"{acceptance_block}\n"
            "Complete this task using the files in the current working directory."
        )

    # Append code-intel enrichment if available
    if enrichment:
        parts = []
        for key, value in enrichment.items():
            if value:
                parts.append(f"### {key.title()} Analysis\n{value}")
        if parts:
            enrichment_section = "\n\n".join(parts)
            prompt += f"\n\n## Code Intelligence Context\n\n{enrichment_section}"

    return prompt


async def send_task_assignment(
    coordinator: HybridCoordinator,
    agent_id: str,
    task: TaskSpec,
    *,
    enrichment: dict[str, str] | None = None,
) -> None:
    """Write an inbox message and send the task prompt to the agent."""
    inbox_path = coordinator.layout["agents"] / f"agent-{agent_id}.inbox.json"
    lock_path = coordinator.layout["locks"] / f"agent-{agent_id}.inbox.lock"
    with locked_file(lock_path):
        raw = read_json(inbox_path, AgentInbox(agent_id=agent_id).to_dict())
        next_seq = int(raw.get("next_seq", 1))
        msg = InboxMessage(
            seq=next_seq,
            message_id=f"{agent_id}-m{next_seq}",
            timestamp=utc_now_iso(),
            kind="task_assign",
            task_id=task.task_id,
            payload={
                "title": task.title,
                "description": task.description,
                "acceptance": task.acceptance,
                "artifacts": task.artifacts,
                "task_kind": task.task_kind,
            },
            requires_ack=True,
        )
        messages = raw.get("messages", [])
        messages.append(
            {
                "seq": msg.seq,
                "message_id": msg.message_id,
                "timestamp": msg.timestamp,
                "kind": msg.kind,
                "task_id": msg.task_id,
                "payload": msg.payload,
                "requires_ack": msg.requires_ack,
            }
        )
        raw["messages"] = messages
        raw["next_seq"] = next_seq + 1
        write_json_atomic(inbox_path, raw)

    prompt_text = build_task_prompt(coordinator, task, enrichment=enrichment)
    adapter = coordinator.adapters[agent_id]
    handle = coordinator.handles[agent_id]
    await adapter.send_message(
        handle,
        AgentMessage(
            message_id=msg.message_id,
            task_id=task.task_id,
            kind="task_assign",
            content=prompt_text,
        ),
    )
    coordinator._append_event(
        "agent.task.launch",
        {"agent_id": agent_id, "task_id": task.task_id, "task_kind": task.task_kind},
    )
    if enrichment:
        coordinator._append_event(
            "codeintel.enrichment.applied",
            {
                "task_id": task.task_id,
                "agent_id": agent_id,
                "enrichment_keys": list(enrichment.keys()),
            },
        )
    if coordinator.config.run.debug:
        coordinator._append_event(
            "debug.task.prompt_sent",
            {
                "agent_id": agent_id,
                "task_id": task.task_id,
                "prompt": prompt_text[:2000],
            },
        )
