"""SwarmYamlConfig builder with evaluation defaults.

Provides sensible defaults for SWE-bench evaluation runs:
- 2M token budget
- $5 USD cost limit
- 1200s timeout
- LLM-based decomposition
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SWEBenchEvalConfig:
    """Configuration for a SWE-bench evaluation run."""

    # Model
    model: str = "claude-sonnet-4-20250514"
    provider: str = "anthropic"

    # Budget
    max_tokens: int = 2_000_000
    max_cost_usd: float = 5.0
    max_runtime_seconds: int = 1200

    # Orchestration
    decomposition_mode: str = "llm"
    max_tasks: int = 8
    max_depth: int = 2

    # Concurrency
    max_concurrent_agents: int = 3
    workspace_mode: str = "shared"

    # Retry
    max_task_attempts: int = 2

    # Extra
    debug: bool = False
    custom_instructions: str = ""


def build_swarm_yaml_dict(
    cfg: SWEBenchEvalConfig,
    working_dir: str,
    run_dir: str = "",
) -> dict[str, Any]:
    """Build a SwarmYamlConfig-compatible dict from eval config."""
    return {
        "run": {
            "name": "swebench-eval",
            "working_dir": working_dir,
            "run_dir": run_dir or "",
            "max_runtime_seconds": cfg.max_runtime_seconds,
            "debug": cfg.debug,
            "default_model": cfg.model,
        },
        "roles": [
            {
                "role_id": "coder",
                "role_type": "coder",
                "backend": "attocode",
                "model": cfg.model,
                "count": cfg.max_concurrent_agents,
                "write_access": True,
                "workspace_mode": cfg.workspace_mode,
            },
        ],
        "budget": {
            "max_tokens": cfg.max_tokens,
            "max_cost_usd": cfg.max_cost_usd,
        },
        "orchestration": {
            "decomposition": cfg.decomposition_mode,
            "max_tasks": cfg.max_tasks,
            "max_depth": cfg.max_depth,
            "custom_instructions": cfg.custom_instructions,
        },
        "retries": {
            "max_task_attempts": cfg.max_task_attempts,
        },
        "workspace": {
            "mode": cfg.workspace_mode,
            "max_concurrent_writers": cfg.max_concurrent_agents,
        },
    }


def config_from_dict(d: dict[str, Any]) -> SWEBenchEvalConfig:
    """Create SWEBenchEvalConfig from a flat dict (e.g. CLI args)."""
    return SWEBenchEvalConfig(
        model=d.get("model", "claude-sonnet-4-20250514"),
        provider=d.get("provider", "anthropic"),
        max_tokens=d.get("max_tokens", 2_000_000),
        max_cost_usd=d.get("max_cost_usd", 5.0),
        max_runtime_seconds=d.get("max_runtime_seconds", 1200),
        decomposition_mode=d.get("decomposition_mode", "llm"),
        max_tasks=d.get("max_tasks", 8),
        max_depth=d.get("max_depth", 2),
        max_concurrent_agents=d.get("max_concurrent_agents", 3),
        workspace_mode=d.get("workspace_mode", "shared"),
        max_task_attempts=d.get("max_task_attempts", 2),
        debug=d.get("debug", False),
    )
