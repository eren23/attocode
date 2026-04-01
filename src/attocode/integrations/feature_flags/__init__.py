"""Feature flag registry — gate capabilities via environment/config.

Unlike CC's Bun-based feature('NAME') with dead-code elimination,
this uses simple env-var lookup with optional override config.
Each flag can also carry a description and deprecation notice.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class FlagKind(StrEnum):
    """Kind of flag — controls how the flag value is interpreted."""

    BOOLEAN = "boolean"  # true/false
    STRING = "string"  # any string value
    NUMBER = "number"  # numeric value
    ENUM = "enum"  # one of a fixed set of values


@dataclass
class FeatureFlag:
    """A single feature flag definition."""

    name: str
    kind: FlagKind
    description: str
    default: Any = False
    env_var: str | None = None  # Override env var name (defaults to ATTOCODE_FLAG_<NAME>)
    valid_values: list[str] = field(default_factory=list)  # For ENUM kind
    deprecated: bool = False
    deprecation_message: str = ""


# -----------------------------------------------------------------------------
# Flag definitions
# -----------------------------------------------------------------------------

ALL_FLAGS: dict[str, FeatureFlag] = {}


def _register(flag: FeatureFlag) -> None:
    ALL_FLAGS[flag.name] = flag


_register(FeatureFlag(
    name="TOOL_DEFERRED_SEARCH",
    kind=FlagKind.BOOLEAN,
    description="Mark expensive tools (LSP, semantic search) as deferred. "
                "The model does a ToolSearch roundtrip before calling them.",
    default=False,
))
_register(FeatureFlag(
    name="COORDINATOR_MODE",
    kind=FlagKind.BOOLEAN,
    description="Enable the orchestrator as a first-class coordinator "
                "with explicit phase management and worker synthesis.",
    default=False,
))
_register(FeatureFlag(
    name="CONTEXT_COLLAPSE",
    kind=FlagKind.BOOLEAN,
    description="Collapse redundant tool results that repeat the same information.",
    default=False,
))
_register(FeatureFlag(
    name="REACTIVE_COMPACT",
    kind=FlagKind.BOOLEAN,
    description="Trigger compaction reactively based on model signals "
                "rather than only on threshold.",
    default=False,
))
_register(FeatureFlag(
    name="BG_SESSIONS",
    kind=FlagKind.BOOLEAN,
    description="Enable background task sessions with foreground/background "
                "switching and isolated transcript.",
    default=False,
))
_register(FeatureFlag(
    name="SKILL_IMPROVEMENT",
    kind=FlagKind.BOOLEAN,
    description="Enable skill auto-improvement hooks that detect "
                "and fix underperforming skills.",
    default=False,
))
_register(FeatureFlag(
    name="EXPERIMENTAL_SKILL_SEARCH",
    kind=FlagKind.BOOLEAN,
    description="Use semantic search to find relevant skills dynamically.",
    default=False,
))
_register(FeatureFlag(
    name="CALL_HIERARCHY",
    kind=FlagKind.BOOLEAN,
    description="Enable incoming/outgoing call hierarchy LSP tools.",
    default=True,
))
_register(FeatureFlag(
    name="GITIGNORED_FILTER",
    kind=FlagKind.BOOLEAN,
    description="Filter LSP location results to exclude gitignored paths.",
    default=True,
))
_register(FeatureFlag(
    name="MCP_SSE_TRANSPORT",
    kind=FlagKind.BOOLEAN,
    description="Enable SSE (Server-Sent Events) MCP transport.",
    default=False,
))
_register(FeatureFlag(
    name="MCP_HTTP_TRANSPORT",
    kind=FlagKind.BOOLEAN,
    description="Enable StreamableHTTP MCP transport.",
    default=False,
))
_register(FeatureFlag(
    name="UNC_PATH_BLOCK",
    kind=FlagKind.BOOLEAN,
    description="Block UNC paths (\\\\server, //server) to prevent credential leaks.",
    default=True,
))
_register(FeatureFlag(
    name="LSP_PROTOCOL_TRACE",
    kind=FlagKind.BOOLEAN,
    description="Enable verbose LSP protocol tracing for debugging.",
    default=False,
))
_register(FeatureFlag(
    name="DIVERSE_SERIALIZATION",
    kind=FlagKind.BOOLEAN,
    description="Use diverse serialization formats for context compression.",
    default=False,
))
_register(FeatureFlag(
    name="FRESH_CONTEXT_THRESHOLD",
    kind=FlagKind.NUMBER,
    description="Token fraction (0-1) that triggers fresh context refresh. "
                "Set via ATTOCODE_FLAG_FRESH_CONTEXT_THRESHOLD=0.5.",
    default=0.6,
))
_register(FeatureFlag(
    name="TOOL_RESULT_DISK_CACHE",
    kind=FlagKind.BOOLEAN,
    description="Persist large tool results to disk and reference them "
                "instead of keeping full content in context.",
    default=False,
))
_register(FeatureFlag(
    name="RECITATION_MODE",
    kind=FlagKind.ENUM,
    description="How to inject goal recitation. Options: off, periodic, adaptive.",
    default="periodic",
    valid_values=["off", "periodic", "adaptive"],
))
_register(FeatureFlag(
    name="HOOKS_TRACE",
    kind=FlagKind.BOOLEAN,
    description="Log all hook invocations for debugging.",
    default=False,
))
_register(FeatureFlag(
    name="FORK_SUBAGENTS",
    kind=FlagKind.BOOLEAN,
    description="Allow agents to fork themselves (share prompt cache, "
                "new conversation thread). Requires provider support.",
    default=False,
))


# -----------------------------------------------------------------------------
# Resolver
# -----------------------------------------------------------------------------


class FlagResolver:
    """Resolve feature flag values from environment + overrides.

    Supports three sources (in priority order):
    1. Explicit overrides set via ``set_override``
    2. Environment variables  (ATTOCODE_FLAG_<NAME> or custom env_var)
    3. Default value from the flag definition
    """

    def __init__(self) -> None:
        self._overrides: dict[str, Any] = {}
        self._resolved: dict[str, Any] = {}  # Cache

    def set_override(self, name: str, value: Any) -> None:
        """Force a flag to a specific value (for testing, CLI overrides)."""
        self._overrides[name] = value
        self._resolved.pop(name, None)  # Invalidate cache

    def clear_override(self, name: str) -> None:
        """Remove an override, reverting to env/default resolution."""
        self._overrides.pop(name, None)
        self._resolved.pop(name, None)

    def get(self, name: str) -> Any:
        """Resolve a flag value.

        Returns the override, env-var, or default.
        Raises KeyError if the flag name is unknown.
        """
        if name in self._resolved:
            return self._resolved[name]

        flag = ALL_FLAGS.get(name)
        if flag is None:
            raise KeyError(f"Unknown feature flag: {name}")

        # 1. Override
        if name in self._overrides:
            value = self._resolved[name] = self._coerce(flag, self._overrides[name])
            return value

        # 2. Environment
        env_var = flag.env_var or f"ATTOCODE_FLAG_{_to_env_name(name)}"
        raw = os.environ.get(env_var)
        if raw is not None:
            value = self._resolved[name] = self._coerce(flag, raw)
            return value

        # 3. Default
        self._resolved[name] = flag.default
        return flag.default

    def _coerce(self, flag: FeatureFlag, raw: Any) -> Any:
        """Coerce a raw value to the flag's type."""
        if flag.kind == FlagKind.BOOLEAN:
            if isinstance(raw, bool):
                return raw
            if isinstance(raw, str):
                return raw.lower() in ("1", "true", "yes", "on")
            return bool(raw)
        if flag.kind == FlagKind.NUMBER:
            return float(raw) if flag.name != "FRESH_CONTEXT_THRESHOLD" else float(raw)
        if flag.kind == FlagKind.ENUM:
            if isinstance(raw, str) and raw in flag.valid_values:
                return raw
            return flag.default
        # STRING
        return str(raw)

    def is_enabled(self, name: str) -> bool:
        """Boolean convenience — returns True if the flag is truthy."""
        return bool(self.get(name))

    def is_disabled(self, name: str) -> bool:
        """Boolean convenience — returns True if the flag is falsy."""
        return not self.get(name)

    def get_str(self, name: str, fallback: str = "") -> str:
        """String convenience — returns the flag as a string or fallback."""
        val = self.get(name)
        return str(val) if val is not None else fallback

    def get_num(self, name: str, fallback: float = 0.0) -> float:
        """Numeric convenience — returns the flag as a float or fallback."""
        try:
            return float(self.get(name))
        except (TypeError, ValueError):
            return fallback

    def list_all(self) -> dict[str, dict[str, Any]]:
        """Return all flags with their resolved values and metadata."""
        return {
            name: {
                "value": self.get(name),
                "kind": flag.kind.value,
                "description": flag.description,
                "default": flag.default,
                "deprecated": flag.deprecated,
                "has_override": name in self._overrides,
                "env_var": flag.env_var or f"ATTOCODE_FLAG_{_to_env_name(name)}",
            }
            for name, flag in ALL_FLAGS.items()
        }

    def list_enabled(self) -> list[str]:
        """Return names of all currently-enabled flags."""
        return [name for name in ALL_FLAGS if self.is_enabled(name)]

    def dump_env_template(self) -> str:
        """Generate a shell snippet of all unset flags with their defaults."""
        lines = ["# Attocode feature flags (auto-generated)", ""]
        for name, flag in sorted(ALL_FLAGS.items()):
            env_var = flag.env_var or f"ATTOCODE_FLAG_{_to_env_name(name)}"
            default_str = "true" if flag.default is True else (
                "false" if flag.default is False else str(flag.default)
            )
            lines.append(f"# {flag.description}")
            if flag.kind == FlagKind.BOOLEAN:
                lines.append(f"# export {env_var}=true  # default: {default_str}")
            elif flag.kind == FlagKind.ENUM:
                opts = "|".join(flag.valid_values)
                lines.append(f"# export {env_var}={flag.default}  # options: {opts}")
            else:
                lines.append(f"# export {env_var}={flag.default}")
            lines.append("")
        return "\n".join(lines)


def _to_env_name(name: str) -> str:
    """Convert flag name to env-var format: SomeFlagName → SOME_FLAG_NAME."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).upper()


# -----------------------------------------------------------------------------
# Global instance
# -----------------------------------------------------------------------------

# Create a module-level singleton so integrations can import and use flags
# without instantiating their own resolvers.
registry = FlagResolver()


def feature(name: str) -> bool:
    """Boolean check: is a feature flag enabled?

    Equivalent to CC's feature('NAME') but with env-var override support.
    Example:
        if feature("TOOL_DEFERRED_SEARCH"):
            deferred_tools.append("lsp_definition")
    """
    return registry.is_enabled(name)
