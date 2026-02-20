"""Tests for resilience layer."""

from __future__ import annotations

import asyncio
import time

import pytest

from attocode.integrations.utilities.resilience import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    CircuitState,
    FallbackChain,
    ProviderScore,
    RateLimitConfig,
    RateLimiter,
    RetryConfig,
    Router,
    RoutingStrategy,
    resilient_fetch,
)


# ============================================================
# Circuit Breaker Tests
# ============================================================


class TestCircuitBreakerClosed:
    def test_allows_calls_when_closed(self) -> None:
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert cb.can_execute()

    def test_success_reduces_failure_count(self) -> None:
        cb = CircuitBreaker()
        cb._failure_count = 3
        cb.record_success()
        assert cb._failure_count == 2

    def test_success_does_not_go_below_zero(self) -> None:
        cb = CircuitBreaker()
        cb.record_success()
        assert cb._failure_count == 0


class TestCircuitBreakerOpenTransition:
    def test_opens_after_threshold_failures(self) -> None:
        cb = CircuitBreaker(config=CircuitBreakerConfig(failure_threshold=3))
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_stays_closed_below_threshold(self) -> None:
        cb = CircuitBreaker(config=CircuitBreakerConfig(failure_threshold=5))
        for _ in range(4):
            cb.record_failure()
        assert cb.state == CircuitState.CLOSED


class TestCircuitBreakerOpen:
    def test_rejects_calls_when_open(self) -> None:
        cb = CircuitBreaker(config=CircuitBreakerConfig(failure_threshold=1))
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert not cb.can_execute()


class TestCircuitBreakerHalfOpen:
    def test_transitions_to_half_open_after_timeout(self) -> None:
        cb = CircuitBreaker(config=CircuitBreakerConfig(
            failure_threshold=1,
            reset_timeout=0.01,
        ))
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.02)
        assert cb.can_execute()
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_to_closed_on_success(self) -> None:
        cb = CircuitBreaker(config=CircuitBreakerConfig(
            failure_threshold=1,
            reset_timeout=0.01,
            success_threshold=1,
        ))
        cb.record_failure()
        time.sleep(0.02)
        cb.can_execute()  # triggers transition to HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 0

    def test_half_open_to_open_on_failure(self) -> None:
        cb = CircuitBreaker(config=CircuitBreakerConfig(
            failure_threshold=1,
            reset_timeout=0.01,
        ))
        cb.record_failure()
        time.sleep(0.02)
        cb.can_execute()  # transitions to HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_half_open_limits_concurrent_calls(self) -> None:
        cb = CircuitBreaker(config=CircuitBreakerConfig(
            failure_threshold=1,
            reset_timeout=0.01,
            half_open_max_calls=1,
        ))
        cb.record_failure()
        time.sleep(0.02)
        cb.can_execute()  # transitions to HALF_OPEN
        cb._half_open_calls = 1
        assert not cb.can_execute()


class TestCircuitBreakerReset:
    def test_reset(self) -> None:
        cb = CircuitBreaker(config=CircuitBreakerConfig(failure_threshold=1))
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 0


class TestCircuitBreakerExecute:
    async def test_execute_success(self) -> None:
        cb = CircuitBreaker()

        async def ok():
            return 42

        result = await cb.execute(ok)
        assert result == 42

    async def test_execute_failure(self) -> None:
        cb = CircuitBreaker()

        async def fail():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await cb.execute(fail)
        assert cb._failure_count == 1

    async def test_execute_when_open_raises(self) -> None:
        cb = CircuitBreaker(config=CircuitBreakerConfig(failure_threshold=1))
        cb.record_failure()

        async def ok():
            return 1

        with pytest.raises(CircuitBreakerOpenError):
            await cb.execute(ok)


# ============================================================
# Rate Limiter Tests
# ============================================================


class TestRateLimiter:
    def test_allows_within_limit(self) -> None:
        rl = RateLimiter(config=RateLimitConfig(max_requests_per_minute=10))
        assert rl.can_proceed()

    def test_blocks_over_limit(self) -> None:
        rl = RateLimiter(config=RateLimitConfig(
            max_requests_per_minute=3,
            max_tokens_per_minute=100_000,
        ))
        for _ in range(3):
            rl.record_request()
        assert not rl.can_proceed()

    def test_blocks_over_token_limit(self) -> None:
        rl = RateLimiter(config=RateLimitConfig(
            max_requests_per_minute=100,
            max_tokens_per_minute=100,
        ))
        rl.record_request(tokens=100)
        assert not rl.can_proceed()

    def test_records_request(self) -> None:
        rl = RateLimiter()
        rl.record_request(tokens=50)
        assert len(rl._request_times) == 1
        assert len(rl._token_usage) == 1

    def test_no_tokens_not_tracked(self) -> None:
        rl = RateLimiter()
        rl.record_request(tokens=0)
        assert len(rl._request_times) == 1
        assert len(rl._token_usage) == 0


# ============================================================
# Resilient Fetch Tests
# ============================================================


