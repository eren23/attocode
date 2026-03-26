from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from attoswarm.research.config import ResearchConfig
from attoswarm.research.evaluator import CommandEvaluator
from attoswarm.research.experiment import Experiment
from attoswarm.research.research_orchestrator import ResearchOrchestrator

from .research_helpers import (
    build_eval_command,
    commit_all,
    git,
    init_repo,
    spawn_fake_worker,
    write_fake_worker,
    write_metric_evaluator,
)

if TYPE_CHECKING:
    from pathlib import Path


pytestmark = pytest.mark.integration


def test_research_orchestrator_real_compose_preapplies_related_patch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo, {"target.txt": "base\n", "compose.txt": "base\n"})
    base = git(repo, "rev-parse", "HEAD")

    (repo / "target.txt").write_text("base\nbetter\n", encoding="utf-8")
    best_commit = commit_all(repo, "best")

    git(repo, "checkout", base)
    (repo / "compose.txt").write_text("base\nimported\n", encoding="utf-8")
    compose_commit = commit_all(repo, "compose")
    compose_diff = git(repo, "show", "--stat", "--patch", "--format=", compose_commit)
    git(repo, "checkout", best_commit)

    worker_script = tmp_path / "fake_worker.py"
    eval_script = tmp_path / "eval_metric.py"
    write_fake_worker(worker_script)
    write_metric_evaluator(eval_script, target_file="compose.txt", token="composed")

    cfg = ResearchConfig(
        working_dir=str(repo),
        run_dir=str(tmp_path / "runs"),
        eval_command=build_eval_command(eval_script),
        total_max_experiments=1,
        max_parallel_experiments=1,
        strategy_mix={"compose": 1, "explore": 0, "exploit": 0, "ablate": 0, "reproduce": 0},
        target_files=["target.txt", "compose.txt"],
        steering_enabled=False,
    )
    orchestrator = ResearchOrchestrator(
        cfg,
        "compose accepted techniques",
        evaluator=CommandEvaluator(cfg.eval_command),
        spawn_fn=lambda task: spawn_fake_worker(worker_script, task),
    )
    orchestrator._state.baseline_value = 0.0
    orchestrator._state.best_value = 0.0
    orchestrator._state.best_experiment_id = "exp-best"
    orchestrator._experiments = [
        Experiment(
            experiment_id="exp-best",
            iteration=1,
            hypothesis="best branch",
            status="accepted",
            strategy="exploit",
            metric_value=0.0,
            accepted=True,
            commit_hash=best_commit,
            files_modified=["target.txt"],
            diff="+better\n",
        ),
        Experiment(
            experiment_id="exp-compose",
            iteration=2,
            hypothesis="orthogonal patch",
            status="accepted",
            strategy="explore",
            metric_value=0.5,
            accepted=True,
            commit_hash=compose_commit,
            files_modified=["compose.txt"],
            diff=compose_diff,
        ),
    ]

    state = asyncio.run(orchestrator.run())

    assert state.accepted_count == 3
    exp = orchestrator._experiments[-1]
    assert exp.strategy == "compose"
    assert exp.accepted is True
    assert exp.related_experiment_ids == ["exp-compose"]
    assert "compose import applied: exp-compose" in exp.raw_output
    assert "compose-ready" in exp.raw_output
    assert "compose.txt" in exp.files_modified
    assert repo.joinpath("compose.txt").read_text(encoding="utf-8") == "base\n"


def test_research_orchestrator_real_ablate_starts_from_best_branch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo, {"target.txt": "base\n"})

    (repo / "target.txt").write_text("base\nfeature\nbetter\n", encoding="utf-8")
    best_commit = commit_all(repo, "best")

    worker_script = tmp_path / "fake_worker.py"
    eval_script = tmp_path / "eval_metric.py"
    write_fake_worker(worker_script)
    write_metric_evaluator(eval_script, token="feature")

    cfg = ResearchConfig(
        working_dir=str(repo),
        run_dir=str(tmp_path / "runs"),
        eval_command=build_eval_command(eval_script),
        total_max_experiments=1,
        max_parallel_experiments=1,
        metric_direction="minimize",
        strategy_mix={"ablate": 1, "compose": 0, "explore": 0, "exploit": 0, "reproduce": 0},
        target_files=["target.txt"],
        steering_enabled=False,
    )
    orchestrator = ResearchOrchestrator(
        cfg,
        "ablate one mechanism",
        evaluator=CommandEvaluator(cfg.eval_command),
        spawn_fn=lambda task: spawn_fake_worker(worker_script, task),
    )
    orchestrator._state.baseline_value = 1.0
    orchestrator._state.best_value = 1.0
    orchestrator._state.best_experiment_id = "exp-best"
    orchestrator._experiments = [
        Experiment(
            experiment_id="exp-best",
            iteration=1,
            hypothesis="best branch",
            status="accepted",
            strategy="exploit",
            metric_value=1.0,
            accepted=True,
            commit_hash=best_commit,
            files_modified=["target.txt"],
            diff="+feature\n+better\n",
        ),
    ]

    state = asyncio.run(orchestrator.run())

    assert state.accepted_count == 2
    exp = orchestrator._experiments[-1]
    assert exp.strategy == "ablate"
    assert exp.accepted is True
    assert exp.metric_value == 0.0
    assert "ablate-applied" in exp.raw_output
    assert repo.joinpath("target.txt").read_text(encoding="utf-8") == "base\nfeature\nbetter\n"
