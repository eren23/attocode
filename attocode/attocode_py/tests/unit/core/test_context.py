"""Tests for AgentContext."""

from __future__ import annotations

import pytest

from attocode.agent.context import AgentContext
from attocode.providers.mock import MockProvider
from attocode.tools.registry import ToolRegistry
from attocode.types.agent import AgentConfig
from attocode.types.budget import ExecutionBudget
from attocode.types.events import AgentEvent, EventType
from attocode.types.messages import Message, Role


@pytest.fixture
def ctx() -> AgentContext:
    return AgentContext(
        provider=MockProvider(),
        registry=ToolRegistry(),
    )


class TestAgentContextBasic:
    def test_defaults(self, ctx: AgentContext) -> None:
        assert ctx.iteration == 0
        assert ctx.metrics.total_tokens == 0
        assert not ctx.is_cancelled
        assert ctx.messages == []

    def test_add_message(self, ctx: AgentContext) -> None:
        msg = Message(role=Role.USER, content="hello")
        ctx.add_message(msg)
        assert len(ctx.messages) == 1
        assert ctx.messages[0].content == "hello"

    def test_add_messages(self, ctx: AgentContext) -> None:
        msgs = [
            Message(role=Role.USER, content="a"),
            Message(role=Role.ASSISTANT, content="b"),
        ]
        ctx.add_messages(msgs)
        assert len(ctx.messages) == 2


class TestAgentContextCancellation:
    def test_cancel(self, ctx: AgentContext) -> None:
        assert not ctx.is_cancelled
        ctx.cancel()
        assert ctx.is_cancelled

    def test_cancelled_event_is_shared(self) -> None:
        ctx = AgentContext(provider=MockProvider(), registry=ToolRegistry())
        # Event should be a standard asyncio.Event
        assert not ctx.cancelled.is_set()
        ctx.cancelled.set()
        assert ctx.is_cancelled


class TestAgentContextBudget:
    def test_check_iteration_budget_ok(self) -> None:
        ctx = AgentContext(
            provider=MockProvider(),
            registry=ToolRegistry(),
            budget=ExecutionBudget(max_iterations=10),
        )
        ctx.iteration = 5
        assert ctx.check_iteration_budget()

    def test_check_iteration_budget_exceeded(self) -> None:
        ctx = AgentContext(
            provider=MockProvider(),
            registry=ToolRegistry(),
            budget=ExecutionBudget(max_iterations=10),
        )
        ctx.iteration = 10
        assert not ctx.check_iteration_budget()

    def test_check_token_budget_ok(self) -> None:
        ctx = AgentContext(
            provider=MockProvider(),
            registry=ToolRegistry(),
            budget=ExecutionBudget(max_tokens=1000),
        )
        ctx.metrics.total_tokens = 500
        assert ctx.check_token_budget()

    def test_check_token_budget_exceeded(self) -> None:
        ctx = AgentContext(
            provider=MockProvider(),
            registry=ToolRegistry(),
            budget=ExecutionBudget(max_tokens=1000),
        )
        ctx.metrics.total_tokens = 1000
        assert not ctx.check_token_budget()

    def test_no_iteration_limit(self) -> None:
        ctx = AgentContext(
            provider=MockProvider(),
            registry=ToolRegistry(),
            budget=ExecutionBudget(max_iterations=None),
            config=AgentConfig(max_iterations=0),
        )
        ctx.iteration = 999
        assert ctx.check_iteration_budget()


class TestAgentContextEvents:
    def test_on_event(self, ctx: AgentContext) -> None:
        events: list[AgentEvent] = []
        ctx.on_event(events.append)
        ctx.emit_simple(EventType.START, task="test")
        assert len(events) == 1
        assert events[0].type == EventType.START

    def test_multiple_handlers(self, ctx: AgentContext) -> None:
        events_a: list[AgentEvent] = []
        events_b: list[AgentEvent] = []
        ctx.on_event(events_a.append)
        ctx.on_event(events_b.append)
        ctx.emit_simple(EventType.ITERATION, iteration=1)
        assert len(events_a) == 1
        assert len(events_b) == 1

    def test_handler_error_doesnt_break(self, ctx: AgentContext) -> None:
        def bad_handler(e: AgentEvent) -> None:
            raise RuntimeError("handler crashed")

        events: list[AgentEvent] = []
        ctx.on_event(bad_handler)
        ctx.on_event(events.append)
        ctx.emit_simple(EventType.START)
        # Second handler should still fire
        assert len(events) == 1

    def test_emit_with_kwargs(self, ctx: AgentContext) -> None:
        events: list[AgentEvent] = []
        ctx.on_event(events.append)
        ctx.emit_simple(EventType.TOOL_COMPLETE, tool="read_file", result="content")
        assert events[0].tool == "read_file"
        assert events[0].result == "content"
