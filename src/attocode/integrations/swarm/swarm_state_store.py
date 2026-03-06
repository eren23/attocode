"""Swarm state store for checkpoint persistence and resume.

Persists swarm execution state (task queue, worker status, checkpoints)
to enable session resume after interruption.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from attocode.integrations.swarm.types import (
    SwarmCheckpoint,
    SwarmPhase,
    SwarmTask,
    SwarmTaskStatus,
)


@dataclass(slots=True)
class SwarmStateSnapshot:
    """Complete snapshot of swarm state for persistence."""

    session_id: str
    phase: str
    timestamp: float
    task_queue: list[dict[str, Any]]
    worker_status: dict[str, Any]
    checkpoint: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None


class SwarmStateStore:
    """Persists swarm state to SQLite for session resume.

    Enables:
    - Saving swarm checkpoints at key milestones
    - Resuming interrupted swarm sessions
    - Listing available sessions for resume
    - Cleaning up old sessions
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS swarm_sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    phase TEXT NOT NULL DEFAULT 'initializing',
                    task_description TEXT DEFAULT '',
                    total_tasks INTEGER DEFAULT 0,
                    completed_tasks INTEGER DEFAULT 0,
                    config_json TEXT DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS swarm_checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    phase TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES swarm_sessions(session_id)
                );

                CREATE INDEX IF NOT EXISTS idx_checkpoints_session
                    ON swarm_checkpoints(session_id, created_at DESC);
            """)

    def save_session(
        self,
        session_id: str,
        phase: str,
        task_description: str = "",
        total_tasks: int = 0,
        completed_tasks: int = 0,
        config: dict[str, Any] | None = None,
    ) -> None:
        """Create or update a swarm session record."""
        now = time.time()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                INSERT INTO swarm_sessions (session_id, created_at, updated_at, phase, task_description, total_tasks, completed_tasks, config_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    updated_at = ?, phase = ?, total_tasks = ?, completed_tasks = ?
            """, (
                session_id, now, now, phase, task_description,
                total_tasks, completed_tasks, json.dumps(config or {}),
                now, phase, total_tasks, completed_tasks,
            ))

    def save_checkpoint(self, session_id: str, snapshot: SwarmStateSnapshot) -> int:
        """Save a checkpoint for a session. Returns checkpoint ID."""
        now = time.time()
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO swarm_checkpoints (session_id, created_at, phase, snapshot_json)
                VALUES (?, ?, ?, ?)
            """, (
                session_id, now, snapshot.phase,
                json.dumps({
                    "session_id": snapshot.session_id,
                    "phase": snapshot.phase,
                    "timestamp": snapshot.timestamp,
                    "task_queue": snapshot.task_queue,
                    "worker_status": snapshot.worker_status,
                    "checkpoint": snapshot.checkpoint,
                    "config": snapshot.config,
                    "metrics": snapshot.metrics,
                }),
            ))
            return cursor.lastrowid or 0

    def load_latest_checkpoint(self, session_id: str) -> SwarmStateSnapshot | None:
        """Load the most recent checkpoint for a session."""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute("""
                SELECT snapshot_json FROM swarm_checkpoints
                WHERE session_id = ?
                ORDER BY created_at DESC LIMIT 1
            """, (session_id,)).fetchone()

        if row is None:
            return None

        data = json.loads(row[0])
        return SwarmStateSnapshot(
            session_id=data.get("session_id", session_id),
            phase=data.get("phase", "unknown"),
            timestamp=data.get("timestamp", 0.0),
            task_queue=data.get("task_queue", []),
            worker_status=data.get("worker_status", {}),
            checkpoint=data.get("checkpoint"),
            config=data.get("config"),
            metrics=data.get("metrics"),
        )

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        """List available swarm sessions for resume."""
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute("""
                SELECT session_id, created_at, updated_at, phase,
                       task_description, total_tasks, completed_tasks
                FROM swarm_sessions
                ORDER BY updated_at DESC
                LIMIT ?
            """, (limit,)).fetchall()

        return [
            {
                "session_id": r[0],
                "created_at": r[1],
                "updated_at": r[2],
                "phase": r[3],
                "task_description": r[4],
                "total_tasks": r[5],
                "completed_tasks": r[6],
            }
            for r in rows
        ]

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Get session details."""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute("""
                SELECT session_id, created_at, updated_at, phase,
                       task_description, total_tasks, completed_tasks, config_json
                FROM swarm_sessions WHERE session_id = ?
            """, (session_id,)).fetchone()

        if row is None:
            return None

        return {
            "session_id": row[0],
            "created_at": row[1],
            "updated_at": row[2],
            "phase": row[3],
            "task_description": row[4],
            "total_tasks": row[5],
            "completed_tasks": row[6],
            "config": json.loads(row[7]) if row[7] else {},
        }

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and its checkpoints."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM swarm_checkpoints WHERE session_id = ?", (session_id,))
            cursor = conn.execute("DELETE FROM swarm_sessions WHERE session_id = ?", (session_id,))
            return cursor.rowcount > 0

    def cleanup_old_sessions(self, max_age_seconds: float = 86400 * 7) -> int:
        """Delete sessions older than max_age. Returns count deleted."""
        cutoff = time.time() - max_age_seconds
        with sqlite3.connect(self._db_path) as conn:
            # Get old session IDs
            rows = conn.execute(
                "SELECT session_id FROM swarm_sessions WHERE updated_at < ?",
                (cutoff,),
            ).fetchall()

            if not rows:
                return 0

            ids = [r[0] for r in rows]
            placeholders = ",".join("?" * len(ids))
            conn.execute(f"DELETE FROM swarm_checkpoints WHERE session_id IN ({placeholders})", ids)
            cursor = conn.execute(f"DELETE FROM swarm_sessions WHERE session_id IN ({placeholders})", ids)
            return cursor.rowcount
