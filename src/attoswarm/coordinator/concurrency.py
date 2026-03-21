"""Adaptive concurrency control using AIMD (Additive Increase, Multiplicative Decrease).

Replaces the fixed ``asyncio.Semaphore`` in SubagentManager with a
concurrency controller that adjusts limits based on runtime feedback:

- Success: +1 (additive increase, with cooldown)
- Rate limit: halve (multiplicative decrease)
- Timeout: -1

Same ``acquire()``/``release()`` interface as ``asyncio.Semaphore``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Minimum seconds between successive increases
_INCREASE_COOLDOWN = 30.0


@dataclass(slots=True)
class ConcurrencyStats:
    """Statistics for the adaptive concurrency controller."""

    increases: int = 0
    decreases: int = 0
    current: int = 0
    floor: int = 0
    ceiling: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "current": self.current,
            "floor": self.floor,
            "ceiling": self.ceiling,
            "increases": self.increases,
            "decreases": self.decreases,
        }


class AdaptiveConcurrency:
    """AIMD concurrency controller with semaphore-compatible interface.

    Usage::

        ac = AdaptiveConcurrency(initial=4, floor=1, ceiling=8)
        async with ac:
            ...  # do work
        ac.on_success()      # +1 (if cooldown elapsed)
        ac.on_rate_limit()   # halve
        ac.on_timeout()      # -1
    """

    def __init__(
        self,
        initial: int = 4,
        floor: int = 1,
        ceiling: int = 8,
    ) -> None:
        self._floor = max(floor, 1)
        self._ceiling = max(ceiling, self._floor)
        self._current = max(min(initial, self._ceiling), self._floor)
        self._semaphore = asyncio.Semaphore(self._current)
        self._last_increase_time: float = 0.0
        self._stats = ConcurrencyStats(
            current=self._current,
            floor=self._floor,
            ceiling=self._ceiling,
        )

    @property
    def current(self) -> int:
        return self._current

    @property
    def stats(self) -> ConcurrencyStats:
        self._stats.current = self._current
        return self._stats

    async def acquire(self) -> None:
        """Acquire a concurrency slot (blocks if at limit)."""
        await self._semaphore.acquire()

    def release(self) -> None:
        """Release a concurrency slot."""
        self._semaphore.release()

    async def __aenter__(self) -> AdaptiveConcurrency:
        await self.acquire()
        return self

    async def __aexit__(self, *args: Any) -> None:
        self.release()

    def on_success(self) -> None:
        """Additive increase: +1 if below ceiling and cooldown has elapsed."""
        now = time.time()
        if now - self._last_increase_time < _INCREASE_COOLDOWN:
            return
        if self._current >= self._ceiling:
            return

        self._current += 1
        self._semaphore.release()  # Add one permit
        self._last_increase_time = now
        self._stats.increases += 1
        self._stats.current = self._current
        logger.debug("Concurrency increased to %d", self._current)

    def on_rate_limit(self) -> None:
        """Multiplicative decrease: halve the concurrency."""
        new = max(self._current // 2, self._floor)
        if new == self._current:
            return

        reduction = self._current - new
        self._current = new

        # Drain excess permits by acquiring without releasing
        for _ in range(reduction):
            # Try to acquire immediately; if not available, that's fine
            # — just reduce the max
            if self._semaphore._value > 0:  # noqa: SLF001
                self._semaphore._value -= 1  # noqa: SLF001

        self._stats.decreases += 1
        self._stats.current = self._current
        logger.info("Concurrency halved to %d (rate limit)", self._current)

    def on_timeout(self) -> None:
        """Linear decrease: -1."""
        if self._current <= self._floor:
            return

        self._current -= 1
        if self._semaphore._value > 0:  # noqa: SLF001
            self._semaphore._value -= 1  # noqa: SLF001

        self._stats.decreases += 1
        self._stats.current = self._current
        logger.debug("Concurrency decreased to %d (timeout)", self._current)
