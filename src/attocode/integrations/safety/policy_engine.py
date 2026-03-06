"""Policy engine for tool permission resolution.

Evaluates tool calls against configured policies to determine
if they should be allowed, prompted for approval, or blocked.
"""

from __future__ import annotations

import fnmatch
import json
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
    # Codebase exploration — read-only AST / tree views
    PolicyRule(tool_pattern="codebase_overview", decision=PolicyDecision.ALLOW, danger_level=DangerLevel.SAFE),
    PolicyRule(tool_pattern="get_repo_map", decision=PolicyDecision.ALLOW, danger_level=DangerLevel.SAFE),
    PolicyRule(tool_pattern="get_tree_view", decision=PolicyDecision.ALLOW, danger_level=DangerLevel.SAFE),
    PolicyRule(tool_pattern="explore_codebase", decision=PolicyDecision.ALLOW, danger_level=DangerLevel.SAFE),
    # LSP tools — read-only language server queries
    PolicyRule(tool_pattern="lsp_definition", decision=PolicyDecision.ALLOW, danger_level=DangerLevel.SAFE),
    PolicyRule(tool_pattern="lsp_references", decision=PolicyDecision.ALLOW, danger_level=DangerLevel.SAFE),
    PolicyRule(tool_pattern="lsp_hover", decision=PolicyDecision.ALLOW, danger_level=DangerLevel.SAFE),
    PolicyRule(tool_pattern="lsp_diagnostics", decision=PolicyDecision.ALLOW, danger_level=DangerLevel.SAFE),
    # Security scanning — read-only analysis
    PolicyRule(tool_pattern="security_scan", decision=PolicyDecision.ALLOW, danger_level=DangerLevel.SAFE),
    # Semantic search — read-only
    PolicyRule(tool_pattern="semantic_search", decision=PolicyDecision.ALLOW, danger_level=DangerLevel.SAFE),
    # Write operations need awareness
    PolicyRule(tool_pattern="write_file", decision=PolicyDecision.ALLOW, danger_level=DangerLevel.LOW),
    PolicyRule(tool_pattern="edit_file", decision=PolicyDecision.ALLOW, danger_level=DangerLevel.LOW),
    # Bash needs approval
    PolicyRule(tool_pattern="bash", decision=PolicyDecision.PROMPT, danger_level=DangerLevel.MEDIUM),
    # Subagent spawning — budget-controlled and sandboxed
    PolicyRule(tool_pattern="spawn_agent", decision=PolicyDecision.ALLOW, danger_level=DangerLevel.LOW),
]


@dataclass(slots=True)
class PolicyEngine:
    """Evaluates tool calls against policies.

    Supports configurable rules that match tool names and arguments
    to determine the appropriate permission level.
    """

    rules: list[PolicyRule] = field(default_factory=lambda: list(DEFAULT_RULES))
    auto_approve_patterns: list[str] = field(default_factory=list)
    _approved_commands: dict[str, set[str]] = field(default_factory=dict, repr=False)

    @staticmethod
    def _args_signature(tool_name: str, arguments: dict[str, Any] | None = None) -> str:
        """Build a stable signature used for command-pattern grants."""
        arguments = arguments or {}
        if tool_name == "bash":
            return str(arguments.get("command", "")).strip()
        try:
            return json.dumps(arguments, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return str(arguments)

    def _is_granted(self, tool_name: str, arguments: dict[str, Any] | None = None) -> bool:
        patterns = self._approved_commands.get(tool_name)
        if not patterns:
            return False
        sig = self._args_signature(tool_name, arguments)
        return any(p == "*" or fnmatch.fnmatch(sig, p) for p in patterns)

    def evaluate(self, tool_name: str, arguments: dict[str, Any] | None = None) -> PolicyResult:
        """Evaluate a tool call against policies.

        Args:
            tool_name: Name of the tool.
            arguments: Tool arguments.

        Returns:
            PolicyResult with the decision.
        """
        # Check session-approved commands (from "Always Allow")
        if self._is_granted(tool_name, arguments):
            return PolicyResult(
                decision=PolicyDecision.ALLOW,
                danger_level=DangerLevel.SAFE,
                tool_name=tool_name,
            )

        # Bash command-aware safety checks.
        if tool_name == "bash":
            from attocode.integrations.safety.bash_policy import CommandRisk, classify_command

            cmd = str((arguments or {}).get("command", ""))
            classification = classify_command(cmd)
            if classification.risk == CommandRisk.BLOCK:
                return PolicyResult(
                    decision=PolicyDecision.DENY,
                    danger_level=DangerLevel.CRITICAL,
                    reason=classification.reason or "Command blocked by bash policy",
                    tool_name=tool_name,
                )

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
                    reason=(
                        classification.reason
                        if tool_name == "bash" and "classification" in locals()
                        else ""
                    ),
                    tool_name=tool_name,
                )

        # Default: prompt for unknown tools
        return PolicyResult(
            decision=PolicyDecision.PROMPT,
            danger_level=DangerLevel.MEDIUM,
            reason=f"Unknown tool '{tool_name}' requires approval",
            tool_name=tool_name,
        )

    def approve_command(self, command: str, pattern: str = "*") -> None:
        """Mark a command as pre-approved."""
        if command not in self._approved_commands:
            self._approved_commands[command] = set()
        self._approved_commands[command].add(pattern or "*")

    def is_approved(self, command: str, args: dict[str, Any] | None = None) -> bool:
        """Check if a command was previously approved."""
        return self._is_granted(command, args)

    @property
    def approved_commands(self) -> set[str]:
        """Return the set of approved commands (for persistence)."""
        return set(self._approved_commands.keys())

    def load_grants(self, commands: list[str]) -> None:
        """Bulk-load pre-approved commands (e.g. from DB)."""
        for cmd in commands:
            self.approve_command(cmd, "*")

    def approve_all(self) -> None:
        """Set all tools to auto-approve."""
        self.rules = [
            PolicyRule(tool_pattern=".*", decision=PolicyDecision.ALLOW, danger_level=DangerLevel.SAFE)
        ]
