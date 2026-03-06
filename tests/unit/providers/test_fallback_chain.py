"""Tests for ProviderFallbackChain."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from attocode.errors import ConfigurationError, ProviderError
from attocode.providers.fallback_chain import (
    FallbackStats,
    ProviderFallbackChain,
)
from attocode.providers.resilient_provider import SimpleCircuitBreaker
from attocode.types.messages import (
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
    """Create a mock provider with name and async chat."""
    p = MagicMock()
    p.name = name
    p.chat = AsyncMock()
    p.close = AsyncMock()
    return p


def _make_response(content: str = "ok", model: str = "test") -> ChatResponse:
    return ChatResponse(
        content=content,
        stop_reason=StopReason.END_TURN,
        usage=TokenUsage(input_tokens=5, output_tokens=3),
        model=model,
    )


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


class TestFallbackChainInit:
    def test_requires_at_least_one_provider(self) -> None:
        with pytest.raises(ConfigurationError, match="At least one provider"):
            ProviderFallbackChain(providers=[])

    def test_name_shows_chain(self) -> None:
        p1 = _make_mock_provider("primary")
        p2 = _make_mock_provider("secondary")
        chain = ProviderFallbackChain(providers=[p1, p2])
        assert chain.name == "fallback(primary > secondary)"

    def test_initial_stats(self) -> None:
        p1 = _make_mock_provider("p")
        chain = ProviderFallbackChain(providers=[p1])
        stats = chain.stats
        assert stats.total_calls == 0
        assert stats.primary_successes == 0
        assert stats.fallback_successes == 0
        assert stats.total_failures == 0


# ---------------------------------------------------------------------------
# Primary success
# ---------------------------------------------------------------------------


class TestPrimarySuccess:
    @pytest.mark.asyncio
    async def test_primary_provider_succeeds(self) -> None:
        p1 = _make_mock_provider("primary")
        p2 = _make_mock_provider("secondary")
        p1.chat.return_value = _make_response("primary response")
        chain = ProviderFallbackChain(providers=[p1, p2])

        messages = [Message(role=Role.USER, content="Hi")]
        result = await chain.chat(messages)

        assert result.content == "primary response"
        assert chain.stats.total_calls == 1
        assert chain.stats.primary_successes == 1
        assert chain.stats.fallback_successes == 0
        p2.chat.assert_not_called()


# ---------------------------------------------------------------------------
# Fallback behavior
# ---------------------------------------------------------------------------


class TestFallback:
    @pytest.mark.asyncio
    async def test_falls_back_on_primary_failure(self) -> None:
        p1 = _make_mock_provider("primary")
        p2 = _make_mock_provider("secondary")
        p1.chat.side_effect = ProviderError("primary down", provider="primary")
        p2.chat.return_value = _make_response("fallback response")
        chain = ProviderFallbackChain(providers=[p1, p2])

        messages = [Message(role=Role.USER, content="Hi")]
        result = await chain.chat(messages)

        assert result.content == "fallback response"
        assert chain.stats.primary_successes == 0
        assert chain.stats.fallback_successes == 1

    @pytest.mark.asyncio
    async def test_falls_back_through_multiple_providers(self) -> None:
        p1 = _make_mock_provider("first")
        p2 = _make_mock_provider("second")
        p3 = _make_mock_provider("third")
        p1.chat.side_effect = ProviderError("p1 down", provider="first")
        p2.chat.side_effect = ProviderError("p2 down", provider="second")
        p3.chat.return_value = _make_response("third provider")
        chain = ProviderFallbackChain(providers=[p1, p2, p3])

        messages = [Message(role=Role.USER, content="Hi")]
        result = await chain.chat(messages)

        assert result.content == "third provider"
        assert chain.stats.fallback_successes == 1

    @pytest.mark.asyncio
    async def test_all_providers_fail_raises(self) -> None:
        p1 = _make_mock_provider("first")
        p2 = _make_mock_provider("second")
        p1.chat.side_effect = ProviderError("p1 fail", provider="first")
        p2.chat.side_effect = ProviderError("p2 fail", provider="second")
        chain = ProviderFallbackChain(providers=[p1, p2])

        messages = [Message(role=Role.USER, content="Hi")]
        with pytest.raises(ProviderError, match="All providers failed"):
            await chain.chat(messages)

        assert chain.stats.total_failures == 1
        assert chain.stats.total_calls == 1

    @pytest.mark.asyncio
    async def test_all_fail_error_includes_details(self) -> None:
        p1 = _make_mock_provider("alpha")
        p2 = _make_mock_provider("beta")
        p1.chat.side_effect = ProviderError("alpha error", provider="alpha")
        p2.chat.side_effect = ProviderError("beta error", provider="beta")
        chain = ProviderFallbackChain(providers=[p1, p2])

        messages = [Message(role=Role.USER, content="Hi")]
        with pytest.raises(ProviderError) as exc_info:
            await chain.chat(messages)

        error_msg = str(exc_info.value)
        assert "alpha" in error_msg
        assert "beta" in error_msg


# ---------------------------------------------------------------------------
# Stats tracking
# ---------------------------------------------------------------------------


class TestStatsTracking:
    @pytest.mark.asyncio
    async def test_attempts_recorded(self) -> None:
        p1 = _make_mock_provider("primary")
        p2 = _make_mock_provider("secondary")
        p1.chat.side_effect = ProviderError("fail", provider="primary")
        p2.chat.return_value = _make_response("ok")
        chain = ProviderFallbackChain(providers=[p1, p2])

        messages = [Message(role=Role.USER, content="Hi")]
        await chain.chat(messages)

        assert len(chain.stats.attempts) == 2
        assert chain.stats.attempts[0].provider_name == "primary"
        assert chain.stats.attempts[0].success is False
        assert chain.stats.attempts[0].error is not None
        assert chain.stats.attempts[1].provider_name == "secondary"
        assert chain.stats.attempts[1].success is True

    def test_fallback_rate_zero_initially(self) -> None:
        p1 = _make_mock_provider("p")
        chain = ProviderFallbackChain(providers=[p1])
        assert chain.stats.fallback_rate == 0.0

    @pytest.mark.asyncio
    async def test_fallback_rate_calculated(self) -> None:
        p1 = _make_mock_provider("primary")
        p2 = _make_mock_provider("secondary")
        p1.chat.side_effect = ProviderError("fail", provider="primary")
        p2.chat.return_value = _make_response("ok")
        chain = ProviderFallbackChain(providers=[p1, p2])

        messages = [Message(role=Role.USER, content="Hi")]
        await chain.chat(messages)
        await chain.chat(messages)

        # 2 total calls, 2 fallback successes
        assert chain.stats.fallback_rate == 1.0


# ---------------------------------------------------------------------------
# Circuit breaker integration
# ---------------------------------------------------------------------------


class TestCircuitBreakerIntegration:
    @pytest.mark.asyncio
    async def test_skips_provider_with_open_circuit_breaker(self) -> None:
        p1 = _make_mock_provider("primary")
        p2 = _make_mock_provider("secondary")
        p2.chat.return_value = _make_response("from secondary")

        cb = SimpleCircuitBreaker(threshold=1, reset_seconds=60.0)
        cb.record_failure()  # Opens the circuit breaker
        assert cb.is_open is True

        chain = ProviderFallbackChain(
            providers=[p1, p2],
            circuit_breakers={"primary": cb},
        )

        messages = [Message(role=Role.USER, content="Hi")]
        result = await chain.chat(messages)

        assert result.content == "from secondary"
        p1.chat.assert_not_called()  # Skipped due to circuit breaker

    @pytest.mark.asyncio
    async def test_records_success_in_circuit_breaker(self) -> None:
        p1 = _make_mock_provider("primary")
        p1.chat.return_value = _make_response("ok")

        cb = SimpleCircuitBreaker(threshold=5)
        cb.record_failure()  # 1 failure, still closed
        assert cb.state == "closed"

        chain = ProviderFallbackChain(
            providers=[p1],
            circuit_breakers={"primary": cb},
        )

        messages = [Message(role=Role.USER, content="Hi")]
        await chain.chat(messages)

        # Success should have reset the failure count
        assert cb.state == "closed"

    @pytest.mark.asyncio
    async def test_records_failure_in_circuit_breaker(self) -> None:
        p1 = _make_mock_provider("primary")
        p2 = _make_mock_provider("secondary")
        p1.chat.side_effect = ProviderError("down", provider="primary")
        p2.chat.return_value = _make_response("ok")

        cb = SimpleCircuitBreaker(threshold=3)

        chain = ProviderFallbackChain(
            providers=[p1, p2],
            circuit_breakers={"primary": cb},
        )

        messages = [Message(role=Role.USER, content="Hi")]
        await chain.chat(messages)

        # p1 should have recorded a failure
        # We can't directly check _failure_count but we can observe behavior
        # After 2 more failures it should open
        await chain.chat(messages)
        await chain.chat(messages)
        assert cb.is_open is True


# ---------------------------------------------------------------------------
# get_healthy_providers
# ---------------------------------------------------------------------------


class TestGetHealthyProviders:
    def test_all_healthy_when_no_breakers(self) -> None:
        p1 = _make_mock_provider("alpha")
        p2 = _make_mock_provider("beta")
        chain = ProviderFallbackChain(providers=[p1, p2])

        healthy = chain.get_healthy_providers()
        assert healthy == ["alpha", "beta"]

    def test_excludes_open_breaker(self) -> None:
        p1 = _make_mock_provider("alpha")
        p2 = _make_mock_provider("beta")

        cb_alpha = SimpleCircuitBreaker(threshold=1, reset_seconds=60.0)
        cb_alpha.record_failure()

        chain = ProviderFallbackChain(
            providers=[p1, p2],
            circuit_breakers={"alpha": cb_alpha},
        )

        healthy = chain.get_healthy_providers()
        assert healthy == ["beta"]

    def test_all_unhealthy(self) -> None:
        p1 = _make_mock_provider("alpha")
        p2 = _make_mock_provider("beta")

        cb_a = SimpleCircuitBreaker(threshold=1, reset_seconds=60.0)
        cb_a.record_failure()
        cb_b = SimpleCircuitBreaker(threshold=1, reset_seconds=60.0)
        cb_b.record_failure()

        chain = ProviderFallbackChain(
            providers=[p1, p2],
            circuit_breakers={"alpha": cb_a, "beta": cb_b},
        )

        healthy = chain.get_healthy_providers()
        assert healthy == []


# ---------------------------------------------------------------------------
# on_fallback callback
# ---------------------------------------------------------------------------


class TestOnFallbackCallback:
    @pytest.mark.asyncio
    async def test_callback_called_on_fallback(self) -> None:
        p1 = _make_mock_provider("primary")
        p2 = _make_mock_provider("secondary")
        p1.chat.side_effect = ProviderError("p1 down", provider="primary")
        p2.chat.return_value = _make_response("ok")

        callback = MagicMock()
        chain = ProviderFallbackChain(
            providers=[p1, p2],
            on_fallback=callback,
        )

        messages = [Message(role=Role.USER, content="Hi")]
        await chain.chat(messages)

        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == "primary"
        assert "p1 down" in args[1]

    @pytest.mark.asyncio
    async def test_callback_not_called_on_primary_success(self) -> None:
        p1 = _make_mock_provider("primary")
        p2 = _make_mock_provider("secondary")
        p1.chat.return_value = _make_response("ok")

        callback = MagicMock()
        chain = ProviderFallbackChain(
            providers=[p1, p2],
            on_fallback=callback,
        )

        messages = [Message(role=Role.USER, content="Hi")]
        await chain.chat(messages)

        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_callback_not_called_on_last_provider(self) -> None:
        p1 = _make_mock_provider("only")
        p1.chat.side_effect = ProviderError("fail", provider="only")

        callback = MagicMock()
        chain = ProviderFallbackChain(
            providers=[p1],
            on_fallback=callback,
        )

        messages = [Message(role=Role.USER, content="Hi")]
        with pytest.raises(ProviderError):
            await chain.chat(messages)

        # Callback should NOT be called for the last provider failure
        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_callback_exception_is_swallowed(self) -> None:
        p1 = _make_mock_provider("primary")
        p2 = _make_mock_provider("secondary")
        p1.chat.side_effect = ProviderError("fail", provider="primary")
        p2.chat.return_value = _make_response("ok")

        def bad_callback(name, error):
            raise RuntimeError("callback error")

        chain = ProviderFallbackChain(
            providers=[p1, p2],
            on_fallback=bad_callback,
        )

        messages = [Message(role=Role.USER, content="Hi")]
        # Should not raise even though callback raises
        result = await chain.chat(messages)
        assert result.content == "ok"


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


class TestClose:
    @pytest.mark.asyncio
    async def test_close_all_providers(self) -> None:
        p1 = _make_mock_provider("alpha")
        p2 = _make_mock_provider("beta")
        chain = ProviderFallbackChain(providers=[p1, p2])

        await chain.close()

        p1.close.assert_awaited_once()
        p2.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_swallows_errors(self) -> None:
        p1 = _make_mock_provider("alpha")
        p2 = _make_mock_provider("beta")
        p1.close.side_effect = RuntimeError("close failed")
        chain = ProviderFallbackChain(providers=[p1, p2])

        # Should not raise
        await chain.close()
        p2.close.assert_awaited_once()
