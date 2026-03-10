"""Generic evaluation harness for running agent benchmarks.

Provides the core infrastructure for setting up benchmark instances,
running the agent, verifying results, and collecting metrics.

Usage:
    harness = EvalHarness(agent_factory=create_agent, results_db="eval_results.db")
    results = await harness.run_suite(instances, concurrency=4)
    harness.report(results)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Protocol

logger = logging.getLogger(__name__)


# =============================================================================
# Types
# =============================================================================


class InstanceStatus(StrEnum):
    """Status of a benchmark instance run."""

    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


@dataclass(slots=True)
class BenchInstance:
    """A single benchmark instance (e.g., one SWE-bench problem).

    Attributes:
        instance_id: Unique identifier (e.g., "django__django-16379").
        repo: Repository URL or path.
        base_commit: Git commit to start from.
        problem_statement: The issue description the agent should solve.
        patch_gold: The gold (correct) patch for verification.
        test_patch: The test patch to apply for verification.
        hints: Optional hints for the agent.
        metadata: Extra metadata (e.g., difficulty, category).
    """

    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    patch_gold: str = ""
    test_patch: str = ""
    hints: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RunResult:
    """Result of running the agent on a single instance.

    Captures everything needed for analysis and regression testing.
    """

    instance_id: str
    status: InstanceStatus
    patch_generated: str = ""
    agent_output: str = ""
    tokens_used: int = 0
    cost_usd: float = 0.0
    wall_time_seconds: float = 0.0
    iterations: int = 0
    tool_calls: int = 0
    error: str = ""
    model: str = ""
    tests_passed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentFactory(Protocol):
    """Protocol for creating agent instances for evaluation."""

    async def create_and_run(
        self,
        working_dir: str,
        problem_statement: str,
        *,
        model: str | None = None,
        max_iterations: int = 50,
        timeout: float = 600.0,
    ) -> dict[str, Any]:
        """Create agent, run on problem, return result dict.

        Expected return keys:
            success: bool
            output: str
            tokens_used: int
            cost: float
            iterations: int
            tool_calls: int
            model: str
        """
        ...


# =============================================================================
# Instance Setup
# =============================================================================


def setup_instance(
    instance: BenchInstance,
    work_dir: str,
) -> str:
    """Set up a benchmark instance in a working directory.

    Clones the repo (or copies), checks out the base commit, and returns
    the path to the working directory.
    """
    instance_dir = os.path.join(work_dir, instance.instance_id)
    os.makedirs(instance_dir, exist_ok=True)

    # Clone repo
    if instance.repo.startswith("http") or instance.repo.startswith("git@"):
        subprocess.run(
            ["git", "clone", "--depth=1", instance.repo, instance_dir],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    elif os.path.isdir(instance.repo):
        subprocess.run(
            ["git", "clone", instance.repo, instance_dir],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    # Checkout base commit
    if instance.base_commit:
        subprocess.run(
            ["git", "checkout", instance.base_commit],
            cwd=instance_dir,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    return instance_dir


def verify_instance(
    instance: BenchInstance,
    instance_dir: str,
) -> bool:
    """Verify an instance result by applying test patch and running tests.

    Returns True if the agent's changes pass the test patch.
    """
    if not instance.test_patch:
        return False

    try:
        # Apply test patch
        proc = subprocess.run(
            ["git", "apply", "--check", "-"],
            input=instance.test_patch,
            cwd=instance_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            # Test patch doesn't apply cleanly — might already be applied
            pass

        subprocess.run(
            ["git", "apply", "-"],
            input=instance.test_patch,
            cwd=instance_dir,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        # Run tests
        test_result = subprocess.run(
            ["python", "-m", "pytest", "--tb=short", "-q", "-x"],
            cwd=instance_dir,
            capture_output=True,
            text=True,
            timeout=300,
        )
        return test_result.returncode == 0

    except Exception as exc:
        logger.warning("Verification failed for %s: %s", instance.instance_id, exc)
        return False


def get_generated_patch(instance_dir: str) -> str:
    """Get the git diff of changes the agent made."""
    try:
        result = subprocess.run(
            ["git", "diff"],
            cwd=instance_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout
    except Exception:
        return ""


# =============================================================================
# Results Database
# =============================================================================


class ResultsDB:
    """SQLite database for storing evaluation results."""

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
            CREATE TABLE IF NOT EXISTS eval_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                model TEXT,
                config_json TEXT,
                total_instances INTEGER DEFAULT 0,
                passed INTEGER DEFAULT 0,
                failed INTEGER DEFAULT 0,
                errors INTEGER DEFAULT 0,
                pass_rate REAL DEFAULT 0.0,
                total_tokens INTEGER DEFAULT 0,
                total_cost REAL DEFAULT 0.0,
                total_wall_time REAL DEFAULT 0.0
            );

            CREATE TABLE IF NOT EXISTS instance_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                instance_id TEXT NOT NULL,
                status TEXT NOT NULL,
                patch_generated TEXT,
                agent_output TEXT,
                tokens_used INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0,
                wall_time_seconds REAL DEFAULT 0.0,
                iterations INTEGER DEFAULT 0,
                tool_calls INTEGER DEFAULT 0,
                tests_passed INTEGER DEFAULT 0,
                error TEXT,
                model TEXT,
                metadata_json TEXT,
                UNIQUE(run_id, instance_id)
            );

            CREATE INDEX IF NOT EXISTS idx_instance_results_run
                ON instance_results(run_id);
        """)
        self._conn.commit()

    def save_result(self, run_id: str, result: RunResult) -> None:
        assert self._conn is not None
        self._conn.execute(
            """INSERT OR REPLACE INTO instance_results
            (run_id, instance_id, status, patch_generated, agent_output,
             tokens_used, cost_usd, wall_time_seconds, iterations,
             tool_calls, tests_passed, error, model, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                result.instance_id,
                result.status.value,
                result.patch_generated[:10000],  # Cap patch size
                result.agent_output[:5000],
                result.tokens_used,
                result.cost_usd,
                result.wall_time_seconds,
                result.iterations,
                result.tool_calls,
                1 if result.tests_passed else 0,
                result.error[:2000] if result.error else "",
                result.model,
                json.dumps(result.metadata),
            ),
        )
        self._conn.commit()

    def save_run_summary(
        self,
        run_id: str,
        model: str,
        config: dict[str, Any],
        results: list[RunResult],
    ) -> None:
        assert self._conn is not None
        passed = sum(1 for r in results if r.status == InstanceStatus.PASSED)
        failed = sum(1 for r in results if r.status == InstanceStatus.FAILED)
        errors = sum(1 for r in results if r.status == InstanceStatus.ERROR)
        total = len(results)
        pass_rate = passed / total if total > 0 else 0.0

        self._conn.execute(
            """INSERT INTO eval_runs
            (run_id, model, config_json, total_instances, passed, failed,
             errors, pass_rate, total_tokens, total_cost, total_wall_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                model,
                json.dumps(config),
                total,
                passed,
                failed,
                errors,
                pass_rate,
                sum(r.tokens_used for r in results),
                sum(r.cost_usd for r in results),
                sum(r.wall_time_seconds for r in results),
            ),
        )
        self._conn.commit()

    def get_run_history(self, limit: int = 20) -> list[dict[str, Any]]:
        assert self._conn is not None
        cursor = self._conn.execute(
            """SELECT run_id, timestamp, model, total_instances, passed,
                      pass_rate, total_tokens, total_cost, total_wall_time
               FROM eval_runs ORDER BY timestamp DESC LIMIT ?""",
            (limit,),
        )
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_run_results(self, run_id: str) -> list[dict[str, Any]]:
        assert self._conn is not None
        cursor = self._conn.execute(
            """SELECT instance_id, status, patch_generated, tokens_used, cost_usd,
                      wall_time_seconds, tests_passed, error, model, metadata_json
               FROM instance_results WHERE run_id = ?
               ORDER BY instance_id""",
            (run_id,),
        )
        columns = [d[0] for d in cursor.description]
        results: list[dict[str, Any]] = []
        for row in cursor.fetchall():
            item = dict(zip(columns, row))
            raw_meta = item.pop("metadata_json", "")
            if raw_meta:
                try:
                    item["metadata"] = json.loads(raw_meta)
                except json.JSONDecodeError:
                    item["metadata"] = {}
            else:
                item["metadata"] = {}
            results.append(item)
        return results

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


