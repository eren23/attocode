"""Tests for tool executor."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from attocode.agent.context import AgentContext
from attocode.core.tool_executor import (
    build_tool_result_messages,
    execute_tool_calls,
)
from attocode.providers.mock import MockProvider
from attocode.tools.base import Tool, ToolSpec
from attocode.tools.registry import ToolRegistry
from attocode.types.events import AgentEvent, EventType
from attocode.types.messages import Role, ToolCall, ToolResult


def _make_registry(*tools: tuple[str, Any]) -> ToolRegistry:
    reg = ToolRegistry()
    for name, fn in tools:
        reg.register(Tool(
            spec=ToolSpec(name=name, description=name, parameters={}),
            execute=fn,
        ))
    return reg


@pytest.fixture
def ctx() -> AgentContext:
    async def echo(args: dict[str, Any]) -> str:
        return f"echo: {args.get('msg', '')}"

    async def fail(args: dict[str, Any]) -> str:
        raise RuntimeError("tool failed")

    reg = _make_registry(("echo", echo), ("fail", fail))
    return AgentContext(provider=MockProvider(), registry=reg)


class TestExecuteToolCalls:
    @pytest.mark.asyncio
    async def test_single_tool_call(self, ctx: AgentContext) -> None:
        tc = ToolCall(id="tc_1", name="echo", arguments={"msg": "hello"})
        results = await execute_tool_calls(ctx, [tc])
        assert len(results) == 1
        assert results[0].call_id == "tc_1"
        assert not results[0].is_error
        assert "hello" in results[0].result

    @pytest.mark.asyncio
    async def test_multiple_tool_calls(self, ctx: AgentContext) -> None:
        calls = [
            ToolCall(id="tc_1", name="echo", arguments={"msg": "a"}),
            ToolCall(id="tc_2", name="echo", arguments={"msg": "b"}),
        ]
        results = await execute_tool_calls(ctx, calls)
        assert len(results) == 2
        assert all(not r.is_error for r in results)

    @pytest.mark.asyncio
    async def test_tool_error_isolated(self, ctx: AgentContext) -> None:
        calls = [
            ToolCall(id="tc_1", name="echo", arguments={"msg": "ok"}),
            ToolCall(id="tc_2", name="fail", arguments={}),
        ]
        results = await execute_tool_calls(ctx, calls)
        assert len(results) == 2
        assert not results[0].is_error
        assert results[1].is_error
        assert "RuntimeError" in results[1].error

    @pytest.mark.asyncio
    async def test_empty_tool_calls(self, ctx: AgentContext) -> None:
        results = await execute_tool_calls(ctx, [])
        assert results == []

    @pytest.mark.asyncio
    async def test_metrics_updated(self, ctx: AgentContext) -> None:
        assert ctx.metrics.tool_calls == 0
        tc = ToolCall(id="tc_1", name="echo", arguments={})
        await execute_tool_calls(ctx, [tc])
        assert ctx.metrics.tool_calls == 1

    @pytest.mark.asyncio
    async def test_events_emitted(self, ctx: AgentContext) -> None:
        events: list[AgentEvent] = []
        ctx.on_event(events.append)

        tc = ToolCall(id="tc_1", name="echo", arguments={"msg": "hi"})
        await execute_tool_calls(ctx, [tc])

        types = [e.type for e in events]
        assert EventType.TOOL_START in types
        assert EventType.TOOL_COMPLETE in types

    @pytest.mark.asyncio
    async def test_error_events_emitted(self, ctx: AgentContext) -> None:
        events: list[AgentEvent] = []
        ctx.on_event(events.append)

        tc = ToolCall(id="tc_1", name="fail", arguments={})
        await execute_tool_calls(ctx, [tc])

        types = [e.type for e in events]
        assert EventType.TOOL_START in types
        assert EventType.TOOL_ERROR in types

    @pytest.mark.asyncio
    async def test_unknown_tool(self, ctx: AgentContext) -> None:
        tc = ToolCall(id="tc_1", name="nonexistent", arguments={})
        results = await execute_tool_calls(ctx, [tc])
        assert len(results) == 1
        assert results[0].is_error

    @pytest.mark.asyncio
    async def test_parallel_execution(self) -> None:
        """Verify tools run concurrently."""
        order: list[str] = []

        async def slow_a(args: dict[str, Any]) -> str:
            order.append("a_start")
            await asyncio.sleep(0.05)
            order.append("a_end")
            return "a"

        async def slow_b(args: dict[str, Any]) -> str:
            order.append("b_start")
            await asyncio.sleep(0.05)
            order.append("b_end")
            return "b"

        reg = _make_registry(("a", slow_a), ("b", slow_b))
        ctx = AgentContext(provider=MockProvider(), registry=reg)

        calls = [
            ToolCall(id="1", name="a", arguments={}),
            ToolCall(id="2", name="b", arguments={}),
        ]
        await execute_tool_calls(ctx, calls)

        # Both should start before either finishes
        assert order.index("a_start") < order.index("a_end")
        assert order.index("b_start") < order.index("b_end")


class TestBuildToolResultMessages:
    def test_success_messages(self) -> None:
        calls = [
            ToolCall(id="tc_1", name="echo", arguments={}),
            ToolCall(id="tc_2", name="echo", arguments={}),
        ]
        results = [
            ToolResult(call_id="tc_1", result="result1"),
            ToolResult(call_id="tc_2", result="result2"),
        ]
        msgs = build_tool_result_messages(calls, results)
        assert len(msgs) == 2
        assert all(m.role == Role.TOOL for m in msgs)
        assert msgs[0].content == "result1"
        assert msgs[0].tool_call_id == "tc_1"

    def test_error_messages(self) -> None:
        calls = [ToolCall(id="tc_1", name="fail", arguments={})]
        results = [ToolResult(call_id="tc_1", error="boom")]
        msgs = build_tool_result_messages(calls, results)
        assert msgs[0].content == "boom"
        assert msgs[0].role == Role.TOOL
