"""Task dispatch logic extracted from HybridCoordinator."""

from __future__ import annotations

import time
from dataclasses import replace
from typing import TYPE_CHECKING

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
            continue
        coordinator.task_attempts[task.task_id] = coordinator.task_attempts.get(task.task_id, 0) + 1
        coordinator.running_task_by_agent[assignment.agent_id] = task.task_id
        coordinator.running_task_last_progress[task.task_id] = time.monotonic()
        coordinator.running_task_started_at[task.task_id] = time.monotonic()
        coordinator._transition_task(task.task_id, "running", "coordinator", "assigned")
        coordinator._persist_task(task, status="running", assigned_agent_id=assignment.agent_id)
        await send_task_assignment(coordinator, assignment.agent_id, task)


def build_task_prompt(coordinator: HybridCoordinator, task: TaskSpec) -> str:
    """Build an actionable prompt for the agent based on task kind.

    The prompt gives the agent coding context and instructions appropriate
    for its task type.  It intentionally does NOT include protocol markers
    like ``[TASK_DONE]`` / ``[TASK_FAILED]`` -- those are emitted by the
    heartbeat wrapper based on exit code.
    """
    desc = task.description.replace(chr(10), " ").strip()
    goal_ctx = f"Project goal: {coordinator.goal}\n\n" if coordinator.goal else ""

    acceptance_block = ""
    if task.acceptance:
        items = "\n".join(f"  - {a}" for a in task.acceptance)
        acceptance_block = f"\nAcceptance criteria:\n{items}\n"

    if task.task_kind in ("implement", "test", "integrate"):
        return (
            f"{goal_ctx}"
            f"Task {task.task_id}: {task.title}\n\n"
            f"{desc}\n"
            f"{acceptance_block}\n"
            "You are a coding agent. Read the existing code in this working directory, "
            "then create or modify the necessary files to complete this task. "
            "Write clean, working code. Run any available tests to verify correctness."
        )

    if task.task_kind in ("analysis", "design"):
        return (
            f"{goal_ctx}"
            f"Task {task.task_id}: {task.title}\n\n"
            f"{desc}\n"
            f"{acceptance_block}\n"
            "Analyze the codebase in this working directory and produce a concrete "
            "written plan or analysis. Include specific file paths, function names, "
            "and implementation details."
        )

    if task.task_kind in ("judge", "critic"):
        return (
            f"{goal_ctx}"
            f"Task {task.task_id}: {task.title}\n\n"
            f"{desc}\n"
            f"{acceptance_block}\n"
            "Evaluate the work in this working directory. Check for correctness, "
            "completeness, and adherence to the acceptance criteria. Report any issues found."
        )

    # Fallback for merge or unknown kinds
    return (
        f"{goal_ctx}"
        f"Task {task.task_id}: {task.title}\n\n"
        f"{desc}\n"
        f"{acceptance_block}\n"
        "Complete this task using the files in the current working directory."
    )


async def send_task_assignment(
    coordinator: HybridCoordinator, agent_id: str, task: TaskSpec
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

    prompt_text = build_task_prompt(coordinator, task)
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
    if coordinator.config.run.debug:
        coordinator._append_event(
            "debug.task.prompt_sent",
            {
                "agent_id": agent_id,
                "task_id": task.task_id,
                "prompt": prompt_text[:2000],
            },
        )
