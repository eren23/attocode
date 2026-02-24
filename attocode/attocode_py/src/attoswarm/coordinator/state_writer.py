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
) -> None:
    counts = Counter(t.status for t in tasks)
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
            "nodes": [{"task_id": t.task_id, "status": t.status, "title": t.title} for t in tasks],
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
    )
    write_json_atomic(Path(state_path), payload.to_dict())
