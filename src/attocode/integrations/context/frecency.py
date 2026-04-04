"""Frecency tracker for intelligent file ranking based on access patterns.

Frecency combines "frequency" and "recency" to rank files that are both
often accessed AND recently accessed. This is similar to browser bookmark
scoring or the fff.nvim frecency algorithm.

Algorithm:
- 10-day half-life (or 3-day for AI mode)
- 30-day lookback window
- Score = Σ e^(-ln(2)/10 * days_ago) with diminishing returns
- Modification bonus: +16 for <2min, +8 for <15min, etc.

Usage:
    tracker = FrecencyTracker(".attocode/frecency")
    tracker.track_access("src/main.py")
    score = tracker.get_score("src/main.py")
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Decay constants (ln(2)/10 for 10-day half-life)
_DECAY_CONSTANT: float = 0.069314718  # ln(2)/10
_SECONDS_PER_DAY: float = 86400.0
_MAX_HISTORY_DAYS: float = 30.0

# AI mode: faster decay since AI sessions are shorter
_AI_DECAY_CONSTANT: float = 0.231  # ln(2)/3 for 3-day half-life
_AI_MAX_HISTORY_DAYS: float = 7.0

# Modification score thresholds (seconds, points)
_MODIFICATION_THRESHOLDS: list[tuple[int, int]] = [
    (120, 16),       # < 2 minutes: 16 points
    (900, 8),        # < 15 minutes: 8 points
    (3600, 4),       # < 1 hour: 4 points
    (86400, 2),      # < 1 day: 2 points
    (604800, 1),     # < 1 week: 1 point
]

# AI mode: compressed thresholds since AI edits happen in rapid bursts
_AI_MODIFICATION_THRESHOLDS: list[tuple[int, int]] = [
    (30, 16),        # < 30 seconds: 16 points
    (300, 8),        # < 5 minutes: 8 points
    (900, 4),        # < 15 minutes: 4 points
    (3600, 2),       # < 1 hour: 2 points
    (14400, 1),      # < 4 hours: 1 point
]

# SQLite schema version
_SCHEMA_VERSION: int = 1


@dataclass
class FrecencyResult:
    """Result of a frecency query."""
    score: int
    accesses: int
    last_access: float | None
    is_ai_mode: bool


class FrecencyTracker:
    """Tracks file access patterns for intelligent ranking.

    Uses SQLite to store access timestamps per file path (keyed by path hash).
    Implements exponential decay with a 10-day half-life (or 3-day for AI mode).
    """

    def __init__(
        self,
        db_path: str | Path = ".attocode/frecency",
        *,
        ai_mode: bool = False,
    ) -> None:
        self._db_path = Path(db_path)
        self._ai_mode = ai_mode
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._ensure_db()

    def _ensure_db(self) -> None:
        """Ensure the database directory and tables exist."""
        self._db_path.mkdir(parents=True, exist_ok=True)
        db_file = self._db_path / "frecency.db"

        conn = sqlite3.connect(
            str(db_file),
            timeout=5.0,
            check_same_thread=False,
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        # Create tables
        conn.execute("""
            CREATE TABLE IF NOT EXISTS frecency_accesses (
                path_hash TEXT PRIMARY KEY,
                timestamps TEXT NOT NULL DEFAULT '[]',
                updated_at REAL NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        # Initialize schema version if not set
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

    def track_access(self, file_path: str | Path) -> None:
        """Record that a file was accessed.

        Args:
            file_path: Path to the file that was accessed.
        """
        path = str(file_path)
        now = time.time()

        with self._lock:
            if self._conn is None:
                return

            cursor = self._conn.execute(
                "SELECT timestamps FROM frecency_accesses WHERE path_hash = ?",
                (path,),
            )
            row = cursor.fetchone()

            if row is None:
                # New entry
                timestamps = [now]
                self._conn.execute(
                    "INSERT INTO frecency_accesses (path_hash, timestamps, updated_at) VALUES (?, ?, ?)",
                    (path, json.dumps(timestamps), now),
                )
            else:
                # Update existing
                timestamps: list[float] = json.loads(row[0])
                timestamps.append(now)

                # Prune old timestamps (beyond retention window)
                max_history = _AI_MAX_HISTORY_DAYS if self._ai_mode else _MAX_HISTORY_DAYS
                cutoff = now - (max_history * _SECONDS_PER_DAY)
                timestamps = [ts for ts in timestamps if ts >= cutoff]

                self._conn.execute(
                    "UPDATE frecency_accesses SET timestamps = ?, updated_at = ? WHERE path_hash = ?",
                    (json.dumps(timestamps), now, path),
                )

            self._conn.commit()

    def get_score(
        self,
        file_path: str | Path,
        *,
        modified_time: float | None = None,
        is_modified_git: bool = False,
        ai_mode: bool | None = None,
    ) -> FrecencyResult:
        """Calculate the frecency score for a file.

        Args:
            file_path: Path to the file.
            modified_time: Unix timestamp of last modification (for git score).
            is_modified_git: Whether the file has uncommitted changes.
            ai_mode: Override AI mode (default: use instance setting).

        Returns:
            FrecencyResult with score and metadata.
        """
        path = str(file_path)
        now = time.time()

        # Determine mode
        use_ai = self._ai_mode if ai_mode is None else ai_mode

        decay_constant = _AI_DECAY_CONSTANT if use_ai else _DECAY_CONSTANT
        max_history_days = _AI_MAX_HISTORY_DAYS if use_ai else _MAX_HISTORY_DAYS
        cutoff_time = now - (max_history_days * _SECONDS_PER_DAY)

        with self._lock:
            if self._conn is None:
                return FrecencyResult(score=0, accesses=0, last_access=None, is_ai_mode=use_ai)

            cursor = self._conn.execute(
                "SELECT timestamps FROM frecency_accesses WHERE path_hash = ?",
                (path,),
            )
            row = cursor.fetchone()

        if row is None:
            timestamps: list[float] = []
        else:
            timestamps = json.loads(row[0])

        # Filter to within retention window
        timestamps = [ts for ts in timestamps if ts >= cutoff_time]

        if not timestamps:
            accesses = 0
            total_frecency = 0.0
        else:
            accesses = len(timestamps)
            total_frecency = 0.0

            for access_time in timestamps:
                days_ago = (now - access_time) / _SECONDS_PER_DAY
                decay_factor = math.exp(-decay_constant * days_ago)
                total_frecency += decay_factor

        # Apply diminishing returns normalization
        # if total > 10: return 10 + sqrt(total - 10)
        if total_frecency <= 10.0:
            normalized = total_frecency
        else:
            normalized = 10.0 + math.sqrt(total_frecency - 10.0)

        frecency_score = round(normalized)

        # Add modification bonus
        if modified_time is not None and is_modified_git:
            thresholds = _AI_MODIFICATION_THRESHOLDS if use_ai else _MODIFICATION_THRESHOLDS
            duration_since = now - modified_time

            for threshold_seconds, points in thresholds:
                if duration_since <= threshold_seconds:
                    frecency_score += points
                    break

        last_access = timestamps[-1] if timestamps else None

        return FrecencyResult(
            score=frecency_score,
            accesses=accesses,
            last_access=last_access,
            is_ai_mode=use_ai,
        )

    def get_scores_batch(
        self,
        file_paths: list[str | Path],
        *,
        modified_times: dict[str, float] | None = None,
        git_status: dict[str, bool] | None = None,
        ai_mode: bool | None = None,
    ) -> dict[str, FrecencyResult]:
        """Get frecency scores for multiple files efficiently.

        Args:
            file_paths: List of file paths to score.
            modified_times: Dict mapping path -> modification timestamp.
            git_status: Dict mapping path -> is_modified bool.
            ai_mode: Override AI mode.

        Returns:
            Dict mapping path -> FrecencyResult.
        """
        modified_times = modified_times or {}
        git_status = git_status or {}

        results = {}
        for path in file_paths:
            path_str = str(path)
            results[path_str] = self.get_score(
                path_str,
                modified_time=modified_times.get(path_str),
                is_modified_git=git_status.get(path_str, False),
                ai_mode=ai_mode,
            )
        return results

    def clear(self, file_path: str | Path | None = None) -> int:
        """Clear frecency data.

        Args:
            file_path: If provided, clear only this file. Otherwise clear all.

        Returns:
            Number of entries cleared.
        """
        with self._lock:
            if self._conn is None:
                return 0

            if file_path is None:
                self._conn.execute("DELETE FROM frecency_accesses")
                self._conn.commit()
                return -1  # Indicates all cleared

            path = str(file_path)
            cursor = self._conn.execute(
                "DELETE FROM frecency_accesses WHERE path_hash = ?",
                (path,),
            )
            self._conn.commit()
            return cursor.rowcount

    def get_stats(self) -> dict:
        """Get frecency statistics."""
        with self._lock:
            if self._conn is None:
                return {"entries": 0, "ai_mode": self._ai_mode}

            cursor = self._conn.execute(
                "SELECT COUNT(*) FROM frecency_accesses",
            )
            row = cursor.fetchone()
            count = row[0] if row else 0

            return {
                "entries": count,
                "ai_mode": self._ai_mode,
                "db_path": str(self._db_path),
            }

    def get_leaderboard(
        self,
        top_n: int = 20,
        *,
        ai_mode: bool | None = None,
    ) -> list[tuple[str, FrecencyResult]]:
        """Get the top N files by frecency score.

        Args:
            top_n: Number of top files to return.
            ai_mode: Override AI mode (default: use instance setting).

        Returns:
            List of (path, FrecencyResult) tuples sorted by score descending.
        """
        with self._lock:
            if self._conn is None:
                return []
            cursor = self._conn.execute(
                "SELECT path_hash FROM frecency_accesses",
            )
            all_paths = [row[0] for row in cursor.fetchall()]

        # Score each path (get_score handles its own locking)
        scored: list[tuple[str, FrecencyResult]] = []
        for path in all_paths:
            result = self.get_score(path, ai_mode=ai_mode)
            if result.score > 0:
                scored.append((path, result))

        scored.sort(key=lambda x: x[1].score, reverse=True)
        return scored[:top_n]

    def vacuum(self) -> None:
        """Compact the database."""
        with self._lock:
            if self._conn is not None:
                self._conn.execute("VACUUM")


# Global singleton instance
_tracker: FrecencyTracker | None = None
_tracker_lock = threading.Lock()


def get_tracker(
    db_path: str | Path = ".attocode/frecency",
    *,
    ai_mode: bool = False,
) -> FrecencyTracker:
    """Get or create the global FrecencyTracker instance.

    Args:
        db_path: Path to the frecency database.
        ai_mode: Whether to use AI mode (faster decay).

    Returns:
        FrecencyTracker singleton.
    """
    global _tracker

    with _tracker_lock:
        if _tracker is None:
            _tracker = FrecencyTracker(db_path=db_path, ai_mode=ai_mode)
        return _tracker


def reset_tracker() -> None:
    """Reset the global tracker instance."""
    global _tracker

    with _tracker_lock:
        if _tracker is not None:
            _tracker.close()
            _tracker = None
