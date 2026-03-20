"""Tests for HealthMonitor and AdaptiveConcurrency."""

from __future__ import annotations

import pytest

from attoswarm.coordinator.concurrency import AdaptiveConcurrency
from attoswarm.coordinator.health_monitor import HealthMonitor


class TestHealthMonitor:
    def test_initial_state(self) -> None:
        monitor = HealthMonitor()
        assert monitor.get_health("claude-3") is None

    def test_record_success(self) -> None:
        monitor = HealthMonitor()
        monitor.record_outcome("claude-3", "success", duration_s=10.0)
        health = monitor.get_health("claude-3")
        assert health is not None
        assert health.successes == 1
        assert health.health_score > 0.9
        assert health.ewma_latency_s == 10.0

    def test_record_rate_limit_halves_score(self) -> None:
        monitor = HealthMonitor()
        monitor.record_outcome("model", "success")
        initial = monitor.get_health("model").health_score  # type: ignore[union-attr]
        monitor.record_outcome("model", "rate_limit")
        health = monitor.get_health("model")
        assert health is not None
        assert health.health_score < initial * 0.6

    def test_record_timeout(self) -> None:
        monitor = HealthMonitor()
        monitor.record_outcome("model", "timeout", duration_s=600.0)
        health = monitor.get_health("model")
        assert health is not None
        assert health.timeouts == 1
        assert health.health_score < 1.0

    def test_get_best_model_unknown(self) -> None:
        monitor = HealthMonitor()
        # Unknown models get benefit of the doubt
        best = monitor.get_best_model(["a", "b"])
        assert best in ("a", "b")

    def test_get_best_model_by_health(self) -> None:
        monitor = HealthMonitor()
        monitor.record_outcome("good", "success")
        monitor.record_outcome("good", "success")
        monitor.record_outcome("bad", "rate_limit")
        monitor.record_outcome("bad", "rate_limit")
        best = monitor.get_best_model(["good", "bad"])
        assert best == "good"

    def test_should_throttle(self) -> None:
        monitor = HealthMonitor(health_threshold=0.5)
        assert not monitor.should_throttle("unknown")
        monitor.record_outcome("model", "rate_limit")
        monitor.record_outcome("model", "rate_limit")
        assert monitor.should_throttle("model")

    def test_ewma_latency(self) -> None:
        monitor = HealthMonitor()
        monitor.record_outcome("m", "success", duration_s=10.0)
        monitor.record_outcome("m", "success", duration_s=20.0)
        health = monitor.get_health("m")
        assert health is not None
        # EWMA with alpha=0.3: 0.3*20 + 0.7*10 = 13.0
        assert abs(health.ewma_latency_s - 13.0) < 0.1


class TestAdaptiveConcurrency:
    def test_initial_current(self) -> None:
        ac = AdaptiveConcurrency(initial=4, floor=1, ceiling=8)
        assert ac.current == 4

    def test_on_success_increases(self) -> None:
        ac = AdaptiveConcurrency(initial=2, floor=1, ceiling=8)
        ac._last_increase_time = 0  # bypass cooldown
        ac.on_success()
        assert ac.current == 3

    def test_on_success_respects_ceiling(self) -> None:
        ac = AdaptiveConcurrency(initial=8, floor=1, ceiling=8)
        ac._last_increase_time = 0
        ac.on_success()
        assert ac.current == 8

    def test_on_rate_limit_halves(self) -> None:
        ac = AdaptiveConcurrency(initial=8, floor=1, ceiling=8)
        ac.on_rate_limit()
        assert ac.current == 4

    def test_on_rate_limit_respects_floor(self) -> None:
        ac = AdaptiveConcurrency(initial=2, floor=2, ceiling=8)
        ac.on_rate_limit()
        assert ac.current == 2

    def test_on_timeout_decreases(self) -> None:
        ac = AdaptiveConcurrency(initial=4, floor=1, ceiling=8)
        ac.on_timeout()
        assert ac.current == 3

    def test_on_timeout_respects_floor(self) -> None:
        ac = AdaptiveConcurrency(initial=1, floor=1, ceiling=8)
        ac.on_timeout()
        assert ac.current == 1

    @pytest.mark.asyncio
    async def test_acquire_release(self) -> None:
        ac = AdaptiveConcurrency(initial=2, floor=1, ceiling=4)
        async with ac:
            assert True  # Just verify it works

    def test_stats(self) -> None:
        ac = AdaptiveConcurrency(initial=4, floor=1, ceiling=8)
        ac._last_increase_time = 0
        ac.on_success()
        ac.on_rate_limit()
        stats = ac.stats
        assert stats.increases == 1
        assert stats.decreases == 1
