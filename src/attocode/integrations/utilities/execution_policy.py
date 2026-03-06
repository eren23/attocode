"""Execution policy manager.

Intent-aware access control for tool execution with support for
deliberate, accidental, and inferred intent classification.
Conditional policies based on argument patterns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class IntentType(StrEnum):
    """Classification of why a tool call was made."""

    DELIBERATE = "deliberate"  # Explicitly requested by user
    ACCIDENTAL = "accidental"  # Likely unintended (hallucination, wrong args)
    INFERRED = "inferred"  # Inferred from context (agent decided)


class PolicyAction(StrEnum):
    """Action to take when a policy matches."""

    ALLOW = "allow"
    DENY = "deny"
    WARN = "warn"  # Allow but warn
    ASK = "ask"  # Require user confirmation


@dataclass(slots=True)
class PolicyCondition:
    """A condition for matching a policy rule."""

    field: str  # 'tool_name', 'argument', 'argument_pattern', 'intent'
    operator: str  # 'equals', 'contains', 'matches', 'in'
    value: str | list[str]

    def matches(self, tool_name: str, arguments: dict[str, Any], intent: IntentType) -> bool:
        """Check if this condition matches the given context."""
        if self.field == "tool_name":
            return self._match_value(tool_name)
        if self.field == "intent":
            return self._match_value(intent.value)
        if self.field == "argument":
            # Check if any argument value matches
            for arg_val in arguments.values():
                if self._match_value(str(arg_val)):
                    return True
            return False
        if self.field == "argument_pattern":
            # Regex match against all argument values
            for arg_val in arguments.values():
                try:
                    if re.search(str(self.value), str(arg_val)):
                        return True
                except re.error:
                    pass
            return False
        return False

    def _match_value(self, actual: str) -> bool:
        if self.operator == "equals":
            return actual == str(self.value)
        if self.operator == "contains":
            return str(self.value) in actual
        if self.operator == "matches":
            try:
                return bool(re.search(str(self.value), actual))
            except re.error:
                return False
        if self.operator == "in":
            if isinstance(self.value, list):
                return actual in self.value
            return actual in str(self.value).split(",")
        return False


@dataclass(slots=True)
class PolicyRule:
    """An execution policy rule."""

    name: str
    action: PolicyAction
    conditions: list[PolicyCondition]
    priority: int = 0  # Higher = evaluated first
    reason: str = ""

    def matches(self, tool_name: str, arguments: dict[str, Any], intent: IntentType) -> bool:
        """Check if all conditions match."""
        return all(c.matches(tool_name, arguments, intent) for c in self.conditions)


@dataclass(slots=True)
class PolicyDecision:
    """Result of evaluating a tool call against policies."""

    action: PolicyAction
    rule_name: str = ""
    reason: str = ""


class ExecutionPolicyManager:
    """Manages execution policies for tool access control.

    Provides intent-aware access control with conditional policies
    based on tool name, argument patterns, and inferred intent.
    """

    def __init__(self) -> None:
        self._rules: list[PolicyRule] = []
        self._default_action = PolicyAction.ALLOW

    @property
    def default_action(self) -> PolicyAction:
        return self._default_action

    def set_default_action(self, action: PolicyAction | str) -> None:
        """Set the default action when no rules match."""
        if isinstance(action, str):
            action = PolicyAction(action)
        self._default_action = action

    def add_rule(self, rule: PolicyRule) -> None:
        """Add an execution policy rule."""
        self._rules.append(rule)
        self._rules.sort(key=lambda r: -r.priority)

    def remove_rule(self, name: str) -> bool:
        """Remove a rule by name."""
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.name != name]
        return len(self._rules) < before

    def evaluate(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        intent: IntentType = IntentType.INFERRED,
    ) -> PolicyDecision:
        """Evaluate a tool call against all policies.

        Args:
            tool_name: Name of the tool being called.
            arguments: Arguments being passed to the tool.
            intent: The classified intent of the call.

        Returns:
            PolicyDecision with the action to take.
        """
        for rule in self._rules:
            if rule.matches(tool_name, arguments, intent):
                return PolicyDecision(
                    action=rule.action,
                    rule_name=rule.name,
                    reason=rule.reason or f"Matched rule: {rule.name}",
                )

        return PolicyDecision(
            action=self._default_action,
            reason="No matching rule, using default action",
        )

    def classify_intent(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        user_requested: bool = False,
        confidence: float = 0.5,
    ) -> IntentType:
        """Classify the intent of a tool call.

        Args:
            tool_name: Name of the tool.
            arguments: Arguments being passed.
            user_requested: Whether user explicitly requested this tool.
            confidence: LLM confidence in the call (0.0-1.0).

        Returns:
            Classified IntentType.
        """
        if user_requested:
            return IntentType.DELIBERATE
        if confidence < 0.3:
            return IntentType.ACCIDENTAL
        return IntentType.INFERRED

    def list_rules(self) -> list[PolicyRule]:
        """List all rules sorted by priority."""
        return list(self._rules)

    def clear(self) -> None:
        """Clear all rules."""
        self._rules.clear()

    def add_default_rules(self) -> None:
        """Add sensible default rules."""
        # Block dangerous patterns
        self.add_rule(PolicyRule(
            name="block_rm_rf_root",
            action=PolicyAction.DENY,
            priority=100,
            conditions=[
                PolicyCondition("tool_name", "equals", "bash"),
                PolicyCondition("argument_pattern", "matches", r"rm\s+-rf\s+/"),
            ],
            reason="Blocked: rm -rf on root path",
        ))

        # Warn on sudo
        self.add_rule(PolicyRule(
            name="warn_sudo",
            action=PolicyAction.WARN,
            priority=50,
            conditions=[
                PolicyCondition("tool_name", "equals", "bash"),
                PolicyCondition("argument", "contains", "sudo"),
            ],
            reason="Warning: sudo command detected",
        ))

        # Ask for git push
        self.add_rule(PolicyRule(
            name="ask_git_push",
            action=PolicyAction.ASK,
            priority=40,
            conditions=[
                PolicyCondition("tool_name", "equals", "bash"),
                PolicyCondition("argument_pattern", "matches", r"git\s+push"),
            ],
            reason="Git push requires confirmation",
        ))

        # Block accidental file deletions
        self.add_rule(PolicyRule(
            name="block_accidental_deletes",
            action=PolicyAction.DENY,
            priority=80,
            conditions=[
                PolicyCondition("intent", "equals", "accidental"),
                PolicyCondition("tool_name", "in", ["bash", "write_file"]),
            ],
            reason="Blocked accidental destructive operation",
        ))
