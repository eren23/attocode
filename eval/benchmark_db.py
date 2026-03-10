"""SQLite store for benchmark history and regression tracking.

Stores per-run, per-repo benchmark metrics for time-series analysis
and CI regression detection.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any


def get_git_info(cwd: str | None = None) -> dict:
    """Get current git SHA and branch."""
    info = {"sha": "unknown", "branch": "unknown"}
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd, capture_output=True, text=True, timeout=10,
        )
        info["sha"] = result.stdout.strip()
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd, capture_output=True, text=True, timeout=10,
        )
        info["branch"] = result.stdout.strip()
    except Exception:
        pass
    return info


@dataclass(slots=True)
class BenchmarkEntry:
    """Single repo benchmark result within a run."""
    repo: str
    bootstrap_time_ms: float
    symbol_count: int
    quality_score: float
    total_time_ms: float = 0.0
    file_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BenchmarkRun:
    """A complete benchmark run across repos."""
    run_id: str
    timestamp: str
    git_sha: str
    branch: str
    entries: list[BenchmarkEntry] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class BenchmarkDB:
    """SQLite database for storing benchmark history."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> None:
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self) -> None:
        assert self._conn is not None
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS benchmark_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL UNIQUE,
                timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                git_sha TEXT,
                branch TEXT,
                metadata_json TEXT
            );

            CREATE TABLE IF NOT EXISTS benchmark_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                repo TEXT NOT NULL,
                bootstrap_time_ms REAL,
                symbol_count INTEGER,
                quality_score REAL,
                total_time_ms REAL,
                file_count INTEGER DEFAULT 0,
                metadata_json TEXT,
                UNIQUE(run_id, repo),
                FOREIGN KEY (run_id) REFERENCES benchmark_runs(run_id)
            );

            CREATE INDEX IF NOT EXISTS idx_entries_run
                ON benchmark_entries(run_id);
            CREATE INDEX IF NOT EXISTS idx_entries_repo
                ON benchmark_entries(repo);
        """)
        self._conn.commit()

    def save_run(self, run: BenchmarkRun) -> None:
        """Save a complete benchmark run."""
        assert self._conn is not None
        self._conn.execute(
            """INSERT OR REPLACE INTO benchmark_runs
            (run_id, timestamp, git_sha, branch, metadata_json)
            VALUES (?, ?, ?, ?, ?)""",
            (run.run_id, run.timestamp, run.git_sha, run.branch,
             json.dumps(run.metadata)),
        )
        for entry in run.entries:
            self._conn.execute(
                """INSERT OR REPLACE INTO benchmark_entries
                (run_id, repo, bootstrap_time_ms, symbol_count, quality_score,
                 total_time_ms, file_count, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (run.run_id, entry.repo, entry.bootstrap_time_ms,
                 entry.symbol_count, entry.quality_score, entry.total_time_ms,
                 entry.file_count, json.dumps(entry.metadata)),
            )
        self._conn.commit()

    def get_run(self, run_id: str) -> BenchmarkRun | None:
        """Load a benchmark run by ID."""
        assert self._conn is not None
        cursor = self._conn.execute(
            "SELECT run_id, timestamp, git_sha, branch, metadata_json "
            "FROM benchmark_runs WHERE run_id = ?",
            (run_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        run = BenchmarkRun(
            run_id=row[0], timestamp=row[1], git_sha=row[2],
            branch=row[3], metadata=json.loads(row[4] or "{}"),
        )
        entries_cursor = self._conn.execute(
            "SELECT repo, bootstrap_time_ms, symbol_count, quality_score, "
            "total_time_ms, file_count, metadata_json "
            "FROM benchmark_entries WHERE run_id = ? ORDER BY repo",
            (run_id,),
        )
        for erow in entries_cursor:
            run.entries.append(BenchmarkEntry(
                repo=erow[0], bootstrap_time_ms=erow[1], symbol_count=erow[2],
                quality_score=erow[3], total_time_ms=erow[4], file_count=erow[5],
                metadata=json.loads(erow[6] or "{}"),
            ))
        return run

    def get_latest_run(self, branch: str = "main") -> BenchmarkRun | None:
        """Get most recent run for a branch."""
        assert self._conn is not None
        cursor = self._conn.execute(
            "SELECT run_id FROM benchmark_runs WHERE branch = ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (branch,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self.get_run(row[0])

    def get_history(
        self,
        repo: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get benchmark history, optionally filtered by repo."""
        assert self._conn is not None
        if repo:
            cursor = self._conn.execute(
                """SELECT r.run_id, r.timestamp, r.git_sha, r.branch,
                          e.bootstrap_time_ms, e.symbol_count, e.quality_score
                   FROM benchmark_runs r
                   JOIN benchmark_entries e ON r.run_id = e.run_id
                   WHERE e.repo = ?
                   ORDER BY r.timestamp DESC LIMIT ?""",
                (repo, limit),
            )
        else:
            cursor = self._conn.execute(
                """SELECT r.run_id, r.timestamp, r.git_sha, r.branch,
                          AVG(e.bootstrap_time_ms), SUM(e.symbol_count),
                          AVG(e.quality_score)
                   FROM benchmark_runs r
                   JOIN benchmark_entries e ON r.run_id = e.run_id
                   GROUP BY r.run_id
                   ORDER BY r.timestamp DESC LIMIT ?""",
                (limit,),
            )
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
