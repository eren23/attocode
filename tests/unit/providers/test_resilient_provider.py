"""Tests for ResilientProvider and SimpleCircuitBreaker."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from attocode.errors import ProviderError
from attocode.providers.resilient_provider import (
    ResilienceConfig,
    ResilienceStats,
    ResilientProvider,
    SimpleCircuitBreaker,
)
from attocode.types.messages import (
    ChatOptions,
    ChatResponse,
    Message,
    Role,
    StopReason,
    TokenUsage,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_provider(name: str = "mock") -> MagicMock:
    """Create a mock provider with chat() as an AsyncMock."""
    p = MagicMock()
    p.name = name
    p.chat = AsyncMock()
    p.close = AsyncMock()
    return p


def _make_response(content: str = "ok") -> ChatResponse:
    return ChatResponse(
        content=content,
        stop_reason=StopReason.END_TURN,
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        model="test-model",
    )


# ---------------------------------------------------------------------------
# SimpleCircuitBreaker
# ---------------------------------------------------------------------------


class TestSimpleCircuitBreaker:
    def test_initial_state_is_closed(self) -> None:
        cb = SimpleCircuitBreaker(threshold=3)
        assert cb.state == "closed"
        assert cb.is_open is False

    def test_stays_closed_below_threshold(self) -> None:
        cb = SimpleCircuitBreaker(threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "closed"
        assert cb.is_open is False

    def test_opens_at_threshold(self) -> None:
        cb = SimpleCircuitBreaker(threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"
        assert cb.is_open is True

    def test_opens_above_threshold(self) -> None:
        cb = SimpleCircuitBreaker(threshold=2)
        for _ in range(5):
            cb.record_failure()
        assert cb.state == "open"
        assert cb.is_open is True

    def test_success_resets_failure_count(self) -> None:
        cb = SimpleCircuitBreaker(threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.state == "closed"
        # Failures reset, so three more needed
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "closed"

    def test_success_closes_from_half_open(self) -> None:
        cb = SimpleCircuitBreaker(threshold=1, reset_seconds=0.0)
        cb.record_failure()
        # reset_seconds=0 means it immediately transitions to half_open
        # when state is accessed (is_open check triggers transition)
        assert cb.state == "half_open"
        cb.record_success()
        assert cb.state == "closed"

    def test_half_open_after_reset_time(self) -> None:
        cb = SimpleCircuitBreaker(threshold=2, reset_seconds=0.01)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"
        assert cb.is_open is True

        # Wait for reset time to elapse
        time.sleep(0.02)
        assert cb.is_open is False
        assert cb.state == "half_open"

    def test_manual_reset(self) -> None:
        cb = SimpleCircuitBreaker(threshold=1)
        cb.record_failure()
        assert cb.state == "open"
        cb.reset()
        assert cb.state == "closed"
        assert cb.is_open is False


# ---------------------------------------------------------------------------
# ResilientProvider
# ---------------------------------------------------------------------------


class TestResilientProvider:
    def test_name_wraps_inner(self) -> None:
        inner = _make_mock_provider("my_provider")
        rp = ResilientProvider(inner)
        assert rp.name == "resilient(my_provider)"

    @pytest.mark.asyncio
    async def test_successful_call(self) -> None:
        inner = _make_mock_provider()
        inner.chat.return_value = _make_response("hello")
        rp = ResilientProvider(inner, config=ResilienceConfig(max_retries=2))

        messages = [Message(role=Role.USER, content="Hi")]
        result = await rp.chat(messages)

        assert result.content == "hello"
        assert rp.stats.total_calls == 1
        assert rp.stats.successful_calls == 1
        assert rp.stats.retried_calls == 0

    @pytest.mark.asyncio
    async def test_retries_on_retryable_error(self) -> None:
        inner = _make_mock_provider()
        inner.chat.side_effect = [
            ProviderError("rate limit", provider="mock", retryable=True),
            _make_response("success after retry"),
        ]
        config = ResilienceConfig(max_retries=2, retry_base_delay=0.001, retry_max_delay=0.01)
        rp = ResilientProvider(inner, config=config)

        messages = [Message(role=Role.USER, content="Hi")]
        result = await rp.chat(messages)

        assert result.content == "success after retry"
        assert rp.stats.total_calls == 1
        assert rp.stats.successful_calls == 1
        assert rp.stats.retried_calls == 1
        assert rp.stats.total_retry_count == 1

    @pytest.mark.asyncio
    async def test_stops_on_non_retryable_error(self) -> None:
        inner = _make_mock_provider()
        inner.chat.side_effect = ProviderError("auth failed", provider="mock", retryable=False)
        config = ResilienceConfig(max_retries=3, retry_base_delay=0.001)
        rp = ResilientProvider(inner, config=config)

        messages = [Message(role=Role.USER, content="Hi")]
        with pytest.raises(ProviderError, match="auth failed"):
            await rp.chat(messages)

        # Should have called chat only once (no retries for non-retryable)
        assert inner.chat.call_count == 1
        assert rp.stats.retried_calls == 0

    @pytest.mark.asyncio
    async def test_exhausts_all_retries(self) -> None:
        inner = _make_mock_provider()
        inner.chat.side_effect = ProviderError("server error", provider="mock", retryable=True)
        config = ResilienceConfig(max_retries=2, retry_base_delay=0.001, retry_max_delay=0.01)
        rp = ResilientProvider(inner, config=config)

        messages = [Message(role=Role.USER, content="Hi")]
        with pytest.raises(ProviderError, match="server error"):
            await rp.chat(messages)

        # initial attempt + 2 retries = 3 calls
        assert inner.chat.call_count == 3
        assert rp.stats.retried_calls == 2
        assert rp.stats.total_retry_count == 2

    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks_calls(self) -> None:
        inner = _make_mock_provider()
        inner.chat.side_effect = ProviderError("fail", provider="mock", retryable=True)
        config = ResilienceConfig(
            max_retries=0,
            circuit_breaker_threshold=2,
            circuit_breaker_reset_seconds=60.0,
        )
        rp = ResilientProvider(inner, config=config)

        messages = [Message(role=Role.USER, content="Hi")]

        # Trigger failures to open circuit breaker
        for _ in range(2):
            with pytest.raises(ProviderError):
                await rp.chat(messages)

        assert rp.circuit_breaker_state == "open"

        # Next call should be blocked by circuit breaker
        with pytest.raises(ProviderError, match="Circuit breaker open"):
            await rp.chat(messages)

        assert rp.stats.circuit_broken_calls == 1

    @pytest.mark.asyncio
    async def test_timeout_handling(self) -> None:
        inner = _make_mock_provider()

        async def slow_chat(*args, **kwargs):
            await asyncio.sleep(10)
            return _make_response()

        inner.chat.side_effect = slow_chat
        config = ResilienceConfig(
            max_retries=0,
            timeout_seconds=0.01,
        )
        rp = ResilientProvider(inner, config=config)

        messages = [Message(role=Role.USER, content="Hi")]
        with pytest.raises((ProviderError, asyncio.TimeoutError)):
            await rp.chat(messages)

        assert rp.stats.timed_out_calls >= 1

    def test_stats_tracking_initial(self) -> None:
        inner = _make_mock_provider()
        rp = ResilientProvider(inner)
        stats = rp.stats

        assert stats.total_calls == 0
        assert stats.successful_calls == 0
        assert stats.retried_calls == 0
        assert stats.timed_out_calls == 0
        assert stats.circuit_broken_calls == 0
        assert stats.total_retry_count == 0

    @pytest.mark.asyncio
    async def test_stats_after_mixed_calls(self) -> None:
        inner = _make_mock_provider()
        inner.chat.side_effect = [
            _make_response("first"),
            ProviderError("fail", provider="mock", retryable=True),
            _make_response("recovered"),
        ]
        config = ResilienceConfig(max_retries=1, retry_base_delay=0.001)
        rp = ResilientProvider(inner, config=config)

        messages = [Message(role=Role.USER, content="Hi")]

        # First call succeeds
        result1 = await rp.chat(messages)
        assert result1.content == "first"

        # Second call fails then retries and succeeds
        result2 = await rp.chat(messages)
        assert result2.content == "recovered"

        assert rp.stats.total_calls == 2
        assert rp.stats.successful_calls == 2
        assert rp.stats.retried_calls == 1

    @pytest.mark.asyncio
    async def test_reset_circuit_breaker(self) -> None:
        inner = _make_mock_provider()
        inner.chat.side_effect = ProviderError("fail", provider="mock", retryable=True)
        config = ResilienceConfig(
            max_retries=0,
            circuit_breaker_threshold=1,
            circuit_breaker_reset_seconds=60.0,
        )
        rp = ResilientProvider(inner, config=config)

        messages = [Message(role=Role.USER, content="Hi")]
        with pytest.raises(ProviderError):
            await rp.chat(messages)

        assert rp.circuit_breaker_state == "open"

        rp.reset_circuit_breaker()
        assert rp.circuit_breaker_state == "closed"

    @pytest.mark.asyncio
    async def test_close_delegates(self) -> None:
        inner = _make_mock_provider()
        rp = ResilientProvider(inner)
        await rp.close()
        inner.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_generic_exception_is_retried(self) -> None:
        inner = _make_mock_provider()
        inner.chat.side_effect = [
            RuntimeError("unexpected"),
            _make_response("recovered"),
        ]
        config = ResilienceConfig(max_retries=1, retry_base_delay=0.001)
        rp = ResilientProvider(inner, config=config)

        messages = [Message(role=Role.USER, content="Hi")]
        result = await rp.chat(messages)
        assert result.content == "recovered"
        assert rp.stats.retried_calls == 1
