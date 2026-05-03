"""SQLite-backed persistent index for symbols, references, and dependencies.

Stores parsed AST data so that ASTService can skip re-parsing unchanged
files on restart.  Modeled after ``VectorStore`` (WAL mode, mtime tracking).

Database location: ``.attocode/index/symbols.db``
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "3"


@dataclass(slots=True)
class StoredFile:
    """Cached file metadata."""

    path: str
    mtime: float
    size: int
    language: str
    line_count: int
    content_hash: str


@dataclass(slots=True)
class StoredSymbol:
    """A persisted symbol definition."""

    id: int
    file_path: str
    name: str
    qualified_name: str
    kind: str
    line: int
    end_line: int
    source: str  # "tree-sitter" | "lsp"


@dataclass(slots=True)
class StoredReference:
    """A persisted symbol reference."""

    id: int
    file_path: str
    symbol_name: str
    ref_kind: str
    line: int
    column: int
    source: str  # "tree-sitter" | "lsp"
    caller_qualified_name: str = ""  # enclosing function/method (call-graph edge)


@dataclass(slots=True)
class IndexStore:
    """SQLite-backed persistent index store.

    Usage::

        store = IndexStore(db_path=".attocode/index/symbols.db")
        store.save_file(StoredFile(...))
        store.save_symbols("src/main.py", [StoredSymbol(...)])
        stale = store.get_stale_files({"src/main.py": 1234567.0})
    """

    db_path: str
    _conn: sqlite3.Connection | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    # When the on-disk schema differed from ``SCHEMA_VERSION`` at startup,
    # we wipe and rebuild — this records the prior version so callers
    # (e.g. ``readiness_report``) can surface a "schema migrated, full
    # re-index pending" hint instead of leaving users guessing why the
    # first request after upgrade is slow.
    _schema_rebuilt_from: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()
        self._check_schema_version()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("IndexStore connection is closed")
        return self._conn

    def _create_tables(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                mtime REAL NOT NULL,
                size INTEGER NOT NULL,
                language TEXT NOT NULL DEFAULT '',
                line_count INTEGER NOT NULL DEFAULT 0,
                content_hash TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS symbols (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE,
                name TEXT NOT NULL,
                qualified_name TEXT NOT NULL,
                kind TEXT NOT NULL,
                line INTEGER NOT NULL DEFAULT 0,
                end_line INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'tree-sitter'
            );

            CREATE TABLE IF NOT EXISTS refs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE,
                symbol_name TEXT NOT NULL,
                ref_kind TEXT NOT NULL DEFAULT 'call',
                line INTEGER NOT NULL DEFAULT 0,
                col INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'tree-sitter',
                caller_qualified_name TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS dependencies (
                source_path TEXT NOT NULL,
                target_path TEXT NOT NULL,
                PRIMARY KEY (source_path, target_path)
            );

            CREATE INDEX IF NOT EXISTS ix_symbols_name ON symbols(name);
            CREATE INDEX IF NOT EXISTS ix_symbols_qname ON symbols(qualified_name);
            CREATE INDEX IF NOT EXISTS ix_symbols_file ON symbols(file_path);
            CREATE INDEX IF NOT EXISTS ix_refs_symbol ON refs(symbol_name);
            CREATE INDEX IF NOT EXISTS ix_refs_file ON refs(file_path);
            CREATE INDEX IF NOT EXISTS ix_refs_caller ON refs(caller_qualified_name);
            CREATE INDEX IF NOT EXISTS ix_deps_target ON dependencies(target_path);
        """)
        conn.commit()

    def _check_schema_version(self) -> None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
        if row:
            if row[0] != SCHEMA_VERSION:
                # Schema migrations clear all persisted index data — the
                # first request after upgrade will trigger a full
                # re-index that may take a while on big repos. We log
                # this prominently and stash the prior version on the
                # store instance + in the SQLite metadata table so a
                # future readiness probe can attribute a slow first
                # request to the rebuild rather than to indexing bugs.
                logger.warning(
                    "Index schema changed (%s -> %s); clearing %r and "
                    "rebuilding from source on next access — full "
                    "re-index will run on demand. Subsequent requests "
                    "may be slow until indexing catches up.",
                    row[0], SCHEMA_VERSION, self.db_path,
                )
                self.clear_all()
                conn.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES ('schema_version', ?)",
                    (SCHEMA_VERSION,),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) "
                    "VALUES ('schema_rebuilt_from_version', ?)",
                    (row[0],),
                )
                conn.commit()
                self._schema_rebuilt_from = row[0]
        else:
            conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES ('schema_version', ?)",
                (SCHEMA_VERSION,),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        conn = self._get_conn()
        with self._lock:
            row = conn.execute(
                "SELECT value FROM metadata WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        conn = self._get_conn()
        with self._lock:
            conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                (key, value),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------

    def save_file(self, f: StoredFile) -> None:
        conn = self._get_conn()
        with self._lock:
            conn.execute(
                """INSERT OR REPLACE INTO files
                   (path, mtime, size, language, line_count, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (f.path, f.mtime, f.size, f.language, f.line_count, f.content_hash),
            )
            conn.commit()

    def save_files_batch(self, files: list[StoredFile]) -> None:
        conn = self._get_conn()
        rows = [
            (f.path, f.mtime, f.size, f.language, f.line_count, f.content_hash)
            for f in files
        ]
        with self._lock:
            conn.executemany(
                """INSERT OR REPLACE INTO files
                   (path, mtime, size, language, line_count, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                rows,
            )
            conn.commit()

    def get_file(self, path: str) -> StoredFile | None:
        conn = self._get_conn()
        with self._lock:
            row = conn.execute(
                "SELECT path, mtime, size, language, line_count, content_hash "
                "FROM files WHERE path = ?",
                (path,),
            ).fetchone()
        if row:
            return StoredFile(*row)
        return None

    def get_all_files(self) -> list[StoredFile]:
        conn = self._get_conn()
        with self._lock:
            rows = conn.execute(
                "SELECT path, mtime, size, language, line_count, content_hash FROM files"
            ).fetchall()
        return [StoredFile(*r) for r in rows]

    def get_stale_files(self, file_mtimes: dict[str, float]) -> list[str]:
        """Return file paths where current mtime > stored mtime (or not indexed)."""
        conn = self._get_conn()
        with self._lock:
            rows = conn.execute("SELECT path, mtime FROM files").fetchall()
        indexed = {row[0]: row[1] for row in rows}
        stale: list[str] = []
        for fpath, current_mtime in file_mtimes.items():
            stored_mtime = indexed.get(fpath)
            if stored_mtime is None or current_mtime > stored_mtime:
                stale.append(fpath)
        return stale

    def get_deleted_files(self, current_files: set[str]) -> list[str]:
        """Return indexed files no longer present on disk."""
        conn = self._get_conn()
        with self._lock:
            rows = conn.execute("SELECT path FROM files").fetchall()
        return [r[0] for r in rows if r[0] not in current_files]

    def remove_file(self, path: str) -> None:
        """Remove a file and all its symbols/refs (CASCADE)."""
        conn = self._get_conn()
        with self._lock:
            conn.execute("DELETE FROM files WHERE path = ?", (path,))
            conn.execute(
                "DELETE FROM dependencies WHERE source_path = ? OR target_path = ?",
                (path, path),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Symbols
    # ------------------------------------------------------------------

    def save_symbols(self, file_path: str, symbols: list[dict[str, Any]]) -> None:
        """Save symbol definitions for a file (replaces existing)."""
        conn = self._get_conn()
        rows = [
            (
                file_path,
                s["name"],
                s["qualified_name"],
                s["kind"],
                s.get("line", 0),
                s.get("end_line", 0),
                s.get("source", "tree-sitter"),
            )
            for s in symbols
        ]
        with self._lock:
            conn.execute("DELETE FROM symbols WHERE file_path = ?", (file_path,))
            conn.executemany(
                """INSERT INTO symbols
                   (file_path, name, qualified_name, kind, line, end_line, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            conn.commit()

    def load_symbols(self, file_path: str | None = None) -> list[StoredSymbol]:
        """Load symbols, optionally filtered by file."""
        conn = self._get_conn()
        with self._lock:
            if file_path:
                rows = conn.execute(
                    "SELECT id, file_path, name, qualified_name, kind, line, end_line, source "
                    "FROM symbols WHERE file_path = ?",
                    (file_path,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, file_path, name, qualified_name, kind, line, end_line, source "
                    "FROM symbols"
                ).fetchall()
        return [
            StoredSymbol(
                id=r[0], file_path=r[1], name=r[2], qualified_name=r[3],
                kind=r[4], line=r[5], end_line=r[6], source=r[7],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # References
    # ------------------------------------------------------------------

    def save_references(self, file_path: str, refs: list[dict[str, Any]]) -> None:
        """Save references for a file (replaces existing)."""
        conn = self._get_conn()
        rows = [
            (
                file_path,
                r["symbol_name"],
                r.get("ref_kind", "call"),
                r.get("line", 0),
                r.get("column", 0),
                r.get("source", "tree-sitter"),
                r.get("caller_qualified_name", ""),
            )
            for r in refs
        ]
        with self._lock:
            conn.execute("DELETE FROM refs WHERE file_path = ?", (file_path,))
            conn.executemany(
                """INSERT INTO refs
                   (file_path, symbol_name, ref_kind, line, col, source,
                    caller_qualified_name)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            conn.commit()

    def load_references(self, file_path: str | None = None) -> list[StoredReference]:
        """Load references, optionally filtered by file."""
        conn = self._get_conn()
        with self._lock:
            if file_path:
                rows = conn.execute(
                    "SELECT id, file_path, symbol_name, ref_kind, line, col, "
                    "source, caller_qualified_name FROM refs WHERE file_path = ?",
                    (file_path,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, file_path, symbol_name, ref_kind, line, col, "
                    "source, caller_qualified_name FROM refs"
                ).fetchall()
        return [
            StoredReference(
                id=r[0], file_path=r[1], symbol_name=r[2], ref_kind=r[3],
                line=r[4], column=r[5], source=r[6], caller_qualified_name=r[7],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Dependencies
    # ------------------------------------------------------------------

    def save_dependencies(self, source_path: str, targets: set[str]) -> None:
        """Save dependency edges from source to targets (replaces existing)."""
        conn = self._get_conn()
        with self._lock:
            conn.execute(
                "DELETE FROM dependencies WHERE source_path = ?", (source_path,)
            )
            if targets:
                conn.executemany(
                    "INSERT OR IGNORE INTO dependencies (source_path, target_path) VALUES (?, ?)",
                    [(source_path, t) for t in targets],
                )
            conn.commit()

    def save_dependencies_batch(self, edges: list[tuple[str, str]]) -> None:
        """Bulk save dependency edges."""
        conn = self._get_conn()
        with self._lock:
            conn.executemany(
                "INSERT OR IGNORE INTO dependencies (source_path, target_path) VALUES (?, ?)",
                edges,
            )
            conn.commit()

    def load_dependencies(self) -> dict[str, set[str]]:
        """Load all dependency edges as forward map."""
        conn = self._get_conn()
        with self._lock:
            rows = conn.execute(
                "SELECT source_path, target_path FROM dependencies"
            ).fetchall()
        forward: dict[str, set[str]] = {}
        for src, tgt in rows:
            forward.setdefault(src, set()).add(tgt)
        return forward

    def clear_dependencies(self) -> None:
        conn = self._get_conn()
        with self._lock:
            conn.execute("DELETE FROM dependencies")
            conn.commit()

    # ------------------------------------------------------------------
    # Bulk operations
    # ------------------------------------------------------------------

    def clear_all(self) -> None:
        """Drop all data (keeps schema)."""
        conn = self._get_conn()
        with self._lock:
            conn.executescript("""
                DELETE FROM refs;
                DELETE FROM symbols;
                DELETE FROM dependencies;
                DELETE FROM files;
            """)
            conn.commit()

    def stats(self) -> dict[str, int]:
        """Return counts of files, symbols, refs, and dependencies."""
        conn = self._get_conn()
        with self._lock:
            files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            symbols = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
            refs = conn.execute("SELECT COUNT(*) FROM refs").fetchone()[0]
            deps = conn.execute("SELECT COUNT(*) FROM dependencies").fetchone()[0]
        return {
            "files": files,
            "symbols": symbols,
            "references": refs,
            "dependencies": deps,
        }

    def record_scan_time(self) -> None:
        """Record current time as last full scan timestamp."""
        self.set_meta("last_full_scan", str(time.time()))

    def get_last_scan_time(self) -> float | None:
        """Return last full scan timestamp, or None if never scanned."""
        val = self.get_meta("last_full_scan")
        return float(val) if val else None

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __del__(self) -> None:
        self.close()
