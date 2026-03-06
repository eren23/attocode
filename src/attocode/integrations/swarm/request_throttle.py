"""Request throttle for rate limiting swarm workers.

Token bucket + minimum spacing + FIFO queue to prevent 429 rate limiting
across all swarm workers. Wraps LLM providers to throttle downstream calls.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from attocode.providers.base import LLMProvider


@dataclass(slots=True)
class ThrottleConfig:
    """Rate limiting configuration."""

    max_concurrent: int = 5
    refill_rate_per_second: float = 2.0
    min_spacing_ms: float = 200.0
    max_backoff_level: int = 3


# Preset configs
FREE_TIER_THROTTLE = ThrottleConfig(
    max_concurrent=2,
    refill_rate_per_second=0.5,
    min_spacing_ms=1500.0,
)

PAID_TIER_THROTTLE = ThrottleConfig(
    max_concurrent=5,
    refill_rate_per_second=2.0,
    min_spacing_ms=200.0,
)


@dataclass(slots=True)
class ThrottleStats:
    """Observable throttle statistics."""

    pending_count: int = 0
    available_tokens: int = 0
    total_acquired: int = 0
    backoff_level: int = 0
    current_max_concurrent: int = 0
    current_min_spacing_ms: float = 0.0


class SwarmThrottle:
    """Token bucket rate limiter with FIFO queue and adaptive backoff.

    Features:
    - Token bucket with configurable refill rate
    - Minimum spacing between requests
    - FIFO ordering for fairness
    - Adaptive backoff on 429 errors
    - Automatic recovery after sustained success
    """

    def __init__(self, config: ThrottleConfig | None = None) -> None:
        self._config = config or ThrottleConfig()
        self._semaphore = asyncio.Semaphore(self._config.max_concurrent)
        self._last_request_time = 0.0
        self._lock = asyncio.Lock()
        self._total_acquired = 0
        self._pending = 0

        # Adaptive state
        self._backoff_level = 0
        self._current_max_concurrent = self._config.max_concurrent
        self._current_min_spacing_ms = self._config.min_spacing_ms
        self._current_refill_rate = self._config.refill_rate_per_second
        self._last_backoff_time = 0.0
        self._success_since_backoff = 0

    async def acquire(self) -> None:
        """FIFO wait for a throttle token with minimum spacing."""
        self._pending += 1
        try:
            await self._semaphore.acquire()

            # Enforce minimum spacing
            async with self._lock:
                now = time.monotonic()
                spacing_sec = self._current_min_spacing_ms / 1000.0
                elapsed = now - self._last_request_time
                if elapsed < spacing_sec:
                    await asyncio.sleep(spacing_sec - elapsed)
                self._last_request_time = time.monotonic()
                self._total_acquired += 1
        finally:
            self._pending -= 1

    def release(self) -> None:
        """Release a throttle token."""
        self._semaphore.release()

    def backoff(self) -> None:
        """Increase throttling after a rate limit error."""
        if self._backoff_level >= self._config.max_backoff_level:
            return

        self._backoff_level += 1
        self._last_backoff_time = time.monotonic()
        self._success_since_backoff = 0

        # Halve concurrency, double spacing, halve refill
        self._current_max_concurrent = max(1, self._config.max_concurrent >> self._backoff_level)
        self._current_min_spacing_ms = self._config.min_spacing_ms * (2 ** self._backoff_level)
        self._current_refill_rate = self._config.refill_rate_per_second / (2 ** self._backoff_level)

    def recover(self) -> None:
        """Step back toward original config after sustained success."""
        if self._backoff_level <= 0:
            return

        # Only recover if we've had 10+ successes since last backoff
        self._success_since_backoff += 1
        if self._success_since_backoff < 10:
            return

        # And at least 10 seconds have passed
        if time.monotonic() - self._last_backoff_time < 10.0:
            return

        self._backoff_level -= 1
        self._success_since_backoff = 0

        if self._backoff_level <= 0:
            self._current_max_concurrent = self._config.max_concurrent
            self._current_min_spacing_ms = self._config.min_spacing_ms
            self._current_refill_rate = self._config.refill_rate_per_second
        else:
            self._current_max_concurrent = max(1, self._config.max_concurrent >> self._backoff_level)
            self._current_min_spacing_ms = self._config.min_spacing_ms * (2 ** self._backoff_level)
            self._current_refill_rate = self._config.refill_rate_per_second / (2 ** self._backoff_level)

    def feed_rate_limit_info(self, remaining: int | None = None, reset_ms: int | None = None) -> None:
        """Proactive adjustment from response headers."""
        if remaining is not None and remaining <= 1:
            self.backoff()
        if reset_ms is not None and reset_ms > 5000:
            self.backoff()

    def get_stats(self) -> ThrottleStats:
        """Get current throttle statistics."""
        return ThrottleStats(
            pending_count=self._pending,
            available_tokens=self._current_max_concurrent,
            total_acquired=self._total_acquired,
            backoff_level=self._backoff_level,
            current_max_concurrent=self._current_max_concurrent,
            current_min_spacing_ms=self._current_min_spacing_ms,
        )


class ThrottledProvider:
    """Wraps an LLM provider with rate throttling.

    Acquires throttle token before each API call, recovers on success,
    backs off on rate limit (429) or spend limit (402) errors.
    """

    def __init__(self, provider: LLMProvider, throttle: SwarmThrottle) -> None:
        self._provider = provider
        self._throttle = throttle

    async def chat(self, messages: list[Any], **kwargs: Any) -> Any:
        """Throttled chat call."""
        await self._throttle.acquire()
        try:
            result = await self._provider.chat(messages, **kwargs)
            self._throttle.recover()
            return result
        except Exception as e:
            error_str = str(e).lower()
            if "429" in error_str or "rate" in error_str:
                self._throttle.backoff()
            elif "402" in error_str:
                self._throttle.backoff()
            raise
        finally:
            self._throttle.release()

    def get_throttle(self) -> SwarmThrottle:
        """Access underlying throttle for inspection."""
        return self._throttle


def create_throttled_provider(
    provider: LLMProvider,
    config: ThrottleConfig | None = None,
) -> ThrottledProvider:
    """Factory function to create a throttled provider."""
    throttle = SwarmThrottle(config)
    return ThrottledProvider(provider, throttle)
