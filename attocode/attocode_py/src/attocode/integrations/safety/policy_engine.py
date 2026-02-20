"""Policy engine for tool permission resolution.

Evaluates tool calls against configured policies to determine
if they should be allowed, prompted for approval, or blocked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class PolicyDecision(StrEnum):
    """The result of a policy evaluation."""

    ALLOW = "allow"
    PROMPT = "prompt"
    DENY = "deny"


class DangerLevel(StrEnum):
    """Danger level of an operation."""

    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(slots=True)
class PolicyResult:
    """Result of policy evaluation."""

    decision: PolicyDecision
    danger_level: DangerLevel = DangerLevel.SAFE
    reason: str = ""
    tool_name: str = ""


@dataclass(slots=True)
class PolicyRule:
    """A single policy rule."""

    tool_pattern: str
    decision: PolicyDecision
    danger_level: DangerLevel = DangerLevel.SAFE
    condition: str = ""


# Default policy rules
DEFAULT_RULES: list[PolicyRule] = [
    # Read-only tools are always safe
    PolicyRule(tool_pattern="read_file", decision=PolicyDecision.ALLOW, danger_level=DangerLevel.SAFE),
    PolicyRule(tool_pattern="glob", decision=PolicyDecision.ALLOW, danger_level=DangerLevel.SAFE),
    PolicyRule(tool_pattern="grep", decision=PolicyDecision.ALLOW, danger_level=DangerLevel.SAFE),
    PolicyRule(tool_pattern="list_files", decision=PolicyDecision.ALLOW, danger_level=DangerLevel.SAFE),
    # Write operations need awareness
    PolicyRule(tool_pattern="write_file", decision=PolicyDecision.ALLOW, danger_level=DangerLevel.LOW),
    PolicyRule(tool_pattern="edit_file", decision=PolicyDecision.ALLOW, danger_level=DangerLevel.LOW),
    # Bash needs approval
    PolicyRule(tool_pattern="bash", decision=PolicyDecision.PROMPT, danger_level=DangerLevel.MEDIUM),
]


@dataclass
class PolicyEngine:
    """Evaluates tool calls against policies.

    Supports configurable rules that match tool names and arguments
    to determine the appropriate permission level.
    """

    rules: list[PolicyRule] = field(default_factory=lambda: list(DEFAULT_RULES))
    auto_approve_patterns: list[str] = field(default_factory=list)
    _approved_commands: set[str] = field(default_factory=set, repr=False)

    def evaluate(self, tool_name: str, arguments: dict[str, Any] | None = None) -> PolicyResult:
        """Evaluate a tool call against policies.

        Args:
            tool_name: Name of the tool.
            arguments: Tool arguments.

        Returns:
            PolicyResult with the decision.
        """
        # Check auto-approve patterns first
        for pattern in self.auto_approve_patterns:
            if re.match(pattern, tool_name):
                return PolicyResult(
                    decision=PolicyDecision.ALLOW,
                    danger_level=DangerLevel.SAFE,
                    tool_name=tool_name,
                )

        # Check rules
        for rule in self.rules:
            if re.match(rule.tool_pattern, tool_name):
                return PolicyResult(
                    decision=rule.decision,
                    danger_level=rule.danger_level,
                    tool_name=tool_name,
                )

        # Default: prompt for unknown tools
        return PolicyResult(
            decision=PolicyDecision.PROMPT,
            danger_level=DangerLevel.MEDIUM,
            reason=f"Unknown tool '{tool_name}' requires approval",
            tool_name=tool_name,
        )

    def approve_command(self, command: str) -> None:
        """Mark a command as pre-approved."""
        self._approved_commands.add(command)

    def is_approved(self, command: str) -> bool:
        """Check if a command was previously approved."""
        return command in self._approved_commands

    def approve_all(self) -> None:
        """Set all tools to auto-approve."""
        self.rules = [
            PolicyRule(tool_pattern=".*", decision=PolicyDecision.ALLOW, danger_level=DangerLevel.SAFE)
        ]
