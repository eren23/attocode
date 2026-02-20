"""Resilience layer for network operations.

Provides:
- Circuit breaker with half-open recovery
- Resilient fetch with retry, timeout, and rate limiting
- Provider fallback chain
- Routing strategies (cost/quality/latency/balanced)
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, TypeVar

T = TypeVar("T")


# ============================================================
# Circuit Breaker
# ============================================================

class CircuitState(StrEnum):
    """Circuit breaker state."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, rejecting calls
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass(slots=True)
class CircuitBreakerConfig:
    """Configuration for a circuit breaker."""

    failure_threshold: int = 5  # Failures before opening
    reset_timeout: float = 30.0  # Seconds before trying half-open
    half_open_max_calls: int = 1  # Max calls in half-open state
    success_threshold: int = 2  # Successes to close from half-open


@dataclass
class CircuitBreaker:
    """Circuit breaker pattern for fault tolerance.

    States: CLOSED → OPEN → HALF_OPEN → CLOSED
    """

    config: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    state: CircuitState = CircuitState.CLOSED
    _failure_count: int = field(default=0, repr=False)
    _success_count: int = field(default=0, repr=False)
    _last_failure_time: float = field(default=0.0, repr=False)
    _half_open_calls: int = field(default=0, repr=False)

    def can_execute(self) -> bool:
        """Check if a call is allowed."""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            # Check if reset timeout has elapsed
            if time.monotonic() - self._last_failure_time >= self.config.reset_timeout:
                self.state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                self._success_count = 0
                return True
            return False

        if self.state == CircuitState.HALF_OPEN:
            return self._half_open_calls < self.config.half_open_max_calls

        return False

    def record_success(self) -> None:
        """Record a successful call."""
        if self.state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.config.success_threshold:
                self.state = CircuitState.CLOSED
                self._failure_count = 0
                self._success_count = 0
        elif self.state == CircuitState.CLOSED:
            self._failure_count = max(0, self._failure_count - 1)

    def record_failure(self) -> None:
        """Record a failed call."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()

        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
        elif self.state == CircuitState.CLOSED:
            if self._failure_count >= self.config.failure_threshold:
                self.state = CircuitState.OPEN

    def reset(self) -> None:
        """Reset the circuit breaker to closed state."""
        self.state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0

    async def execute(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute a function with circuit breaker protection.

        Args:
            func: Async function to execute.
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            Function result.

        Raises:
            CircuitBreakerOpenError: If circuit is open.
        """
        if not self.can_execute():
            raise CircuitBreakerOpenError(
                f"Circuit breaker is {self.state.value}. "
                f"Retry after {self.config.reset_timeout}s"
            )

        if self.state == CircuitState.HALF_OPEN:
            self._half_open_calls += 1

        try:
            result = await func(*args, **kwargs)
            self.record_success()
            return result
        except Exception:
            self.record_failure()
            raise


class CircuitBreakerOpenError(Exception):
    """Raised when a circuit breaker is open."""


# ============================================================
# Resilient Fetch
# ============================================================

@dataclass(slots=True)
class RetryConfig:
    """Configuration for retry behavior."""

    max_retries: int = 3
    initial_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0
    jitter: bool = True
    retryable_status_codes: frozenset[int] = frozenset({429, 500, 502, 503, 504})


@dataclass(slots=True)
class RateLimitConfig:
    """Rate limiting configuration."""

    max_requests_per_minute: int = 60
    max_tokens_per_minute: int = 100_000


@dataclass
class RateLimiter:
    """Token bucket rate limiter."""

    config: RateLimitConfig = field(default_factory=RateLimitConfig)
    _request_times: deque[float] = field(
        default_factory=lambda: deque(maxlen=1000), repr=False
    )
    _token_usage: deque[tuple[float, int]] = field(
        default_factory=lambda: deque(maxlen=1000), repr=False
    )

    def can_proceed(self) -> bool:
        """Check if a request can proceed without exceeding rate limits."""
        now = time.monotonic()
        cutoff = now - 60.0

        # Check request rate
        recent_requests = sum(1 for t in self._request_times if t > cutoff)
        if recent_requests >= self.config.max_requests_per_minute:
            return False

        # Check token rate
        recent_tokens = sum(
            tokens for t, tokens in self._token_usage if t > cutoff
        )
        if recent_tokens >= self.config.max_tokens_per_minute:
            return False

        return True

    def record_request(self, tokens: int = 0) -> None:
        """Record a request and its token usage."""
        now = time.monotonic()
        self._request_times.append(now)
        if tokens > 0:
            self._token_usage.append((now, tokens))

    async def wait_if_needed(self) -> None:
        """Wait if rate limit would be exceeded."""
        while not self.can_proceed():
            await asyncio.sleep(0.5)


