"""Embedding rotation state machine for the local ``vectors`` store.

Migrates every stored embedding from one model to another without ever
touching (let alone wiping) the live rows — the opposite of the
destructive-NULL path Phase 1 killed.

States::

        none
         │    embeddings_rotate_start(new_model, new_dim)
         ▼
      pending ─── staging table created, total row count captured
         │
         │    embeddings_rotate_step(batch_size)   (call repeatedly)
         ▼
    backfilling ── each batch: read N old rows, embed with new provider,
         │                     insert into vectors_rotating
         │
         │    last batch processed (cursor exhausted)
         ▼
  ready_to_cutover
         │
         │    embeddings_rotate_cutover(confirm=True)
         ▼                             ┌── rename vectors → vectors_archive
    cutover_done                       └── rename vectors_rotating → vectors
         │                                 update store_metadata.dimension
         │    embeddings_rotate_gc_old(confirm=True)
         ▼
      gc_done ──── vectors_archive dropped; rotation metadata cleared
         │
         ▼
        none

At any pre-cutover state, ``embeddings_rotate_abort(confirm=True)`` drops
``vectors_rotating`` and resets state to ``none`` — the primary ``vectors``
table is untouched.

**Known limitation:** new writes to ``vectors`` that happen DURING rotation
(e.g. ``notify_file_changed`` triggering a reindex mid-rotation) land in
the old table and never reach ``vectors_rotating``. After cutover they're
effectively missing. For Phase 2b the recommendation is to avoid concurrent
indexing during a rotation, or run a normal ``semantic_search`` reindex
afterwards to catch up.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import struct
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from attocode.integrations.context.embeddings import EmbeddingProvider

logger = logging.getLogger(__name__)

# Staging table name used for the rotation target.
STAGING_TABLE = "vectors_rotating"
# Archive table name used to hold the pre-rotation rows until GC.
ARCHIVE_TABLE = "vectors_archive"

# All store_metadata keys the rotator owns. Clearing these drops all
# rotation state back to a clean slate.
_ROTATION_KEYS: tuple[str, ...] = (
    "rotation_state",
    "rotation_from_model",
    "rotation_from_version",
    "rotation_from_dim",
    "rotation_to_model",
    "rotation_to_version",
    "rotation_to_dim",
    "rotation_started_at",
    "rotation_cursor",
    "rotation_processed_rows",
    "rotation_total_rows",
    "rotation_last_error",
)


class RotationState(StrEnum):
    """Finite state machine for one embedding rotation."""

    NONE = "none"
    PENDING = "pending"
    BACKFILLING = "backfilling"
    READY_TO_CUTOVER = "ready_to_cutover"
    CUTOVER_DONE = "cutover_done"
    GC_DONE = "gc_done"
    ABORTED = "aborted"
    FAILED = "failed"


@dataclass(slots=True)
class RotationStatus:
    """Public snapshot of the current rotation (or lack thereof)."""

    state: RotationState
    from_model: str
    from_version: str
    from_dim: int
    to_model: str
    to_version: str
    to_dim: int
    started_at: float
    processed_rows: int
    total_rows: int
    last_error: str

    def is_active(self) -> bool:
        return self.state not in (
            RotationState.NONE,
            RotationState.GC_DONE,
            RotationState.ABORTED,
            RotationState.FAILED,
        )

    def progress_pct(self) -> float:
        if self.total_rows <= 0:
            return 0.0
        return 100.0 * self.processed_rows / self.total_rows

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "from": {
                "model": self.from_model,
                "version": self.from_version,
                "dim": self.from_dim,
            },
            "to": {
                "model": self.to_model,
                "version": self.to_version,
                "dim": self.to_dim,
            },
            "started_at": self.started_at,
            "processed_rows": self.processed_rows,
            "total_rows": self.total_rows,
            "progress_pct": round(self.progress_pct(), 2),
            "last_error": self.last_error,
        }


# ---------------------------------------------------------------------------
# EmbeddingRotator
# ---------------------------------------------------------------------------


class EmbeddingRotator:
    """Rotation driver operating directly on a ``vectors.db`` file.

    Deliberately bypasses ``VectorStore`` so that a dimension mismatch
    between the old and new models doesn't trip ``_validate_dimension``.
    All reads / writes go through raw ``sqlite3``; the rotator is
    responsible for its own locking.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None
        if os.path.exists(db_path):
            self._conn = sqlite3.connect(db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError(
                f"EmbeddingRotator: no vectors.db at {self.db_path}"
            )
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Metadata helpers
    # ------------------------------------------------------------------

    def _set_meta(self, key: str, value: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO store_metadata (key, value) VALUES (?, ?)",
            (key, str(value)),
        )

    def _get_meta(self, key: str, default: str = "") -> str:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT value FROM store_metadata WHERE key = ?", (key,),
        ).fetchone()
        return row[0] if row else default

    def _clear_rotation_meta(self) -> None:
        conn = self._get_conn()
        for key in _ROTATION_KEYS:
            conn.execute("DELETE FROM store_metadata WHERE key = ?", (key,))

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> RotationStatus:
        """Read the current rotation state from ``store_metadata``."""
        if self._conn is None:
            return RotationStatus(
                state=RotationState.NONE,
                from_model="", from_version="", from_dim=0,
                to_model="", to_version="", to_dim=0,
                started_at=0.0,
                processed_rows=0, total_rows=0,
                last_error="vectors.db not found",
            )
        state_raw = self._get_meta("rotation_state", RotationState.NONE.value)
        try:
            state = RotationState(state_raw)
        except ValueError:
            state = RotationState.NONE
        return RotationStatus(
            state=state,
            from_model=self._get_meta("rotation_from_model"),
            from_version=self._get_meta("rotation_from_version"),
            from_dim=int(self._get_meta("rotation_from_dim") or "0"),
            to_model=self._get_meta("rotation_to_model"),
            to_version=self._get_meta("rotation_to_version"),
            to_dim=int(self._get_meta("rotation_to_dim") or "0"),
            started_at=float(self._get_meta("rotation_started_at") or "0"),
            processed_rows=int(self._get_meta("rotation_processed_rows") or "0"),
            total_rows=int(self._get_meta("rotation_total_rows") or "0"),
            last_error=self._get_meta("rotation_last_error"),
        )

    # ------------------------------------------------------------------
    # start
    # ------------------------------------------------------------------

    def start(
        self,
        *,
        to_model: str,
        to_version: str,
        to_dim: int,
    ) -> RotationStatus:
        """Begin a new rotation.

        Raises RuntimeError if a rotation is already active or if the
        main ``vectors`` table is empty.
        """
        conn = self._get_conn()

        current = self.status()
        if current.is_active():
            raise RuntimeError(
                f"rotation already active (state={current.state.value}); "
                "abort it before starting a new one"
            )

        # Capture the current "from" metadata from the active store_metadata.
        from_dim = int(self._get_meta("dimension") or "0")
        # "from" model is approximated from the most common model_name on
        # existing rows. If the column was never populated (legacy rows
        # from Phase 0), we fall back to "legacy".
        from_model = self._dominant_model_name(conn) or "legacy"
        from_version = self._dominant_model_version(conn)

        row_count = conn.execute("SELECT COUNT(*) FROM vectors").fetchone()[0]
        if row_count == 0:
            raise RuntimeError("no vectors to rotate — table is empty")

        # Clean any prior staging table from a failed rotation.
        conn.execute(f"DROP TABLE IF EXISTS {STAGING_TABLE}")
        # Mirror the vectors table schema. Using a literal CREATE keeps
        # the PK + NOT NULL / DEFAULT constraints that a
        # ``CREATE TABLE x AS SELECT`` would strip.
        conn.execute(
            f"""
            CREATE TABLE {STAGING_TABLE} (
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
            """
        )
        # Matching indexes on the staging table so they're in place for
        # search as soon as the cutover rename swap completes.
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_rot_vectors_file "
            f"ON {STAGING_TABLE}(file_path)"
        )
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_rot_vectors_model "
            f"ON {STAGING_TABLE}(model_name, model_version)"
        )
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_rot_vectors_blob "
            f"ON {STAGING_TABLE}(blob_oid)"
        )

        self._clear_rotation_meta()
        self._set_meta("rotation_state", RotationState.PENDING.value)
        self._set_meta("rotation_from_model", from_model)
        self._set_meta("rotation_from_version", from_version)
        self._set_meta("rotation_from_dim", str(from_dim))
        self._set_meta("rotation_to_model", to_model)
        self._set_meta("rotation_to_version", to_version)
        self._set_meta("rotation_to_dim", str(to_dim))
        self._set_meta("rotation_started_at", str(time.time()))
        self._set_meta("rotation_cursor", "")
        self._set_meta("rotation_processed_rows", "0")
        self._set_meta("rotation_total_rows", str(row_count))
        self._set_meta("rotation_last_error", "")
        conn.commit()

        return self.status()

    def _dominant_model_name(self, conn: sqlite3.Connection) -> str:
        """Return the most common ``model_name`` in the vectors table.

        Returns an empty string if no rows have a non-empty name (e.g.
        a fresh v2 store where rows were inserted before provenance was
        wired through).
        """
        try:
            row = conn.execute(
                "SELECT model_name, COUNT(*) as c FROM vectors "
                "WHERE model_name != '' "
                "GROUP BY model_name ORDER BY c DESC LIMIT 1"
            ).fetchone()
        except sqlite3.OperationalError:
            return ""
        return row[0] if row else ""

    def _dominant_model_version(self, conn: sqlite3.Connection) -> str:
        try:
            row = conn.execute(
                "SELECT model_version, COUNT(*) as c FROM vectors "
                "WHERE model_version != '' "
                "GROUP BY model_version ORDER BY c DESC LIMIT 1"
            ).fetchone()
        except sqlite3.OperationalError:
            return ""
        return row[0] if row else ""

    # ------------------------------------------------------------------
    # step — advance the backfill
    # ------------------------------------------------------------------

    def step(
        self,
        provider: EmbeddingProvider,
        batch_size: int = 32,
    ) -> int:
        """Embed one batch of rows with ``provider`` and write them to
        the staging table.

        Returns the number of rows processed. Returns 0 when the
        rotation is done (state transitions to ``ready_to_cutover``).

        Raises RuntimeError if there's no active rotation or if
        ``provider.dimension()`` doesn't match the target dim recorded
        at ``start``.
        """
        conn = self._get_conn()
        status = self.status()

        # Idempotent no-op once the backfill is already done — callers
        # that drive step() in a while-loop would otherwise have to
        # duplicate state-check logic.
        if status.state == RotationState.READY_TO_CUTOVER:
            return 0

        if status.state not in (RotationState.PENDING, RotationState.BACKFILLING):
            raise RuntimeError(
                f"step() requires state pending|backfilling, got {status.state.value}"
            )

        provider_dim = provider.dimension()
        if provider_dim != status.to_dim:
            self._set_meta(
                "rotation_last_error",
                f"provider dim {provider_dim} != target dim {status.to_dim}",
            )
            self._set_meta("rotation_state", RotationState.FAILED.value)
            conn.commit()
            raise RuntimeError(
                f"provider {provider.name} has dim {provider_dim}, "
                f"but rotation target dim is {status.to_dim}"
            )

        last_cursor = self._get_meta("rotation_cursor", "")
        rows = conn.execute(
            "SELECT id, file_path, chunk_type, name, text, blob_oid, action_hash "
            "FROM vectors WHERE id > ? ORDER BY id LIMIT ?",
            (last_cursor, batch_size),
        ).fetchall()

        if not rows:
            # Nothing left to process.
            self._set_meta("rotation_state", RotationState.READY_TO_CUTOVER.value)
            conn.commit()
            return 0

        # Promote to BACKFILLING on the first processed batch.
        if status.state == RotationState.PENDING:
            self._set_meta("rotation_state", RotationState.BACKFILLING.value)

        texts = [r[4] for r in rows]
        try:
            new_vectors = provider.embed(texts)
        except Exception as exc:  # noqa: BLE001 — surface provider errors loudly
            self._set_meta("rotation_last_error", f"embed failed: {exc}")
            self._set_meta("rotation_state", RotationState.FAILED.value)
            conn.commit()
            raise

        if len(new_vectors) != len(rows):
            self._set_meta(
                "rotation_last_error",
                f"embed returned {len(new_vectors)} vectors for {len(rows)} inputs",
            )
            self._set_meta("rotation_state", RotationState.FAILED.value)
            conn.commit()
            raise RuntimeError("embed() length mismatch")

        produced_at = time.time()
        provider_name = provider.name  # property, not callable
        to_version = status.to_version
        to_dim = status.to_dim

        insert_sql = (
            f"INSERT OR REPLACE INTO {STAGING_TABLE} "
            "(id, file_path, chunk_type, name, text, vector, "
            "model_name, model_version, dimension, produced_at, "
            "blob_oid, action_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        for (row, vec) in zip(rows, new_vectors, strict=True):
            if len(vec) != to_dim:
                self._set_meta(
                    "rotation_last_error",
                    f"provider returned vec of len {len(vec)}, expected {to_dim}",
                )
                self._set_meta("rotation_state", RotationState.FAILED.value)
                conn.commit()
                raise RuntimeError(
                    f"provider returned vec of wrong length: {len(vec)} != {to_dim}"
                )
            packed = struct.pack(f"{to_dim}f", *vec)
            conn.execute(
                insert_sql,
                (
                    row[0],        # id
                    row[1],        # file_path
                    row[2],        # chunk_type
                    row[3],        # name
                    row[4],        # text
                    packed,        # new vector
                    provider_name, # model_name
                    to_version,    # model_version
                    to_dim,        # dimension
                    produced_at,   # produced_at
                    row[5],        # blob_oid (carried over)
                    row[6],        # action_hash (carried over)
                ),
            )

        # Update cursor + processed count.
        last_id = rows[-1][0]
        processed = status.processed_rows + len(rows)
        self._set_meta("rotation_cursor", last_id)
        self._set_meta("rotation_processed_rows", str(processed))
        conn.commit()

        # If we drained the table, transition to ready_to_cutover.
        if len(rows) < batch_size:
            # We got fewer rows than requested, so the table is exhausted.
            self._set_meta("rotation_state", RotationState.READY_TO_CUTOVER.value)
            conn.commit()

        return len(rows)

    # ------------------------------------------------------------------
    # cutover
    # ------------------------------------------------------------------

    def cutover(self) -> RotationStatus:
        """Atomically swap ``vectors`` and ``vectors_rotating``.

        The existing ``vectors`` becomes ``vectors_archive`` (still
        present until ``gc_old``). Subsequent reads / writes hit the
        new table. ``store_metadata.dimension`` is updated to the new
        target dim.

        Requires state ``ready_to_cutover``.
        """
        conn = self._get_conn()
        status = self.status()
        if status.state != RotationState.READY_TO_CUTOVER:
            raise RuntimeError(
                f"cutover() requires state ready_to_cutover, got {status.state.value}"
            )

        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(f"DROP TABLE IF EXISTS {ARCHIVE_TABLE}")
            conn.execute(f"ALTER TABLE vectors RENAME TO {ARCHIVE_TABLE}")
            conn.execute(f"ALTER TABLE {STAGING_TABLE} RENAME TO vectors")
            # Update stored dimension pointer so next VectorStore open
            # doesn't trip the mismatch check.
            conn.execute(
                "INSERT OR REPLACE INTO store_metadata (key, value) VALUES ('dimension', ?)",
                (str(status.to_dim),),
            )
            conn.execute(
                "INSERT OR REPLACE INTO store_metadata (key, value) VALUES (?, ?)",
                ("rotation_state", RotationState.CUTOVER_DONE.value),
            )
            # Invalidate the vector cache version so open VectorStores
            # reload. Uses a monotonic bump stored in store_metadata.
            prev_ver = int(self._get_meta("_rotator_cache_ver") or "0")
            conn.execute(
                "INSERT OR REPLACE INTO store_metadata (key, value) VALUES (?, ?)",
                ("_rotator_cache_ver", str(prev_ver + 1)),
            )
            conn.commit()
        except sqlite3.Error:
            conn.execute("ROLLBACK")
            self._set_meta("rotation_state", RotationState.FAILED.value)
            self._set_meta("rotation_last_error", "cutover SQL failed")
            conn.commit()
            raise

        return self.status()

    # ------------------------------------------------------------------
    # gc_old
    # ------------------------------------------------------------------

    def gc_old(self) -> RotationStatus:
        """Drop the archive table and clear rotation metadata.

        Requires state ``cutover_done``. Transitions through ``gc_done``
        back to ``none``.
        """
        conn = self._get_conn()
        status = self.status()
        if status.state != RotationState.CUTOVER_DONE:
            raise RuntimeError(
                f"gc_old() requires state cutover_done, got {status.state.value}"
            )
        conn.execute(f"DROP TABLE IF EXISTS {ARCHIVE_TABLE}")
        self._set_meta("rotation_state", RotationState.GC_DONE.value)
        conn.commit()
        # Then clean the rotation metadata entirely so state goes back to NONE.
        self._clear_rotation_meta()
        conn.commit()
        return self.status()

    # ------------------------------------------------------------------
    # abort
    # ------------------------------------------------------------------

    def abort(self) -> RotationStatus:
        """Cancel a pre-cutover rotation.

        Drops ``vectors_rotating`` and clears rotation metadata. The
        primary ``vectors`` table is untouched. Legal from any state
        other than ``cutover_done`` / ``gc_done``.
        """
        conn = self._get_conn()
        status = self.status()
        if status.state in (RotationState.CUTOVER_DONE, RotationState.GC_DONE):
            raise RuntimeError(
                f"abort() would corrupt state {status.state.value}; "
                "use gc_old instead or restore from a snapshot"
            )
        conn.execute(f"DROP TABLE IF EXISTS {STAGING_TABLE}")
        self._set_meta("rotation_state", RotationState.ABORTED.value)
        conn.commit()
        # Clear metadata back to NONE so a fresh rotation can begin.
        self._clear_rotation_meta()
        conn.commit()
        return self.status()
