"""Async subagent manager for parallel subagent spawning.

Manages concurrent async subagent execution with lifecycle tracking,
timeout management, and result collection.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, Awaitable


class SubagentStatus(StrEnum):
    """Status of an async subagent."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class SubagentHandle:
    """Handle to a running subagent."""

    id: str
    agent_type: str
    task: str
    status: SubagentStatus = SubagentStatus.PENDING
    result: Any = None
    error: str | None = None
    started_at: float = 0.0
    completed_at: float = 0.0
    tokens_used: int = 0


@dataclass(slots=True)
class AsyncSubagentConfig:
    """Configuration for async subagent management."""

    max_concurrent: int = 5
    default_timeout: float = 300.0  # 5 minutes
    collect_timeout: float = 10.0   # Timeout for result collection
    enable_progress_tracking: bool = True


class AsyncSubagentManager:
    """Manages parallel async subagent execution.

    Features:
    - Spawn multiple subagents concurrently with semaphore control
    - Track lifecycle status per subagent
    - Automatic timeout with configurable grace periods
    - Collect results as they complete (streaming)
    - Cancel individual or all running subagents
    """

    def __init__(self, config: AsyncSubagentConfig | None = None) -> None:
        self.config = config or AsyncSubagentConfig()
        self._handles: dict[str, SubagentHandle] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent)
        self._results_queue: asyncio.Queue[SubagentHandle] = asyncio.Queue()
        self._next_id = 0

    def _gen_id(self) -> str:
        self._next_id += 1
        return f"sub-{self._next_id}"

    async def spawn(
        self,
        agent_type: str,
        task: str,
        execute_fn: Callable[..., Awaitable[Any]],
        *,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> SubagentHandle:
        """Spawn an async subagent.

        Args:
            agent_type: Type of agent (researcher, coder, etc.)
            task: Task description
            execute_fn: Async function that executes the subagent work
            timeout: Override default timeout
            **kwargs: Additional arguments passed to execute_fn
        """
        handle = SubagentHandle(
            id=self._gen_id(),
            agent_type=agent_type,
            task=task,
        )
        self._handles[handle.id] = handle

        async_task = asyncio.create_task(
            self._run_subagent(handle, execute_fn, timeout or self.config.default_timeout, kwargs)
        )
        self._tasks[handle.id] = async_task
        return handle

    async def _run_subagent(
        self,
        handle: SubagentHandle,
        execute_fn: Callable[..., Awaitable[Any]],
        timeout: float,
        kwargs: dict[str, Any],
    ) -> None:
        """Execute a subagent with semaphore and timeout control."""
        async with self._semaphore:
            handle.status = SubagentStatus.RUNNING
            handle.started_at = time.monotonic()

            try:
                result = await asyncio.wait_for(
                    execute_fn(**kwargs),
                    timeout=timeout,
                )
                handle.result = result
                handle.status = SubagentStatus.COMPLETED
            except asyncio.TimeoutError:
                handle.status = SubagentStatus.TIMED_OUT
                handle.error = f"Timed out after {timeout}s"
            except asyncio.CancelledError:
                handle.status = SubagentStatus.CANCELLED
                handle.error = "Cancelled"
            except Exception as e:
                handle.status = SubagentStatus.FAILED
                handle.error = str(e)
            finally:
                handle.completed_at = time.monotonic()
                await self._results_queue.put(handle)

    async def wait_all(self, timeout: float | None = None) -> list[SubagentHandle]:
        """Wait for all spawned subagents to complete."""
        if not self._tasks:
            return []

        tasks = list(self._tasks.values())
        await asyncio.wait(tasks, timeout=timeout)
        return list(self._handles.values())

    async def wait_any(self, timeout: float | None = None) -> SubagentHandle | None:
        """Wait for the next subagent to complete."""
        try:
            return await asyncio.wait_for(
                self._results_queue.get(),
                timeout=timeout or self.config.collect_timeout,
            )
        except asyncio.TimeoutError:
            return None

    async def cancel(self, subagent_id: str) -> bool:
        """Cancel a running subagent."""
        task = self._tasks.get(subagent_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    async def cancel_all(self) -> int:
        """Cancel all running subagents. Returns count cancelled."""
        count = 0
        for task in self._tasks.values():
            if not task.done():
                task.cancel()
                count += 1
        return count

    def get_handle(self, subagent_id: str) -> SubagentHandle | None:
        """Get a subagent handle by ID."""
        return self._handles.get(subagent_id)

    def get_running(self) -> list[SubagentHandle]:
        """Get all currently running subagents."""
        return [h for h in self._handles.values() if h.status == SubagentStatus.RUNNING]

    def get_completed(self) -> list[SubagentHandle]:
        """Get all completed subagents."""
        return [
            h for h in self._handles.values()
            if h.status in (SubagentStatus.COMPLETED, SubagentStatus.FAILED, SubagentStatus.TIMED_OUT)
        ]

    def get_stats(self) -> dict[str, int]:
        """Get subagent statistics."""
        statuses: dict[str, int] = {}
        for h in self._handles.values():
            statuses[h.status.value] = statuses.get(h.status.value, 0) + 1
        return {
            "total": len(self._handles),
            **statuses,
        }

    def clear(self) -> None:
        """Clear all handles and tasks."""
        self._handles.clear()
        self._tasks.clear()
