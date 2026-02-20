"""SQLite-based session store using aiosqlite.

Provides async persistence for sessions, checkpoints, goals,
tool calls, file changes, compaction history, pending plans,
dead letters, remembered permissions, and usage logs.
"""

from __future__ import annotations

import fnmatch
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiosqlite

# Schema version for migrations
SCHEMA_VERSION = 2

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    task TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    model TEXT DEFAULT '',
    total_tokens INTEGER DEFAULT 0,
    total_cost REAL DEFAULT 0.0,
    iterations INTEGER DEFAULT 0,
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    messages TEXT NOT NULL,
    metrics TEXT DEFAULT '{}',
    created_at REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at REAL NOT NULL,
    completed_at REAL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    iteration INTEGER NOT NULL,
    tool_name TEXT NOT NULL,
    args_json TEXT DEFAULT '{}',
    result_json TEXT DEFAULT '{}',
    duration_ms INTEGER DEFAULT 0,
    danger_level TEXT DEFAULT 'safe',
    approved INTEGER DEFAULT 1,
    timestamp REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS file_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    iteration INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    before_content TEXT DEFAULT '',
    after_content TEXT DEFAULT '',
    tool_name TEXT DEFAULT '',
    timestamp REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS compaction_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    iteration INTEGER NOT NULL,
    messages_before INTEGER NOT NULL,
    messages_after INTEGER NOT NULL,
    tokens_saved INTEGER DEFAULT 0,
    strategy TEXT DEFAULT '',
    timestamp REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS pending_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at REAL NOT NULL,
    resolved_at REAL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS dead_letters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    error_message TEXT DEFAULT '',
    retry_count INTEGER DEFAULT 0,
    created_at REAL NOT NULL,
    last_retry_at REAL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS remembered_permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    pattern TEXT NOT NULL DEFAULT '*',
    permission_type TEXT NOT NULL DEFAULT 'allow',
    granted_at REAL NOT NULL,
    expires_at REAL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS usage_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    iteration INTEGER NOT NULL,
    provider TEXT DEFAULT '',
    model TEXT DEFAULT '',
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_write_tokens INTEGER DEFAULT 0,
    cost REAL DEFAULT 0.0,
    timestamp REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_checkpoints_session ON checkpoints(session_id);
