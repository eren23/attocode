"""Pending plan manager: write interception and queuing.

Intercepts file-write operations so they can be reviewed (approved or
rejected) before being flushed to disk.  Supports crash recovery via
an optional session store.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums & data classes
# ---------------------------------------------------------------------------


class WriteStatus(StrEnum):
    """Lifecycle status of a pending write."""

    QUEUED = "queued"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"


@dataclass(slots=True)
class PendingWrite:
    """A file-write operation that is awaiting approval."""

    id: str
    file_path: str
    content: str
    tool_name: str
    queued_at: float = field(default_factory=time.monotonic)
    status: WriteStatus = WriteStatus.QUEUED
    error: str | None = None


# ---------------------------------------------------------------------------
# Session store protocol (optional persistence)
# ---------------------------------------------------------------------------


class _SessionStore(Protocol):
    """Minimal interface for crash-recovery persistence."""

    def save_pending_writes(self, writes: list[dict[str, Any]]) -> None: ...
    def load_pending_writes(self) -> list[dict[str, Any]]: ...
    def clear_pending_writes(self) -> None: ...


# ---------------------------------------------------------------------------
# PendingPlanManager
# ---------------------------------------------------------------------------


class PendingPlanManager:
    """Queues file-write operations for approval before execution.

    Typical flow::

        mgr.queue_write("src/foo.py", code, "write_file")
        # ... user reviews ...
        mgr.approve_all()           # writes are flushed to disk
        # or
        mgr.reject_all("not ready") # writes are discarded

    Individual writes can be approved or rejected with
    :meth:`approve_one` and :meth:`reject_one`.
    """

    def __init__(self, session_store: _SessionStore | None = None) -> None:
        self._writes: dict[str, PendingWrite] = {}
        self._session_store = session_store

    # -- Queuing -----------------------------------------------------------

    def queue_write(
        self,
        file_path: str,
        content: str,
        tool_name: str = "write_file",
    ) -> PendingWrite:
        """Queue a write operation and return the :class:`PendingWrite`."""
        write = PendingWrite(
            id=uuid.uuid4().hex[:12],
            file_path=file_path,
            content=content,
            tool_name=tool_name,
        )
        self._writes[write.id] = write
        self._persist()
        logger.debug(
            "Queued write %s for %s (%d bytes)",
            write.id,
            file_path,
            len(content),
        )
        return write

    # -- Queries -----------------------------------------------------------

    def get_pending_writes(self) -> list[PendingWrite]:
        """Return all writes that are still queued (not yet decided)."""
        return [
            w for w in self._writes.values() if w.status == WriteStatus.QUEUED
        ]

    def has_pending(self) -> bool:
        """Return ``True`` if any queued writes exist."""
        return any(w.status == WriteStatus.QUEUED for w in self._writes.values())

    def get_write(self, write_id: str) -> PendingWrite | None:
        """Look up a write by ID."""
        return self._writes.get(write_id)

    def get_all(self) -> list[PendingWrite]:
        """Return every tracked write regardless of status."""
        return list(self._writes.values())

    # -- Approval / rejection (batch) --------------------------------------

    def approve_all(self) -> list[PendingWrite]:
        """Approve and execute all queued writes. Returns executed writes."""
        executed: list[PendingWrite] = []
        for write in list(self._writes.values()):
            if write.status == WriteStatus.QUEUED:
                self._execute_write(write)
                executed.append(write)
        self._persist()
        return executed

    def reject_all(self, reason: str = "") -> list[PendingWrite]:
        """Reject all queued writes. Returns rejected writes."""
        rejected: list[PendingWrite] = []
        for write in list(self._writes.values()):
            if write.status == WriteStatus.QUEUED:
                write.status = WriteStatus.REJECTED
                write.error = reason or None
                rejected.append(write)
        self._persist()
        logger.info("Rejected %d pending writes: %s", len(rejected), reason)
        return rejected

    # -- Approval / rejection (individual) ---------------------------------

    def approve_one(self, write_id: str) -> PendingWrite | None:
        """Approve and execute a single write. Returns the write or ``None``."""
        write = self._writes.get(write_id)
        if write is None or write.status != WriteStatus.QUEUED:
            return None
        self._execute_write(write)
        self._persist()
        return write

    def reject_one(self, write_id: str, reason: str = "") -> PendingWrite | None:
        """Reject a single write. Returns the write or ``None``."""
        write = self._writes.get(write_id)
        if write is None or write.status != WriteStatus.QUEUED:
            return None
        write.status = WriteStatus.REJECTED
        write.error = reason or None
        self._persist()
        return write

    # -- Crash recovery ----------------------------------------------------

    def crash_recovery(
        self,
        session_store: _SessionStore | None = None,
    ) -> list[PendingWrite]:
        """Recover pending writes from the session store.

        Returns the list of writes that were still queued at crash time.
        """
        store = session_store or self._session_store
        if store is None:
            return []

        try:
            raw_writes = store.load_pending_writes()
        except Exception:
            logger.warning("Failed to load pending writes for crash recovery")
            return []

        recovered: list[PendingWrite] = []
        for raw in raw_writes:
            status_val = raw.get("status", WriteStatus.QUEUED)
            try:
                status = WriteStatus(status_val)
            except ValueError:
                status = WriteStatus.QUEUED

            write = PendingWrite(
                id=raw.get("id", uuid.uuid4().hex[:12]),
                file_path=raw.get("file_path", ""),
                content=raw.get("content", ""),
                tool_name=raw.get("tool_name", "write_file"),
                queued_at=raw.get("queued_at", time.monotonic()),
                status=status,
            )
            self._writes[write.id] = write
            if write.status == WriteStatus.QUEUED:
                recovered.append(write)

        logger.info(
            "Crash recovery: loaded %d writes, %d still queued",
            len(raw_writes),
            len(recovered),
        )
        return recovered

    # -- Housekeeping ------------------------------------------------------

    def clear(self) -> None:
        """Remove all tracked writes."""
        self._writes.clear()
        if self._session_store:
            try:
                self._session_store.clear_pending_writes()
            except Exception:
                logger.warning("Failed to clear pending writes from session store")

    # -- Private helpers ---------------------------------------------------

    def _execute_write(self, write: PendingWrite) -> None:
        """Flush a single write to disk."""
        try:
            dir_path = os.path.dirname(write.file_path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            with open(write.file_path, "w", encoding="utf-8") as f:
                f.write(write.content)
            write.status = WriteStatus.EXECUTED
            logger.debug("Executed write %s -> %s", write.id, write.file_path)
        except OSError as exc:
            write.status = WriteStatus.FAILED
            write.error = str(exc)
            logger.error("Write %s failed: %s", write.id, exc)

    def _persist(self) -> None:
        """Persist current queue to session store (if available)."""
        if self._session_store is None:
            return
        try:
            payload = [
                {
                    "id": w.id,
                    "file_path": w.file_path,
                    "content": w.content,
                    "tool_name": w.tool_name,
                    "queued_at": w.queued_at,
                    "status": w.status.value,
                }
                for w in self._writes.values()
            ]
            self._session_store.save_pending_writes(payload)
        except Exception:
            logger.warning("Failed to persist pending writes")
