"""Query history tracker with combo boosting.

Tracks successful query-result pairs to boost files that are repeatedly
opened with the same query. This is different from frecency which tracks
file access patterns.

Combo boosting:
- When user searches "foo" and opens "bar.py", we track that mapping
- If user repeatedly opens "bar.py" when searching "foo", we boost "bar.py"
- This helps prioritize commonly co-occuring results

Based on fff.nvim's query_tracker.rs.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Combo boosting constants
_MIN_COMBO_COUNT: int = 3  # Minimum selections before combo boost applies
_COMBO_BOOST_MULTIPLIER: float = 100.0  # Score multiplier for combo matches
_MAX_HISTORY_DAYS: int = 30  # Only consider selections within 30 days

# SQLite schema version
_SCHEMA_VERSION: int = 1


@dataclass
class QueryResult:
    """A tracked query result."""
    query: str
    file_path: str
    count: int  # How many times this query led to opening this file
    last_selected: float  # Unix timestamp of last selection
    combo_score: float  # Calculated combo boost score


@dataclass
class QueryHistoryStats:
    """Statistics about the query history."""
    total_queries: int
    total_selections: int
    unique_queries: int
    unique_files: int
    combo_boosts: int  # Number of files with combo boost > 0


class QueryHistoryTracker:
    """Tracks query-result pairs for combo boosting.

    Stores which files were selected after which queries, allowing
    us to boost results that commonly appear together.
    """

    def __init__(
        self,
        db_path: str | Path = ".attocode/query_history",
        *,
        min_combo_count: int = _MIN_COMBO_COUNT,
        combo_boost_multiplier: float = _COMBO_BOOST_MULTIPLIER,
    ) -> None:
        self._db_path = Path(db_path)
        self._min_combo_count = min_combo_count
        self._combo_boost_multiplier = combo_boost_multiplier
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._ensure_db()

    def _ensure_db(self) -> None:
        """Ensure the database directory and tables exist."""
        self._db_path.mkdir(parents=True, exist_ok=True)
        db_file = self._db_path / "query_history.db"

        conn = sqlite3.connect(
            str(db_file),
            timeout=5.0,
            check_same_thread=False,
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        # Main table: query_selections
        conn.execute("""
            CREATE TABLE IF NOT EXISTS query_selections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                file_path TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 1,
                last_selected REAL NOT NULL,
                UNIQUE(query, file_path)
            )
        """)

        # Index for fast lookups
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_query
            ON query_selections(query)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_file
            ON query_selections(file_path)
        """)

        # Meta table for schema version
        conn.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        cursor = conn.execute(
            "SELECT value FROM meta WHERE key = 'version'",
        )
        row = cursor.fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('version', ?)",
                (str(_SCHEMA_VERSION),),
            )
            conn.commit()

        self._conn = conn

    def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def track_selection(self, query: str, file_path: str) -> None:
        """Record that a user selected a file after searching for query.

        Args:
            query: The search query.
            file_path: The file that was selected/opened.
        """
        now = time.time()
        query_lower = query.lower().strip()
        file_path = str(file_path)

        with self._lock:
            if self._conn is None:
                return

            # Try to update existing
            cursor = self._conn.execute(
                """
                UPDATE query_selections
                SET count = count + 1, last_selected = ?
                WHERE query = ? AND file_path = ?
                """,
                (now, query_lower, file_path),
            )

            if cursor.rowcount == 0:
                # Insert new record
                self._conn.execute(
                    """
                    INSERT INTO query_selections (query, file_path, count, last_selected)
                    VALUES (?, ?, 1, ?)
                    """,
                    (query_lower, file_path, now),
                )

            self._conn.commit()

            # Prune old entries
            cutoff = now - (_MAX_HISTORY_DAYS * 86400)
            self._conn.execute(
                "DELETE FROM query_selections WHERE last_selected < ?",
                (cutoff,),
            )
            self._conn.commit()

    def get_combo_boost(self, query: str, file_path: str) -> float:
        """Get the combo boost score for a query+file pair.

        Args:
            query: The search query.
            file_path: The file to get the boost for.

        Returns:
            Combo boost score (0 if below min_combo_count).
        """
        query_lower = query.lower().strip()
        file_path = str(file_path)

        with self._lock:
            if self._conn is None:
                return 0.0

            cursor = self._conn.execute(
                """
                SELECT count, last_selected FROM query_selections
                WHERE query = ? AND file_path = ?
                """,
                (query_lower, file_path),
            )
            row = cursor.fetchone()

        if row is None:
            return 0.0

        count, last_selected = row

        # Check if within history window
        now = time.time()
        cutoff = now - (_MAX_HISTORY_DAYS * 86400)
        if last_selected < cutoff:
            return 0.0

        # Apply combo boost if above threshold
        if count >= self._min_combo_count:
            return float(count) * self._combo_boost_multiplier

        return 0.0

    def get_combo_boosts_batch(
        self,
        query: str,
        file_paths: list[str],
    ) -> dict[str, float]:
        """Get combo boost scores for multiple files for a query.

        Args:
            query: The search query.
            file_paths: List of file paths to check.

        Returns:
            Dict mapping file_path -> combo_boost_score.
        """
        boosts: dict[str, float] = {}
        for path in file_paths:
            boosts[path] = self.get_combo_boost(query, path)
        return boosts

    def get_top_files_for_query(
        self,
        query: str,
        limit: int = 10,
    ) -> list[tuple[str, int, float]]:
        """Get the top files for a given query.

        Args:
            query: The search query.
            limit: Maximum number of results.

        Returns:
            List of (file_path, count, combo_score) tuples.
        """
        query_lower = query.lower().strip()

        with self._lock:
            if self._conn is None:
                return []

            cursor = self._conn.execute(
                """
                SELECT file_path, count, last_selected
                FROM query_selections
                WHERE query = ? AND last_selected > ?
                ORDER BY count DESC
                LIMIT ?
                """,
                (query_lower, time.time() - (_MAX_HISTORY_DAYS * 86400), limit),
            )

            results: list[tuple[str, int, float]] = []
            for row in cursor.fetchall():
                file_path, count, last_selected = row
                combo_score = (
                    float(count) * self._combo_boost_multiplier
                    if count >= self._min_combo_count
                    else 0.0
                )
                results.append((file_path, count, combo_score))

        return results

    def get_stats(self) -> QueryHistoryStats:
        """Get statistics about the query history."""
        with self._lock:
            if self._conn is None:
                return QueryHistoryStats(
                    total_queries=0,
                    total_selections=0,
                    unique_queries=0,
                    unique_files=0,
                    combo_boosts=0,
                )

            # Total selections
            cursor = self._conn.execute(
                "SELECT COALESCE(SUM(count), 0) FROM query_selections",
            )
            total_selections = cursor.fetchone()[0] or 0

            # Total queries
            cursor = self._conn.execute(
                "SELECT COUNT(*) FROM query_selections",
            )
            total_queries = cursor.fetchone()[0] or 0

            # Unique queries
            cursor = self._conn.execute(
                "SELECT COUNT(DISTINCT query) FROM query_selections",
            )
            unique_queries = cursor.fetchone()[0] or 0

            # Unique files
            cursor = self._conn.execute(
                "SELECT COUNT(DISTINCT file_path) FROM query_selections",
            )
            unique_files = cursor.fetchone()[0] or 0

            # Files with combo boost > 0
            cursor = self._conn.execute(
                """
                SELECT COUNT(*) FROM query_selections
                WHERE count >= ?
                """,
                (self._min_combo_count,),
            )
            combo_boosts = cursor.fetchone()[0] or 0

            return QueryHistoryStats(
                total_queries=total_queries,
                total_selections=total_selections,
                unique_queries=unique_queries,
                unique_files=unique_files,
                combo_boosts=combo_boosts,
            )

    def clear(self, query: str | None = None, file_path: str | None = None) -> int:
        """Clear query history.

        Args:
            query: If provided, clear only this query. If None, clear all.
            file_path: If provided with query, clear only that pair.

        Returns:
            Number of entries cleared.
        """
        with self._lock:
            if self._conn is None:
                return 0

            if query is None:
                self._conn.execute("DELETE FROM query_selections")
                self._conn.commit()
                return -1

            query_lower = query.lower().strip()

            if file_path is None:
                cursor = self._conn.execute(
                    "DELETE FROM query_selections WHERE query = ?",
                    (query_lower,),
                )
            else:
                cursor = self._conn.execute(
                    "DELETE FROM query_selections WHERE query = ? AND file_path = ?",
                    (query_lower, str(file_path)),
                )

            self._conn.commit()
            return cursor.rowcount


# Global singleton instance
_tracker: QueryHistoryTracker | None = None
_tracker_lock = threading.Lock()


def get_query_tracker(
    db_path: str | Path = ".attocode/query_history",
    *,
    min_combo_count: int = _MIN_COMBO_COUNT,
    combo_boost_multiplier: float = _COMBO_BOOST_MULTIPLIER,
) -> QueryHistoryTracker:
    """Get or create the global QueryHistoryTracker instance."""
    global _tracker

    with _tracker_lock:
        if _tracker is None:
            _tracker = QueryHistoryTracker(
                db_path=db_path,
                min_combo_count=min_combo_count,
                combo_boost_multiplier=combo_boost_multiplier,
            )
        return _tracker


def reset_query_tracker() -> None:
    """Reset the global tracker instance."""
    global _tracker

    with _tracker_lock:
        if _tracker is not None:
            _tracker.close()
            _tracker = None