# =============================================================================
# Eval Harness
# =============================================================================


class EvalHarness:
    """Main evaluation harness — runs agent on benchmark instances.

    Coordinates setup, execution, verification, and result collection.
    Supports concurrent execution for throughput.
    """

    def __init__(
        self,
        agent_factory: AgentFactory,
        results_db: str = "eval_results.db",
        work_dir: str | None = None,
        model: str = "",
        max_iterations: int = 50,
        timeout: float = 600.0,
    ) -> None:
        self.agent_factory = agent_factory
        self.model = model
        self.max_iterations = max_iterations
        self.timeout = timeout
        self.work_dir = work_dir or tempfile.mkdtemp(prefix="attocode-eval-")

        self._db = ResultsDB(results_db)
        self._db.connect()

    async def run_instance(self, instance: BenchInstance) -> RunResult:
        """Run the agent on a single benchmark instance."""
        start_time = time.monotonic()
        instance_dir = ""

        try:
            # Setup
            instance_dir = setup_instance(instance, self.work_dir)

            # Optional per-instance hook for factories that need full BenchInstance context.
            bind_instance = getattr(self.agent_factory, "set_instance", None)
            if callable(bind_instance):
                bind_instance(instance)

            # Run agent
            agent_result = await self.agent_factory.create_and_run(
                working_dir=instance_dir,
                problem_statement=instance.problem_statement,
                model=self.model or None,
                max_iterations=self.max_iterations,
                timeout=self.timeout,
            )

            wall_time = time.monotonic() - start_time

            # Get generated patch
            patch = get_generated_patch(instance_dir)

            # Verify
            tests_passed = verify_instance(instance, instance_dir) if patch else False

            status = InstanceStatus.PASSED if tests_passed else InstanceStatus.FAILED

            return RunResult(
                instance_id=instance.instance_id,
                status=status,
                patch_generated=patch,
                agent_output=agent_result.get("output", ""),
                tokens_used=agent_result.get("tokens_used", 0),
                cost_usd=agent_result.get("cost", 0.0),
                wall_time_seconds=wall_time,
                iterations=agent_result.get("iterations", 0),
                tool_calls=agent_result.get("tool_calls", 0),
                model=agent_result.get("model", self.model),
                tests_passed=tests_passed,
                metadata={
                    "repo": instance.repo,
                    "base_commit": instance.base_commit,
                    "problem_statement": instance.problem_statement,
                    "test_patch": instance.test_patch,
                    "patch_gold": instance.patch_gold,
                    "hints": instance.hints,
                    "instance_metadata": instance.metadata,
                    "working_dir": instance_dir,
                },
            )

        except asyncio.TimeoutError:
            return RunResult(
                instance_id=instance.instance_id,
                status=InstanceStatus.TIMEOUT,
                wall_time_seconds=time.monotonic() - start_time,
                error="Agent timed out",
                model=self.model,
                metadata={
                    "repo": instance.repo,
                    "base_commit": instance.base_commit,
                    "problem_statement": instance.problem_statement,
                    "test_patch": instance.test_patch,
                    "patch_gold": instance.patch_gold,
                    "hints": instance.hints,
                    "instance_metadata": instance.metadata,
                    "working_dir": instance_dir,
                },
            )
        except Exception as exc:
            return RunResult(
                instance_id=instance.instance_id,
                status=InstanceStatus.ERROR,
                wall_time_seconds=time.monotonic() - start_time,
                error=str(exc),
                model=self.model,
                metadata={
                    "repo": instance.repo,
                    "base_commit": instance.base_commit,
                    "problem_statement": instance.problem_statement,
                    "test_patch": instance.test_patch,
                    "patch_gold": instance.patch_gold,
                    "hints": instance.hints,
                    "instance_metadata": instance.metadata,
                    "working_dir": instance_dir,
                },
            )

    async def run_suite(
        self,
        instances: list[BenchInstance],
        *,
        run_id: str = "",
        concurrency: int = 1,
        config: dict[str, Any] | None = None,
    ) -> list[RunResult]:
        """Run agent on all instances with configurable concurrency.

        Args:
            instances: Benchmark instances to evaluate.
            run_id: Unique ID for this eval run. Auto-generated if empty.
            concurrency: Max parallel instances.
            config: Config metadata to store with results.

        Returns:
            List of RunResult for each instance.
        """
        if not run_id:
            run_id = f"eval-{int(time.time())}"

        semaphore = asyncio.Semaphore(concurrency)
        results: list[RunResult] = []

        async def run_with_semaphore(inst: BenchInstance) -> RunResult:
            async with semaphore:
                logger.info("Running instance %s", inst.instance_id)
                result = await self.run_instance(inst)
                self._db.save_result(run_id, result)
                logger.info(
                    "Instance %s: %s (%.1fs, %d tokens)",
                    inst.instance_id,
                    result.status.value,
                    result.wall_time_seconds,
                    result.tokens_used,
                )
                return result

        tasks = [run_with_semaphore(inst) for inst in instances]
        results = await asyncio.gather(*tasks)

        # Save run summary
        self._db.save_run_summary(
            run_id,
            self.model,
            config or {},
            list(results),
        )

        return list(results)

    def report(self, results: list[RunResult]) -> str:
        """Generate a text report from results."""
        from eval.metrics import compute_metrics, format_report
        metrics = compute_metrics(results)
        return format_report(metrics)

    def close(self) -> None:
        """Close database connection."""
        self._db.close()
