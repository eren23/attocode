from __future__ import annotations

import asyncio
import subprocess
from types import SimpleNamespace
from typing import TYPE_CHECKING

from attoswarm.research.evaluator import EvalResult
from attoswarm.research.experiment import Experiment, FindingRecord, ResearchState
from attoswarm.research.experiment_db import ExperimentDB
from attoswarm.research.research_orchestrator import ResearchOrchestrator

if TYPE_CHECKING:
    from pathlib import Path


def _init_repo(repo: Path, files: dict[str, str]) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    for relative_path, content in files.items():
        target = repo / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "init",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def test_research_orchestrator_sets_error_when_baseline_fails(tmp_path: Path) -> None:
    from attoswarm.research.config import ResearchConfig

    repo = tmp_path / "repo"
    _init_repo(repo, {"target.txt": "base\n"})

    class FailingEvaluator:
        async def evaluate(self, working_dir: str) -> EvalResult:
            return EvalResult(metric_value=0.0, success=False, error="baseline failed")

    orchestrator = ResearchOrchestrator(
        ResearchConfig(working_dir=str(repo), run_dir=str(tmp_path / "runs"), eval_command=""),
        "improve metric",
        evaluator=FailingEvaluator(),
    )

    state = asyncio.run(orchestrator.run())

    assert state.status == "error"
    assert state.total_experiments == 0


def test_research_orchestrator_stops_on_budget_after_baseline(tmp_path: Path) -> None:
    from attoswarm.research.config import ResearchConfig

    repo = tmp_path / "repo"
    _init_repo(repo, {"target.txt": "base\n"})

    class StaticEvaluator:
        async def evaluate(self, working_dir: str) -> EvalResult:
            return EvalResult(metric_value=1.0)

    orchestrator = ResearchOrchestrator(
        ResearchConfig(
            working_dir=str(repo),
            run_dir=str(tmp_path / "runs"),
            eval_command="",
            total_max_cost_usd=0.0,
            total_max_experiments=5,
        ),
        "improve metric",
        evaluator=StaticEvaluator(),
    )

    state = asyncio.run(orchestrator.run())

    assert state.status == "budget_exceeded"
    assert state.baseline_value == 1.0
    assert state.total_experiments == 0


def test_research_orchestrator_records_error_experiment_when_no_spawn_fn(tmp_path: Path) -> None:
    from attoswarm.research.config import ResearchConfig

    repo = tmp_path / "repo"
    _init_repo(repo, {"target.txt": "base\n"})

    class StaticEvaluator:
        async def evaluate(self, working_dir: str) -> EvalResult:
            return EvalResult(metric_value=0.0)

    orchestrator = ResearchOrchestrator(
        ResearchConfig(
            working_dir=str(repo),
            run_dir=str(tmp_path / "runs"),
            eval_command="",
            total_max_experiments=1,
            target_files=["target.txt"],
        ),
        "improve metric",
        evaluator=StaticEvaluator(),
        spawn_fn=None,
    )

    state = asyncio.run(orchestrator.run())

    assert state.total_experiments == 1
    exp = orchestrator._experiments[0]
    assert exp.status == "error"
    assert exp.error == "No spawn function configured for non-reproduce experiment"
    assert len(orchestrator._findings) == 1
    assert "invalid result" in orchestrator._findings[0].claim


def test_research_orchestrator_removes_rejected_worktrees_when_disabled(tmp_path: Path) -> None:
    from attoswarm.research.config import ResearchConfig

    repo = tmp_path / "repo"
    _init_repo(repo, {"target.txt": "base\n"})

    class StaticEvaluator:
        async def evaluate(self, working_dir: str) -> EvalResult:
            return EvalResult(metric_value=0.0)

    async def noop_spawn(task: dict) -> SimpleNamespace:
        return SimpleNamespace(result_summary="no change", tokens_used=1, cost_usd=0.0)

    orchestrator = ResearchOrchestrator(
        ResearchConfig(
            working_dir=str(repo),
            run_dir=str(tmp_path / "runs"),
            eval_command="",
            total_max_experiments=1,
            preserve_worktrees=False,
            target_files=["target.txt"],
        ),
        "improve metric",
        evaluator=StaticEvaluator(),
        spawn_fn=noop_spawn,
    )

    state = asyncio.run(orchestrator.run())

    assert state.rejected_count == 1
    exp = orchestrator._experiments[0]
    assert exp.status == "rejected"
    assert exp.worktree_path == ""


def test_research_orchestrator_resume_rehydrates_experiments_and_findings(tmp_path: Path) -> None:
    from attoswarm.research.config import ResearchConfig

    repo = tmp_path / "repo"
    _init_repo(repo, {"target.txt": "base\n"})
    run_dir = tmp_path / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    store = ExperimentDB(run_dir / "research.db")
    try:
        store.create_run("run-resume", "resume me", config={"metric_name": "score", "metric_direction": "maximize"})
        store.save_experiment(
            "run-resume",
            Experiment(
                experiment_id="exp-1",
                iteration=1,
                hypothesis="existing experiment",
                status="accepted",
                strategy="explore",
                metric_value=1.5,
                accepted=True,
            ),
        )
        store.add_finding(
            "run-resume",
            FindingRecord(
                finding_id="finding-1",
                experiment_id="exp-1",
                claim="existing finding",
                confidence=0.8,
            ),
        )
        store.save_checkpoint(
            "run-resume",
            ResearchState(
                run_id="run-resume",
                goal="resume me",
                metric_name="score",
                metric_direction="maximize",
                baseline_value=1.0,
                best_value=1.5,
                best_experiment_id="exp-1",
                total_experiments=1,
                accepted_count=1,
            ),
        )
    finally:
        store.close()

    class StaticEvaluator:
        async def evaluate(self, working_dir: str) -> EvalResult:
            return EvalResult(metric_value=0.0)

    orchestrator = ResearchOrchestrator(
        ResearchConfig(
            working_dir=str(repo),
            run_dir=str(run_dir),
            eval_command="",
            total_max_experiments=1,
        ),
        "resume me",
        evaluator=StaticEvaluator(),
    )

    state = asyncio.run(orchestrator.run(resume_run_id="run-resume"))

    assert state.run_id == "run-resume"
    assert state.best_experiment_id == "exp-1"
    assert len(orchestrator._experiments) == 1
    assert len(orchestrator._findings) == 1
