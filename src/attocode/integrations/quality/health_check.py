"""Health check system for monitoring agent components.

Provides pluggable health checks with parallel execution,
periodic monitoring, and status change detection.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class HealthCheckResult:
    """Result of a health check."""

    name: str
    healthy: bool
    latency_ms: float = 0.0
    error: str | None = None
    timestamp: float = field(default_factory=time.time)
    details: dict[str, Any] | None = None


@dataclass
class HealthReport:
    """Aggregate health report from all checks."""

    healthy: bool
    healthy_count: int
    total_count: int
    checks: list[HealthCheckResult]
    timestamp: float = field(default_factory=time.time)
    total_latency_ms: float = 0.0


@dataclass
class HealthCheckConfig:
    """Configuration for a single health check."""

    name: str
    check: Callable[[], Any]  # async or sync callable -> bool
    timeout: float = 5.0  # seconds
    critical: bool = False
    description: str = ""


@dataclass
class HealthCheckerConfig:
    """Configuration for the health checker."""

    default_timeout: float = 5.0
    parallel: bool = True


HealthEventListener = Callable[[str, dict[str, Any]], None]


class HealthChecker:
    """Monitors health of agent components.

    Supports pluggable checks with timeouts, parallel/serial
    execution, and periodic monitoring.
    """

    def __init__(self, config: HealthCheckerConfig | None = None) -> None:
        self._config = config or HealthCheckerConfig()
        self._checks: dict[str, HealthCheckConfig] = {}
        self._last_results: dict[str, HealthCheckResult] = {}
        self._listeners: set[HealthEventListener] = set()
        self._periodic_task: asyncio.Task[None] | None = None

    def register(
        self,
        name: str,
        check: Callable[[], Any],
        timeout: float | None = None,
        critical: bool = False,
        description: str = "",
    ) -> None:
        """Register a health check."""
        self._checks[name] = HealthCheckConfig(
            name=name,
            check=check,
            timeout=timeout or self._config.default_timeout,
            critical=critical,
            description=description,
        )

    def unregister(self, name: str) -> bool:
        """Unregister a health check."""
        if name in self._checks:
            del self._checks[name]
            self._last_results.pop(name, None)
            return True
        return False

    async def check(self, name: str) -> HealthCheckResult:
        """Run a single health check."""
        config = self._checks.get(name)
        if config is None:
            return HealthCheckResult(
                name=name, healthy=False, error=f"Check '{name}' not registered"
            )

        self._emit("check.started", {"name": name})

        start = time.monotonic()
        try:
            result = config.check()
            if asyncio.iscoroutine(result):
                healthy = await asyncio.wait_for(result, timeout=config.timeout)
            else:
                healthy = result
            healthy = bool(healthy)
        except asyncio.TimeoutError:
            healthy = False
            error = f"Timed out after {config.timeout}s"
            result_obj = HealthCheckResult(
                name=name,
                healthy=False,
                latency_ms=(time.monotonic() - start) * 1000,
                error=error,
            )
            self._update_result(name, result_obj)
            return result_obj
        except Exception as e:
            healthy = False
            result_obj = HealthCheckResult(
                name=name,
                healthy=False,
                latency_ms=(time.monotonic() - start) * 1000,
                error=str(e),
            )
            self._update_result(name, result_obj)
            return result_obj

        latency_ms = (time.monotonic() - start) * 1000
        result_obj = HealthCheckResult(
            name=name, healthy=healthy, latency_ms=latency_ms
        )
        self._update_result(name, result_obj)
        return result_obj

    async def check_all(self) -> HealthReport:
        """Run all health checks."""
        start = time.monotonic()
        results: list[HealthCheckResult] = []

        if self._config.parallel:
            tasks = [self.check(name) for name in self._checks]
            results = list(await asyncio.gather(*tasks))
        else:
            for name in self._checks:
                results.append(await self.check(name))

        total_latency = (time.monotonic() - start) * 1000
        healthy_count = sum(1 for r in results if r.healthy)

        report = HealthReport(
            healthy=all(r.healthy for r in results),
            healthy_count=healthy_count,
            total_count=len(results),
            checks=results,
            total_latency_ms=total_latency,
        )

        self._emit("report.generated", {"healthy": report.healthy, "total": report.total_count})
        return report

    def get_last_result(self, name: str) -> HealthCheckResult | None:
        """Get the last result for a check."""
        return self._last_results.get(name)

    def get_all_last_results(self) -> dict[str, HealthCheckResult]:
        """Get all last results."""
        return dict(self._last_results)

    def is_healthy(self) -> bool:
        """Check if all critical checks are passing."""
        for name, config in self._checks.items():
            if config.critical:
                result = self._last_results.get(name)
                if result is not None and not result.healthy:
                    return False
        return True

    def get_unhealthy_checks(self) -> list[str]:
        """Get names of unhealthy checks."""
        return [
            name
            for name, result in self._last_results.items()
            if not result.healthy
        ]

    async def start_periodic_checks(self, interval_seconds: float) -> None:
        """Start periodic health checks."""
        self.stop_periodic_checks()

        async def _run_periodic() -> None:
            while True:
                await self.check_all()
                await asyncio.sleep(interval_seconds)

        self._periodic_task = asyncio.create_task(_run_periodic())

    def stop_periodic_checks(self) -> None:
        """Stop periodic health checks."""
        if self._periodic_task is not None:
            self._periodic_task.cancel()
            self._periodic_task = None

    def on(self, listener: HealthEventListener) -> Callable[[], None]:
        """Subscribe to health events. Returns unsubscribe function."""
        self._listeners.add(listener)

        def unsubscribe() -> None:
            self._listeners.discard(listener)

        return unsubscribe

    def get_check_names(self) -> list[str]:
        """Get all registered check names."""
        return list(self._checks.keys())

    def dispose(self) -> None:
        """Clean up resources."""
        self.stop_periodic_checks()
        self._checks.clear()
        self._last_results.clear()
        self._listeners.clear()

    def _update_result(self, name: str, result: HealthCheckResult) -> None:
        """Update stored result and detect status changes."""
        prev = self._last_results.get(name)
        self._last_results[name] = result

        self._emit("check.completed", {"name": name, "healthy": result.healthy})

        if prev is not None and prev.healthy != result.healthy:
            self._emit("status.changed", {
                "name": name,
                "from_healthy": prev.healthy,
                "to_healthy": result.healthy,
            })

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        """Emit an event to listeners."""
        for listener in self._listeners:
            try:
                listener(event, data)
            except Exception:
                pass


def format_health_report(report: HealthReport) -> str:
    """Format a health report for terminal display."""
    status = "HEALTHY" if report.healthy else "UNHEALTHY"
    lines = [
        f"Health: {status} ({report.healthy_count}/{report.total_count} checks passing)",
        f"Total latency: {report.total_latency_ms:.0f}ms",
    ]

    for check in report.checks:
        marker = "ok" if check.healthy else "FAIL"
        line = f"  [{marker}] {check.name} ({check.latency_ms:.0f}ms)"
        if check.error:
            line += f" - {check.error}"
        lines.append(line)

    return "\n".join(lines)
