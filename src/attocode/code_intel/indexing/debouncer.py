"""Per-project file change debouncer.

Collects file change notifications and fires a batch update after a
configurable quiet period (default 500ms). Prevents redundant re-parsing
when a single tool call writes multiple files.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

# Type alias for the batch handler
# handler(project_id, branch, paths, files)
BatchHandler = Callable[[str, str, list[str], dict[str, str] | None], Awaitable[None]]


_MAX_PENDING_PER_KEY = 10_000  # M9: cap pending paths to prevent unbounded memory


class FileChangeDebouncer:
    """Debounces file change notifications per (project, branch).

    Usage:
        debouncer = FileChangeDebouncer(handler=my_batch_handler)
        await debouncer.notify("proj-1", "feat/x", ["src/a.py", "src/b.py"])
        # ... 200ms later ...
        await debouncer.notify("proj-1", "feat/x", ["src/c.py"])
        # handler fires ~500ms after last notify with all 3 paths
    """

    def __init__(
        self,
        handler: BatchHandler,
        delay_seconds: float = 0.5,
        max_pending_per_key: int = _MAX_PENDING_PER_KEY,
    ) -> None:
        self._handler = handler
        self._delay = delay_seconds
        self._max_pending = max_pending_per_key
        # Pending paths per (project_id, branch)
        self._pending: dict[tuple[str, str], set[str]] = defaultdict(set)
        # Pending file contents per (project_id, branch) — path → base64 content
        self._pending_files: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
        # Active timers per (project_id, branch)
        self._timers: dict[tuple[str, str], asyncio.Task] = {}

    async def notify(self, project_id: str, branch: str, paths: list[str], *, files: dict[str, str] | None = None) -> None:
        """Add paths to the pending batch for (project_id, branch).

        Resets the debounce timer. Handler fires after `delay_seconds` of quiet.
        M9: Caps pending paths per key at max_pending_per_key.
        """
        key = (project_id, branch)
        pending = self._pending[key]
        pending.update(paths)

        # Accumulate file contents (latest wins per path)
        if files:
            self._pending_files[key].update(files)

        # M9: cap pending paths to prevent unbounded memory
        if len(pending) > self._max_pending:
            logger.warning(
                "Debouncer: pending paths for %s/%s exceeded %d, truncating",
                project_id, branch, self._max_pending,
            )
            # Keep first max_pending items (arbitrary but bounded)
            excess = len(pending) - self._max_pending
            for _ in range(excess):
                pending.pop()

        # Cancel existing timer if any
        if key in self._timers:
            self._timers[key].cancel()

        # Start new timer
        self._timers[key] = asyncio.create_task(self._fire_after_delay(key))

    async def _fire_after_delay(self, key: tuple[str, str]) -> None:
        """Wait for the quiet period, then fire the batch handler."""
        try:
            await asyncio.sleep(self._delay)
        except asyncio.CancelledError:
            return

        # M1 fix: copy batch, then clear pending — prevents lost updates
        # if new paths arrive between pop and handler execution
        batch = self._pending.pop(key, set())
        files = self._pending_files.pop(key, None) or None
        paths = list(batch)
        self._timers.pop(key, None)

        if not paths:
            return

        project_id, branch = key
        logger.info(
            "Debouncer firing for %s/%s: %d files",
            project_id, branch, len(paths),
        )
        try:
            await self._handler(project_id, branch, paths, files)
        except Exception:
            logger.exception(
                "Error in debounce handler for %s/%s",
                project_id, branch,
            )

    async def flush(self, project_id: str, branch: str) -> None:
        """Force-fire pending batch immediately (e.g., on shutdown)."""
        key = (project_id, branch)
        if key in self._timers:
            self._timers[key].cancel()
            self._timers.pop(key, None)
        paths = list(self._pending.pop(key, set()))
        files = self._pending_files.pop(key, None) or None
        if paths:
            await self._handler(project_id, branch, paths, files)

    async def shutdown(self) -> None:
        """Cancel all pending timers. Call on app shutdown."""
        for task in self._timers.values():
            task.cancel()
        self._timers.clear()
        self._pending.clear()
        self._pending_files.clear()

    @property
    def pending_count(self) -> int:
        """Number of pending batches."""
        return len(self._pending)
