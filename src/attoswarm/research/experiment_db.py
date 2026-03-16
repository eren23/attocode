"""SQLite-backed experiment database for research mode."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from attoswarm.research.experiment import Experiment, ResearchState

logger = logging.getLogger(__name__)


class ExperimentDB:
    """SQLite store for research experiments.

    Tables:
    - research_runs: overall run metadata
    - experiments: individual experiment results
    - checkpoints: periodic state snapshots for resume
    """

    def __init__(self, db_path: str | Path) -> None:
        self._path = str(db_path)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS research_runs (
                run_id TEXT PRIMARY KEY,
                goal TEXT NOT NULL,
                config_json TEXT,
                status TEXT DEFAULT 'running',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS experiments (
                experiment_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                iteration INTEGER NOT NULL,
                hypothesis TEXT,
                diff TEXT,
                metric_value REAL,
                baseline_value REAL,
                accepted INTEGER DEFAULT 0,
                reject_reason TEXT,
                tokens_used INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0,
                duration_s REAL DEFAULT 0.0,
                files_modified TEXT,
                error TEXT,
                timestamp TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (run_id) REFERENCES research_runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS checkpoints (
                checkpoint_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                state_json TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (run_id) REFERENCES research_runs(run_id)
            );

            CREATE INDEX IF NOT EXISTS idx_experiments_run ON experiments(run_id, iteration);
            CREATE INDEX IF NOT EXISTS idx_checkpoints_run ON checkpoints(run_id);
        """)
        self._conn.commit()

    def create_run(self, run_id: str, goal: str, config: dict[str, Any] | None = None) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO research_runs (run_id, goal, config_json) VALUES (?, ?, ?)",
            (run_id, goal, json.dumps(config or {})),
        )
        self._conn.commit()

    def save_experiment(self, run_id: str, experiment: Experiment) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO experiments
            (experiment_id, run_id, iteration, hypothesis, diff, metric_value,
             baseline_value, accepted, reject_reason, tokens_used, cost_usd,
             duration_s, files_modified, error, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                experiment.experiment_id,
                run_id,
                experiment.iteration,
                experiment.hypothesis,
                experiment.diff[:5000],
                experiment.metric_value,
                experiment.baseline_value,
                1 if experiment.accepted else 0,
                experiment.reject_reason,
                experiment.tokens_used,
                experiment.cost_usd,
                experiment.duration_s,
                json.dumps(experiment.files_modified),
                experiment.error,
                experiment.timestamp,
            ),
        )
        self._conn.commit()

    def get_experiments(self, run_id: str) -> list[Experiment]:
        rows = self._conn.execute(
            "SELECT * FROM experiments WHERE run_id = ? ORDER BY iteration",
            (run_id,),
        ).fetchall()
        return [self._row_to_experiment(row) for row in rows]

    def get_best_experiment(self, run_id: str, direction: str = "maximize") -> Experiment | None:
        order = "DESC" if direction == "maximize" else "ASC"
        row = self._conn.execute(
            f"SELECT * FROM experiments WHERE run_id = ? AND accepted = 1 "
            f"ORDER BY metric_value {order} LIMIT 1",
            (run_id,),
        ).fetchone()
        return self._row_to_experiment(row) if row else None

    def save_checkpoint(self, run_id: str, state: ResearchState) -> None:
        self._conn.execute(
            "INSERT INTO checkpoints (run_id, state_json) VALUES (?, ?)",
            (run_id, json.dumps(state.to_dict())),
        )
        self._conn.commit()

    def load_checkpoint(self, run_id: str) -> ResearchState | None:
        row = self._conn.execute(
            "SELECT state_json FROM checkpoints WHERE run_id = ? ORDER BY checkpoint_id DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        if not row:
            return None
        data = json.loads(row["state_json"])
        return ResearchState(**{k: v for k, v in data.items() if k in ResearchState.__dataclass_fields__})

    def update_run_status(self, run_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE research_runs SET status = ?, updated_at = datetime('now') WHERE run_id = ?",
            (status, run_id),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _row_to_experiment(row: sqlite3.Row) -> Experiment:
        files = json.loads(row["files_modified"]) if row["files_modified"] else []
        return Experiment(
            experiment_id=row["experiment_id"],
            iteration=row["iteration"],
            hypothesis=row["hypothesis"] or "",
            diff=row["diff"] or "",
            metric_value=row["metric_value"],
            baseline_value=row["baseline_value"],
            accepted=bool(row["accepted"]),
            reject_reason=row["reject_reason"] or "",
            tokens_used=row["tokens_used"] or 0,
            cost_usd=row["cost_usd"] or 0.0,
            duration_s=row["duration_s"] or 0.0,
            files_modified=files,
            error=row["error"] or "",
            timestamp=row["timestamp"] or "",
        )
