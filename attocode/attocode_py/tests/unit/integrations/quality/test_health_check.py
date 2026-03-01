"""Tests for HealthChecker: registration, execution, timeouts, events."""

from __future__ import annotations

import asyncio

import pytest

from attocode.integrations.quality.health_check import (
    HealthChecker,
    HealthCheckerConfig,
    format_health_report,
)


class TestHealthCheckerRegistration:
    """Register and unregister checks."""

    def test_register_adds_check(self) -> None:
        hc = HealthChecker()
        hc.register("db", lambda: True)
        assert "db" in hc.get_check_names()

    def test_register_multiple_checks(self) -> None:
        hc = HealthChecker()
        hc.register("db", lambda: True)
        hc.register("cache", lambda: True)
        hc.register("api", lambda: True)
        assert sorted(hc.get_check_names()) == ["api", "cache", "db"]

    def test_unregister_existing(self) -> None:
        hc = HealthChecker()
        hc.register("db", lambda: True)
        assert hc.unregister("db") is True
        assert "db" not in hc.get_check_names()

    def test_unregister_nonexistent(self) -> None:
        hc = HealthChecker()
        assert hc.unregister("missing") is False

    @pytest.mark.asyncio
    async def test_unregister_clears_last_result(self) -> None:
        """Unregistering also removes cached results."""
        hc = HealthChecker()
        hc.register("db", lambda: True)
        await hc.check("db")
        assert hc.get_last_result("db") is not None
        hc.unregister("db")
        assert hc.get_last_result("db") is None

    @pytest.mark.asyncio
    async def test_register_overwrites(self) -> None:
        """Re-registering a check replaces the old one."""
        hc = HealthChecker()
        hc.register("db", lambda: True)
        hc.register("db", lambda: False)
        result = await hc.check("db")
        assert result.healthy is False


class TestHealthCheckerCheck:
    """Run individual checks."""

    @pytest.mark.asyncio
    async def test_check_sync_healthy(self) -> None:
        hc = HealthChecker()
        hc.register("ok", lambda: True)
        result = await hc.check("ok")
        assert result.healthy is True
        assert result.name == "ok"
        assert result.error is None
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_check_sync_unhealthy(self) -> None:
        hc = HealthChecker()
        hc.register("bad", lambda: False)
        result = await hc.check("bad")
        assert result.healthy is False

    @pytest.mark.asyncio
    async def test_check_async_healthy(self) -> None:
        async def healthy_check() -> bool:
            return True

        hc = HealthChecker()
        hc.register("async_ok", healthy_check)
        result = await hc.check("async_ok")
        assert result.healthy is True

    @pytest.mark.asyncio
    async def test_check_async_unhealthy(self) -> None:
        async def unhealthy_check() -> bool:
            return False

        hc = HealthChecker()
        hc.register("async_bad", unhealthy_check)
        result = await hc.check("async_bad")
        assert result.healthy is False

    @pytest.mark.asyncio
    async def test_check_exception_returns_unhealthy(self) -> None:
        def boom() -> bool:
            raise RuntimeError("connection refused")

        hc = HealthChecker()
        hc.register("boom", boom)
        result = await hc.check("boom")
        assert result.healthy is False
        assert "connection refused" in (result.error or "")

    @pytest.mark.asyncio
    async def test_check_unregistered_name(self) -> None:
        hc = HealthChecker()
        result = await hc.check("ghost")
        assert result.healthy is False
        assert "not registered" in (result.error or "")

    @pytest.mark.asyncio
    async def test_check_truthy_coercion(self) -> None:
        """Non-bool truthy values are coerced to True."""
        hc = HealthChecker()
        hc.register("truthy", lambda: "yes")
        result = await hc.check("truthy")
        assert result.healthy is True

    @pytest.mark.asyncio
    async def test_check_falsy_coercion(self) -> None:
        """Non-bool falsy values are coerced to False."""
        hc = HealthChecker()
        hc.register("falsy", lambda: 0)
        result = await hc.check("falsy")
        assert result.healthy is False

    @pytest.mark.asyncio
    async def test_last_result_updated(self) -> None:
        hc = HealthChecker()
        hc.register("db", lambda: True)
        await hc.check("db")
        last = hc.get_last_result("db")
        assert last is not None
        assert last.healthy is True