CREATE INDEX IF NOT EXISTS idx_goals_session ON goals(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_tool_calls_session ON tool_calls(session_id);
CREATE INDEX IF NOT EXISTS idx_file_changes_session ON file_changes(session_id);
CREATE INDEX IF NOT EXISTS idx_compaction_history_session ON compaction_history(session_id);
CREATE INDEX IF NOT EXISTS idx_pending_plans_session ON pending_plans(session_id);
CREATE INDEX IF NOT EXISTS idx_dead_letters_session ON dead_letters(session_id);
CREATE INDEX IF NOT EXISTS idx_remembered_permissions_session ON remembered_permissions(session_id);
CREATE INDEX IF NOT EXISTS idx_usage_logs_session ON usage_logs(session_id);
"""


@dataclass(slots=True)
class SessionRecord:
    """A stored session."""

    id: str
    task: str
    status: str = "active"
    created_at: float = 0.0
    updated_at: float = 0.0
    model: str = ""
    total_tokens: int = 0
    total_cost: float = 0.0
    iterations: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CheckpointRecord:
    """A stored checkpoint."""

    id: int
    session_id: str
    messages: list[dict[str, Any]]
    metrics: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0


@dataclass(slots=True)
class GoalRecord:
    """A stored goal."""

    id: int
    session_id: str
    description: str
    status: str = "active"
    created_at: float = 0.0
    completed_at: float | None = None


@dataclass(slots=True)
class ToolCallRecord:
    """A stored tool call."""

    id: int
    session_id: str
    iteration: int
    tool_name: str
    args_json: str = "{}"
    result_json: str = "{}"
    duration_ms: int = 0
    danger_level: str = "safe"
    approved: bool = True
    timestamp: float = 0.0


@dataclass(slots=True)
class FileChangeRecord:
    """A stored file change for undo support."""

    id: int
    session_id: str
    iteration: int
    file_path: str
    before_content: str = ""
    after_content: str = ""
    tool_name: str = ""
    timestamp: float = 0.0


@dataclass(slots=True)
class CompactionRecord:
    """A stored compaction event."""

    id: int
    session_id: str
    iteration: int
    messages_before: int
    messages_after: int
    tokens_saved: int = 0
    strategy: str = ""
    timestamp: float = 0.0


@dataclass(slots=True)
class PendingPlanRecord:
    """A stored pending plan."""

    id: int
    session_id: str
    plan_json: str
    status: str = "pending"
    created_at: float = 0.0
    resolved_at: float | None = None


@dataclass(slots=True)
class DeadLetterRecord:
    """A stored dead letter (failed operation for retry)."""

    id: int
    session_id: str
    operation_type: str
    payload_json: str
    error_message: str = ""
    retry_count: int = 0
    created_at: float = 0.0
    last_retry_at: float | None = None


@dataclass(slots=True)
class PermissionRecord:
    """A stored remembered permission."""

    id: int
    session_id: str
    tool_name: str
    pattern: str = "*"
    permission_type: str = "allow"
    granted_at: float = 0.0
    expires_at: float | None = None


@dataclass(slots=True)
class UsageLogRecord:
    """A stored usage log entry."""

    id: int
    session_id: str
    iteration: int
    provider: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost: float = 0.0
    timestamp: float = 0.0


class SessionStore:
    """Async SQLite session store.

    Provides CRUD operations for sessions, checkpoints, and goals.
    Uses aiosqlite for async database access.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Open the database and create tables."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(CREATE_TABLES_SQL)
        await self._db.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    def _ensure_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("SessionStore not initialized. Call initialize() first.")
        return self._db

    # --- Session operations ---

    async def create_session(
        self,
        session_id: str,
        task: str,
        *,
        model: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SessionRecord:
        """Create a new session."""
        db = self._ensure_db()
        now = time.time()
        meta = json.dumps(metadata or {})
        await db.execute(
            "INSERT INTO sessions (id, task, status, created_at, updated_at, model, metadata) "
            "VALUES (?, ?, 'active', ?, ?, ?, ?)",
            (session_id, task, now, now, model, meta),
        )
        await db.commit()
        return SessionRecord(
            id=session_id,
            task=task,
            status="active",
            created_at=now,
            updated_at=now,
            model=model,
            metadata=metadata or {},
        )

    async def get_session(self, session_id: str) -> SessionRecord | None:
        """Get a session by ID."""
        db = self._ensure_db()
        async with db.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return self._row_to_session(row)

    async def list_sessions(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[SessionRecord]:
        """List sessions, optionally filtered by status."""
        db = self._ensure_db()
        if status:
            query = "SELECT * FROM sessions WHERE status = ? ORDER BY updated_at DESC LIMIT ?"
            params: tuple[Any, ...] = (status, limit)
        else:
            query = "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?"
            params = (limit,)

        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_session(r) for r in rows]

    async def update_session(
        self,
        session_id: str,
        *,
        status: str | None = None,
        total_tokens: int | None = None,
        total_cost: float | None = None,
        iterations: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Update session fields."""
        db = self._ensure_db()
        updates: list[str] = ["updated_at = ?"]
        params: list[Any] = [time.time()]

        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if total_tokens is not None:
            updates.append("total_tokens = ?")
            params.append(total_tokens)
        if total_cost is not None:
            updates.append("total_cost = ?")
            params.append(total_cost)
        if iterations is not None:
            updates.append("iterations = ?")
            params.append(iterations)
        if metadata is not None:
            updates.append("metadata = ?")
            params.append(json.dumps(metadata))

        params.append(session_id)
        await db.execute(
            f"UPDATE sessions SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        await db.commit()

    async def delete_session(self, session_id: str) -> None:
        """Delete a session and its checkpoints and goals."""
        db = self._ensure_db()
        await db.execute("DELETE FROM checkpoints WHERE session_id = ?", (session_id,))
        await db.execute("DELETE FROM goals WHERE session_id = ?", (session_id,))
        await db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        await db.commit()

    # --- Checkpoint operations ---

    async def save_checkpoint(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        metrics: dict[str, Any] | None = None,
    ) -> int:
        """Save a checkpoint for a session.

        Returns the checkpoint ID.
        """
        db = self._ensure_db()
        now = time.time()
        async with db.execute(
            "INSERT INTO checkpoints (session_id, messages, metrics, created_at) "
            "VALUES (?, ?, ?, ?)",
            (session_id, json.dumps(messages), json.dumps(metrics or {}), now),
        ) as cursor:
            checkpoint_id = cursor.lastrowid or 0
        await db.commit()
        return checkpoint_id

    async def load_checkpoint(self, session_id: str) -> CheckpointRecord | None:
        """Load the latest checkpoint for a session."""
        db = self._ensure_db()
        async with db.execute(
            "SELECT * FROM checkpoints WHERE session_id = ? ORDER BY created_at DESC LIMIT 1",
            (session_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return CheckpointRecord(
                id=row["id"],
                session_id=row["session_id"],
                messages=json.loads(row["messages"]),
                metrics=json.loads(row["metrics"]),
                created_at=row["created_at"],
            )

    async def list_checkpoints(self, session_id: str) -> list[CheckpointRecord]:
        """List all checkpoints for a session."""
        db = self._ensure_db()
        async with db.execute(
            "SELECT * FROM checkpoints WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                CheckpointRecord(
                    id=r["id"],
                    session_id=r["session_id"],
                    messages=json.loads(r["messages"]),
                    metrics=json.loads(r["metrics"]),
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    # --- Goal operations ---

    async def create_goal(
        self,
        session_id: str,
        description: str,
    ) -> int:
        """Create a goal. Returns the goal ID."""
        db = self._ensure_db()
        now = time.time()
        async with db.execute(
            "INSERT INTO goals (session_id, description, status, created_at) VALUES (?, ?, 'active', ?)",
            (session_id, description, now),
        ) as cursor:
            goal_id = cursor.lastrowid or 0
        await db.commit()
        return goal_id

    async def complete_goal(self, goal_id: int) -> None:
        """Mark a goal as completed."""
        db = self._ensure_db()
        await db.execute(
            "UPDATE goals SET status = 'completed', completed_at = ? WHERE id = ?",
            (time.time(), goal_id),
        )
        await db.commit()

    async def list_goals(
        self,
        session_id: str,
        *,
        status: str | None = None,
    ) -> list[GoalRecord]:
        """List goals for a session."""
        db = self._ensure_db()
        if status:
            query = "SELECT * FROM goals WHERE session_id = ? AND status = ? ORDER BY created_at"
            params: tuple[Any, ...] = (session_id, status)
        else:
            query = "SELECT * FROM goals WHERE session_id = ? ORDER BY created_at"
            params = (session_id,)

        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [
                GoalRecord(
                    id=r["id"],
                    session_id=r["session_id"],
                    description=r["description"],
                    status=r["status"],
                    created_at=r["created_at"],
                    completed_at=r["completed_at"],
                )
                for r in rows
            ]

    def _row_to_session(self, row: Any) -> SessionRecord:
        """Convert a database row to a SessionRecord."""
        meta = row["metadata"]
        if isinstance(meta, str):
            meta = json.loads(meta)
        return SessionRecord(
            id=row["id"],
            task=row["task"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            model=row["model"] or "",
            total_tokens=row["total_tokens"] or 0,
            total_cost=row["total_cost"] or 0.0,
            iterations=row["iterations"] or 0,
            metadata=meta if isinstance(meta, dict) else {},
        )

    # --- Tool call operations ---

    async def log_tool_call(
        self,
        session_id: str,
        iteration: int,
        tool_name: str,
        args: dict[str, Any] | str,
        result: dict[str, Any] | str,
        duration_ms: int = 0,
        danger_level: str = "safe",
        approved: bool = True,
    ) -> int:
        """Log a tool call. Returns the record ID."""
        db = self._ensure_db()
        now = time.time()
        args_str = json.dumps(args) if isinstance(args, dict) else args
        result_str = json.dumps(result) if isinstance(result, dict) else result
        async with db.execute(
            "INSERT INTO tool_calls "
            "(session_id, iteration, tool_name, args_json, result_json, "
            "duration_ms, danger_level, approved, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                iteration,
                tool_name,
                args_str,
                result_str,
                duration_ms,
                danger_level,
                1 if approved else 0,
                now,
            ),
        ) as cursor:
            record_id = cursor.lastrowid or 0
        await db.commit()
        return record_id

    async def list_tool_calls(self, session_id: str) -> list[ToolCallRecord]:
        """List all tool calls for a session."""
        db = self._ensure_db()
        async with db.execute(
            "SELECT * FROM tool_calls WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                ToolCallRecord(
                    id=r["id"],
                    session_id=r["session_id"],
                    iteration=r["iteration"],
                    tool_name=r["tool_name"],
                    args_json=r["args_json"],
                    result_json=r["result_json"],
                    duration_ms=r["duration_ms"],
                    danger_level=r["danger_level"],
                    approved=bool(r["approved"]),
                    timestamp=r["timestamp"],
                )
                for r in rows
            ]

    # --- File change operations ---

    async def log_file_change(
        self,
        session_id: str,
        iteration: int,
        file_path: str,
        before_content: str,
        after_content: str,
        tool_name: str = "",
    ) -> int:
        """Log a file change for undo support. Returns the record ID."""
        db = self._ensure_db()
        now = time.time()
        async with db.execute(
            "INSERT INTO file_changes "
            "(session_id, iteration, file_path, before_content, after_content, "
            "tool_name, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, iteration, file_path, before_content, after_content, tool_name, now),
        ) as cursor:
            record_id = cursor.lastrowid or 0
        await db.commit()
        return record_id

    async def list_file_changes(self, session_id: str) -> list[FileChangeRecord]:
        """List all file changes for a session."""
        db = self._ensure_db()
        async with db.execute(
            "SELECT * FROM file_changes WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                FileChangeRecord(
                    id=r["id"],
                    session_id=r["session_id"],
                    iteration=r["iteration"],
                    file_path=r["file_path"],
                    before_content=r["before_content"],
                    after_content=r["after_content"],
                    tool_name=r["tool_name"],
                    timestamp=r["timestamp"],
                )
                for r in rows
            ]

    # --- Compaction history operations ---

    async def log_compaction(
        self,
        session_id: str,
        iteration: int,
        messages_before: int,
        messages_after: int,
        tokens_saved: int = 0,
        strategy: str = "",
    ) -> int:
        """Log a compaction event. Returns the record ID."""
        db = self._ensure_db()
        now = time.time()
        async with db.execute(
            "INSERT INTO compaction_history "
            "(session_id, iteration, messages_before, messages_after, "
            "tokens_saved, strategy, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, iteration, messages_before, messages_after, tokens_saved, strategy, now),
        ) as cursor:
            record_id = cursor.lastrowid or 0
        await db.commit()
        return record_id

    async def list_compactions(self, session_id: str) -> list[CompactionRecord]:
        """List all compaction events for a session."""
        db = self._ensure_db()
        async with db.execute(
            "SELECT * FROM compaction_history WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                CompactionRecord(
                    id=r["id"],
                    session_id=r["session_id"],
                    iteration=r["iteration"],
                    messages_before=r["messages_before"],
                    messages_after=r["messages_after"],
                    tokens_saved=r["tokens_saved"],
                    strategy=r["strategy"],
                    timestamp=r["timestamp"],
                )
                for r in rows
            ]

    # --- Pending plan operations ---

    async def save_pending_plan(
        self,
        session_id: str,
        plan_data: dict[str, Any] | list[Any],
    ) -> int:
        """Save a pending plan. Returns the record ID."""
        db = self._ensure_db()
        now = time.time()
        async with db.execute(
            "INSERT INTO pending_plans (session_id, plan_json, status, created_at) "
            "VALUES (?, ?, 'pending', ?)",
            (session_id, json.dumps(plan_data), now),
        ) as cursor:
            record_id = cursor.lastrowid or 0
        await db.commit()
        return record_id

    async def load_pending_plan(self, session_id: str) -> PendingPlanRecord | None:
        """Load the latest pending plan for a session."""
        db = self._ensure_db()
        async with db.execute(
            "SELECT * FROM pending_plans "
            "WHERE session_id = ? AND status = 'pending' "
            "ORDER BY created_at DESC LIMIT 1",
            (session_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return PendingPlanRecord(
                id=row["id"],
                session_id=row["session_id"],
                plan_json=row["plan_json"],
                status=row["status"],
                created_at=row["created_at"],
                resolved_at=row["resolved_at"],
            )

    async def resolve_pending_plan(self, session_id: str, status: str = "resolved") -> None:
        """Resolve all pending plans for a session."""
        db = self._ensure_db()
        now = time.time()
        await db.execute(
            "UPDATE pending_plans SET status = ?, resolved_at = ? "
            "WHERE session_id = ? AND status = 'pending'",
            (status, now, session_id),
        )
        await db.commit()

    # --- Dead letter operations ---

    async def add_dead_letter(
        self,
        session_id: str,
        op_type: str,
        payload: dict[str, Any] | str,
        error: str,
    ) -> int:
        """Add a dead letter (failed operation). Returns the record ID."""
        db = self._ensure_db()
        now = time.time()
        payload_str = json.dumps(payload) if isinstance(payload, dict) else payload
        async with db.execute(
            "INSERT INTO dead_letters "
            "(session_id, operation_type, payload_json, error_message, "
            "retry_count, created_at) "
            "VALUES (?, ?, ?, ?, 0, ?)",
            (session_id, op_type, payload_str, error, now),
        ) as cursor:
            record_id = cursor.lastrowid or 0
        await db.commit()
        return record_id

    async def drain_dead_letters(self, session_id: str) -> list[DeadLetterRecord]:
        """Retrieve all dead letters for a session."""
        db = self._ensure_db()
        async with db.execute(
            "SELECT * FROM dead_letters WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                DeadLetterRecord(
                    id=r["id"],
                    session_id=r["session_id"],
                    operation_type=r["operation_type"],
                    payload_json=r["payload_json"],
                    error_message=r["error_message"],
                    retry_count=r["retry_count"],
                    created_at=r["created_at"],
                    last_retry_at=r["last_retry_at"],
                )
                for r in rows
            ]

    async def retry_dead_letter(self, letter_id: int) -> None:
        """Increment retry count and update last_retry_at for a dead letter."""
        db = self._ensure_db()
        now = time.time()
        await db.execute(
            "UPDATE dead_letters SET retry_count = retry_count + 1, last_retry_at = ? "
            "WHERE id = ?",
            (now, letter_id),
        )
        await db.commit()

    # --- Remembered permission operations ---

    async def grant_permission(
        self,
        session_id: str,
        tool_name: str,
        pattern: str,
        perm_type: str = "allow",
        expires_at: float | None = None,
    ) -> int:
        """Grant a remembered permission. Returns the record ID."""
        db = self._ensure_db()
        now = time.time()
        async with db.execute(
            "INSERT INTO remembered_permissions "
            "(session_id, tool_name, pattern, permission_type, granted_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, tool_name, pattern, perm_type, now, expires_at),
        ) as cursor:
            record_id = cursor.lastrowid or 0
        await db.commit()
        return record_id

    async def check_permission(
        self,
        session_id: str,
        tool_name: str,
        args_str: str = "",
    ) -> bool:
        """Check if a permission exists for a tool and argument pattern.

        Returns True if an 'allow' permission matches, False otherwise.
        Expired permissions are ignored.
        """
        db = self._ensure_db()
        now = time.time()
        async with db.execute(
            "SELECT * FROM remembered_permissions "
            "WHERE session_id = ? AND tool_name = ? AND permission_type = 'allow' "
            "AND (expires_at IS NULL OR expires_at > ?)",
            (session_id, tool_name, now),
        ) as cursor:
            rows = await cursor.fetchall()
            for r in rows:
                pattern = r["pattern"]
                if pattern == "*" or fnmatch.fnmatch(args_str, pattern):
                    return True
        return False

    async def list_permissions(self, session_id: str) -> list[PermissionRecord]:
        """List all remembered permissions for a session."""
        db = self._ensure_db()
        async with db.execute(
            "SELECT * FROM remembered_permissions "
            "WHERE session_id = ? ORDER BY granted_at",
            (session_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                PermissionRecord(
                    id=r["id"],
                    session_id=r["session_id"],
                    tool_name=r["tool_name"],
                    pattern=r["pattern"],
                    permission_type=r["permission_type"],
                    granted_at=r["granted_at"],
                    expires_at=r["expires_at"],
                )
                for r in rows
            ]

    # --- Usage log operations ---

    async def log_usage(
        self,
        session_id: str,
        iteration: int,
        provider: str = "",
        model: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read: int = 0,
        cache_write: int = 0,
        cost: float = 0.0,
    ) -> int:
        """Log token usage for an LLM call. Returns the record ID."""
        db = self._ensure_db()
        now = time.time()
        async with db.execute(
            "INSERT INTO usage_logs "
            "(session_id, iteration, provider, model, input_tokens, output_tokens, "
            "cache_read_tokens, cache_write_tokens, cost, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                iteration,
                provider,
                model,
                input_tokens,
                output_tokens,
                cache_read,
                cache_write,
                cost,
                now,
            ),
        ) as cursor:
            record_id = cursor.lastrowid or 0
        await db.commit()
        return record_id

    async def list_usage_logs(self, session_id: str) -> list[UsageLogRecord]:
        """List all usage logs for a session."""
        db = self._ensure_db()
        async with db.execute(
            "SELECT * FROM usage_logs WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                UsageLogRecord(
                    id=r["id"],
                    session_id=r["session_id"],
                    iteration=r["iteration"],
                    provider=r["provider"],
                    model=r["model"],
                    input_tokens=r["input_tokens"],
                    output_tokens=r["output_tokens"],
                    cache_read_tokens=r["cache_read_tokens"],
                    cache_write_tokens=r["cache_write_tokens"],
                    cost=r["cost"],
                    timestamp=r["timestamp"],
                )
                for r in rows
            ]

    # --- Session resume operations ---

    async def list_recent_sessions(self, limit: int = 10) -> list[dict[str, Any]]:
        """List recent sessions with summary information.

        Returns a list of dicts with keys: id, goal, created_at,
        message_count, last_active, status, model, total_tokens, total_cost.
        """
        db = self._ensure_db()
        async with db.execute(
            """
            SELECT
                s.id,
                s.task,
                s.status,
                s.model,
                s.created_at,
                s.updated_at,
                s.total_tokens,
                s.total_cost,
                s.iterations,
                (SELECT COUNT(*) FROM checkpoints c WHERE c.session_id = s.id) AS checkpoint_count,
                (SELECT COUNT(json_each.value)
                 FROM checkpoints c2, json_each(c2.messages)
                 WHERE c2.session_id = s.id
                 AND c2.id = (
                     SELECT c3.id FROM checkpoints c3
                     WHERE c3.session_id = s.id
                     ORDER BY c3.created_at DESC LIMIT 1
                 )
                ) AS message_count
            FROM sessions s
            ORDER BY s.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "id": r["id"],
                    "goal": r["task"],
                    "status": r["status"],
                    "model": r["model"] or "",
                    "created_at": r["created_at"],
                    "last_active": r["updated_at"],
                    "total_tokens": r["total_tokens"] or 0,
                    "total_cost": r["total_cost"] or 0.0,
                    "iterations": r["iterations"] or 0,
                    "checkpoint_count": r["checkpoint_count"] or 0,
                    "message_count": r["message_count"] or 0,
                }
                for r in rows
            ]

    async def resume_session(self, session_id: str) -> dict[str, Any] | None:
        """Resume a session by loading its full state.

        Returns a dict with keys: session, messages, metrics, goals,
        pending_plan, tool_calls_count, file_changes_count.
        Returns None if the session does not exist.
        """
        db = self._ensure_db()

        # Load session record
        session = await self.get_session(session_id)
        if session is None:
            return None

        # Load latest checkpoint for messages and metrics
        checkpoint = await self.load_checkpoint(session_id)
        messages: list[dict[str, Any]] = []
        metrics: dict[str, Any] = {}
        if checkpoint is not None:
            messages = checkpoint.messages
            metrics = checkpoint.metrics

        # Load active goals
        goals = await self.list_goals(session_id, status="active")

        # Load pending plan if any
        pending_plan = await self.load_pending_plan(session_id)

        # Get counts for tool calls and file changes
        async with db.execute(
            "SELECT COUNT(*) AS cnt FROM tool_calls WHERE session_id = ?",
            (session_id,),
        ) as cursor:
            row = await cursor.fetchone()
            tool_calls_count = row["cnt"] if row else 0

        async with db.execute(
            "SELECT COUNT(*) AS cnt FROM file_changes WHERE session_id = ?",
            (session_id,),
        ) as cursor:
            row = await cursor.fetchone()
            file_changes_count = row["cnt"] if row else 0

        # Mark session as active again
        await self.update_session(session_id, status="active")

        return {
            "session": {
                "id": session.id,
                "task": session.task,
                "status": "active",
                "model": session.model,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
                "total_tokens": session.total_tokens,
                "total_cost": session.total_cost,
                "iterations": session.iterations,
                "metadata": session.metadata,
            },
            "messages": messages,
            "metrics": metrics,
            "goals": [
                {
                    "id": g.id,
                    "description": g.description,
                    "status": g.status,
                }
                for g in goals
            ],
            "pending_plan": (
                {
                    "id": pending_plan.id,
                    "plan": json.loads(pending_plan.plan_json),
                    "status": pending_plan.status,
                    "created_at": pending_plan.created_at,
                }
                if pending_plan
                else None
            ),
            "tool_calls_count": tool_calls_count,
            "file_changes_count": file_changes_count,
        }
