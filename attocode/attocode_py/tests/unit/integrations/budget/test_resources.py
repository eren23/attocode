"""Tests for resource monitoring and limits."""

from __future__ import annotations

import pytest

from attocode.integrations.budget.resources import (
    ResourceCheck,
    ResourceConfig,
    ResourceManager,
    ResourceStatus,
)


class TestResourceManager:
    def test_default_initialization(self) -> None:
        rm = ResourceManager()
        assert rm.config.enabled is True
        assert rm.config.max_concurrent_ops == 10

    def test_custom_config(self) -> None:
        config = ResourceConfig(max_memory_mb=256, max_cpu_time_sec=60)
        rm = ResourceManager(config=config)
        assert rm.config.max_memory_mb == 256
        assert rm.config.max_cpu_time_sec == 60

    def test_acquire_and_release_operation(self) -> None:
        config = ResourceConfig(max_concurrent_ops=2)
        rm = ResourceManager(config=config)
        assert rm.acquire_operation() is True
        assert rm.acquire_operation() is True
        assert rm.acquire_operation() is False  # at limit
        rm.release_operation()
        assert rm.acquire_operation() is True

    def test_release_does_not_go_negative(self) -> None:
        rm = ResourceManager()
        rm.release_operation()
        rm.release_operation()
        # Should stay at 0, not go negative
        check = rm.check()
        assert check.concurrent_ops == 0

    def test_check_returns_ok_when_disabled(self) -> None:
        config = ResourceConfig(enabled=False)
        rm = ResourceManager(config=config)
        check = rm.check()
        assert check.status == ResourceStatus.OK
        assert check.should_stop is False

    def test_check_returns_resource_check(self) -> None:
        rm = ResourceManager()
        check = rm.check()
        assert isinstance(check, ResourceCheck)
        assert check.status in list(ResourceStatus)
        assert check.memory_usage_mb >= 0
        assert check.cpu_time_sec >= 0

    def test_get_stats(self) -> None:
        rm = ResourceManager()
        stats = rm.get_stats()
        assert "memory_mb" in stats
        assert "peak_memory_mb" in stats
        assert "cpu_time_sec" in stats
        assert "concurrent_ops" in stats
        assert "status" in stats

    def test_reset_prompt_resets_cpu_tracking(self) -> None:
        rm = ResourceManager()
        check1 = rm.check()
        cpu1 = check1.cpu_time_sec
        rm.reset_prompt()
        check2 = rm.check()
        # After reset, CPU time should be close to 0
        assert check2.cpu_time_sec <= cpu1 + 0.1

    def test_concurrent_ops_tracked_in_check(self) -> None:
        rm = ResourceManager()
        rm.acquire_operation()
        rm.acquire_operation()
        check = rm.check()
        assert check.concurrent_ops == 2
        rm.release_operation()
        check = rm.check()
        assert check.concurrent_ops == 1


class TestResourceStatus:
    def test_status_values(self) -> None:
        assert ResourceStatus.OK == "ok"
        assert ResourceStatus.WARNING == "warning"
        assert ResourceStatus.CRITICAL == "critical"
        assert ResourceStatus.EXHAUSTED == "exhausted"