class TestHealthCheckerCheckAll:
    """Run all checks together."""

    @pytest.mark.asyncio
    async def test_check_all_all_healthy(self) -> None:
        hc = HealthChecker()
        hc.register("a", lambda: True)
        hc.register("b", lambda: True)
        report = await hc.check_all()
        assert report.healthy is True
        assert report.healthy_count == 2
        assert report.total_count == 2
        assert len(report.checks) == 2

    @pytest.mark.asyncio
    async def test_check_all_one_unhealthy(self) -> None:
        hc = HealthChecker()
        hc.register("a", lambda: True)
        hc.register("b", lambda: False)
        report = await hc.check_all()
        assert report.healthy is False
        assert report.healthy_count == 1
        assert report.total_count == 2

    @pytest.mark.asyncio
    async def test_check_all_empty(self) -> None:
        hc = HealthChecker()
        report = await hc.check_all()
        assert report.healthy is True
        assert report.total_count == 0

    @pytest.mark.asyncio
    async def test_check_all_serial_mode(self) -> None:
        cfg = HealthCheckerConfig(parallel=False)
        hc = HealthChecker(cfg)
        hc.register("x", lambda: True)
        hc.register("y", lambda: True)
        report = await hc.check_all()
        assert report.healthy is True
        assert report.total_count == 2

    @pytest.mark.asyncio
    async def test_check_all_latency_measured(self) -> None:
        hc = HealthChecker()
        hc.register("a", lambda: True)
        report = await hc.check_all()
        assert report.total_latency_ms >= 0


class TestHealthCheckerIsHealthy:
    """is_healthy considers critical checks only."""

    @pytest.mark.asyncio
    async def test_healthy_when_no_checks(self) -> None:
        hc = HealthChecker()
        assert hc.is_healthy() is True

    @pytest.mark.asyncio
    async def test_healthy_when_critical_passing(self) -> None:
        hc = HealthChecker()
        hc.register("db", lambda: True, critical=True)
        await hc.check("db")
        assert hc.is_healthy() is True

    @pytest.mark.asyncio
    async def test_unhealthy_when_critical_failing(self) -> None:
        hc = HealthChecker()
        hc.register("db", lambda: False, critical=True)
        await hc.check("db")
        assert hc.is_healthy() is False

    @pytest.mark.asyncio
    async def test_healthy_when_non_critical_failing(self) -> None:
        """Non-critical failures do not affect is_healthy."""
        hc = HealthChecker()
        hc.register("cache", lambda: False, critical=False)
        await hc.check("cache")
        assert hc.is_healthy() is True

    @pytest.mark.asyncio
    async def test_healthy_when_critical_not_yet_run(self) -> None:
        """Critical checks that haven't run yet don't count as unhealthy."""
        hc = HealthChecker()
        hc.register("db", lambda: False, critical=True)
        # No check run yet, so no result stored.
        assert hc.is_healthy() is True


class TestHealthCheckerGetCheckNames:
    """get_check_names returns all registered names."""

    def test_empty(self) -> None:
        hc = HealthChecker()
        assert hc.get_check_names() == []

    def test_preserves_insertion_order(self) -> None:
        hc = HealthChecker()
        hc.register("c", lambda: True)
        hc.register("a", lambda: True)
        hc.register("b", lambda: True)
        assert hc.get_check_names() == ["c", "a", "b"]


class TestHealthCheckerUnhealthyChecks:
    """get_unhealthy_checks returns names of failing checks."""

    @pytest.mark.asyncio
    async def test_unhealthy_checks(self) -> None:
        hc = HealthChecker()
        hc.register("ok", lambda: True)
        hc.register("bad", lambda: False)
        await hc.check_all()
        unhealthy = hc.get_unhealthy_checks()
        assert unhealthy == ["bad"]

    @pytest.mark.asyncio
    async def test_no_unhealthy(self) -> None:
        hc = HealthChecker()
        hc.register("ok", lambda: True)
        await hc.check_all()
        assert hc.get_unhealthy_checks() == []


class TestHealthCheckerTimeout:
    """Timeout handling in async checks."""

    @pytest.mark.asyncio
    async def test_timeout_returns_unhealthy(self) -> None:
        async def slow_check() -> bool:
            await asyncio.sleep(10)
            return True

        hc = HealthChecker()
        hc.register("slow", slow_check, timeout=0.05)
        result = await hc.check("slow")
        assert result.healthy is False
        assert result.error is not None
        assert "Timed out" in result.error

    @pytest.mark.asyncio
    async def test_timeout_uses_default_when_not_specified(self) -> None:
        cfg = HealthCheckerConfig(default_timeout=0.05)
        hc = HealthChecker(cfg)

        async def slow_check() -> bool:
            await asyncio.sleep(10)
            return True

        hc.register("slow", slow_check)
        result = await hc.check("slow")
        assert result.healthy is False
        assert "Timed out" in (result.error or "")


