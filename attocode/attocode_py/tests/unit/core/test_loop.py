"""Tests for the execution loop."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from attocode.agent.context import AgentContext
from attocode.core.loop import LoopResult, loop_result_to_agent_result, run_execution_loop
from attocode.providers.mock import MockProvider
from attocode.tools.base import Tool, ToolSpec
from attocode.tools.registry import ToolRegistry
from attocode.types.agent import CompletionReason
from attocode.types.budget import ExecutionBudget
from attocode.types.events import AgentEvent, EventType
from attocode.types.messages import (
    Message,
    Role,
    StopReason,
    TokenUsage,
    ToolCall,
)


def _make_ctx(
    provider: MockProvider | None = None,
    registry: ToolRegistry | None = None,
    max_iterations: int = 100,
    max_tokens: int = 1_000_000,
) -> AgentContext:
    p = provider or MockProvider()
    r = registry or ToolRegistry()
    ctx = AgentContext(
        provider=p,
        registry=r,
        budget=ExecutionBudget(
            max_iterations=max_iterations,
            max_tokens=max_tokens,
        ),
    )
    # Add initial messages
    ctx.add_message(Message(role=Role.SYSTEM, content="You are helpful."))
    ctx.add_message(Message(role=Role.USER, content="Do something."))
    return ctx


class TestExecutionLoopBasic:
    @pytest.mark.asyncio
    async def test_simple_completion(self) -> None:
        provider = MockProvider()
        provider.add_response(
            content="Done!",
            usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )
        ctx = _make_ctx(provider)
        result = await run_execution_loop(ctx)
        assert result.success
        assert result.reason == CompletionReason.COMPLETED
        assert result.response == "Done!"
        assert ctx.iteration == 1

    @pytest.mark.asyncio
    async def test_tool_call_then_complete(self) -> None:
        async def echo(args: dict[str, Any]) -> str:
            return f"echoed: {args.get('msg', '')}"

        reg = ToolRegistry()
        reg.register(Tool(
            spec=ToolSpec(name="echo", description="echo", parameters={}),
            execute=echo,
        ))

        provider = MockProvider()
        # First: tool call
        provider.add_response(
            content="Let me echo that.",
            tool_calls=[ToolCall(id="tc_1", name="echo", arguments={"msg": "hello"})],
            stop_reason=StopReason.TOOL_USE,
            usage=TokenUsage(input_tokens=10, output_tokens=10, total_tokens=20),
        )
        # Second: final response
        provider.add_response(
            content="The echo said: hello",
            usage=TokenUsage(input_tokens=20, output_tokens=10, total_tokens=30),
        )

        ctx = _make_ctx(provider, reg)
        result = await run_execution_loop(ctx)

        assert result.success
        assert "hello" in result.response
        assert ctx.iteration == 2
        assert ctx.metrics.tool_calls == 1

    @pytest.mark.asyncio
    async def test_multiple_tool_iterations(self) -> None:
        async def noop(args: dict[str, Any]) -> str:
            return "ok"

        reg = ToolRegistry()
        reg.register(Tool(
            spec=ToolSpec(name="step", description="step", parameters={}),
            execute=noop,
        ))

        provider = MockProvider()
        usage = TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15)
        # 3 tool calls then final
        for i in range(3):
            provider.add_response(
                content=f"Step {i+1}",
                tool_calls=[ToolCall(id=f"tc_{i}", name="step", arguments={})],
                stop_reason=StopReason.TOOL_USE,
                usage=usage,
            )
        provider.add_response(content="All done", usage=usage)

        ctx = _make_ctx(provider, reg)
        result = await run_execution_loop(ctx)

        assert result.success
        assert result.response == "All done"
        assert ctx.iteration == 4
        assert ctx.metrics.tool_calls == 3


class TestExecutionLoopBudget:
    @pytest.mark.asyncio
    async def test_iteration_limit(self) -> None:
        provider = MockProvider()
        # Always returns tool calls so loop never naturally stops
        for _ in range(10):
            provider.add_response(
                content="more work",
                tool_calls=[ToolCall(id="tc", name="noop", arguments={})],
                stop_reason=StopReason.TOOL_USE,
                usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
            )

        async def noop(args: dict[str, Any]) -> str:
            return "ok"

        reg = ToolRegistry()
        reg.register(Tool(
            spec=ToolSpec(name="noop", description="noop", parameters={}),
            execute=noop,
        ))

        ctx = _make_ctx(provider, reg, max_iterations=3)
        result = await run_execution_loop(ctx)

        assert not result.success
        assert result.reason == CompletionReason.MAX_ITERATIONS

    @pytest.mark.asyncio
    async def test_token_budget_limit(self) -> None:
        provider = MockProvider()
        # Each call uses lots of tokens
        for _ in range(10):
            provider.add_response(
                content="more work",
                tool_calls=[ToolCall(id="tc", name="noop", arguments={})],
                stop_reason=StopReason.TOOL_USE,
                usage=TokenUsage(input_tokens=500, output_tokens=500, total_tokens=1000),
            )

        async def noop(args: dict[str, Any]) -> str:
            return "ok"

        reg = ToolRegistry()
        reg.register(Tool(
            spec=ToolSpec(name="noop", description="noop", parameters={}),
            execute=noop,
        ))

        ctx = _make_ctx(provider, reg, max_tokens=2000)
        result = await run_execution_loop(ctx)

        assert not result.success
        assert result.reason == CompletionReason.BUDGET_LIMIT


class TestExecutionLoopCancellation:
    @pytest.mark.asyncio
    async def test_cancel_before_start(self) -> None:
        provider = MockProvider()
        provider.add_response(content="should not see this")
        ctx = _make_ctx(provider)
        ctx.cancel()

        result = await run_execution_loop(ctx)
        assert not result.success
        assert result.reason == CompletionReason.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_during_execution(self) -> None:
        async def cancel_tool(args: dict[str, Any]) -> str:
            # Cancel the context when this tool runs
            ctx.cancel()
            return "cancelled"

        reg = ToolRegistry()
        reg.register(Tool(
            spec=ToolSpec(name="cancel_me", description="cancels", parameters={}),
            execute=cancel_tool,
        ))

        provider = MockProvider()
        provider.add_response(
            content="calling tool",
            tool_calls=[ToolCall(id="tc_1", name="cancel_me", arguments={})],
            stop_reason=StopReason.TOOL_USE,
            usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )
        provider.add_response(
            content="should not reach here",
            usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )

        ctx = _make_ctx(provider, reg)
        result = await run_execution_loop(ctx)

        assert not result.success
        assert result.reason == CompletionReason.CANCELLED


class TestExecutionLoopErrors:
    @pytest.mark.asyncio
    async def test_llm_error(self) -> None:
        provider = MockProvider()

        async def always_fail(msgs, opts):
            raise RuntimeError("LLM is down")

        provider.response_fn = always_fail
        ctx = _make_ctx(provider)
        result = await run_execution_loop(ctx)

        assert not result.success
        assert result.reason == CompletionReason.ERROR
        assert "LLM" in result.message or "error" in result.message.lower()


class TestExecutionLoopEvents:
    @pytest.mark.asyncio
    async def test_events_emitted(self) -> None:
        provider = MockProvider()
        provider.add_response(
            content="Done",
            usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )

        ctx = _make_ctx(provider)
        events: list[AgentEvent] = []
        ctx.on_event(events.append)

        await run_execution_loop(ctx)

        types = [e.type for e in events]
        assert EventType.START in types
        assert EventType.ITERATION in types
        assert EventType.LLM_START in types
        assert EventType.LLM_COMPLETE in types
        assert EventType.COMPLETE in types


class TestLoopResultToAgentResult:
    def test_success(self) -> None:
        ctx = _make_ctx()
        lr = LoopResult(success=True, response="Done", reason=CompletionReason.COMPLETED)
        ar = loop_result_to_agent_result(lr, ctx)
        assert ar.success
        assert ar.response == "Done"
        assert ar.completion.reason == CompletionReason.COMPLETED
        assert ar.error is None

    def test_failure(self) -> None:
        ctx = _make_ctx()
        lr = LoopResult(
            success=False,
            response="partial",
            reason=CompletionReason.BUDGET_LIMIT,
            message="out of tokens",
        )
        ar = loop_result_to_agent_result(lr, ctx)
        assert not ar.success
        assert ar.error == "out of tokens"
        assert ar.completion.reason == CompletionReason.BUDGET_LIMIT
