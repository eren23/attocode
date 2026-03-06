"""Resource monitoring and limits.

Tracks CPU time, memory usage, file handles, and concurrent operations
to prevent resource exhaustion during long-running agent sessions.
"""

from __future__ import annotations

import os
import resource
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ResourceStatus(StrEnum):
    """Current resource status."""

    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"
    EXHAUSTED = "exhausted"


@dataclass(slots=True)
class ResourceConfig:
    """Resource monitoring configuration."""

    enabled: bool = True
    max_memory_mb: int = 512
    max_cpu_time_sec: int = 1_800  # 30 minutes per prompt
    max_concurrent_ops: int = 10
    warn_threshold: float = 0.7
    critical_threshold: float = 0.9


@dataclass(slots=True)
class ResourceCheck:
    """Result of a resource check."""

    status: ResourceStatus
    memory_usage_mb: float = 0.0
    cpu_time_sec: float = 0.0
    concurrent_ops: int = 0
    message: str = ""
    should_stop: bool = False


@dataclass
class ResourceManager:
    """Monitors and limits system resource usage.

    Tracks CPU time, memory, and concurrent operations. Resets CPU
    tracking per-prompt so limits apply to individual prompt executions.
    """

    config: ResourceConfig = field(default_factory=ResourceConfig)

    _prompt_start_cpu: float = field(default=0.0, repr=False)
    _concurrent_ops: int = field(default=0, repr=False)
    _peak_memory_mb: float = field(default=0.0, repr=False)

    def __post_init__(self) -> None:
        self.reset_prompt()

    def reset_prompt(self) -> None:
        """Reset per-prompt CPU tracking. Call at start of each new prompt."""
        usage = resource.getrusage(resource.RUSAGE_SELF)
        self._prompt_start_cpu = usage.ru_utime + usage.ru_stime

    def acquire_operation(self) -> bool:
        """Try to acquire a slot for a concurrent operation.

        Returns True if allowed, False if at limit.
        """
        if self._concurrent_ops >= self.config.max_concurrent_ops:
            return False
        self._concurrent_ops += 1
        return True

    def release_operation(self) -> None:
        """Release a concurrent operation slot."""
        self._concurrent_ops = max(0, self._concurrent_ops - 1)

    def check(self) -> ResourceCheck:
        """Check current resource usage against limits."""
        if not self.config.enabled:
            return ResourceCheck(status=ResourceStatus.OK)

        # Memory check
        try:
            usage = resource.getrusage(resource.RUSAGE_SELF)
            # ru_maxrss is in bytes on Linux, KB on macOS
            memory_kb = usage.ru_maxrss
            if os.uname().sysname == "Darwin":
                memory_mb = memory_kb / (1024 * 1024)  # bytes -> MB on macOS
            else:
                memory_mb = memory_kb / 1024  # KB -> MB on Linux
        except (OSError, AttributeError):
            memory_mb = 0.0

        self._peak_memory_mb = max(self._peak_memory_mb, memory_mb)

        # CPU time check (per-prompt)
        try:
            usage = resource.getrusage(resource.RUSAGE_SELF)
            cpu_time = (usage.ru_utime + usage.ru_stime) - self._prompt_start_cpu
        except (OSError, AttributeError):
            cpu_time = 0.0

        # Determine status
        status = ResourceStatus.OK
        message = ""
        should_stop = False

        # Memory exhaustion
        if self.config.max_memory_mb > 0:
            mem_ratio = memory_mb / self.config.max_memory_mb
            if mem_ratio >= 1.0:
                status = ResourceStatus.EXHAUSTED
                message = f"Memory limit exceeded: {memory_mb:.0f}MB / {self.config.max_memory_mb}MB"
                should_stop = True
            elif mem_ratio >= self.config.critical_threshold:
                status = ResourceStatus.CRITICAL
                message = f"Memory critical: {memory_mb:.0f}MB / {self.config.max_memory_mb}MB"
            elif mem_ratio >= self.config.warn_threshold:
                status = ResourceStatus.WARNING
                message = f"Memory warning: {memory_mb:.0f}MB / {self.config.max_memory_mb}MB"

        # CPU time exhaustion
        if self.config.max_cpu_time_sec > 0 and not should_stop:
            cpu_ratio = cpu_time / self.config.max_cpu_time_sec
            if cpu_ratio >= 1.0:
                status = ResourceStatus.EXHAUSTED
                message = f"CPU time exceeded: {cpu_time:.0f}s / {self.config.max_cpu_time_sec}s"
                should_stop = True
            elif cpu_ratio >= self.config.critical_threshold and status.value < ResourceStatus.CRITICAL.value:
                status = ResourceStatus.CRITICAL
                message = f"CPU time critical: {cpu_time:.0f}s / {self.config.max_cpu_time_sec}s"

        return ResourceCheck(
            status=status,
            memory_usage_mb=memory_mb,
            cpu_time_sec=cpu_time,
            concurrent_ops=self._concurrent_ops,
            message=message,
            should_stop=should_stop,
        )

    def get_stats(self) -> dict[str, Any]:
        """Get current resource stats."""
        check = self.check()
        return {
            "memory_mb": check.memory_usage_mb,
            "peak_memory_mb": self._peak_memory_mb,
            "cpu_time_sec": check.cpu_time_sec,
            "concurrent_ops": self._concurrent_ops,
            "status": check.status.value,
        }