class TestHealthCheckerEventListener:
    """Event listener receives notifications."""

    @pytest.mark.asyncio
    async def test_check_started_and_completed_events(self) -> None:
        events: list[tuple[str, dict]] = []

        def listener(event: str, data: dict) -> None:
            events.append((event, data))

        hc = HealthChecker()
        hc.on(listener)
        hc.register("db", lambda: True)
        await hc.check("db")

        event_names = [e[0] for e in events]
        assert "check.started" in event_names
        assert "check.completed" in event_names

    @pytest.mark.asyncio
    async def test_status_changed_event(self) -> None:
        events: list[tuple[str, dict]] = []

        def listener(event: str, data: dict) -> None:
            events.append((event, data))

        call_count = 0

        def flapping() -> bool:
            nonlocal call_count
            call_count += 1
            return call_count != 2  # True, False, True, ...

        hc = HealthChecker()
        hc.on(listener)
        hc.register("flap", flapping)

        await hc.check("flap")  # healthy=True
        await hc.check("flap")  # healthy=False -> status.changed
        await hc.check("flap")  # healthy=True -> status.changed

        changed_events = [e for e in events if e[0] == "status.changed"]
        assert len(changed_events) == 2
        assert changed_events[0][1]["from_healthy"] is True
        assert changed_events[0][1]["to_healthy"] is False
        assert changed_events[1][1]["from_healthy"] is False
        assert changed_events[1][1]["to_healthy"] is True

    @pytest.mark.asyncio
    async def test_unsubscribe(self) -> None:
        events: list[tuple[str, dict]] = []

        def listener(event: str, data: dict) -> None:
            events.append((event, data))

        hc = HealthChecker()
        unsub = hc.on(listener)
        hc.register("db", lambda: True)
        await hc.check("db")
        count_before = len(events)
        unsub()
        await hc.check("db")
        assert len(events) == count_before

    @pytest.mark.asyncio
    async def test_report_generated_event(self) -> None:
        events: list[tuple[str, dict]] = []

        def listener(event: str, data: dict) -> None:
            events.append((event, data))

        hc = HealthChecker()
        hc.on(listener)
        hc.register("a", lambda: True)
        await hc.check_all()

        report_events = [e for e in events if e[0] == "report.generated"]
        assert len(report_events) == 1
        assert report_events[0][1]["healthy"] is True

    @pytest.mark.asyncio
    async def test_listener_exception_does_not_break(self) -> None:
        """A listener that raises does not prevent others from being called."""
        called: list[str] = []

        def bad_listener(event: str, data: dict) -> None:
            raise RuntimeError("oops")

        def good_listener(event: str, data: dict) -> None:
            called.append(event)

        hc = HealthChecker()
        hc.on(bad_listener)
        hc.on(good_listener)
        hc.register("db", lambda: True)
        await hc.check("db")
        assert len(called) > 0


class TestHealthCheckerDispose:
    """dispose() clears all state."""

    @pytest.mark.asyncio
    async def test_dispose_clears_everything(self) -> None:
        hc = HealthChecker()
        hc.register("a", lambda: True)
        await hc.check("a")
        hc.dispose()
        assert hc.get_check_names() == []
        assert hc.get_all_last_results() == {}


class TestFormatHealthReport:
    """format_health_report produces readable output."""

    @pytest.mark.asyncio
    async def test_format_healthy_report(self) -> None:
        hc = HealthChecker()
        hc.register("db", lambda: True)
        report = await hc.check_all()
        text = format_health_report(report)
        assert "HEALTHY" in text
        assert "db" in text
        assert "1/1" in text

    @pytest.mark.asyncio
    async def test_format_unhealthy_report(self) -> None:
        def broken() -> bool:
            raise RuntimeError("down")

        hc = HealthChecker()
        hc.register("api", broken)
        report = await hc.check_all()
        text = format_health_report(report)
        assert "UNHEALTHY" in text
        assert "FAIL" in text
        assert "down" in text
