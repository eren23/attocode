"""Tests for response handler."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from attocode.agent.context import AgentContext
from attocode.core.response_handler import call_llm
from attocode.errors import LLMError, ProviderError
from attocode.providers.mock import MockProvider
from attocode.tools.registry import ToolRegistry
from attocode.types.events import AgentEvent, EventType
from attocode.types.messages import (
    ChatResponse,
    Message,
    Role,
    StopReason,
    TokenUsage,
)


@pytest.fixture
def ctx() -> AgentContext:
    provider = MockProvider()
    provider.add_response(
        content="Hello!",
        usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15, cost=0.001),
    )
    ctx = AgentContext(provider=provider, registry=ToolRegistry())
    ctx.add_message(Message(role=Role.USER, content="Hi"))
    return ctx


class TestCallLLM:
    @pytest.mark.asyncio
    async def test_basic_call(self, ctx: AgentContext) -> None:
        response = await call_llm(ctx)
        assert response.content == "Hello!"
        assert ctx.metrics.llm_calls == 1
        assert ctx.metrics.total_tokens == 15

    @pytest.mark.asyncio
    async def test_events_emitted(self, ctx: AgentContext) -> None:
        events: list[AgentEvent] = []
        ctx.on_event(events.append)
        await call_llm(ctx)
        types = [e.type for e in events]
        assert EventType.LLM_START in types
        assert EventType.LLM_COMPLETE in types

    @pytest.mark.asyncio
    async def test_metrics_accumulated(self) -> None:
        provider = MockProvider()
        provider.add_response(
            content="first",
            usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15, cost=0.001),
        )
        provider.add_response(
            content="second",
            usage=TokenUsage(input_tokens=20, output_tokens=10, total_tokens=30, cost=0.002),
        )
        ctx = AgentContext(provider=provider, registry=ToolRegistry())
        ctx.add_message(Message(role=Role.USER, content="Hi"))

        await call_llm(ctx)
        await call_llm(ctx)

        assert ctx.metrics.llm_calls == 2
        assert ctx.metrics.total_tokens == 45
        assert abs(ctx.metrics.estimated_cost - 0.003) < 1e-9

    @pytest.mark.asyncio
    async def test_cancelled_raises(self) -> None:
        ctx = AgentContext(provider=MockProvider(), registry=ToolRegistry())
        ctx.add_message(Message(role=Role.USER, content="Hi"))
        ctx.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call_llm(ctx)


class TestCallLLMRetry:
    @pytest.mark.asyncio
    async def test_retries_on_retryable_error(self) -> None:
        provider = MockProvider()
        call_count = 0

        async def failing_then_success(msgs, opts):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise ProviderError(
                    "rate limit",
                    provider="mock",
                    status_code=429,
                    retryable=True,
                )
            return ChatResponse(
                content="success",
                stop_reason=StopReason.END_TURN,
                usage=TokenUsage(input_tokens=5, output_tokens=5, total_tokens=10),
            )

        provider.response_fn = failing_then_success
        ctx = AgentContext(provider=provider, registry=ToolRegistry())
        ctx.add_message(Message(role=Role.USER, content="Hi"))

        response = await call_llm(ctx, max_retries=3, retry_base_delay=0.01)
        assert response.content == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_non_retryable(self) -> None:
        provider = MockProvider()

        async def auth_error(msgs, opts):
            raise ProviderError(
                "auth failed",
                provider="mock",
                status_code=401,
                retryable=False,
            )

        provider.response_fn = auth_error
        ctx = AgentContext(provider=provider, registry=ToolRegistry())
        ctx.add_message(Message(role=Role.USER, content="Hi"))

        with pytest.raises(ProviderError) as exc_info:
            await call_llm(ctx, max_retries=3, retry_base_delay=0.01)
        assert not exc_info.value.retryable

    @pytest.mark.asyncio
    async def test_exhausted_retries(self) -> None:
        provider = MockProvider()

        async def always_fail(msgs, opts):
            raise ProviderError(
                "server error",
                provider="mock",
                status_code=500,
                retryable=True,
            )

        provider.response_fn = always_fail
        ctx = AgentContext(provider=provider, registry=ToolRegistry())
        ctx.add_message(Message(role=Role.USER, content="Hi"))

        with pytest.raises(ProviderError):
            await call_llm(ctx, max_retries=2, retry_base_delay=0.01)

    @pytest.mark.asyncio
    async def test_unexpected_error_wrapped(self) -> None:
        provider = MockProvider()

        async def unexpected(msgs, opts):
            raise ValueError("something weird")

        provider.response_fn = unexpected
        ctx = AgentContext(provider=provider, registry=ToolRegistry())
        ctx.add_message(Message(role=Role.USER, content="Hi"))

        with pytest.raises(LLMError, match="Unexpected"):
            await call_llm(ctx)

    @pytest.mark.asyncio
    async def test_error_events_emitted(self) -> None:
        provider = MockProvider()

        async def fail_once(msgs, opts):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ProviderError("error", provider="mock", status_code=500, retryable=True)
            return ChatResponse(
                content="ok",
                stop_reason=StopReason.END_TURN,
                usage=TokenUsage(input_tokens=5, output_tokens=5, total_tokens=10),
            )

        call_count = 0
        provider.response_fn = fail_once
        ctx = AgentContext(provider=provider, registry=ToolRegistry())
        ctx.add_message(Message(role=Role.USER, content="Hi"))

        events: list[AgentEvent] = []
        ctx.on_event(events.append)

        await call_llm(ctx, max_retries=2, retry_base_delay=0.01)

        types = [e.type for e in events]
        assert EventType.LLM_ERROR in types
        assert EventType.LLM_COMPLETE in types