class TestResilientFetch:
    async def test_successful_call(self) -> None:
        call_count = 0

        async def ok():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await resilient_fetch(ok, retry_config=RetryConfig(max_retries=0))
        assert result == "success"
        assert call_count == 1

    async def test_retry_on_failure(self) -> None:
        call_count = 0

        async def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("fail")
            return "ok"

        result = await resilient_fetch(
            fail_then_succeed,
            retry_config=RetryConfig(
                max_retries=3,
                initial_delay=0.01,
                jitter=False,
            ),
        )
        assert result == "ok"
        assert call_count == 3

    async def test_exhausted_retries_raises(self) -> None:
        async def always_fail():
            raise ConnectionError("fail")

        with pytest.raises(ConnectionError, match="fail"):
            await resilient_fetch(
                always_fail,
                retry_config=RetryConfig(max_retries=1, initial_delay=0.01, jitter=False),
            )

    async def test_with_circuit_breaker(self) -> None:
        cb = CircuitBreaker()

        async def ok():
            return 42

        result = await resilient_fetch(ok, circuit_breaker=cb, retry_config=RetryConfig(max_retries=0))
        assert result == 42

    async def test_circuit_breaker_open_raises(self) -> None:
        cb = CircuitBreaker(config=CircuitBreakerConfig(failure_threshold=1))
        cb.record_failure()

        async def ok():
            return 42

        with pytest.raises(CircuitBreakerOpenError):
            await resilient_fetch(ok, circuit_breaker=cb, retry_config=RetryConfig(max_retries=0))

    async def test_timeout(self) -> None:
        async def slow():
            await asyncio.sleep(10)
            return "late"

        with pytest.raises(asyncio.TimeoutError):
            await resilient_fetch(
                slow,
                timeout=0.05,
                retry_config=RetryConfig(max_retries=0),
            )


# ============================================================
# Fallback Chain Tests
# ============================================================


class _MockProvider:
    def __init__(self, name: str, fail: bool = False) -> None:
        self.name = name
        self._fail = fail

    async def chat(self, prompt: str) -> str:
        if self._fail:
            raise RuntimeError(f"{self.name} failed")
        return f"{self.name}: {prompt}"


class TestFallbackChain:
    async def test_tries_first_provider(self) -> None:
        chain = FallbackChain()
        chain.add_provider(_MockProvider("p1"))
        chain.add_provider(_MockProvider("p2"))
        result = await chain.execute("chat", "hello")
        assert result == "p1: hello"

    async def test_falls_back_on_failure(self) -> None:
        chain = FallbackChain()
        chain.add_provider(_MockProvider("p1", fail=True))
        chain.add_provider(_MockProvider("p2"))
        result = await chain.execute("chat", "hello")
        assert result == "p2: hello"

    async def test_all_fail_raises(self) -> None:
        chain = FallbackChain()
        chain.add_provider(_MockProvider("p1", fail=True))
        chain.add_provider(_MockProvider("p2", fail=True))
        with pytest.raises(RuntimeError, match="All providers failed"):
            await chain.execute("chat", "hello")

    async def test_skips_open_circuit_breaker(self) -> None:
        chain = FallbackChain()
        chain.add_provider(
            _MockProvider("p1"),
            breaker_config=CircuitBreakerConfig(failure_threshold=1),
        )
        chain.add_provider(_MockProvider("p2"))

        # Open p1's circuit breaker
        chain.circuit_breakers["p1"].record_failure()
        assert chain.circuit_breakers["p1"].state == CircuitState.OPEN

        result = await chain.execute("chat", "hello")
        assert result == "p2: hello"


# ============================================================
# Router Tests
# ============================================================


class _ScoredProvider:
    def __init__(self, name: str) -> None:
        self.name = name


class TestRouter:
    def test_no_providers_raises(self) -> None:
        router = Router()
        with pytest.raises(RuntimeError, match="No providers"):
            router.select_provider()

    def test_single_provider(self) -> None:
        router = Router()
        p = _ScoredProvider("only")
        router.add_provider(p)
        assert router.select_provider() is p

    def test_cost_strategy(self) -> None:
        router = Router(strategy=RoutingStrategy.COST)
        cheap = _ScoredProvider("cheap")
        expensive = _ScoredProvider("expensive")
        router.add_provider(cheap, cost_score=0.9)
        router.add_provider(expensive, cost_score=0.3)
        assert router.select_provider() is cheap

    def test_quality_strategy(self) -> None:
        router = Router(strategy=RoutingStrategy.QUALITY)
        good = _ScoredProvider("good")
        bad = _ScoredProvider("bad")
        router.add_provider(bad, quality_score=0.2)
        router.add_provider(good, quality_score=0.9)
        assert router.select_provider() is good

    def test_latency_strategy(self) -> None:
        router = Router(strategy=RoutingStrategy.LATENCY)
        fast = _ScoredProvider("fast")
        slow = _ScoredProvider("slow")
        router.add_provider(slow, latency_score=0.3)
        router.add_provider(fast, latency_score=0.9)
        assert router.select_provider() is fast

    def test_balanced_strategy(self) -> None:
        router = Router(strategy=RoutingStrategy.BALANCED)
        good_overall = _ScoredProvider("good_overall")
        mediocre = _ScoredProvider("mediocre")
        router.add_provider(
            good_overall, cost_score=0.8, quality_score=0.8, latency_score=0.8,
        )
        router.add_provider(
            mediocre, cost_score=0.3, quality_score=0.3, latency_score=0.3,
        )
        assert router.select_provider() is good_overall

    def test_update_score(self) -> None:
        router = Router()
        p = _ScoredProvider("p1")
        router.add_provider(p, cost_score=0.5)
        router.update_score("p1", cost_score=0.9)
        assert router._scores["p1"].cost_score == 0.9

    def test_update_score_nonexistent(self) -> None:
        router = Router()
        # Should not raise
        router.update_score("nonexistent", cost_score=0.9)


class TestProviderScore:
    def test_balanced_score(self) -> None:
        score = ProviderScore(
            provider=None,
            cost_score=0.6,
            quality_score=0.9,
            latency_score=0.3,
        )
        expected = (0.6 + 0.9 + 0.3) / 3
        assert abs(score.balanced_score - expected) < 0.001
