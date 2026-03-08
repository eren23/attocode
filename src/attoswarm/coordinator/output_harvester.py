"""Output harvesting logic extracted from HybridCoordinator."""

from __future__ import annotations

import subprocess
import time
from typing import TYPE_CHECKING, Any

from attoswarm.protocol.io import read_json, write_json_atomic
from attoswarm.protocol.locks import locked_file
from attoswarm.protocol.models import AgentOutbox

if TYPE_CHECKING:
    from attoswarm.coordinator.loop import HybridCoordinator


async def harvest_outputs(coordinator: HybridCoordinator) -> None:
    """Read new events from every agent's adapter and process them."""
    for agent_id, adapter in coordinator.adapters.items():
        handle = coordinator.handles[agent_id]
        events = await adapter.read_output(
            handle, since_seq=coordinator.outbox_cursors.get(agent_id, 0)
        )
        if not events:
            if (
                handle.process.returncode is not None
                and agent_id in coordinator.running_task_by_agent
            ):
                from attoswarm.coordinator.failure_handler import mark_running_task_failed

                await mark_running_task_failed(
                    coordinator,
                    agent_id,
                    coordinator._exit_reason(agent_id, "process_exit_without_terminal_event"),
                )
            continue

        outbox_path = coordinator.layout["agents"] / f"agent-{agent_id}.outbox.json"
        lock_path = coordinator.layout["locks"] / f"agent-{agent_id}.outbox.lock"
        with locked_file(lock_path):
            raw = read_json(outbox_path, AgentOutbox(agent_id=agent_id).to_dict())
            next_seq = int(raw.get("next_seq", 1))
            raw_events = raw.get("events", [])
            for ev in events:
                task_id = coordinator.running_task_by_agent.get(agent_id)
                line = str(ev.payload.get("line", ""))
                coordinator.budget.add_usage(ev.token_usage, ev.cost_usd, text=line)
                payload: dict[str, Any] = {
                    "seq": next_seq,
                    "event_id": f"{agent_id}-e{next_seq}",
                    "timestamp": ev.timestamp,
                    "type": ev.type,
                    "task_id": task_id,
                    "payload": ev.payload,
                    "token_usage": ev.token_usage,
                    "cost_usd": ev.cost_usd,
                }
                raw_events.append(payload)
                coordinator.outbox_cursors[agent_id] = next_seq
                coordinator._append_event(
                    "agent.event",
                    {
                        "agent_id": agent_id,
                        "task_id": task_id,
                        "event_type": ev.type,
                        "payload": ev.payload,
                    },
                )

                if ev.type == "task_done" and task_id:
                    await handle_completion_claim(coordinator, agent_id, task_id)
                elif ev.type == "task_failed" and task_id:
                    from attoswarm.coordinator.failure_handler import handle_task_failed

                    await handle_task_failed(
                        coordinator, agent_id, task_id, reason="worker_reported_failure"
                    )
                else:
                    if task_id:
                        coordinator.running_task_last_progress[task_id] = time.monotonic()
                next_seq += 1
            raw["events"] = raw_events
            raw["next_seq"] = next_seq
            write_json_atomic(outbox_path, raw)


def capture_partial_output(coordinator: HybridCoordinator, agent_id: str) -> str:
    """Best-effort capture of partial progress from an agent's outbox."""
    try:
        outbox_path = coordinator.layout["agents"] / f"agent-{agent_id}.outbox.json"
        outbox = read_json(outbox_path, {})
        events = outbox.get("events", [])
        if events:
            last_events = events[-3:]
            return "; ".join(
                str(
                    e.get("payload", {}).get("line")
                    or e.get("payload", {}).get("message")
                    or e.get("payload", {}).get("result")
                    or e.get("type", "")
                )[:100]
                for e in last_events
                if isinstance(e, dict)
            )
    except Exception:
        pass
    return ""


async def handle_completion_claim(
    coordinator: HybridCoordinator, agent_id: str, task_id: str
) -> None:
    """Process a task_done claim from an agent."""
    detect_file_changes(coordinator, agent_id, task_id)
    coordinator.running_task_by_agent.pop(agent_id, None)
    coordinator.running_task_last_progress.pop(task_id, None)
    coordinator.running_task_started_at.pop(task_id, None)
    coordinator._append_event(
        "agent.task.exit",
        {"agent_id": agent_id, "task_id": task_id, "result": "task_done"},
    )
    coordinator._append_event(
        "agent.task.classified",
        {"agent_id": agent_id, "task_id": task_id, "classification": "success"},
    )
    task = coordinator._find_task(task_id)
    if task is None:
        return
    from attoswarm.coordinator.loop import SKIP_REVIEW_KINDS

    if task.task_kind in SKIP_REVIEW_KINDS:
        coordinator._transition_task(
            task_id, "done", coordinator._role_type_by_agent(agent_id), "terminal_claim"
        )
        coordinator._persist_task(task, status="done")
        return
    # Worker tasks become reviewing first; higher hierarchy decides final status.
    coordinator._transition_task(
        task_id, "reviewing", coordinator._role_type_by_agent(agent_id), "completion_claim"
    )
    coordinator._persist_task(task, status="reviewing")
    coordinator.merge_queue.enqueue(task_id, artifacts=task.artifacts)


def detect_file_changes(
    coordinator: HybridCoordinator, agent_id: str, task_id: str
) -> None:
    """Best-effort detection of files changed in an agent's worktree."""
    handle = coordinator.handles.get(agent_id)
    if not handle:
        return
    cwd = handle.spec.cwd
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        changed = [f for f in result.stdout.strip().splitlines() if f]
        new_files = [f"+ {f}" for f in untracked.stdout.strip().splitlines() if f]
        all_files = changed + new_files
        if all_files:
            coordinator._append_event(
                "task.files_changed",
                {
                    "agent_id": agent_id,
                    "task_id": task_id,
                    "files": all_files[:50],
                    "cwd": cwd,
                },
            )
    except Exception:
        pass  # Best-effort
