"""Resilient provider wrapper.

Wraps any LLMProvider with retry, timeout, and circuit breaker
for production reliability.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from attocode.errors import ProviderError
from attocode.types.messages import (
    ChatOptions,
    ChatResponse,
    Message,
    MessageWithStructuredContent,
)


@dataclass(slots=True)
class ResilienceConfig:
    """Configuration for resilient provider wrapper."""

    max_retries: int = 3
    retry_base_delay: float = 1.0
    retry_max_delay: float = 30.0
    timeout_seconds: float = 600.0
    circuit_breaker_threshold: int = 5
    circuit_breaker_reset_seconds: float = 60.0


@dataclass(slots=True)
class ResilienceStats:
    """Stats for the resilient provider."""

    total_calls: int = 0
    successful_calls: int = 0
    retried_calls: int = 0
    timed_out_calls: int = 0
    circuit_broken_calls: int = 0
    total_retry_count: int = 0


class SimpleCircuitBreaker:
    """Minimal circuit breaker for provider wrapping."""

    def __init__(self, threshold: int = 5, reset_seconds: float = 60.0) -> None:
        self._threshold = threshold
        self._reset_seconds = reset_seconds
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._state = "closed"  # closed, open, half_open

    @property
    def is_open(self) -> bool:
        if self._state == "open":
            # Check if reset time has elapsed
            if time.monotonic() - self._last_failure_time >= self._reset_seconds:
                self._state = "half_open"
                return False
            return True
        return False

    @property
    def state(self) -> str:
        # Refresh state on access
        if self._state == "open" and not self.is_open:
            return "half_open"
        return self._state

    def record_success(self) -> None:
        self._failure_count = 0
        self._state = "closed"

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self._threshold:
            self._state = "open"

    def reset(self) -> None:
        self._failure_count = 0
        self._state = "closed"
        self._last_failure_time = 0.0


class ResilientProvider:
    """Wraps any LLMProvider with retry, timeout, and circuit breaker.

    Usage:
        provider = ResilientProvider(
            AnthropicProvider(api_key=key),
            config=ResilienceConfig(max_retries=3, timeout_seconds=60),
        )
        response = await provider.chat(messages, options)
    """

    def __init__(
        self,
        inner: Any,
        *,
        config: ResilienceConfig | None = None,
    ) -> None:
        self._inner = inner
        self._config = config or ResilienceConfig()
        self._cb = SimpleCircuitBreaker(
            threshold=self._config.circuit_breaker_threshold,
            reset_seconds=self._config.circuit_breaker_reset_seconds,
        )
        self._stats = ResilienceStats()

    @property
    def name(self) -> str:
        inner_name = getattr(self._inner, "name", "unknown")
        return f"resilient({inner_name})"

    @property
    def stats(self) -> ResilienceStats:
        return self._stats

    @property
    def circuit_breaker_state(self) -> str:
        return self._cb.state

    async def chat(
        self,
        messages: list[Message | MessageWithStructuredContent],
        options: ChatOptions | None = None,
    ) -> ChatResponse:
        """Call the inner provider with retry, timeout, and circuit breaker."""
        self._stats.total_calls += 1

        # Check circuit breaker
        if self._cb.is_open:
            self._stats.circuit_broken_calls += 1
            raise ProviderError(
                f"Circuit breaker open for {self.name}",
                provider=self.name,
                retryable=True,
            )

        last_error: Exception | None = None

        for attempt in range(self._config.max_retries + 1):
            try:
                response = await asyncio.wait_for(
                    self._inner.chat(messages, options),
                    timeout=self._config.timeout_seconds,
                )
                self._cb.record_success()
                self._stats.successful_calls += 1
                return response

            except asyncio.TimeoutError:
                self._stats.timed_out_calls += 1
                self._cb.record_failure()
                last_error = ProviderError(
                    f"Timeout after {self._config.timeout_seconds}s",
                    provider=self.name,
                    retryable=True,
                )

            except ProviderError as e:
                last_error = e
                self._cb.record_failure()

                if not e.retryable or attempt >= self._config.max_retries:
                    raise

            except Exception as e:
                last_error = ProviderError(
                    str(e), provider=self.name, retryable=True,
                )
                self._cb.record_failure()

            # Retry with exponential backoff
            if attempt < self._config.max_retries:
                self._stats.retried_calls += 1
                self._stats.total_retry_count += 1
                delay = min(
                    self._config.retry_base_delay * (2 ** attempt),
                    self._config.retry_max_delay,
                )
                await asyncio.sleep(delay)

        raise last_error or ProviderError(
            "All retries exhausted", provider=self.name, retryable=False,
        )

    async def close(self) -> None:
        """Close the inner provider."""
        if hasattr(self._inner, "close"):
            await self._inner.close()

    def reset_circuit_breaker(self) -> None:
        """Manually reset the circuit breaker."""
        self._cb.reset()
