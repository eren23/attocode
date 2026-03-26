"""Research mode configuration."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ResearchConfig:
    """Configuration for a research run.

    Mirrors the schema in ``attoswarm.config.schema.ResearchConfig`` but
    can be constructed standalone (e.g. from CLI flags).
    """

    metric_name: str = "score"
    metric_direction: str = "maximize"  # maximize|minimize
    experiment_timeout_seconds: float = 300.0
    experiment_max_tokens: int = 500_000
    experiment_max_cost_usd: float = 2.0
    total_max_experiments: int = 100
    total_max_cost_usd: float = 50.0
    total_max_wall_seconds: float = 28800.0  # 8 hours
    min_improvement_threshold: float = 0.0
    eval_command: str = ""
    eval_repeat: int = 1
    baseline_repeats: int = 1
    promotion_repeats: int = 1
    target_files: list[str] = field(default_factory=list)
    use_git_stash: bool = True
    model: str = ""
    backend: str = "claude"
    max_parallel_experiments: int = 1
    search_policy: str = "round_robin"
    experiment_workspace_mode: str = "worktree"
    strategy_mix: dict[str, int] = field(default_factory=lambda: {
        "explore": 2,
        "exploit": 1,
        "ablate": 1,
        "compose": 1,
        "reproduce": 1,
    })
    steering_enabled: bool = True
    preserve_worktrees: bool = True
    working_dir: str = "."
    run_dir: str = ".agent/research"
