"""Model health monitoring for adaptive task dispatch.

Tracks per-model success/failure/timeout/rate-limit statistics with
EWMA latency smoothing.  Provides health-weighted model selection
and throttling recommendations.

Includes a circuit breaker that trips when a model accumulates too many
failures within a sliding time window, preventing dispatch to unhealthy
models.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# EWMA smoothing factor for latency
_LATENCY_ALPHA = 0.3

# Decay factor for health score recovery (per minute)
_HEALTH_DECAY_INTERVAL = 60.0


@dataclass(slots=True)
class ModelHealth:
    """Health statistics for a single model."""

    model: str
    successes: int = 0
    failures: int = 0
    timeouts: int = 0
    rate_limits: int = 0
    ewma_latency_s: float = 0.0
    health_score: float = 1.0  # 0.0 (dead) to 1.0 (perfect)
    last_update: float = field(default_factory=time.time)

    @property
    def total_requests(self) -> int:
        return self.successes + self.failures + self.timeouts + self.rate_limits

    @property
    def success_rate(self) -> float:
        total = self.total_requests
        return self.successes / total if total > 0 else 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "successes": self.successes,
            "failures": self.failures,
            "timeouts": self.timeouts,
            "rate_limits": self.rate_limits,
            "ewma_latency_s": round(self.ewma_latency_s, 2),
            "health_score": round(self.health_score, 3),
            "success_rate": round(self.success_rate, 3),
            "total_requests": self.total_requests,
        }


class HealthMonitor:
    """Tracks model health and provides adaptive recommendations.

    Usage::

        monitor = HealthMonitor()
        monitor.record_outcome("claude-3", "success", duration_s=12.5)
        monitor.record_outcome("claude-3", "rate_limit")
        best = monitor.get_best_model(["claude-3", "gpt-4"])
        if monitor.should_throttle("claude-3"):
            await asyncio.sleep(backoff)
        if monitor.check_circuit_breaker("claude-3"):
            # Model is tripped — do not dispatch
            ...
    """

    # Circuit breaker configuration — override via subclass or config injection
    CIRCUIT_BREAKER_WINDOW: float = 60.0   # seconds
    CIRCUIT_BREAKER_THRESHOLD: int = 3     # failures in window to trip

    def __init__(self, health_threshold: float = 0.5) -> None:
        self._models: dict[str, ModelHealth] = {}
        self._threshold = health_threshold
        # Circuit breaker: per-model failure timestamps (monotonic)
        self._failure_timestamps: dict[str, list[float]] = defaultdict(list)

    def record_outcome(
        self,
        model: str,
        result: str,
        duration_s: float = 0.0,
        failure_cause: str = "",
    ) -> None:
        """Record the outcome of an LLM call.

        Args:
            model: Model identifier.
            result: One of "success", "failure", "timeout", "rate_limit".
            duration_s: Call duration in seconds.
            failure_cause: Optional failure attribution cause.
        """
        health = self._models.get(model)
        if not health:
            health = ModelHealth(model=model)
            self._models[model] = health

        # Apply time-based recovery before recording new outcome
        self._apply_recovery(health)

        now = time.time()
        health.last_update = now

        # Update latency EWMA
        if duration_s > 0:
            if health.ewma_latency_s == 0.0:
                health.ewma_latency_s = duration_s
            else:
                health.ewma_latency_s = (
                    _LATENCY_ALPHA * duration_s
                    + (1 - _LATENCY_ALPHA) * health.ewma_latency_s
                )

        # Map failure_cause to result if not explicitly set
        if result == "failure" and failure_cause:
            if failure_cause == "timeout":
                result = "timeout"
            elif failure_cause == "budget" and "rate" in failure_cause.lower():
                result = "rate_limit"

        # Update counters and health score
        if result == "success":
            health.successes += 1
            # Reward: move toward 1.0
            health.health_score = min(1.0, health.health_score + 0.05)
        elif result == "rate_limit":
            health.rate_limits += 1
            # Heavy penalty for rate limits
            health.health_score = max(0.0, health.health_score * 0.5)
        elif result == "timeout":
            health.timeouts += 1
            health.health_score = max(0.0, health.health_score - 0.15)
        else:  # failure
            health.failures += 1
            health.health_score = max(0.0, health.health_score - 0.1)

        # Circuit breaker: record failure/timeout timestamps
        if result in ("failure", "timeout"):
            now_mono = time.monotonic()
            self._failure_timestamps[model].append(now_mono)
            # Trim old timestamps (keep last window only)
            cutoff = now_mono - self.CIRCUIT_BREAKER_WINDOW
            self._failure_timestamps[model] = [
                t for t in self._failure_timestamps[model] if t > cutoff
            ]

    def _apply_recovery(self, health: ModelHealth) -> None:
        """Allow health score to recover over time (natural healing)."""
        elapsed = time.time() - health.last_update
        if elapsed > _HEALTH_DECAY_INTERVAL and health.health_score < 1.0:
            recovery_periods = elapsed / _HEALTH_DECAY_INTERVAL
            # Recover 5% per period, capped at 1.0
            health.health_score = min(1.0, health.health_score + 0.05 * recovery_periods)

    def get_health(self, model: str) -> ModelHealth | None:
        """Return health data for a model, or None if not tracked."""
        health = self._models.get(model)
        if health:
            self._apply_recovery(health)
        return health

    def get_best_model(self, available: list[str]) -> str:
        """Select the healthiest model from a list of candidates.

        Returns the first candidate if none are tracked yet.
        """
        if not available:
            return ""

        best_model = available[0]
        best_score = -1.0

        for model in available:
            health = self._models.get(model)
            if health is None:
                # Unknown model gets benefit of the doubt
                if best_score < 1.0:
                    best_score = 1.0
                    best_model = model
            else:
                self._apply_recovery(health)
                if health.health_score > best_score:
                    best_score = health.health_score
                    best_model = model

        return best_model

    def should_throttle(self, model: str) -> bool:
        """Return True if the model's health is below the threshold."""
        health = self._models.get(model)
        if health is None:
            return False
        self._apply_recovery(health)
        return health.health_score < self._threshold

    def check_circuit_breaker(self, model: str) -> bool:
        """Check if circuit breaker is open (too many recent failures).

        Returns True if the model should NOT be dispatched to.
        """
        cutoff = time.monotonic() - self.CIRCUIT_BREAKER_WINDOW
        recent = [t for t in self._failure_timestamps.get(model, []) if t > cutoff]
        return len(recent) >= self.CIRCUIT_BREAKER_THRESHOLD

    def all_health(self) -> dict[str, ModelHealth]:
        """Return health data for all tracked models."""
        for health in self._models.values():
            self._apply_recovery(health)
        return dict(self._models)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for model, health in self.all_health().items():
            entry = health.to_dict()
            entry["circuit_breaker_open"] = self.check_circuit_breaker(model)
            cutoff = time.monotonic() - self.CIRCUIT_BREAKER_WINDOW
            recent_failures = [
                t for t in self._failure_timestamps.get(model, []) if t > cutoff
            ]
            entry["recent_failures_in_window"] = len(recent_failures)
            result[model] = entry
        return result
