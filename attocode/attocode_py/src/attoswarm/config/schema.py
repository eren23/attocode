"""Configuration schema for attoswarm YAML files."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RunConfig:
    name: str = "hybrid-run"
    working_dir: str = "."
    run_dir: str = ".agent/hybrid-swarm"
    poll_interval_ms: int = 250
    max_runtime_seconds: int = 600
    monitor_detach_on_exit: bool = True
    debug: bool = False


@dataclass(slots=True)
class RoleConfig:
    role_id: str
    role_type: str
    backend: str
    model: str  # empty string = use the tool's own default model
    count: int = 1
    write_access: bool = False
    workspace_mode: str = "shared_ro"
    task_kinds: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    command: list[str] | None = None
    execution_mode: str = "oneshot"


@dataclass(slots=True)
class BudgetConfig:
    max_tokens: int = 5_000_000
    max_cost_usd: float = 25.0
    reserve_ratio: float = 0.15
    chars_per_token_fallback: float = 4.0


@dataclass(slots=True)
class MergeConfig:
    authority_role: str = "merger"
    judge_roles: list[str] = field(default_factory=list)
    quality_threshold: float = 0.75
    judge_policy: str = "quorum"
    auto_apply_non_conflicting: bool = True


@dataclass(slots=True)
class WatchdogConfig:
    heartbeat_timeout_seconds: float = 45.0
    task_silence_timeout_seconds: float = 120.0  # 2 min — no progress (not even heartbeats) means dead
    task_max_duration_seconds: float = 600.0  # hard wall-clock limit per task assignment (10 min)


@dataclass(slots=True)
class RetryConfig:
    max_task_attempts: int = 2


@dataclass(slots=True)
class OrchestrationConfig:
    decomposition: str = "llm"  # llm | parallel | heuristic | fast | manual
    max_tasks: int = 20
    max_depth: int = 3
    custom_instructions: str = ""  # Prepended to decompose prompt for domain-specific guidance


@dataclass(slots=True)
class UIConfig:
    default_view: str = "overview"
    poll_ms: int = 500


@dataclass(slots=True)
class WorkspaceConfig:
    mode: str = "shared"  # "shared" (default, AoT+OCC) | "worktree" (legacy subprocess per worktree)
    reconciliation_strategy: str = "ast_merge"  # "ast_merge" | "last_write_wins"
    max_concurrent_writers: int = 4


@dataclass(slots=True)
class SwarmYamlConfig:
    version: int = 1
    run: RunConfig = field(default_factory=RunConfig)
    roles: list[RoleConfig] = field(default_factory=list)
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    merge: MergeConfig = field(default_factory=MergeConfig)
    watchdog: WatchdogConfig = field(default_factory=WatchdogConfig)
    retries: RetryConfig = field(default_factory=RetryConfig)
    orchestration: OrchestrationConfig = field(default_factory=OrchestrationConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
