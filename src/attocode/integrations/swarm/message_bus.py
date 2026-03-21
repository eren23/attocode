"""Inter-worker message bus for swarm communication.

Typed message protocol that augments SharedBlackboard with structured
inter-worker messaging.  SQLite-backed for persistence across crashes.

Message types:
- ``worker_done``    — worker reports completion with summary
- ``file_locked``    — worker claims exclusive access to a file
- ``context_share``  — worker shares context/findings with siblings
- ``escalation``     — worker escalates an issue to orchestrator
- ``file_unlocked``  — worker releases file lock
- ``request``        — worker requests information from a sibling

Usage:
    bus = SwarmMessageBus(":memory:")  # or path to SQLite file
    bus.send("task-1", "file_locked", {"path": "src/main.py"})
    messages = bus.receive("task-2")  # get all unread messages for task-2
    locks = bus.get_file_locks()      # see who has what locked
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class MessageType(StrEnum):
    """Types of inter-worker messages."""

    WORKER_DONE = "worker_done"
    FILE_LOCKED = "file_locked"
    FILE_UNLOCKED = "file_unlocked"
    CONTEXT_SHARE = "context_share"
    ESCALATION = "escalation"
    REQUEST = "request"


@dataclass(slots=True)
class SwarmMessage:
    """A single message in the bus."""

    id: int
    sender: str  # task_id or "orchestrator"
    recipient: str  # task_id, "all", or "orchestrator"
    type: MessageType
    payload: dict[str, Any]
    timestamp: float
    read: bool = False


@dataclass(slots=True)
class FileLock:
    """A file lock held by a worker."""

    path: str
    holder: str  # task_id
    acquired_at: float


class SwarmMessageBus:
    """SQLite-backed message bus for inter-worker communication.

    Workers can send typed messages to specific recipients, broadcast
    to all workers, or escalate to the orchestrator. File locking is
    supported as a first-class concept.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._connect()

    def _connect(self) -> None:
        """Initialize database connection and schema."""
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT NOT NULL,
                recipient TEXT NOT NULL,
                type TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                timestamp REAL NOT NULL,
                read INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_messages_recipient
                ON messages(recipient, read);

            CREATE TABLE IF NOT EXISTS file_locks (
                path TEXT PRIMARY KEY,
                holder TEXT NOT NULL,
                acquired_at REAL NOT NULL
            );
        """)
        self._conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        """Return the active connection or raise if closed."""
        if self._conn is None:
            raise RuntimeError("SwarmMessageBus connection is closed")
        return self._conn

    def send(
        self,
        sender: str,
        msg_type: str | MessageType,
        payload: dict[str, Any] | None = None,
        recipient: str = "all",
    ) -> int:
        """Send a message.

        Args:
            sender: Task ID of the sender.
            msg_type: Message type (see MessageType enum).
            payload: Message payload dict.
            recipient: Target task ID, ``"all"`` for broadcast,
                or ``"orchestrator"`` for escalation.

        Returns:
            Message ID.
        """
        conn = self._get_conn()

        now = time.time()
        payload = payload or {}

        # Handle file lock/unlock side effects
        if msg_type == MessageType.FILE_LOCKED:
            path = payload.get("path", "")
            if path:
                self._acquire_lock(path, sender, now)
        elif msg_type == MessageType.FILE_UNLOCKED:
            path = payload.get("path", "")
            if path:
                self._release_lock(path, sender)

        cursor = conn.execute(
            """INSERT INTO messages (sender, recipient, type, payload_json, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            (sender, recipient, str(msg_type), json.dumps(payload), now),
        )
        conn.commit()

        msg_id = cursor.lastrowid or 0
        logger.debug(
            "Message #%d: %s -> %s [%s]", msg_id, sender, recipient, msg_type,
        )
        return msg_id

    def receive(
        self,
        recipient: str,
        *,
        msg_type: str | MessageType | None = None,
        unread_only: bool = True,
        mark_read: bool = True,
        limit: int = 100,
    ) -> list[SwarmMessage]:
        """Receive messages for a recipient.

        Args:
            recipient: Task ID to receive messages for. Also matches
                ``"all"`` broadcast messages.
            msg_type: Filter by message type.
            unread_only: Only return unread messages.
            mark_read: Mark returned messages as read.
            limit: Maximum messages to return.

        Returns:
            List of SwarmMessage objects.
        """
        conn = self._get_conn()

        conditions = ["(recipient = ? OR recipient = 'all')"]
        params: list[Any] = [recipient]

        if unread_only:
            conditions.append("read = 0")

        if msg_type is not None:
            conditions.append("type = ?")
            params.append(str(msg_type))

        where = " AND ".join(conditions)
        params.append(limit)

        cursor = conn.execute(
            f"""SELECT id, sender, recipient, type, payload_json, timestamp, read
                FROM messages WHERE {where}
                ORDER BY timestamp ASC LIMIT ?""",
            params,
        )

        messages: list[SwarmMessage] = []
        ids_to_mark: list[int] = []

        for row in cursor.fetchall():
            msg = SwarmMessage(
                id=row[0],
                sender=row[1],
                recipient=row[2],
                type=MessageType(row[3]),
                payload=json.loads(row[4]),
                timestamp=row[5],
                read=bool(row[6]),
            )
            messages.append(msg)
            if mark_read and not msg.read:
                ids_to_mark.append(msg.id)

        if ids_to_mark:
            placeholders = ",".join("?" for _ in ids_to_mark)
            conn.execute(
                f"UPDATE messages SET read = 1 WHERE id IN ({placeholders})",
                ids_to_mark,
            )
            conn.commit()

        return messages

    def get_escalations(self, *, unread_only: bool = True) -> list[SwarmMessage]:
        """Get escalation messages for the orchestrator."""
        return self.receive(
            "orchestrator",
            msg_type=MessageType.ESCALATION,
            unread_only=unread_only,
        )

    def broadcast_done(
        self,
        sender: str,
        summary: str,
        files_modified: list[str] | None = None,
    ) -> int:
        """Broadcast a worker_done message."""
        return self.send(
            sender,
            MessageType.WORKER_DONE,
            {
                "summary": summary,
                "files_modified": files_modified or [],
            },
            recipient="all",
        )

    def share_context(
        self,
        sender: str,
        recipient: str,
        context: str,
        context_type: str = "finding",
    ) -> int:
        """Share context/findings with a specific worker."""
        return self.send(
            sender,
            MessageType.CONTEXT_SHARE,
            {"context": context, "context_type": context_type},
            recipient=recipient,
        )

    def escalate(
        self,
        sender: str,
        issue: str,
        severity: str = "medium",
    ) -> int:
        """Escalate an issue to the orchestrator."""
        return self.send(
            sender,
            MessageType.ESCALATION,
            {"issue": issue, "severity": severity},
            recipient="orchestrator",
        )

    # ---- File Locking ----

    def lock_file(self, path: str, holder: str) -> bool:
        """Attempt to acquire a file lock.

        Returns True if lock acquired, False if already held by another.
        """
        existing = self.get_file_lock(path)
        if existing and existing.holder != holder:
            return False

        self.send(holder, MessageType.FILE_LOCKED, {"path": path}, recipient="all")
        return True

    def unlock_file(self, path: str, holder: str) -> bool:
        """Release a file lock.

        Returns True if released, False if not held by this holder.
        """
        existing = self.get_file_lock(path)
        if existing and existing.holder != holder:
            return False

        self.send(holder, MessageType.FILE_UNLOCKED, {"path": path}, recipient="all")
        return True

    def get_file_lock(self, path: str) -> FileLock | None:
        """Get the current lock holder for a file."""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT path, holder, acquired_at FROM file_locks WHERE path = ?",
            (path,),
        )
        row = cursor.fetchone()
        if row:
            return FileLock(path=row[0], holder=row[1], acquired_at=row[2])
        return None

    def get_file_locks(self) -> list[FileLock]:
        """Get all current file locks."""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT path, holder, acquired_at FROM file_locks ORDER BY acquired_at",
        )
        return [
            FileLock(path=row[0], holder=row[1], acquired_at=row[2])
            for row in cursor.fetchall()
        ]

    def release_all_locks(self, holder: str) -> int:
        """Release all file locks held by a worker. Returns count released."""
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM file_locks WHERE holder = ?",
            (holder,),
        )
        conn.commit()
        count = cursor.rowcount
        if count > 0:
            logger.debug("Released %d file locks for %s", count, holder)
        return count

    # ---- Stats ----

    def get_message_count(self, *, unread_only: bool = False) -> int:
        """Get total message count."""
        conn = self._get_conn()
        if unread_only:
            cursor = conn.execute("SELECT COUNT(*) FROM messages WHERE read = 0")
        else:
            cursor = conn.execute("SELECT COUNT(*) FROM messages")
        return cursor.fetchone()[0]

    # ---- Lifecycle ----

    def clear(self) -> None:
        """Clear all messages and locks."""
        conn = self._get_conn()
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM file_locks")
        conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    # ---- Internal ----

    def _acquire_lock(self, path: str, holder: str, timestamp: float) -> None:
        """Insert or update a file lock."""
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO file_locks (path, holder, acquired_at) VALUES (?, ?, ?)",
            (path, holder, timestamp),
        )
        conn.commit()

    def _release_lock(self, path: str, holder: str) -> None:
        """Remove a file lock if held by holder."""
        conn = self._get_conn()
        conn.execute(
            "DELETE FROM file_locks WHERE path = ? AND holder = ?",
            (path, holder),
        )
        conn.commit()
