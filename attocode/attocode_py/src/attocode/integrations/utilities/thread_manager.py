"""Session thread and fork management.

Manages multiple conversation threads (branches) within a session,
allowing users to fork, switch, and merge conversation histories.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from attocode.types.messages import Message


@dataclass(slots=True)
class ThreadInfo:
    """Metadata for a conversation thread."""

    thread_id: str
    label: str
    parent_id: str | None = None
    fork_point: int = 0  # Message index where fork occurred
    created_at: float = 0.0
    last_active: float = 0.0
    message_count: int = 0
    is_active: bool = True

    def __post_init__(self) -> None:
        if self.created_at == 0.0:
            self.created_at = time.time()
        if self.last_active == 0.0:
            self.last_active = self.created_at


@dataclass(slots=True)
class ThreadSnapshot:
    """A snapshot of a thread's state for persistence."""

    info: ThreadInfo
    messages: list[Message | Any]


class ThreadManager:
    """Manage conversation threads within a session.

    Supports creating forks from any point in the conversation,
    switching between threads, and listing thread history.

    Args:
        session_id: The parent session ID.
    """

    def __init__(self, session_id: str = "") -> None:
        self._session_id = session_id
        self._threads: dict[str, ThreadInfo] = {}
        self._thread_messages: dict[str, list[Message | Any]] = {}
        self._active_thread_id: str | None = None

        # Create the main thread
        main = ThreadInfo(
            thread_id="main",
            label="Main",
        )
        self._threads["main"] = main
        self._thread_messages["main"] = []
        self._active_thread_id = "main"

    @property
    def active_thread(self) -> ThreadInfo | None:
        if self._active_thread_id:
            return self._threads.get(self._active_thread_id)
        return None

    @property
    def active_thread_id(self) -> str:
        return self._active_thread_id or "main"

    @property
    def thread_count(self) -> int:
        return len(self._threads)

    def create_fork(
        self,
        label: str = "",
        *,
        fork_at: int | None = None,
        messages: list[Message | Any] | None = None,
    ) -> ThreadInfo:
        """Create a new thread forking from the current thread.

        Args:
            label: Human-readable label for the fork.
            fork_at: Message index to fork at (default: current length).
            messages: Current messages to copy up to fork_at.

        Returns:
            The new ThreadInfo.
        """
        thread_id = f"fork-{uuid.uuid4().hex[:8]}"
        parent_id = self._active_thread_id or "main"

        current_messages = messages or self._thread_messages.get(parent_id, [])
        fork_point = fork_at if fork_at is not None else len(current_messages)

        info = ThreadInfo(
            thread_id=thread_id,
            label=label or f"Fork from {parent_id}",
            parent_id=parent_id,
            fork_point=fork_point,
            message_count=fork_point,
        )

        self._threads[thread_id] = info
        self._thread_messages[thread_id] = list(current_messages[:fork_point])

        return info

    def switch_thread(self, thread_id: str) -> ThreadInfo:
        """Switch to a different thread.

        Args:
            thread_id: The thread to switch to.

        Returns:
            The ThreadInfo for the switched-to thread.

        Raises:
            KeyError: If thread_id doesn't exist.
        """
        if thread_id not in self._threads:
            raise KeyError(f"Thread {thread_id!r} not found")

        info = self._threads[thread_id]
        info.last_active = time.time()
        self._active_thread_id = thread_id
        return info

    def add_message(
        self,
        message: Message | Any,
        *,
        thread_id: str | None = None,
    ) -> None:
        """Add a message to a thread (default: active thread)."""
        tid = thread_id or self._active_thread_id or "main"
        if tid not in self._thread_messages:
            self._thread_messages[tid] = []
        self._thread_messages[tid].append(message)

        info = self._threads.get(tid)
        if info:
            info.message_count = len(self._thread_messages[tid])
            info.last_active = time.time()

    def get_messages(
        self,
        thread_id: str | None = None,
    ) -> list[Message | Any]:
        """Get messages for a thread (default: active thread)."""
        tid = thread_id or self._active_thread_id or "main"
        return list(self._thread_messages.get(tid, []))

    def list_threads(self, *, active_only: bool = False) -> list[ThreadInfo]:
        """List all threads, optionally filtering by active status."""
        threads = list(self._threads.values())
        if active_only:
            threads = [t for t in threads if t.is_active]
        return sorted(threads, key=lambda t: t.last_active, reverse=True)

    def close_thread(self, thread_id: str) -> bool:
        """Mark a thread as inactive. Returns True if it existed."""
        info = self._threads.get(thread_id)
        if info:
            info.is_active = False
            return True
        return False

    def delete_thread(self, thread_id: str) -> bool:
        """Delete a thread entirely. Cannot delete 'main'."""
        if thread_id == "main":
            return False
        if thread_id in self._threads:
            del self._threads[thread_id]
            self._thread_messages.pop(thread_id, None)
            if self._active_thread_id == thread_id:
                self._active_thread_id = "main"
            return True
        return False

    def get_thread_tree(self) -> dict[str, list[str]]:
        """Get the thread parentage tree.

        Returns:
            Dict mapping parent_id to list of child thread IDs.
        """
        tree: dict[str, list[str]] = {}
        for tid, info in self._threads.items():
            parent = info.parent_id or "root"
            tree.setdefault(parent, []).append(tid)
        return tree

    def snapshot(self, thread_id: str | None = None) -> ThreadSnapshot | None:
        """Create a snapshot of a thread for persistence."""
        tid = thread_id or self._active_thread_id or "main"
        info = self._threads.get(tid)
        if not info:
            return None
        return ThreadSnapshot(
            info=info,
            messages=list(self._thread_messages.get(tid, [])),
        )
