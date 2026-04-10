"""SQLite-backed learning store for cross-agent memory.

Stores project learnings (patterns, conventions, gotchas, workarounds,
anti-patterns) with FTS5 full-text search and scope-aware recall.
Follows the same storage conventions as ``graph_store.py``.

Usage::

    store = MemoryStore("/path/to/project")
    lid = store.add("convention", "Always use dataclass(slots=True)", scope="src/")
    results = store.recall("dataclass patterns", scope="src/models/")
    store.record_feedback(lid, helpful=True)
"""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

VALID_TYPES = {"pattern", "antipattern", "workaround", "convention", "gotcha"}
VALID_STATUSES = {"active", "archived"}

# FTS rank threshold for deduplication.
# FTS5 rank is negative; closer to 0 = better match.
# -1.0 is a very generous threshold (catches near-exact duplicates).
_DEDUP_RANK_THRESHOLD = -1.0

# Confidence thresholds
_CONFIDENCE_FLOOR = 0.1
_CONFIDENCE_CAP = 1.0
_AUTO_ARCHIVE_THRESHOLD = 0.15
_UNHELPFUL_AUTO_ARCHIVE = 5

# Confidence adjustments
_HELPFUL_BOOST = 0.05
_UNHELPFUL_REDUCE = 0.1
_RECALL_DECAY = 0.001


