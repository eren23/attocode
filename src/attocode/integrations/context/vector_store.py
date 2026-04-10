"""SQLite-backed vector store for semantic search.

Stores embeddings as packed float32 BLOBs in SQLite. Uses numpy-accelerated
batch cosine similarity with in-memory caching for fast retrieval.
"""

from __future__ import annotations

import logging
import math
import os
import sqlite3
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Any

try:
    import numpy as np

    _HAS_NUMPY = True
except ImportError:
    np = None  # type: ignore[assignment]
    _HAS_NUMPY = False

logger = logging.getLogger(__name__)

# Schema version for the vectors DB. Bump this when adding columns so the
# store detects upgrades automatically and runs the appropriate ALTER
# scripts at startup.
VECTOR_STORE_SCHEMA_VERSION = "2"


class VectorStoreDimensionMismatchError(RuntimeError):
    """Raised when the running embedding provider's dimension does not match
    the vectors already persisted on disk.

    The old behavior in this store was to silently DELETE every row on
    dim mismatch. That was the local-side sibling of the server-side
    ``UPDATE embeddings SET vector = NULL`` footgun — quietly destroying
    user data because the system couldn't figure out the right thing to do.

    Now: loud error. Caller (``SemanticSearchManager``) catches it once,
    logs a visible warning, and puts the store into a degraded read-only
    mode until the user resolves it (via ``clear_embeddings`` once that
    tool lands in phase 2, or by picking a provider that matches).
    """

    def __init__(self, *, stored: int, expected: int, db_path: str) -> None:
        self.stored = stored
        self.expected = expected
        self.db_path = db_path
        super().__init__(
            f"vector store at {db_path} has stored dim {stored} but provider "
            f"expects dim {expected}. Refusing to wipe the existing vectors. "
            f"Resolve by choosing a provider with matching dim, or (phase 2) "
            f"run embeddings_rotate_model() or clear_embeddings(confirm=True)."
        )


