"""Tests for policy engine."""

from __future__ import annotations

from attocode.integrations.safety.policy_engine import (
    DangerLevel,
    PolicyDecision,
    PolicyEngine,
    PolicyResult,
    PolicyRule,
)


class TestPolicyEngine:
    def test_read_file_allowed(self) -> None:
        pe = PolicyEngine()
        result = pe.evaluate("read_file")
        assert result.decision == PolicyDecision.ALLOW
        assert result.danger_level == DangerLevel.SAFE

    def test_glob_allowed(self) -> None:
        pe = PolicyEngine()
        assert pe.evaluate("glob").decision == PolicyDecision.ALLOW

    def test_bash_prompts(self) -> None:
        pe = PolicyEngine()
        result = pe.evaluate("bash")
        assert result.decision == PolicyDecision.PROMPT
        assert result.danger_level == DangerLevel.MEDIUM

    def test_write_file_allowed_low_danger(self) -> None:
        pe = PolicyEngine()
        result = pe.evaluate("write_file")
        assert result.decision == PolicyDecision.ALLOW
        assert result.danger_level == DangerLevel.LOW

    def test_unknown_tool_prompts(self) -> None:
        pe = PolicyEngine()
        result = pe.evaluate("some_new_tool")
        assert result.decision == PolicyDecision.PROMPT

    def test_auto_approve_pattern(self) -> None:
        pe = PolicyEngine(auto_approve_patterns=[".*"])
        result = pe.evaluate("bash")
        assert result.decision == PolicyDecision.ALLOW

    def test_custom_rule(self) -> None:
        pe = PolicyEngine(rules=[
            PolicyRule(tool_pattern="my_tool", decision=PolicyDecision.DENY, danger_level=DangerLevel.CRITICAL),
        ])
        result = pe.evaluate("my_tool")
        assert result.decision == PolicyDecision.DENY

    def test_approve_command(self) -> None:
        pe = PolicyEngine()
        pe.approve_command("npm test")
        assert pe.is_approved("npm test")
        assert not pe.is_approved("npm publish")

    def test_approve_all(self) -> None:
        pe = PolicyEngine()
        pe.approve_all()
        result = pe.evaluate("bash")
        assert result.decision == PolicyDecision.ALLOW
