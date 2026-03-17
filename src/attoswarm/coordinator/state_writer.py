"""Swarm state snapshot persistence."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from attoswarm.protocol.io import write_json_atomic
from attoswarm.protocol.models import SwarmState, TaskSpec, utc_now_iso


def write_state(
    state_path: str,
    run_id: str,
    phase: str,
    tasks: list[TaskSpec],
    active_agents: list[dict],
    dag_edges: list[tuple[str, str]],
    budget: dict,
    watchdog: dict,
    merge_queue: dict,
    index_status: dict,
    cursors: dict,
    assignments: dict,
    attempts: dict,
    state_seq: int,
    errors: list[dict],
    task_transition_log: list[dict],
    event_timeline: dict,
    agent_messages_index: dict,
    elapsed_s: float = 0.0,
    timeout_overrides: dict[str, int] | None = None,
) -> None:
    counts = Counter(t.status for t in tasks)

    # Build assignment lookup: task_id -> agent_id
    running_by_agent = assignments.get("running_by_agent", {})
    agent_for_task: dict[str, str] = {
        task_id: agent_id for agent_id, task_id in running_by_agent.items()
    }

    # Build attempt lookup
    by_task = attempts.get("by_task", {}) if isinstance(attempts, dict) else {}

    # dag_summary: counts by display bucket (pending/running/done/failed)
    dag_summary = {
        "pending": counts.get("pending", 0) + counts.get("ready", 0) + counts.get("blocked", 0),
        "running": counts.get("running", 0) + counts.get("reviewing", 0),
        "done": counts.get("done", 0),
        "failed": counts.get("failed", 0) + counts.get("skipped", 0),
    }

    # Enriched dag nodes
    dag_nodes = []
    for t in tasks:
        node: dict = {
            "task_id": t.task_id,
            "status": t.status,
            "title": t.title,
            "description": t.description[:200] if t.description else "",
            "task_kind": t.task_kind,
            "role_hint": t.role_hint or "",
            "assigned_agent": agent_for_task.get(t.task_id, ""),
            "target_files": t.target_files[:5],
            "result_summary": t.result_summary[:200] if t.result_summary else "",
            "attempts": by_task.get(t.task_id, 0),
        }
        dag_nodes.append(node)

    payload = SwarmState(
        run_id=run_id,
        phase=phase,
        updated_at=utc_now_iso(),
        tasks={
            "pending": counts.get("pending", 0),
            "ready": counts.get("ready", 0),
            "running": counts.get("running", 0),
            "done": counts.get("done", 0),
            "failed": counts.get("failed", 0),
            "blocked": counts.get("blocked", 0),
        },
        active_agents=active_agents,  # type: ignore[arg-type]
        dag={
            "nodes": dag_nodes,
            "edges": [[a, b] for a, b in dag_edges],
        },
        budget=budget,
        watchdog=watchdog,
        merge_queue=merge_queue,
        index_status=index_status,
        cursors=cursors,
        assignments=assignments,
        attempts=attempts,
        state_seq=state_seq,
        errors=errors,
        task_transition_log=task_transition_log,
        event_timeline=event_timeline,
        agent_messages_index=agent_messages_index,
        dag_summary=dag_summary,
        elapsed_s=elapsed_s,
    )
    state_dict = payload.to_dict()
    if timeout_overrides:
        state_dict["timeout_overrides"] = timeout_overrides
    write_json_atomic(Path(state_path), state_dict)
