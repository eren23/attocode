"""SQLite-backed store for research campaigns."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from attoswarm.research.experiment import Experiment, FindingRecord, ResearchState, SteeringNote

logger = logging.getLogger(__name__)


class ExperimentDB:
    """SQLite store for research campaigns and experiment lineage."""

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
                parent_experiment_id TEXT DEFAULT '',
                related_experiment_ids_json TEXT DEFAULT '[]',
                strategy TEXT DEFAULT 'explore',
                status TEXT DEFAULT 'queued',
                hypothesis TEXT,
                branch TEXT DEFAULT '',
                worktree_path TEXT DEFAULT '',
                commit_hash TEXT DEFAULT '',
                diff TEXT,
                metric_value REAL,
                metrics_json TEXT DEFAULT '{}',
                baseline_value REAL,
                accepted INTEGER DEFAULT 0,
                reject_reason TEXT,
                tokens_used INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0,
                duration_s REAL DEFAULT 0.0,
                files_modified TEXT DEFAULT '[]',
                artifacts_json TEXT DEFAULT '[]',
                raw_output TEXT DEFAULT '',
                error TEXT,
                steering_notes_json TEXT DEFAULT '[]',
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

            CREATE TABLE IF NOT EXISTS findings (
                finding_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                experiment_id TEXT NOT NULL,
                claim TEXT NOT NULL,
                evidence TEXT DEFAULT '',
                confidence REAL DEFAULT 0.5,
                scope TEXT DEFAULT 'experiment',
                composeability TEXT DEFAULT 'unknown',
                status TEXT DEFAULT 'proposed',
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (run_id) REFERENCES research_runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS steering_notes (
                note_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                content TEXT NOT NULL,
                scope TEXT DEFAULT 'global',
                target TEXT DEFAULT '',
                active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (run_id) REFERENCES research_runs(run_id)
            );

            CREATE INDEX IF NOT EXISTS idx_experiments_run ON experiments(run_id, iteration);
            CREATE INDEX IF NOT EXISTS idx_experiments_metric ON experiments(run_id, metric_value);
            CREATE INDEX IF NOT EXISTS idx_checkpoints_run ON checkpoints(run_id);
            CREATE INDEX IF NOT EXISTS idx_findings_run ON findings(run_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_steering_run ON steering_notes(run_id, active, created_at);
        """)
        self._ensure_column(
            "experiments",
            "related_experiment_ids_json",
            "TEXT DEFAULT '[]'",
        )
        self._conn.commit()

    def _ensure_column(self, table: str, column: str, column_def: str) -> None:
        columns = {
            row["name"]
            for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}")

    def create_run(self, run_id: str, goal: str, config: dict[str, Any] | None = None) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO research_runs (run_id, goal, config_json, updated_at)
               VALUES (?, ?, ?, datetime('now'))""",
            (run_id, goal, json.dumps(config or {})),
        )
        self._conn.commit()

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM research_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        config: dict[str, Any] = {}
        raw_config = row["config_json"]
        if raw_config:
            try:
                parsed = json.loads(raw_config)
                if isinstance(parsed, dict):
                    config = parsed
            except json.JSONDecodeError:
                config = {}
        return {
            "run_id": row["run_id"],
            "goal": row["goal"],
            "config": config,
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def save_experiment(self, run_id: str, experiment: Experiment) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO experiments (
                experiment_id, run_id, iteration, parent_experiment_id, related_experiment_ids_json, strategy, status,
                hypothesis, branch, worktree_path, commit_hash, diff, metric_value,
                metrics_json, baseline_value, accepted, reject_reason, tokens_used,
                cost_usd, duration_s, files_modified, artifacts_json, raw_output,
                error, steering_notes_json, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                experiment.experiment_id,
                run_id,
                experiment.iteration,
                experiment.parent_experiment_id,
                json.dumps(experiment.related_experiment_ids),
                experiment.strategy,
                experiment.status,
                experiment.hypothesis,
                experiment.branch,
                experiment.worktree_path,
                experiment.commit_hash,
                experiment.diff[:20_000],
                experiment.metric_value,
                json.dumps(experiment.metrics),
                experiment.baseline_value,
                1 if experiment.accepted else 0,
                experiment.reject_reason,
                experiment.tokens_used,
                experiment.cost_usd,
                experiment.duration_s,
                json.dumps(experiment.files_modified),
                json.dumps(experiment.artifacts),
                experiment.raw_output[:20_000],
                experiment.error,
                json.dumps(experiment.steering_notes),
                experiment.timestamp,
            ),
        )
        self._conn.commit()

    def get_experiments(self, run_id: str) -> list[Experiment]:
        rows = self._conn.execute(
            "SELECT * FROM experiments WHERE run_id = ? ORDER BY iteration, experiment_id",
            (run_id,),
        ).fetchall()
        return [self._row_to_experiment(row) for row in rows]

    def get_experiment(self, run_id: str, experiment_id: str) -> Experiment | None:
        row = self._conn.execute(
            "SELECT * FROM experiments WHERE run_id = ? AND experiment_id = ?",
            (run_id, experiment_id),
        ).fetchone()
        return self._row_to_experiment(row) if row else None

    def get_best_experiment(self, run_id: str, direction: str = "maximize") -> Experiment | None:
        order = "DESC" if direction == "maximize" else "ASC"
        row = self._conn.execute(
            f"""SELECT * FROM experiments
                WHERE run_id = ? AND metric_value IS NOT NULL AND accepted = 1
                ORDER BY metric_value {order}, iteration ASC LIMIT 1""",
            (run_id,),
        ).fetchone()
        return self._row_to_experiment(row) if row else None

    def get_leaderboard(self, run_id: str, direction: str = "maximize", limit: int = 10) -> list[Experiment]:
        order = "DESC" if direction == "maximize" else "ASC"
        rows = self._conn.execute(
            f"""SELECT * FROM experiments
                WHERE run_id = ? AND metric_value IS NOT NULL
                ORDER BY metric_value {order}, iteration ASC LIMIT ?""",
            (run_id, limit),
        ).fetchall()
        return [self._row_to_experiment(row) for row in rows]

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

    def add_finding(self, run_id: str, finding: FindingRecord) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO findings (
                finding_id, run_id, experiment_id, claim, evidence, confidence,
                scope, composeability, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                finding.finding_id,
                run_id,
                finding.experiment_id,
                finding.claim,
                finding.evidence,
                finding.confidence,
                finding.scope,
                finding.composeability,
                finding.status,
                finding.created_at,
            ),
        )
        self._conn.commit()

    def list_findings(self, run_id: str, limit: int = 50) -> list[FindingRecord]:
        rows = self._conn.execute(
            "SELECT * FROM findings WHERE run_id = ? ORDER BY created_at DESC LIMIT ?",
            (run_id, limit),
        ).fetchall()
        return [self._row_to_finding(row) for row in rows]

    def add_steering_note(self, note: SteeringNote) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO steering_notes (
                note_id, run_id, content, scope, target, active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                note.note_id,
                note.run_id,
                note.content,
                note.scope,
                note.target,
                1 if note.active else 0,
                note.created_at,
            ),
        )
        self._conn.commit()

    def list_active_steering_notes(self, run_id: str) -> list[SteeringNote]:
        rows = self._conn.execute(
            """SELECT * FROM steering_notes
               WHERE run_id = ? AND active = 1
               ORDER BY created_at ASC, note_id ASC""",
            (run_id,),
        ).fetchall()
        return [self._row_to_steering(row) for row in rows]

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _row_to_experiment(row: sqlite3.Row) -> Experiment:
        return Experiment(
            experiment_id=row["experiment_id"],
            iteration=row["iteration"],
            hypothesis=row["hypothesis"] or "",
            parent_experiment_id=row["parent_experiment_id"] or "",
            related_experiment_ids=_loads_list(row["related_experiment_ids_json"]),
            strategy=row["strategy"] or "explore",
            status=row["status"] or "queued",
            branch=row["branch"] or "",
            worktree_path=row["worktree_path"] or "",
            commit_hash=row["commit_hash"] or "",
            diff=row["diff"] or "",
            metric_value=row["metric_value"],
            metrics=_loads_dict(row["metrics_json"]),
            baseline_value=row["baseline_value"],
            accepted=bool(row["accepted"]),
            reject_reason=row["reject_reason"] or "",
            tokens_used=row["tokens_used"] or 0,
            cost_usd=row["cost_usd"] or 0.0,
            duration_s=row["duration_s"] or 0.0,
            files_modified=_loads_list(row["files_modified"]),
            artifacts=_loads_list(row["artifacts_json"]),
            raw_output=row["raw_output"] or "",
            error=row["error"] or "",
            steering_notes=_loads_list(row["steering_notes_json"]),
            timestamp=row["timestamp"] or "",
        )

    @staticmethod
    def _row_to_finding(row: sqlite3.Row) -> FindingRecord:
        return FindingRecord(
            finding_id=row["finding_id"],
            experiment_id=row["experiment_id"],
            claim=row["claim"] or "",
            evidence=row["evidence"] or "",
            confidence=row["confidence"] or 0.5,
            scope=row["scope"] or "experiment",
            composeability=row["composeability"] or "unknown",
            status=row["status"] or "proposed",
            created_at=row["created_at"] or "",
        )

    @staticmethod
    def _row_to_steering(row: sqlite3.Row) -> SteeringNote:
        return SteeringNote(
            note_id=row["note_id"],
            run_id=row["run_id"],
            content=row["content"] or "",
            scope=row["scope"] or "global",
            target=row["target"] or "",
            active=bool(row["active"]),
            created_at=row["created_at"] or "",
        )


def _loads_dict(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _loads_list(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []
