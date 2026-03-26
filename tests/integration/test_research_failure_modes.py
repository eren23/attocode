from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from attoswarm.research.experiment import Experiment

from .research_helpers import (
    build_eval_command,
    init_repo,
    open_store,
    parse_run_id,
    run_attoswarm,
    write_fake_worker,
    write_metric_evaluator,
    write_swarm_config,
)

if TYPE_CHECKING:
    from pathlib import Path


pytestmark = pytest.mark.integration


def _assert_failure(result) -> None:
    assert result.returncode != 0, f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"


def _assert_ok(result) -> None:
    assert result.returncode == 0, f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"


def test_research_leaderboard_runs_via_real_subprocess(tmp_path: Path) -> None:
    db_path = tmp_path / "research.db"
    store = open_store(db_path)
    try:
        store.create_run(
            "run-board",
            "improve metric",
            config={"metric_name": "val_bpb", "metric_direction": "minimize"},
        )
        store.save_experiment(
            "run-board",
            Experiment(
                experiment_id="exp-board",
                iteration=1,
                hypothesis="board entry",
                status="accepted",
                strategy="explore",
                metric_value=1.1,
                accepted=True,
            ),
        )
    finally:
        store.close()

    result = run_attoswarm(
        ["research", "leaderboard", "--run-id", "run-board", "--db", str(db_path)],
        cwd=tmp_path,
    )

    _assert_ok(result)
    assert "Research Run: run-board" in result.stdout
    assert "Metric: val_bpb (minimize)" in result.stdout


def test_research_start_without_config_records_no_spawn_error(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo, {"target.txt": "base\n"})
    eval_script = tmp_path / "eval_metric.py"
    write_metric_evaluator(eval_script)

    result = run_attoswarm(
        [
            "research",
            "start",
            "fail without worker config",
            "-e",
            build_eval_command(eval_script),
            "--working-dir",
            str(repo),
            "--max-experiments",
            "1",
        ],
        cwd=repo,
    )
    _assert_ok(result)

    run_id = parse_run_id(result.stdout)
    store = open_store(repo / ".agent" / "research" / "research.db")
    try:
        experiments = store.get_experiments(run_id)
    finally:
        store.close()

    assert len(experiments) == 1
    assert experiments[0].status == "error"
    assert experiments[0].error == "No spawn function configured for non-reproduce experiment"


def test_research_reproduce_validates_argument_and_missing_run_errors(tmp_path: Path) -> None:
    db_path = tmp_path / "research.db"
    result = run_attoswarm(
        [
            "research",
            "reproduce",
            "missing-run",
            "--experiment-id",
            "exp-1",
            "--ref",
            "HEAD",
            "--db",
            str(db_path),
        ],
        cwd=tmp_path,
    )
    _assert_failure(result)
    assert "Pass only one of --experiment-id or --ref." in result.stderr

    missing = run_attoswarm(
        ["research", "reproduce", "missing-run", "--ref", "HEAD", "--db", str(db_path)],
        cwd=tmp_path,
    )
    _assert_failure(missing)
    assert "Research run not found: missing-run" in missing.stderr


def test_research_import_patch_validates_argument_and_missing_run_errors(tmp_path: Path) -> None:
    db_path = tmp_path / "research.db"
    patch_path = tmp_path / "patch.diff"
    patch_path.write_text("diff --git a/a.txt b/a.txt\n", encoding="utf-8")

    result = run_attoswarm(
        [
            "research",
            "import-patch",
            "missing-run",
            str(patch_path),
            "--base-experiment-id",
            "exp-1",
            "--base-ref",
            "HEAD",
            "--db",
            str(db_path),
        ],
        cwd=tmp_path,
    )
    _assert_failure(result)
    assert "Pass only one of --base-experiment-id or --base-ref." in result.stderr

    missing = run_attoswarm(
        ["research", "import-patch", "missing-run", str(patch_path), "--db", str(db_path)],
        cwd=tmp_path,
    )
    _assert_failure(missing)
    assert "Research run not found: missing-run" in missing.stderr


@pytest.mark.slow
def test_research_resume_longer_campaign_locally(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo, {"target.txt": "base\n"})

    worker_script = tmp_path / "fake_worker.py"
    eval_script = tmp_path / "eval_metric.py"
    swarm_config = tmp_path / "swarm.yaml"
    write_fake_worker(worker_script)
    write_metric_evaluator(eval_script)
    write_swarm_config(swarm_config, working_dir=repo, run_dir=repo / ".agent" / "research", worker_script=worker_script)

    first = run_attoswarm(
        [
            "research",
            "start",
            "resume a deeper local campaign",
            "-e",
            build_eval_command(eval_script),
            "--config",
            str(swarm_config),
            "--working-dir",
            str(repo),
            "--max-experiments",
            "2",
            "--max-parallel",
            "2",
            "--promotion-repeats",
            "2",
        ],
        cwd=repo,
    )
    _assert_ok(first)
    run_id = parse_run_id(first.stdout)

    second = run_attoswarm(
        [
            "research",
            "start",
            "resume a deeper local campaign",
            "-e",
            build_eval_command(eval_script),
            "--config",
            str(swarm_config),
            "--working-dir",
            str(repo),
            "--max-experiments",
            "4",
            "--max-parallel",
            "2",
            "--promotion-repeats",
            "2",
            "--resume",
            run_id,
        ],
        cwd=repo,
    )
    _assert_ok(second)

    store = open_store(repo / ".agent" / "research" / "research.db")
    try:
        experiments = store.get_experiments(run_id)
        checkpoint = store.load_checkpoint(run_id)
    finally:
        store.close()

    assert len(experiments) == 4
    assert checkpoint is not None
    assert checkpoint.total_experiments == 4
