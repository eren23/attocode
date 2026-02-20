"""Tests for context engineering manager."""

from __future__ import annotations

from attocode.integrations.context.context_engineering import (
    ContextEngineeringManager,
    FailureRecord,
)
from attocode.types.messages import Message, Role


class TestContextEngineeringGoals:
    def test_set_goals(self) -> None:
        cem = ContextEngineeringManager()
        cem.set_goals(["Build API", "Write tests"])
        assert len(cem.goals) == 2

    def test_add_goal(self) -> None:
        cem = ContextEngineeringManager()
        cem.add_goal("Build API")
        cem.add_goal("Write tests")
        assert len(cem.goals) == 2


class TestRecitation:
    def test_no_recitation_without_goals(self) -> None:
        cem = ContextEngineeringManager()
        msgs = [Message(role=Role.USER, content="hi")]
        result = cem.inject_recitation(msgs, current_iteration=10)
        assert len(result) == len(msgs)

    def test_recitation_injected(self) -> None:
        cem = ContextEngineeringManager()
        cem.set_goals(["Build API"])
        cem._recitation_interval = 1  # inject every iteration
        msgs = [Message(role=Role.USER, content="continue")]
        result = cem.inject_recitation(msgs, current_iteration=5)
        assert len(result) > len(msgs)
        contents = " ".join(m.content for m in result)
        assert "Build API" in contents

    def test_recitation_respects_interval(self) -> None:
        cem = ContextEngineeringManager()
        cem.set_goals(["Goal"])
        cem._recitation_interval = 5
        msgs = [Message(role=Role.USER, content="hi")]
        # First call at iteration 0 should inject
        result1 = cem.inject_recitation(msgs, current_iteration=0)
        # Second call at iteration 2 should NOT inject (within interval)
        result2 = cem.inject_recitation(msgs, current_iteration=2)
        assert len(result2) == len(msgs)


class TestFailureEvidence:
    def test_record_failure(self) -> None:
        cem = ContextEngineeringManager()
        cem.record_failure("bash", "command not found", 1)
        assert cem.failure_count == 1

    def test_get_failure_context(self) -> None:
        cem = ContextEngineeringManager()
        cem.record_failure("bash", "permission denied", 1)
        ctx = cem.get_failure_context()
        assert ctx is not None
        assert "permission denied" in ctx

    def test_no_failures_returns_none(self) -> None:
        cem = ContextEngineeringManager()
        assert cem.get_failure_context() is None

    def test_inject_failure_context(self) -> None:
        cem = ContextEngineeringManager()
        cem.record_failure("bash", "timeout", 1)
        msgs = [Message(role=Role.USER, content="try again")]
        result = cem.inject_failure_context(msgs)
        assert len(result) > len(msgs)

    def test_recent_failures_limited(self) -> None:
        cem = ContextEngineeringManager()
        for i in range(10):
            cem.record_failure("tool", f"error {i}", i)
        assert len(cem.recent_failures) == 5


class TestReset:
    def test_reset(self) -> None:
        cem = ContextEngineeringManager()
        cem.set_goals(["Goal"])
        cem.record_failure("tool", "error", 1)
        cem.reset()
        assert len(cem.goals) == 0
        assert cem.failure_count == 0
