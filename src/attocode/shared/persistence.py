"""Persistence adapters for shared state.

Provides file-based and SQLite-based backends for saving/loading
shared state across sessions and checkpoints.
"""

from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class PersistenceAdapter(ABC):
    """Abstract persistence interface for shared state."""

    @abstractmethod
    async def save(self, namespace: str, key: str, data: Any) -> None:
        """Save data under a namespace/key pair."""

    @abstractmethod
    async def load(self, namespace: str, key: str) -> Any | None:
        """Load data by namespace/key, returning None if not found."""

    @abstractmethod
    async def list_keys(self, namespace: str) -> list[str]:
        """List all keys in a namespace."""

    @abstractmethod
    async def delete(self, namespace: str, key: str) -> bool:
        """Delete a key. Returns True if it existed."""

    @abstractmethod
    async def exists(self, namespace: str, key: str) -> bool:
        """Check if a key exists."""


class JSONFilePersistenceAdapter(PersistenceAdapter):
    """File-based persistence using JSON files.

    namespace = directory, key = JSON file.
    """

    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, namespace: str, key: str) -> Path:
        ns_dir = self.base_dir / namespace
        ns_dir.mkdir(parents=True, exist_ok=True)
        return ns_dir / f"{key}.json"

    async def save(self, namespace: str, key: str, data: Any) -> None:
        path = self._path(namespace, key)
        path.write_text(json.dumps(data, default=str), encoding="utf-8")

    async def load(self, namespace: str, key: str) -> Any | None:
        path = self._path(namespace, key)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    async def list_keys(self, namespace: str) -> list[str]:
        ns_dir = self.base_dir / namespace
        if not ns_dir.exists():
            return []
        return [p.stem for p in ns_dir.glob("*.json")]

    async def delete(self, namespace: str, key: str) -> bool:
        path = self._path(namespace, key)
        if path.exists():
            path.unlink()
            return True
        return False

    async def exists(self, namespace: str, key: str) -> bool:
        return self._path(namespace, key).exists()


class SQLitePersistenceAdapter(PersistenceAdapter):
    """SQLite-based persistence with namespace partitioning."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._ensure_table()

    def _ensure_table(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS shared_state (
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    data TEXT NOT NULL,
                    updated_at REAL NOT NULL DEFAULT (julianday('now')),
                    PRIMARY KEY (namespace, key)
                )
            """)

    async def save(self, namespace: str, key: str, data: Any) -> None:
        encoded = json.dumps(data, default=str)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO shared_state (namespace, key, data) VALUES (?, ?, ?)",
                (namespace, key, encoded),
            )

    async def load(self, namespace: str, key: str) -> Any | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT data FROM shared_state WHERE namespace = ? AND key = ?",
                (namespace, key),
            ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return None

    async def list_keys(self, namespace: str) -> list[str]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT key FROM shared_state WHERE namespace = ?",
                (namespace,),
            ).fetchall()
        return [r[0] for r in rows]

    async def delete(self, namespace: str, key: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM shared_state WHERE namespace = ? AND key = ?",
                (namespace, key),
            )
        return cursor.rowcount > 0

    async def exists(self, namespace: str, key: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM shared_state WHERE namespace = ? AND key = ? LIMIT 1",
                (namespace, key),
            ).fetchone()
        return row is not None
