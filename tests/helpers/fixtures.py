"""Synthetic run directory factory for swarm trace testing."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from attoswarm.protocol.io import append_jsonl, write_json_atomic
from attoswarm.protocol.models import default_run_layout


def _ts(offset_s: float = 0.0) -> str:
    """ISO timestamp with optional offset from 'now'."""
    return (datetime(2026, 2, 24, 12, 0, 0, tzinfo=UTC) + timedelta(seconds=offset_s)).isoformat()


@dataclass
class SyntheticAgent:
    agent_id: str = ""
    role_id: str = "coder"
    role_type: str = "worker"
    backend: str = "claude"
    status: str = "idle"
    task_id: str | None = None
    exit_code: int | None = None
    cwd: str = "/tmp/work"
    command: str = "claude --agent"
    restart_count: int = 0
    stderr_tail: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "agent_id": self.agent_id or f"agent-{uuid.uuid4().hex[:8]}",
            "role_id": self.role_id,
            "role_type": self.role_type,
            "backend": self.backend,
            "status": self.status,
            "task_id": self.task_id,
            "exit_code": self.exit_code,
            "cwd": self.cwd,
            "command": self.command,
            "restart_count": self.restart_count,
            "stderr_tail": self.stderr_tail,
        }
        return d


@dataclass
class SyntheticTask:
    task_id: str = ""
    title: str = "Implement feature"
    description: str = "Build the feature"
    status: str = "done"
    task_kind: str = "implement"
    role_hint: str = "coder"
    attempts: int = 1
    assigned_agent_id: str = ""
    last_error: str = ""
    transitions: list[dict[str, Any]] = field(default_factory=list)
    deps: list[str] = field(default_factory=list)
    priority: int = 50

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "task_kind": self.task_kind,
            "role_hint": self.role_hint,
            "attempts": self.attempts,
            "assigned_agent_id": self.assigned_agent_id,
            "last_error": self.last_error,
            "transitions": self.transitions,
        }


@dataclass
class SyntheticRunSpec:
    """Specification for building a fake run directory."""

    run_id: str = ""
    goal: str = "Build a REST API"
    phase: str = "completed"
    agents: list[SyntheticAgent] = field(default_factory=list)
    tasks: list[SyntheticTask] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    budget_tokens_used: int = 100_000
    budget_tokens_max: int = 5_000_000
    budget_cost_used: float = 0.50
    budget_cost_max: float = 25.0


def create_synthetic_run(
    base_dir: Path,
    spec: SyntheticRunSpec | None = None,
) -> Path:
    """Build a complete run directory from a spec. Returns the run_dir path.

    If *spec* is None a default clean run (1 agent, 2 done tasks, healthy
    events) is created.
    """
    if spec is None:
        spec = _default_clean_spec()

    run_id = spec.run_id or f"run_{uuid.uuid4().hex[:12]}"
    run_dir = base_dir / run_id
    layout = default_run_layout(run_dir)

    # Create directories
    for key in ("agents", "tasks", "locks", "logs", "worktrees"):
        layout[key].mkdir(parents=True, exist_ok=True)

    # --- manifest ---
    manifest = {
        "schema_version": "1.0",
        "run_id": run_id,
        "goal": spec.goal,
        "created_at": _ts(),
        "roles": [
            {
                "role_id": a.role_id,
                "role_type": a.role_type,
                "backend": a.backend,
                "model": "claude-sonnet-4-20250514",
                "count": 1,
            }
            for a in spec.agents
        ],
        "tasks": [
            {
                "task_id": t.task_id,
                "title": t.title,
                "description": t.description,
                "deps": t.deps,
                "role_hint": t.role_hint,
                "priority": t.priority,
                "status": "pending",
                "task_kind": t.task_kind,
            }
            for t in spec.tasks
        ],
        "budget": {
            "max_tokens": spec.budget_tokens_max,
            "max_cost_usd": spec.budget_cost_max,
        },
    }
    write_json_atomic(layout["manifest"], manifest)

    # --- state ---
    dag_nodes = [
        {"task_id": t.task_id, "title": t.title, "status": t.status}
        for t in spec.tasks
    ]
    dag_edges = []
    for t in spec.tasks:
        for dep in t.deps:
            dag_edges.append({"from": dep, "to": t.task_id})

    state = {
        "schema_version": "1.0",
        "run_id": run_id,
        "phase": spec.phase,
        "updated_at": _ts(60),
        "tasks": {},
        "active_agents": [a.to_dict() for a in spec.agents],
        "dag": {"nodes": dag_nodes, "edges": dag_edges},
        "budget": {
            "tokens_used": spec.budget_tokens_used,
            "tokens_max": spec.budget_tokens_max,
            "cost_used_usd": spec.budget_cost_used,
            "cost_max_usd": spec.budget_cost_max,
        },
        "merge_queue": {"pending": 0, "in_review": 0, "merged": 0},
        "errors": spec.errors,
        "state_seq": 1,
        "attempts": {"by_task": {t.task_id: t.attempts for t in spec.tasks}},
        "event_timeline": {},
        "agent_messages_index": {},
    }
    write_json_atomic(layout["state"], state)

    # --- task files ---
    for t in spec.tasks:
        write_json_atomic(
            layout["tasks"] / f"task-{t.task_id}.json",
            t.to_dict(),
        )

    # --- agent inbox/outbox ---
    for a in spec.agents:
        aid = a.agent_id or a.to_dict()["agent_id"]
        write_json_atomic(
            layout["agents"] / f"agent-{aid}.inbox.json",
            {"schema_version": "1.0", "agent_id": aid, "next_seq": 1, "messages": []},
        )
        write_json_atomic(
            layout["agents"] / f"agent-{aid}.outbox.json",
            {"schema_version": "1.0", "agent_id": aid, "next_seq": 1, "events": []},
        )

    # --- events ---
    for ev in spec.events:
        ev.setdefault("run_id", run_id)
        append_jsonl(layout["events"], ev)

    return run_dir


# ---------------------------------------------------------------------------
# Preset specs
# ---------------------------------------------------------------------------

def _default_clean_spec() -> SyntheticRunSpec:
    """A clean completed run with 1 agent and 2 done tasks."""
    agent = SyntheticAgent(agent_id="a1", role_id="coder", status="idle")
    t1 = SyntheticTask(task_id="t1", title="Implement feature", status="done", assigned_agent_id="a1")
    t2 = SyntheticTask(task_id="t2", title="Write tests", status="done", task_kind="test", assigned_agent_id="a1", deps=["t1"])

    events = _build_healthy_events("a1", [t1, t2])
    return SyntheticRunSpec(
        agents=[agent],
        tasks=[t1, t2],
        events=events,
    )


def _build_healthy_events(
    agent_id: str,
    tasks: list[SyntheticTask],
) -> list[dict[str, Any]]:
    """Generate a plausible event stream for completed tasks."""
    events: list[dict[str, Any]] = []
    offset = 0.0

    for t in tasks:
        # pending -> ready
        events.append({
            "timestamp": _ts(offset),
            "type": "task.transition",
            "payload": {"task_id": t.task_id, "from_state": "pending", "to_state": "ready", "reason": "deps_met"},
        })
        offset += 1.0

        # ready -> running
        events.append({
            "timestamp": _ts(offset),
            "type": "task.transition",
            "payload": {"task_id": t.task_id, "from_state": "ready", "to_state": "running", "reason": "assigned"},
        })
        offset += 1.0

        # agent heartbeats (include file-op evidence for coding task checks)
        heartbeat_messages = [
            "Analyzing requirements...",
            f"Created src/{t.task_id}.py with write_file",
            "Edited tests and verified output",
        ]
        for msg in heartbeat_messages:
            events.append({
                "timestamp": _ts(offset),
                "type": "agent.event",
                "payload": {"agent_id": agent_id, "task_id": t.task_id, "message": msg},
            })
            offset += 5.0

        # agent.task.exit
        events.append({
            "timestamp": _ts(offset),
            "type": "agent.task.exit",
            "payload": {"agent_id": agent_id, "task_id": t.task_id, "exit_code": 0},
        })
        offset += 1.0

        # agent.task.classified
        events.append({
            "timestamp": _ts(offset),
            "type": "agent.task.classified",
            "payload": {"agent_id": agent_id, "task_id": t.task_id, "classification": "success"},
        })
        offset += 1.0

        # running -> done
        events.append({
            "timestamp": _ts(offset),
            "type": "task.transition",
            "payload": {"task_id": t.task_id, "from_state": "running", "to_state": "done", "reason": "classified_success"},
        })
        offset += 1.0

    return events