async def resilient_fetch(
    func: Callable[..., Any],
    *args: Any,
    retry_config: RetryConfig | None = None,
    rate_limiter: RateLimiter | None = None,
    circuit_breaker: CircuitBreaker | None = None,
    timeout: float = 30.0,
    **kwargs: Any,
) -> Any:
    """Execute an async function with retry, rate limiting, and circuit breaker.

    Args:
        func: Async function to execute.
        *args: Positional arguments for func.
        retry_config: Retry configuration.
        rate_limiter: Rate limiter instance.
        circuit_breaker: Circuit breaker instance.
        timeout: Overall timeout in seconds.
        **kwargs: Keyword arguments for func.

    Returns:
        Function result.

    Raises:
        Exception: Last error after all retries exhausted.
    """
    config = retry_config or RetryConfig()
    last_error: Exception | None = None

    for attempt in range(config.max_retries + 1):
        # Rate limiting
        if rate_limiter:
            await rate_limiter.wait_if_needed()

        # Circuit breaker
        if circuit_breaker and not circuit_breaker.can_execute():
            raise CircuitBreakerOpenError("Circuit breaker is open")

        try:
            result = await asyncio.wait_for(
                func(*args, **kwargs),
                timeout=timeout,
            )

            # Record success
            if circuit_breaker:
                circuit_breaker.record_success()
            if rate_limiter:
                rate_limiter.record_request()

            return result

        except asyncio.TimeoutError:
            last_error = asyncio.TimeoutError(f"Timeout after {timeout}s")
            if circuit_breaker:
                circuit_breaker.record_failure()
        except Exception as e:
            last_error = e
            if circuit_breaker:
                circuit_breaker.record_failure()

        # Calculate retry delay
        if attempt < config.max_retries:
            delay = min(
                config.initial_delay * (config.exponential_base ** attempt),
                config.max_delay,
            )
            if config.jitter:
                import random
                delay *= 0.5 + random.random()

            await asyncio.sleep(delay)

    if last_error:
        raise last_error
    raise RuntimeError("Resilient fetch failed with no error recorded")


# ============================================================
# Provider Fallback Chain
# ============================================================

@dataclass
class FallbackChain:
    """Provider fallback chain for resilience.

    Tries providers in order, falling back to the next on failure.
    Each provider has its own circuit breaker.
    """

    providers: list[Any] = field(default_factory=list)
    circuit_breakers: dict[str, CircuitBreaker] = field(default_factory=dict)

    def add_provider(
        self,
        provider: Any,
        breaker_config: CircuitBreakerConfig | None = None,
    ) -> None:
        """Add a provider to the chain."""
        self.providers.append(provider)
        name = getattr(provider, "name", str(len(self.providers)))
        self.circuit_breakers[name] = CircuitBreaker(
            config=breaker_config or CircuitBreakerConfig()
        )

    async def execute(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """Execute a method across the provider chain.

        Tries each provider in order, falling back on failure.

        Args:
            method: Method name to call on providers.
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            Result from the first successful provider.

        Raises:
            RuntimeError: All providers failed.
        """
        errors: list[str] = []

        for provider in self.providers:
            name = getattr(provider, "name", "unknown")
            breaker = self.circuit_breakers.get(name)

            if breaker and not breaker.can_execute():
                errors.append(f"{name}: circuit breaker open")
                continue

            try:
                func = getattr(provider, method)
                result = await func(*args, **kwargs)
                if breaker:
                    breaker.record_success()
                return result
            except Exception as e:
                if breaker:
                    breaker.record_failure()
                errors.append(f"{name}: {e}")

        raise RuntimeError(
            f"All providers failed:\n" + "\n".join(f"  - {e}" for e in errors)
        )


# ============================================================
# Routing Strategies
# ============================================================

class RoutingStrategy(StrEnum):
    """Strategy for selecting a provider."""

    COST = "cost"
    QUALITY = "quality"
    LATENCY = "latency"
    BALANCED = "balanced"
    RULES = "rules"


@dataclass(slots=True)
class ProviderScore:
    """Score for a provider based on routing criteria."""

    provider: Any
    cost_score: float = 0.5
    quality_score: float = 0.5
    latency_score: float = 0.5

    @property
    def balanced_score(self) -> float:
        return (self.cost_score + self.quality_score + self.latency_score) / 3


@dataclass
class Router:
    """Routes requests to providers based on strategy.

    Selects the best provider based on the configured strategy,
    with fallback support.
    """

    strategy: RoutingStrategy = RoutingStrategy.BALANCED
    providers: list[Any] = field(default_factory=list)
    _scores: dict[str, ProviderScore] = field(default_factory=dict, repr=False)

    def add_provider(
        self,
        provider: Any,
        cost_score: float = 0.5,
        quality_score: float = 0.5,
        latency_score: float = 0.5,
    ) -> None:
        """Add a provider with scoring metadata."""
        self.providers.append(provider)
        name = getattr(provider, "name", str(len(self.providers)))
        self._scores[name] = ProviderScore(
            provider=provider,
            cost_score=cost_score,
            quality_score=quality_score,
            latency_score=latency_score,
        )

    def select_provider(self) -> Any:
        """Select the best provider based on the current strategy.

        Returns:
            The selected provider.

        Raises:
            RuntimeError: No providers available.
        """
        if not self.providers:
            raise RuntimeError("No providers available")

        if len(self.providers) == 1:
            return self.providers[0]

        scores = list(self._scores.values())

        if self.strategy == RoutingStrategy.COST:
            scores.sort(key=lambda s: s.cost_score, reverse=True)
        elif self.strategy == RoutingStrategy.QUALITY:
            scores.sort(key=lambda s: s.quality_score, reverse=True)
        elif self.strategy == RoutingStrategy.LATENCY:
            scores.sort(key=lambda s: s.latency_score, reverse=True)
        else:  # balanced
            scores.sort(key=lambda s: s.balanced_score, reverse=True)

        return scores[0].provider

    def update_score(
        self,
        provider_name: str,
        *,
        cost_score: float | None = None,
        quality_score: float | None = None,
        latency_score: float | None = None,
    ) -> None:
        """Update scoring for a provider based on observed performance."""
        score = self._scores.get(provider_name)
        if score:
            if cost_score is not None:
                score.cost_score = cost_score
            if quality_score is not None:
                score.quality_score = quality_score
            if latency_score is not None:
                score.latency_score = latency_score
