"""Swarm role registry — extensible role system for multi-agent orchestration.

Two fixed roles (always present):
- **Orchestrator** — decomposes, schedules, coordinates, replans.
- **Judge** — scores worker output 1-5, enforces quality gates.

Configurable roles (0 or more):
- **Critic** — read-only wave reviewer, produces fixup instructions.
- **Scout** — read-only codebase explorer, gathers context before implementation.
- **Builder** — implementation worker, writes code and runs tests.
- **Tester** — dedicated test writer/runner.
- **Merger** — handles integration of parallel outputs, resolves conflicts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RoleConfig:
    """Configuration for a swarm role."""

    name: str
    model: str | None = None       # None = inherit from orchestrator
    persona: str = ""               # System prompt persona override
    capabilities: list[str] = field(default_factory=lambda: ["code"])
    allowed_tools: list[str] | None = None
    read_only: bool = False         # Scout, reviewer, critic
    max_per_swarm: int | None = None  # None = unlimited
    quality_threshold: int | None = None  # Override default quality threshold


BUILTIN_ROLES: dict[str, RoleConfig] = {
    "orchestrator": RoleConfig(
        "orchestrator",
        capabilities=["orchestrate"],
        max_per_swarm=1,
    ),
    "judge": RoleConfig(
        "judge",
        read_only=True,
        capabilities=["review"],
        max_per_swarm=1,
    ),
    "critic": RoleConfig(
        "critic",
        read_only=True,
        capabilities=["review"],
        persona=(
            "You are a strict code reviewer. Analyze the output of each "
            "completed wave and identify issues, gaps, and improvements. "
            "Be specific and actionable in your feedback."
        ),
    ),
    "scout": RoleConfig(
        "scout",
        read_only=True,
        capabilities=["research"],
        persona=(
            "You are a codebase explorer. Your job is to read and analyze "
            "files, understand architecture, identify patterns, and report "
            "findings that will help implementation workers."
        ),
    ),
    "builder": RoleConfig(
        "builder",
        capabilities=["code", "test"],
    ),
    "tester": RoleConfig(
        "tester",
        capabilities=["test"],
    ),
    "merger": RoleConfig(
        "merger",
        capabilities=["code", "write"],
    ),
}


def get_role_config(
    role_name: str,
    overrides: dict[str, Any] | None = None,
) -> RoleConfig:
    """Get a role config, optionally with field overrides.

    Args:
        role_name: Name of the role (must be in BUILTIN_ROLES).
        overrides: Dict of field overrides (e.g. ``{"model": "claude-sonnet-4-6"}``).

    Returns:
        A RoleConfig with the built-in defaults merged with overrides.
    """
    builtin = BUILTIN_ROLES.get(role_name)
    if builtin is None:
        # Unknown role — create a generic builder-like config
        base = RoleConfig(name=role_name)
    else:
        # Copy the builtin
        base = RoleConfig(
            name=builtin.name,
            model=builtin.model,
            persona=builtin.persona,
            capabilities=list(builtin.capabilities),
            allowed_tools=list(builtin.allowed_tools) if builtin.allowed_tools else None,
            read_only=builtin.read_only,
            max_per_swarm=builtin.max_per_swarm,
            quality_threshold=builtin.quality_threshold,
        )

    if overrides:
        for key, val in overrides.items():
            if hasattr(base, key):
                setattr(base, key, val)

    return base


def build_role_map(
    roles_config: dict[str, dict[str, Any]] | None = None,
) -> dict[str, RoleConfig]:
    """Build a complete role map from config.

    Always includes ``orchestrator`` and ``judge``.
    Additional roles are added from ``roles_config``.

    Args:
        roles_config: Mapping of role_name → field overrides from YAML/config.

    Returns:
        Complete role map with all configured roles.
    """
    roles: dict[str, RoleConfig] = {}

    # Always include fixed roles
    roles["orchestrator"] = get_role_config("orchestrator")
    roles["judge"] = get_role_config("judge")

    # Add configured roles
    if roles_config:
        for name, overrides in roles_config.items():
            roles[name] = get_role_config(name, overrides)

    # If no builder configured, add default
    if "builder" not in roles:
        roles["builder"] = get_role_config("builder")

    return roles


def get_judge_model(
    roles: dict[str, RoleConfig],
    orchestrator_model: str,
) -> str:
    """Get the model to use for the judge role.

    Falls back to orchestrator model if judge has no model override.
    """
    judge = roles.get("judge")
    if judge and judge.model:
        return judge.model
    return orchestrator_model


def get_critic_config(
    roles: dict[str, RoleConfig],
) -> RoleConfig | None:
    """Get the critic role config, or None if not configured."""
    return roles.get("critic")


def get_scout_config(
    roles: dict[str, RoleConfig],
) -> RoleConfig | None:
    """Get the scout role config, or None if not configured."""
    return roles.get("scout")
