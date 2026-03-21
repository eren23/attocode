"""SQLite-backed vector store for semantic search.

Stores embeddings as packed float32 BLOBs in SQLite. Uses linear scan
for similarity — sufficient for typical codebases (5000 vectors,
384-dim ~2ms scan).
"""

from __future__ import annotations

import logging
import math
import os
import sqlite3
import struct
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class VectorEntry:
    """A stored vector with metadata."""

    id: str
    file_path: str
    chunk_type: str  # "file", "function", "class"
    name: str
    text: str
    vector: list[float]


@dataclass(slots=True)
class SearchResult:
    """A search result with similarity score."""

    id: str
    file_path: str
    chunk_type: str
    name: str
    text: str
    score: float


def _pack_vector(vec: list[float]) -> bytes:
    """Pack a float vector into bytes."""
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack_vector(data: bytes, dim: int) -> list[float]:
    """Unpack bytes into a float vector."""
    return list(struct.unpack(f"{dim}f", data))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


@dataclass(slots=True)
class VectorStore:
    """SQLite-backed vector store.

    Usage::

        store = VectorStore(db_path="vectors.db", dimension=384)
        store.upsert(VectorEntry(id="f1", ...))
        results = store.search(query_vector, top_k=10)
    """

    db_path: str
    dimension: int
    _conn: sqlite3.Connection | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()
        self._validate_dimension()

    def _get_conn(self) -> sqlite3.Connection:
        """Return the active connection or raise if closed."""
        if self._conn is None:
            raise RuntimeError("VectorStore connection is closed")
        return self._conn

    def _create_tables(self) -> None:
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vectors (
                id TEXT PRIMARY KEY,
                file_path TEXT NOT NULL,
                chunk_type TEXT NOT NULL,
                name TEXT NOT NULL,
                text TEXT NOT NULL,
                vector BLOB NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_vectors_file ON vectors(file_path)"
        )
        # Metadata table for tracking index freshness per file
        conn.execute("""
            CREATE TABLE IF NOT EXISTS file_metadata (
                file_path TEXT PRIMARY KEY,
                last_indexed_at REAL NOT NULL,
                file_mtime REAL NOT NULL,
                chunk_count INTEGER NOT NULL DEFAULT 0
            )
        """)
        # Store-level metadata (dimension, etc.)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS store_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.commit()

    def _validate_dimension(self) -> None:
        """Check stored dimension matches current; clear if mismatched."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT value FROM store_metadata WHERE key = 'dimension'"
        ).fetchone()
        if row:
            stored_dim = int(row[0])
            if stored_dim != self.dimension:
                logger.warning(
                    "Embedding dimension changed (%d -> %d), clearing vector index",
                    stored_dim, self.dimension,
                )
                conn.execute("DELETE FROM vectors")
                conn.execute("DELETE FROM file_metadata")
                conn.execute(
                    "INSERT OR REPLACE INTO store_metadata (key, value) VALUES ('dimension', ?)",
                    (str(self.dimension),),
                )
                conn.commit()
        else:
            conn.execute(
                "INSERT OR REPLACE INTO store_metadata (key, value) VALUES ('dimension', ?)",
                (str(self.dimension),),
            )
            conn.commit()

    def upsert(self, entry: VectorEntry) -> None:
        """Insert or update a vector entry."""
        conn = self._get_conn()
        packed = _pack_vector(entry.vector)
        with self._lock:
            conn.execute(
                """INSERT OR REPLACE INTO vectors
                   (id, file_path, chunk_type, name, text, vector)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (entry.id, entry.file_path, entry.chunk_type, entry.name, entry.text, packed),
            )
            conn.commit()

    def upsert_batch(self, entries: list[VectorEntry]) -> None:
        """Batch insert/update vector entries."""
        conn = self._get_conn()
        rows = [
            (e.id, e.file_path, e.chunk_type, e.name, e.text, _pack_vector(e.vector))
            for e in entries
        ]
        with self._lock:
            conn.executemany(
                """INSERT OR REPLACE INTO vectors
                   (id, file_path, chunk_type, name, text, vector)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                rows,
            )
            conn.commit()

    def delete_by_file(self, file_path: str) -> int:
        """Delete all entries for a file. Returns count deleted."""
        conn = self._get_conn()
        with self._lock:
            cursor = conn.execute(
                "DELETE FROM vectors WHERE file_path = ?", (file_path,),
            )
            conn.commit()
            return cursor.rowcount

    def search(
        self,
        query_vector: list[float],
        top_k: int = 10,
        file_filter: str = "",
        existing_files: set[str] | None = None,
    ) -> list[SearchResult]:
        """Search for similar vectors using linear scan.

        Args:
            query_vector: Query embedding vector.
            top_k: Number of results to return.
            file_filter: Optional glob pattern to filter files (e.g. "*.py").
            existing_files: Optional set of file paths that exist on disk.
                When provided, vectors whose file_path is not in this set
                are skipped (filters out stale branch data in local mode).

        Returns:
            Top-k results sorted by similarity score (highest first).
        """
        conn = self._get_conn()
        if not query_vector:
            return []

        if file_filter:
            import fnmatch
            def _file_filter_fn(fp: str) -> bool:
                return fnmatch.fnmatch(fp, file_filter)
        else:
            _file_filter_fn = None

        with self._lock:
            rows = conn.execute(
                "SELECT id, file_path, chunk_type, name, text, vector FROM vectors",
            ).fetchall()

        results: list[SearchResult] = []
        for row in rows:
            if existing_files is not None and row[1] not in existing_files:
                continue
            if _file_filter_fn and not _file_filter_fn(row[1]):
                continue
            try:
                vec = _unpack_vector(row[5], self.dimension)
            except struct.error:
                logger.warning("Skipping corrupt vector row id=%s", row[0])
                continue
            score = _cosine_similarity(query_vector, vec)
            results.append(SearchResult(
                id=row[0],
                file_path=row[1],
                chunk_type=row[2],
                name=row[3],
                text=row[4],
                score=round(score, 4),
            ))

        # Sort by score descending
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def count(self) -> int:
        """Return total number of stored vectors."""
        conn = self._get_conn()
        with self._lock:
            row = conn.execute("SELECT COUNT(*) FROM vectors").fetchone()
        return row[0] if row else 0

    def set_file_metadata(
        self, file_path: str, mtime: float, chunk_count: int,
    ) -> None:
        """Record when a file was last indexed and its mtime."""
        conn = self._get_conn()
        import time as _time
        with self._lock:
            conn.execute(
                """INSERT OR REPLACE INTO file_metadata
                   (file_path, last_indexed_at, file_mtime, chunk_count)
                   VALUES (?, ?, ?, ?)""",
                (file_path, _time.time(), mtime, chunk_count),
            )
            conn.commit()

    def get_file_metadata(self, file_path: str) -> dict[str, Any] | None:
        """Get index metadata for a file. Returns None if not indexed."""
        conn = self._get_conn()
        with self._lock:
            row = conn.execute(
                "SELECT last_indexed_at, file_mtime, chunk_count "
                "FROM file_metadata WHERE file_path = ?",
                (file_path,),
            ).fetchone()
        if row:
            return {"last_indexed_at": row[0], "file_mtime": row[1], "chunk_count": row[2]}
        return None

    def get_stale_files(self, file_mtimes: dict[str, float]) -> list[str]:
        """Return files whose mtime is newer than last indexed mtime.

        Args:
            file_mtimes: Dict of relative_path -> current mtime.

        Returns:
            List of file paths that need re-indexing.
        """
        conn = self._get_conn()
        with self._lock:
            rows = conn.execute(
                "SELECT file_path, file_mtime FROM file_metadata"
            ).fetchall()
        indexed = {row[0]: row[1] for row in rows}
        stale: list[str] = []
        for fpath, current_mtime in file_mtimes.items():
            stored_mtime = indexed.get(fpath)
            if stored_mtime is None or current_mtime > stored_mtime:
                stale.append(fpath)
        return stale

    def get_all_indexed_files(self) -> list[str]:
        """Return all file paths that have metadata in the store."""
        conn = self._get_conn()
        with self._lock:
            rows = conn.execute("SELECT file_path FROM file_metadata").fetchall()
        return [r[0] for r in rows]

    def delete_file_metadata(self, file_path: str) -> None:
        """Remove metadata for a file."""
        conn = self._get_conn()
        with self._lock:
            conn.execute(
                "DELETE FROM file_metadata WHERE file_path = ?", (file_path,),
            )
            conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __del__(self) -> None:
        self.close()