@dataclass(slots=True)
class VectorEntry:
    """A stored vector with metadata."""

    id: str
    file_path: str
    chunk_type: str  # "file", "function", "class"
    name: str
    text: str
    vector: list[float]
    # Provenance — optional; empty defaults keep callers that don't care
    # working. New indexers should fill these in.
    blob_oid: str = ""
    action_hash: str = ""


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
    """Compute cosine similarity between two vectors (pure Python fallback)."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _batch_cosine_similarity(
    query: np.ndarray,
    matrix: np.ndarray,
) -> np.ndarray:
    """Vectorized cosine similarity: query (D,) vs matrix (N, D) → scores (N,).

    Uses numpy BLAS for a single matrix-vector multiply instead of N Python loops.
    """
    query_norm = np.linalg.norm(query)
    if query_norm == 0.0 or len(matrix) == 0:
        return np.zeros(len(matrix), dtype=np.float32)

    query_normed = query / query_norm
    norms = np.linalg.norm(matrix, axis=1)

    scores = np.zeros(len(matrix), dtype=np.float32)
    mask = norms > 0
    scores[mask] = (matrix[mask] @ query_normed) / norms[mask]
    return scores


@dataclass(slots=True)
class VectorStore:
    """SQLite-backed vector store with numpy-accelerated search.

    Usage::

        store = VectorStore(db_path="vectors.db", dimension=384)
        store.upsert(VectorEntry(id="f1", ...))
        results = store.search(query_vector, top_k=10)
    """

    db_path: str
    dimension: int
    # Optional provenance for new inserts. If set, every upsert records these
    # fields into the vectors row so we can later answer "which model made
    # this?" and detect silent drift.
    model_name: str = ""
    model_version: str = ""
    # When True, a dimension mismatch puts the store in degraded read-only
    # mode instead of raising. Used by callers that want to show a nice
    # error in the UI rather than crash on import.
    strict_dimension: bool = True
    # Set by _validate_dimension on mismatch so callers can detect degraded
    # mode without catching the exception.
    degraded: bool = False
    degraded_reason: str = ""
    _conn: sqlite3.Connection | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    # In-memory vector cache for numpy batch search
    _vec_matrix: Any = field(default=None, repr=False)  # np.ndarray (N, D)
    _vec_meta: list[tuple] | None = field(default=None, repr=False)
    _vec_cache_version: int = field(default=0, repr=False)
    _vec_loaded_version: int = field(default=-1, repr=False)

    def __post_init__(self) -> None:
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()
        self._migrate_schema()
        self._validate_dimension()

    def _get_conn(self) -> sqlite3.Connection:
        """Return the active connection or raise if closed."""
        if self._conn is None:
            raise RuntimeError("VectorStore connection is closed")
        return self._conn

    def _create_tables(self) -> None:
        conn = self._get_conn()
        # Schema v2 — includes provenance columns. Pre-v2 stores have the
        # same base shape and are migrated in _migrate_schema().
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vectors (
                id TEXT PRIMARY KEY,
                file_path TEXT NOT NULL,
                chunk_type TEXT NOT NULL,
                name TEXT NOT NULL,
                text TEXT NOT NULL,
                vector BLOB NOT NULL,
                model_name TEXT NOT NULL DEFAULT '',
                model_version TEXT NOT NULL DEFAULT '',
                dimension INTEGER NOT NULL DEFAULT 0,
                produced_at REAL NOT NULL DEFAULT 0,
                blob_oid TEXT NOT NULL DEFAULT '',
                action_hash TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_vectors_file ON vectors(file_path)"
        )
        # The model/blob indexes reference columns that a pre-v2 table may not
        # have yet — they're created in ``_migrate_schema`` after the columns
        # are guaranteed to exist.
        # Metadata table for tracking index freshness per file
        conn.execute("""
            CREATE TABLE IF NOT EXISTS file_metadata (
                file_path TEXT PRIMARY KEY,
                last_indexed_at REAL NOT NULL,
                file_mtime REAL NOT NULL,
                chunk_count INTEGER NOT NULL DEFAULT 0
            )
        """)
        # Store-level metadata (dimension, schema_version, active model, etc.)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS store_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.commit()

    def _migrate_schema(self) -> None:
        """Additively migrate an older vectors table to the current schema.

        Pre-v2 stores lack the provenance columns (``model_name``,
        ``model_version``, ``dimension``, ``produced_at``, ``blob_oid``,
        ``action_hash``). We ADD COLUMN each missing one with a safe default;
        existing rows get a 'legacy' marker so later tools can identify
        them for re-indexing.

        Idempotent: running on a fresh v2 store is a no-op.
        """
        conn = self._get_conn()
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(vectors)").fetchall()
        }
        added: list[str] = []
        additive_columns = [
            ("model_name", "TEXT NOT NULL DEFAULT ''"),
            ("model_version", "TEXT NOT NULL DEFAULT ''"),
            ("dimension", "INTEGER NOT NULL DEFAULT 0"),
            ("produced_at", "REAL NOT NULL DEFAULT 0"),
            ("blob_oid", "TEXT NOT NULL DEFAULT ''"),
            ("action_hash", "TEXT NOT NULL DEFAULT ''"),
        ]
        for col, ddl in additive_columns:
            if col not in columns:
                conn.execute(f"ALTER TABLE vectors ADD COLUMN {col} {ddl}")
                added.append(col)

        if added:
            # Mark pre-v2 rows so callers can find and re-index them later.
            conn.execute(
                "UPDATE vectors SET model_name = 'legacy-pre-v2' "
                "WHERE model_name = '' AND length(vector) > 0"
            )
            logger.info(
                "vector_store: migrated v1 schema -> v2 (added columns: %s)",
                ", ".join(added),
            )

        # Ensure indexes exist on newly-added columns.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_vectors_model ON vectors(model_name, model_version)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_vectors_blob ON vectors(blob_oid)"
        )

        # Record schema version.
        conn.execute(
            "INSERT OR REPLACE INTO store_metadata (key, value) VALUES ('schema_version', ?)",
            (VECTOR_STORE_SCHEMA_VERSION,),
        )
        conn.commit()

    def _validate_dimension(self) -> None:
        """Check stored dimension matches current.

        Behavior change vs the old code: a mismatch NO LONGER silently wipes
        ``vectors`` + ``file_metadata``. Instead:

          - If ``strict_dimension`` is True (the default): raise
            :class:`VectorStoreDimensionMismatchError`. The caller is expected
            to handle this by switching providers, running a rotation, or
            invoking the (phase-2) ``clear_embeddings`` tool.
          - If ``strict_dimension`` is False: put the store into degraded
            read-only mode by setting ``self.degraded`` and
            ``self.degraded_reason``, and bail out of the constructor. Writes
            then refuse to land.

        Why change: silent wipe meant every `attocode` invocation with a
        different env-var / model flag deleted the user's embedding index
        without ever telling them. That's the exact footgun this whole
        work item is fixing.
        """
        conn = self._get_conn()
        row = conn.execute(
            "SELECT value FROM store_metadata WHERE key = 'dimension'"
        ).fetchone()
        if row:
            stored_dim = int(row[0])
            if stored_dim != self.dimension:
                # Non-destructive: refuse to proceed.
                msg = (
                    f"embedding dimension mismatch (stored={stored_dim}, "
                    f"expected={self.dimension})"
                )
                if self.strict_dimension:
                    logger.error(
                        "%s; refusing to wipe vectors. Use embeddings_rotate_model "
                        "or clear_embeddings(confirm=true) to resolve.", msg,
                    )
                    raise VectorStoreDimensionMismatchError(
                        stored=stored_dim,
                        expected=self.dimension,
                        db_path=self.db_path,
                    )
                logger.warning(
                    "%s; store is in DEGRADED read-only mode. "
                    "Existing vectors preserved.", msg,
                )
                self.degraded = True
                self.degraded_reason = "dimension_mismatch"
                return
        else:
            conn.execute(
                "INSERT OR REPLACE INTO store_metadata (key, value) VALUES ('dimension', ?)",
                (str(self.dimension),),
            )
            conn.commit()

    def _guard_writes(self) -> None:
        """Refuse writes when the store is in degraded mode."""
        if self.degraded:
            raise VectorStoreDimensionMismatchError(
                stored=0,
                expected=self.dimension,
                db_path=self.db_path,
            )

    def upsert(self, entry: VectorEntry) -> None:
        """Insert or update a vector entry."""
        self._guard_writes()
        conn = self._get_conn()
        packed = _pack_vector(entry.vector)
        now = time.time()
        with self._lock:
            conn.execute(
                """INSERT OR REPLACE INTO vectors
                   (id, file_path, chunk_type, name, text, vector,
                    model_name, model_version, dimension, produced_at,
                    blob_oid, action_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.id, entry.file_path, entry.chunk_type, entry.name,
                    entry.text, packed,
                    self.model_name, self.model_version, self.dimension,
                    now, entry.blob_oid, entry.action_hash,
                ),
            )
            conn.commit()
            self._vec_cache_version += 1

    def upsert_batch(self, entries: list[VectorEntry]) -> None:
        """Batch insert/update vector entries."""
        self._guard_writes()
        conn = self._get_conn()
        now = time.time()
        rows = [
            (
                e.id, e.file_path, e.chunk_type, e.name, e.text,
                _pack_vector(e.vector),
                self.model_name, self.model_version, self.dimension,
                now, e.blob_oid, e.action_hash,
            )
            for e in entries
        ]
        with self._lock:
            conn.executemany(
                """INSERT OR REPLACE INTO vectors
                   (id, file_path, chunk_type, name, text, vector,
                    model_name, model_version, dimension, produced_at,
                    blob_oid, action_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            conn.commit()
            self._vec_cache_version += 1

    def delete_by_file(self, file_path: str) -> int:
        """Delete all entries for a file. Returns count deleted."""
        conn = self._get_conn()
        with self._lock:
            cursor = conn.execute(
                "DELETE FROM vectors WHERE file_path = ?", (file_path,),
            )
            conn.commit()
            self._vec_cache_version += 1
            return cursor.rowcount

    # ------------------------------------------------------------------
    # In-memory vector cache for numpy batch search
    # ------------------------------------------------------------------

    def _load_vector_cache(self) -> None:
        """Load all vectors from SQLite into a numpy matrix."""
        conn = self._get_conn()
        with self._lock:
            rows = conn.execute(
                "SELECT id, file_path, chunk_type, name, text, vector FROM vectors",
            ).fetchall()

        if not rows:
            self._vec_matrix = np.empty((0, self.dimension), dtype=np.float32)
            self._vec_meta = []
            self._vec_loaded_version = self._vec_cache_version
            return

        meta: list[tuple] = []
        vecs: list[np.ndarray] = []
        for row in rows:
            try:
                v = np.frombuffer(row[5], dtype=np.float32)
                if len(v) == self.dimension:
                    vecs.append(v)
                    meta.append((row[0], row[1], row[2], row[3], row[4]))
            except (ValueError, struct.error):
                logger.warning("Skipping corrupt vector row id=%s", row[0])

        if vecs:
            self._vec_matrix = np.vstack(vecs)
        else:
            self._vec_matrix = np.empty((0, self.dimension), dtype=np.float32)
        self._vec_meta = meta
        self._vec_loaded_version = self._vec_cache_version
        logger.debug(
            "Vector cache loaded: %d vectors (%d dim)",
            len(meta), self.dimension,
        )

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query_vector: list[float],
        top_k: int = 10,
        file_filter: str = "",
        existing_files: set[str] | None = None,
    ) -> list[SearchResult]:
        """Search for similar vectors.

        Uses numpy batch cosine similarity when available (100-1000x faster
        than pure Python), with automatic in-memory caching of the vector
        matrix. Falls back to per-vector Python loop if numpy is unavailable.

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
        if not query_vector:
            return []

        if _HAS_NUMPY:
            return self._search_numpy(query_vector, top_k, file_filter, existing_files)
        return self._search_python(query_vector, top_k, file_filter, existing_files)

    def _search_numpy(
        self,
        query_vector: list[float],
        top_k: int,
        file_filter: str,
        existing_files: set[str] | None,
    ) -> list[SearchResult]:
        """Numpy-accelerated vector search with in-memory cache."""
        # Ensure cache is current
        if self._vec_loaded_version != self._vec_cache_version or self._vec_matrix is None:
            self._load_vector_cache()

        if self._vec_matrix is None or len(self._vec_matrix) == 0:
            return []

        query_np = np.array(query_vector, dtype=np.float32)

        # Batch cosine similarity — single BLAS matmul
        scores = _batch_cosine_similarity(query_np, self._vec_matrix)

        # Apply filters by zeroing out excluded entries
        if file_filter or existing_files is not None:
            import fnmatch

            for i, meta in enumerate(self._vec_meta):
                fp = meta[1]  # file_path
                if existing_files is not None and fp not in existing_files:  # noqa: SIM114 — clearer as two branches than one combined or
                    scores[i] = -1.0
                elif file_filter and not fnmatch.fnmatch(fp, file_filter):
                    scores[i] = -1.0

        # Top-k selection: argpartition is O(N) vs O(N log N) for full sort
        n = len(scores)
        if n <= top_k:
            top_indices = np.argsort(scores)[::-1]
        else:
            top_indices = np.argpartition(scores, -top_k)[-top_k:]
            top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]

        results: list[SearchResult] = []
        for idx in top_indices:
            s = float(scores[idx])
            if s <= 0:
                break
            m = self._vec_meta[idx]
            results.append(SearchResult(
                id=m[0], file_path=m[1], chunk_type=m[2],
                name=m[3], text=m[4], score=round(s, 4),
            ))
        return results

    def _search_python(
        self,
        query_vector: list[float],
        top_k: int,
        file_filter: str,
        existing_files: set[str] | None,
    ) -> list[SearchResult]:
        """Pure Python fallback when numpy is unavailable."""
        conn = self._get_conn()

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
