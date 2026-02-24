"""Filesystem protocol types for attoswarm."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

SchemaVersion = Literal["1.0"]
TaskStatus = Literal["pending", "ready", "running", "done", "failed", "blocked", "skipped"]
RoleType = Literal[
    "orchestrator",
    "worker",
    "judge",
    "critic",
    "synthesizer",
    "researcher",
    "merger",
]
WorkspaceMode = Literal["worktree", "shared_ro"]


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class RoleSpec:
    role_id: str
    role_type: RoleType
    backend: str
    model: str
    count: int = 1
    write_access: bool = False
    workspace_mode: WorkspaceMode = "shared_ro"
    capabilities: list[str] = field(default_factory=list)
    task_kinds: list[str] = field(default_factory=list)
    execution_mode: str = "oneshot"


@dataclass(slots=True)
class TaskSpec:
    task_id: str
    title: str
    description: str
    deps: list[str] = field(default_factory=list)
    ready_when: Literal["all"] = "all"
    role_hint: str | None = None
    priority: int = 50
    acceptance: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    status: TaskStatus = "pending"
    task_kind: str = "implement"


@dataclass(slots=True)
class BudgetSpec:
    max_tokens: int = 5_000_000
    max_cost_usd: float = 25.0
    reserve_ratio: float = 0.15
    estimation_fallback: str = "chars_to_tokens_v1"
    chars_per_token_fallback: float = 4.0


@dataclass(slots=True)
class MergePolicy:
    authority_role: str = "merger"
    quality_threshold: float = 0.75


@dataclass(slots=True)
class CodeIndexSpec:
    snapshot_id: str | None = None
    freshness_ts: str | None = None
    index_version: str = "1"


@dataclass(slots=True)
class SwarmManifest:
    schema_version: SchemaVersion = "1.0"
    run_id: str = ""
    goal: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    roles: list[RoleSpec] = field(default_factory=list)
    tasks: list[TaskSpec] = field(default_factory=list)
    budget: BudgetSpec = field(default_factory=BudgetSpec)
    merge_policy: MergePolicy = field(default_factory=MergePolicy)
    code_index: CodeIndexSpec = field(default_factory=CodeIndexSpec)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class InboxMessage:
    seq: int
    message_id: str
    timestamp: str
    kind: str
    task_id: str | None
    payload: dict[str, Any]
    requires_ack: bool = False


@dataclass(slots=True)
class AgentInbox:
    schema_version: SchemaVersion = "1.0"
    agent_id: str = ""
    next_seq: int = 1
    messages: list[InboxMessage] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class OutboxEvent:
    seq: int
    event_id: str
    timestamp: str
    type: str
    task_id: str | None
    payload: dict[str, Any]
    token_usage: dict[str, int] | None = None
    cost_usd: float | None = None


@dataclass(slots=True)
class AgentOutbox:
    schema_version: SchemaVersion = "1.0"
    agent_id: str = ""
    next_seq: int = 1
    events: list[OutboxEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AgentState:
    agent_id: str
    role_id: str
    backend: str
    status: str
    task_id: str | None
    last_heartbeat_ts: str
    tokens_used: int = 0
    cost_usd: float = 0.0


@dataclass(slots=True)
class SwarmState:
    schema_version: SchemaVersion = "1.0"
    run_id: str = ""
    phase: str = "init"
    updated_at: str = field(default_factory=utc_now_iso)
    tasks: dict[str, int] = field(default_factory=dict)
    active_agents: list[AgentState] = field(default_factory=list)
    dag: dict[str, Any] = field(default_factory=lambda: {"nodes": [], "edges": []})
    budget: dict[str, Any] = field(default_factory=dict)
    watchdog: dict[str, Any] = field(default_factory=dict)
    merge_queue: dict[str, Any] = field(default_factory=dict)
    index_status: dict[str, Any] = field(default_factory=dict)
    cursors: dict[str, Any] = field(default_factory=dict)
    assignments: dict[str, Any] = field(default_factory=dict)
    attempts: dict[str, Any] = field(default_factory=dict)
    state_seq: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    task_transition_log: list[dict[str, Any]] = field(default_factory=list)
    event_timeline: dict[str, Any] = field(default_factory=dict)
    agent_messages_index: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_run_layout(run_dir: Path) -> dict[str, Path]:
    return {
        "root": run_dir,
        "agents": run_dir / "agents",
        "tasks": run_dir / "tasks",
        "locks": run_dir / "locks",
        "logs": run_dir / "logs",
        "worktrees": run_dir / "worktrees",
        "manifest": run_dir / "swarm.manifest.json",
        "state": run_dir / "swarm.state.json",
        "events": run_dir / "swarm.events.jsonl",
    }