@dataclass(slots=True)
class MemoryStore:
    """SQLite-backed persistent store for project learnings.

    Stores learnings with FTS5 search, scope hierarchy, confidence
    tracking, and automatic deduplication.
    """

    project_dir: str
    db_path: str = field(default="", repr=False)
    _conn: sqlite3.Connection | None = field(default=None, repr=False)
    _last_decay_at: float = field(default=0.0, repr=False)

    def __post_init__(self) -> None:
        if not self.db_path:
            store_dir = os.path.join(self.project_dir, ".attocode", "cache")
            os.makedirs(store_dir, exist_ok=True)
            self.db_path = os.path.join(store_dir, "memory.db")

        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._create_tables()

    def _get_conn(self) -> sqlite3.Connection:
        """Return the active connection or raise if closed."""
        if self._conn is None:
            raise RuntimeError("MemoryStore connection is closed")
        return self._conn

    def _create_tables(self) -> None:
        """Create tables if they don't exist."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS learnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                description TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '',
                scope TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0.7,
                apply_count INTEGER NOT NULL DEFAULT 0,
                help_count INTEGER NOT NULL DEFAULT 0,
                unhelpful_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                anchor_blob_oid TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_learnings_scope ON learnings(scope);
            CREATE INDEX IF NOT EXISTS idx_learnings_status ON learnings(status);
            CREATE INDEX IF NOT EXISTS idx_learnings_type ON learnings(type);
        """)
        # The anchor index references a column that may not exist yet
        # on pre-2c databases — migrate first, then create the index.
        self._migrate_schema()

        # FTS5 virtual table — created separately (can't be in executescript
        # with IF NOT EXISTS reliably on all SQLite versions)
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS learnings_fts
                USING fts5(description, details, content=learnings, content_rowid=id)
            """)

        # Triggers to keep FTS in sync
        for trigger_sql in [
            """CREATE TRIGGER IF NOT EXISTS learnings_ai AFTER INSERT ON learnings BEGIN
                INSERT INTO learnings_fts(rowid, description, details)
                VALUES (new.id, new.description, new.details);
            END""",
            """CREATE TRIGGER IF NOT EXISTS learnings_ad AFTER DELETE ON learnings BEGIN
                INSERT INTO learnings_fts(learnings_fts, rowid, description, details)
                VALUES ('delete', old.id, old.description, old.details);
            END""",
            """CREATE TRIGGER IF NOT EXISTS learnings_au AFTER UPDATE ON learnings BEGIN
                INSERT INTO learnings_fts(learnings_fts, rowid, description, details)
                VALUES ('delete', old.id, old.description, old.details);
                INSERT INTO learnings_fts(rowid, description, details)
                VALUES (new.id, new.description, new.details);
            END""",
        ]:
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute(trigger_sql)

        conn.commit()

    def _migrate_schema(self) -> None:
        """Additive in-place migration for pre-anchor learnings databases.

        Adds the ``anchor_blob_oid`` column if missing so an existing
        Phase 1 / 2a / 2b store keeps working after the Phase 2c
        upgrade. Idempotent.
        """
        conn = self._get_conn()
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(learnings)").fetchall()
        }
        if "anchor_blob_oid" not in columns:
            conn.execute(
                "ALTER TABLE learnings ADD COLUMN anchor_blob_oid "
                "TEXT NOT NULL DEFAULT ''"
            )
            logger.info("memory_store: migrated learnings table (+ anchor_blob_oid)")
        # Ensure the new partial index is present regardless of whether
        # we just added the column or it was already there.
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_learnings_anchor "
                "ON learnings(anchor_blob_oid) WHERE anchor_blob_oid != ''"
            )
        conn.commit()

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def add(
        self,
        type: str,  # noqa: A002
        description: str,
        details: str = "",
        scope: str = "",
        confidence: float = 0.7,
        anchor_blob_oid: str = "",
    ) -> int:
        """Record a new learning. Returns learning ID.

        Deduplicates via FTS similarity — if a highly similar learning
        exists with the same type and scope, updates its confidence instead.

        Args:
            anchor_blob_oid: Optional content-addressed anchor for the
                file this learning references (e.g. ``"git:abc123"``).
                When set, ``orphan_scan`` can check git reachability to
                detect learnings whose referenced content has been removed
                from the repo. Pass an empty string to fall back to the
                path-based ``scope`` heuristic.
        """
        conn = self._get_conn()

        if type not in VALID_TYPES:
            raise ValueError(f"Invalid type '{type}'. Must be one of: {VALID_TYPES}")

        confidence = max(_CONFIDENCE_FLOOR, min(_CONFIDENCE_CAP, confidence))
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Deduplication: check FTS for similar existing learning
        existing_id = self._find_duplicate(type, description, scope)
        if existing_id is not None:
            # Boost confidence of existing learning. Also backfill the
            # anchor_blob_oid if the new call has one and the existing
            # row doesn't — a learning gains provenance on re-record.
            if anchor_blob_oid:
                conn.execute(
                    """UPDATE learnings
                       SET confidence = MIN(?, confidence + 0.05),
                           updated_at = ?,
                           anchor_blob_oid = CASE
                               WHEN anchor_blob_oid = '' THEN ?
                               ELSE anchor_blob_oid
                           END
                       WHERE id = ?""",
                    (_CONFIDENCE_CAP, now, anchor_blob_oid, existing_id),
                )
            else:
                conn.execute(
                    """UPDATE learnings
                       SET confidence = MIN(?, confidence + 0.05),
                           updated_at = ?
                       WHERE id = ?""",
                    (_CONFIDENCE_CAP, now, existing_id),
                )
            conn.commit()
            return existing_id

        cursor = conn.execute(
            """INSERT INTO learnings
               (type, description, details, scope, confidence,
                anchor_blob_oid, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (type, description, details, scope, confidence,
             anchor_blob_oid, now, now),
        )
        conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def _find_duplicate(self, type: str, description: str, scope: str) -> int | None:  # noqa: A002
        """Check if a similar learning already exists."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """SELECT l.id, rank
                   FROM learnings_fts f
                   JOIN learnings l ON l.id = f.rowid
                   WHERE learnings_fts MATCH ?
                     AND l.type = ?
                     AND l.scope = ?
                     AND l.status = 'active'
                   ORDER BY rank DESC
                   LIMIT 1""",
                (self._escape_fts_query(description), type, scope),
            )
            row = cursor.fetchone()
            if row and row[1] > _DEDUP_RANK_THRESHOLD:
                return row[0]
        except sqlite3.OperationalError:
            pass  # FTS match syntax issue — skip dedup
        return None

    def record_feedback(self, learning_id: int, helpful: bool) -> None:
        """Record feedback on a learning.

        Helpful: boost confidence by 0.05 (cap 1.0).
        Unhelpful: reduce confidence by 0.1 (floor 0.1).
        Auto-archive if unhelpful_count >= 5 or confidence < 0.15.
        """
        conn = self._get_conn()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if helpful:
            conn.execute(
                """UPDATE learnings
                   SET help_count = help_count + 1,
                       confidence = MIN(?, confidence + ?),
                       updated_at = ?
                   WHERE id = ?""",
                (_CONFIDENCE_CAP, _HELPFUL_BOOST, now, learning_id),
            )
        else:
            conn.execute(
                """UPDATE learnings
                   SET unhelpful_count = unhelpful_count + 1,
                       confidence = MAX(?, confidence - ?),
                       updated_at = ?
                   WHERE id = ?""",
                (_CONFIDENCE_FLOOR, _UNHELPFUL_REDUCE, now, learning_id),
            )

        # Auto-archive check
        conn.execute(
            """UPDATE learnings
               SET status = 'archived', updated_at = ?
               WHERE id = ?
                 AND (unhelpful_count >= ? OR confidence < ?)""",
            (now, learning_id, _UNHELPFUL_AUTO_ARCHIVE, _AUTO_ARCHIVE_THRESHOLD),
        )
        conn.commit()

    def record_applied(self, learning_id: int) -> None:
        """Increment apply_count (called when learning injected into context)."""
        conn = self._get_conn()
        conn.execute(
            "UPDATE learnings SET apply_count = apply_count + 1 WHERE id = ?",
            (learning_id,),
        )
        conn.commit()

    def update(self, learning_id: int, **kwargs: str | float) -> None:
        """Update fields on a learning."""
        conn = self._get_conn()
        allowed = {"type", "description", "details", "scope", "confidence", "status"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return

        if "type" in updates and updates["type"] not in VALID_TYPES:
            raise ValueError(f"Invalid type '{updates['type']}'. Must be one of: {VALID_TYPES}")
        if "status" in updates and updates["status"] not in VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{updates['status']}'. Must be one of: {VALID_STATUSES}"
            )

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        updates["updated_at"] = now

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [learning_id]
        conn.execute(
            f"UPDATE learnings SET {set_clause} WHERE id = ?",  # noqa: S608
            values,
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def recall(
        self,
        query: str,
        scope: str = "",
        max_results: int = 10,
    ) -> list[dict]:
        """Retrieve relevant learnings by FTS + scope filtering.

        Scope hierarchy: exact match > parent dir > global.
        Results ranked by: FTS relevance x scope_proximity x confidence.
        """
        conn = self._get_conn()

        # Apply slow confidence decay to all active learnings
        self._apply_decay()

        # Build scope candidates (exact → parents → global)
        scope_candidates = self._build_scope_hierarchy(scope)

        results: list[dict] = []
        seen_ids: set[int] = set()

        # First: FTS-matched results
        if query.strip():
            try:
                cursor = conn.execute(
                    """SELECT l.id, l.type, l.description, l.details, l.scope,
                              l.confidence, l.apply_count, l.help_count,
                              l.unhelpful_count, l.created_at, l.updated_at,
                              l.anchor_blob_oid, rank
                       FROM learnings_fts f
                       JOIN learnings l ON l.id = f.rowid
                       WHERE learnings_fts MATCH ?
                         AND l.status = 'active'
                       ORDER BY rank DESC
                       LIMIT ?""",
                    (self._escape_fts_query(query), max_results * 3),
                )
                for row in cursor:
                    entry = self._row_to_dict(row[:12])
                    entry["_rank"] = row[12]
                    results.append(entry)
                    seen_ids.add(entry["id"])
            except sqlite3.OperationalError:
                pass  # FTS syntax error — fall back to scope-only

        # Second: scope-matched results (for when FTS doesn't match but scope does)
        if len(results) < max_results and scope_candidates:
            placeholders = ",".join("?" * len(scope_candidates))
            cursor = conn.execute(
                f"""SELECT id, type, description, details, scope,
                           confidence, apply_count, help_count,
                           unhelpful_count, created_at, updated_at,
                           anchor_blob_oid
                    FROM learnings
                    WHERE status = 'active'
                      AND scope IN ({placeholders})
                    ORDER BY confidence DESC
                    LIMIT ?""",  # noqa: S608
                [*scope_candidates, max_results * 2],
            )
            for row in cursor:
                entry = self._row_to_dict(row)
                if entry["id"] not in seen_ids:
                    entry["_rank"] = 0.0  # No FTS rank
                    results.append(entry)
                    seen_ids.add(entry["id"])

        # Score and sort
        results = self._score_results(results, scope_candidates)
        return results[:max_results]

    def list_all(
        self,
        status: str = "active",
        type: str | None = None,  # noqa: A002
    ) -> list[dict]:
        """List all learnings, optionally filtered by status and type."""
        conn = self._get_conn()

        query = (
            "SELECT id, type, description, details, scope, confidence,"
            " apply_count, help_count, unhelpful_count, created_at, updated_at,"
            " anchor_blob_oid"
            " FROM learnings WHERE status = ?"
        )
        params: list[str] = [status]

        if type:
            query += " AND type = ?"
            params.append(type)

        query += " ORDER BY confidence DESC, updated_at DESC"

        cursor = conn.execute(query, params)
        return [self._row_to_dict(row) for row in cursor]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _escape_fts_query(self, query: str) -> str:
        """Escape FTS5 special characters by quoting each term."""
        terms = query.split()
        return " ".join(f'"{t}"' for t in terms if t)

    def _row_to_dict(self, row: tuple) -> dict:
        """Convert a row tuple to a dict.

        Tolerant of the row length — if the caller's SELECT doesn't
        include ``anchor_blob_oid`` (legacy code paths not yet updated),
        the field defaults to an empty string.
        """
        result = {
            "id": row[0],
            "type": row[1],
            "description": row[2],
            "details": row[3],
            "scope": row[4],
            "confidence": row[5],
            "apply_count": row[6],
            "help_count": row[7],
            "unhelpful_count": row[8],
            "created_at": row[9],
            "updated_at": row[10],
        }
        if len(row) > 11:
            result["anchor_blob_oid"] = row[11]
        else:
            result["anchor_blob_oid"] = ""
        return result

    def _build_scope_hierarchy(self, scope: str) -> list[str]:
        """Build scope candidates from most specific to global."""
        if not scope:
            return [""]

        candidates = [scope]
        parts = scope.rstrip("/").split("/")
        for i in range(len(parts) - 1, 0, -1):
            candidates.append("/".join(parts[:i]) + "/")
        candidates.append("")  # Global
        return candidates

    def _score_results(
        self,
        results: list[dict],
        scope_candidates: list[str],
    ) -> list[dict]:
        """Score results by FTS relevance x scope proximity x confidence."""
        scope_weights = {s: 1.0 - (i * 0.15) for i, s in enumerate(scope_candidates)}

        for r in results:
            fts_score = 1.0 / (1.0 + abs(r.get("_rank", 0.0)))
            scope_weight = scope_weights.get(r["scope"], 0.3)
            r["_score"] = fts_score * scope_weight * r["confidence"]

        results.sort(key=lambda r: r["_score"], reverse=True)

        # Clean up internal keys
        for r in results:
            r.pop("_rank", None)
            r.pop("_score", None)

        return results

    def _apply_decay(self) -> None:
        """Apply very slow confidence decay to all active learnings.

        Time-gated to once per hour to prevent excessive decay in
        swarm mode where multiple workers call recall() frequently.
        """
        now = time.time()
        if now - self._last_decay_at < 3600:
            return
        self._last_decay_at = now

        conn = self._get_conn()
        conn.execute(
            """UPDATE learnings
               SET confidence = MAX(?, confidence - ?)
               WHERE status = 'active'""",
            (_CONFIDENCE_FLOOR, _RECALL_DECAY),
        )
        # Auto-archive any that fell below threshold
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        conn.execute(
            """UPDATE learnings
               SET status = 'archived', updated_at = ?
               WHERE status = 'active' AND confidence < ?""",
            (now, _AUTO_ARCHIVE_THRESHOLD),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Deletion
    # ------------------------------------------------------------------

    def clear_all(self, status_filter: str = "") -> int:
        """Hard-delete learnings.

        Args:
            status_filter: If non-empty, only delete learnings whose
                ``status`` matches (e.g. ``"archived"``). Empty string
                wipes every row.

        Returns the count deleted. FTS rows are removed via the existing
        AFTER DELETE trigger on the ``learnings`` table. MemoryStore
        doesn't serialize writes with a lock elsewhere (SQLite's own
        busy handler is the contention path), so we follow the same
        pattern here.
        """
        conn = self._get_conn()
        if status_filter:
            cursor = conn.execute(
                "DELETE FROM learnings WHERE status = ?",
                (status_filter,),
            )
        else:
            cursor = conn.execute("DELETE FROM learnings")
        conn.commit()
        return cursor.rowcount

    def delete_by_id(self, learning_id: int) -> bool:
        """Hard-delete one learning by id. Returns True on success."""
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM learnings WHERE id = ?", (learning_id,),
        )
        conn.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
