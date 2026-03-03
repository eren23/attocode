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
from dataclasses import dataclass, field
from pathlib import Path
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
    dot = sum(x * y for x, y in zip(a, b))
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

    def __post_init__(self) -> None:
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self) -> None:
        assert self._conn is not None
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS vectors (
                id TEXT PRIMARY KEY,
                file_path TEXT NOT NULL,
                chunk_type TEXT NOT NULL,
                name TEXT NOT NULL,
                text TEXT NOT NULL,
                vector BLOB NOT NULL
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_vectors_file ON vectors(file_path)"
        )
        self._conn.commit()

    def upsert(self, entry: VectorEntry) -> None:
        """Insert or update a vector entry."""
        assert self._conn is not None
        packed = _pack_vector(entry.vector)
        self._conn.execute(
            """INSERT OR REPLACE INTO vectors
               (id, file_path, chunk_type, name, text, vector)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (entry.id, entry.file_path, entry.chunk_type, entry.name, entry.text, packed),
        )
        self._conn.commit()

    def upsert_batch(self, entries: list[VectorEntry]) -> None:
        """Batch insert/update vector entries."""
        assert self._conn is not None
        rows = [
            (e.id, e.file_path, e.chunk_type, e.name, e.text, _pack_vector(e.vector))
            for e in entries
        ]
        self._conn.executemany(
            """INSERT OR REPLACE INTO vectors
               (id, file_path, chunk_type, name, text, vector)
               VALUES (?, ?, ?, ?, ?, ?)""",
            rows,
        )
        self._conn.commit()

    def delete_by_file(self, file_path: str) -> int:
        """Delete all entries for a file. Returns count deleted."""
        assert self._conn is not None
        cursor = self._conn.execute(
            "DELETE FROM vectors WHERE file_path = ?", (file_path,),
        )
        self._conn.commit()
        return cursor.rowcount

    def search(
        self,
        query_vector: list[float],
        top_k: int = 10,
        file_filter: str = "",
    ) -> list[SearchResult]:
        """Search for similar vectors using linear scan.

        Args:
            query_vector: Query embedding vector.
            top_k: Number of results to return.
            file_filter: Optional glob pattern to filter files (e.g. "*.py").

        Returns:
            Top-k results sorted by similarity score (highest first).
        """
        assert self._conn is not None
        if not query_vector:
            return []

        if file_filter:
            # Fetch all and filter with fnmatch for correct glob semantics
            # (SQL LIKE can't handle ** properly)
            import fnmatch
            cursor = self._conn.execute(
                "SELECT id, file_path, chunk_type, name, text, vector FROM vectors",
            )
            _file_filter_fn = lambda fp: fnmatch.fnmatch(fp, file_filter)
        else:
            _file_filter_fn = None
            cursor = self._conn.execute(
                "SELECT id, file_path, chunk_type, name, text, vector FROM vectors",
            )

        results: list[SearchResult] = []
        for row in cursor:
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
        assert self._conn is not None
        row = self._conn.execute("SELECT COUNT(*) FROM vectors").fetchone()
        return row[0] if row else 0

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __del__(self) -> None:
        self.close()
