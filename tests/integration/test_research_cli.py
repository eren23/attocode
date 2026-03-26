from __future__ import annotations

from pathlib import Path

import pytest

from attoswarm.research.experiment import Experiment, FindingRecord, ResearchState, SteeringNote

from .research_helpers import (
    build_eval_command,
    init_repo,
    make_patch,
    open_store,
    parse_run_id,
    run_attoswarm,
    write_fake_worker,
    write_metric_evaluator,
    write_swarm_config,
)

pytestmark = pytest.mark.integration


def _assert_ok(result) -> None:
    assert result.returncode == 0, f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"


def test_research_start_real_cli_validates_candidate_before_promotion(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo, {"target.txt": "base\n"})

    worker_script = tmp_path / "fake_worker.py"
    eval_script = tmp_path / "eval_metric.py"
    swarm_config = tmp_path / "swarm.yaml"
    write_fake_worker(worker_script)
    write_metric_evaluator(eval_script)
    write_swarm_config(swarm_config, working_dir=repo, run_dir=repo / ".agent" / "research", worker_script=worker_script)

    result = run_attoswarm(
        [
            "research",
            "start",
            "improve target metric",
            "-e",
            build_eval_command(eval_script),
            "--config",
            str(swarm_config),
            "--working-dir",
            str(repo),
            "--max-experiments",
            "2",
            "--max-parallel",
            "1",
            "--promotion-repeats",
            "2",
        ],
        cwd=repo,
    )
    _assert_ok(result)

    run_id = parse_run_id(result.stdout)
    store = open_store(repo / ".agent" / "research" / "research.db")
    try:
        experiments = store.get_experiments(run_id)
        state = store.load_checkpoint(run_id)
    finally:
        store.close()

    assert len(experiments) == 2
    root = experiments[0]
    child = experiments[1]
    assert root.status == "accepted"
    assert root.accepted is True
    assert root.strategy in {"explore", "exploit", "compose", "ablate"}
    assert "improvement-applied" in root.raw_output
    assert root.metrics["secondary_metrics"] == {"length": 2}
    assert root.metrics["constraint_checks"]["artifact_ok"]["passed"] is True
    assert root.artifacts == ["artifact.txt"]
    assert child.strategy == "reproduce"
    assert child.status == "validated"
    assert child.parent_experiment_id == root.experiment_id
    assert repo.joinpath("target.txt").read_text(encoding="utf-8") == "base\n"
    assert Path(root.worktree_path).exists()
    assert Path(child.worktree_path).exists()
    assert state is not None
    assert state.best_experiment_id == root.experiment_id
    assert "Research Run:" in result.stdout


def test_research_start_real_cli_parallel_batches_use_isolated_worktrees(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo, {"target.txt": "base\n"})

    worker_script = tmp_path / "fake_worker.py"
    eval_script = tmp_path / "eval_metric.py"
    swarm_config = tmp_path / "swarm.yaml"
    write_fake_worker(worker_script)
    write_metric_evaluator(eval_script)
    write_swarm_config(swarm_config, working_dir=repo, run_dir=repo / ".agent" / "research", worker_script=worker_script)

    result = run_attoswarm(
        [
            "research",
            "start",
            "parallel metric search",
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

    assert len(experiments) == 2
    assert len({exp.worktree_path for exp in experiments}) == 2
    assert any(exp.status == "accepted" for exp in experiments)
    assert repo.joinpath("target.txt").read_text(encoding="utf-8") == "base\n"


def test_research_cli_monitor_feed_control_and_compare_via_subprocess(tmp_path: Path) -> None:
    db_path = tmp_path / "research.db"
    store = open_store(db_path)
    try:
        store.create_run(
            "run-ops",
            "improve metric",
            config={"metric_name": "score", "metric_direction": "maximize", "promotion_repeats": 3},
        )
        store.save_experiment(
            "run-ops",
            Experiment(
                experiment_id="exp-base",
                iteration=1,
                hypothesis="baseline win",
                status="accepted",
                strategy="explore",
                metric_value=1.0,
                accepted=True,
                branch="research/exp-base",
            ),
        )
        store.save_experiment(
            "run-ops",
            Experiment(
                experiment_id="exp-candidate",
                iteration=2,
                hypothesis="candidate branch",
                status="candidate",
                strategy="compose",
                metric_value=2.0,
                branch="research/exp-candidate",
            ),
        )
        store.save_experiment(
            "run-ops",
            Experiment(
                experiment_id="exp-validate",
                iteration=3,
                hypothesis="validation pass",
                parent_experiment_id="exp-candidate",
                status="validated",
                strategy="reproduce",
                metric_value=2.0,
                branch="research/exp-validate",
            ),
        )
        store.add_finding(
            "run-ops",
            FindingRecord(
                finding_id="finding-base",
                experiment_id="exp-base",
                claim="baseline improved score",
                confidence=0.8,
                status="validated",
            ),
        )
        store.add_steering_note(
            SteeringNote(
                note_id="note-1",
                run_id="run-ops",
                content="favor orthogonal wins",
                scope="global",
            ),
        )
    finally:
        store.close()

    inject = run_attoswarm(["research", "inject", "run-ops", "push quantization", "--db", str(db_path)], cwd=tmp_path)
    monitor = run_attoswarm(["research", "monitor", "--run-id", "run-ops", "--db", str(db_path)], cwd=tmp_path)
    feed = run_attoswarm(["research", "feed", "--run-id", "run-ops", "--db", str(db_path)], cwd=tmp_path)
    hold = run_attoswarm(["research", "hold", "run-ops", "exp-validate", "--reason", "needs review", "--db", str(db_path)], cwd=tmp_path)
    resume = run_attoswarm(["research", "resume", "run-ops", "exp-candidate", "--db", str(db_path)], cwd=tmp_path)
    kill = run_attoswarm(["research", "kill", "run-ops", "exp-validate", "--reason", "dead end", "--db", str(db_path)], cwd=tmp_path)
    resume_after_kill = run_attoswarm(["research", "resume", "run-ops", "exp-candidate", "--db", str(db_path)], cwd=tmp_path)
    promote = run_attoswarm(["research", "promote", "run-ops", "exp-candidate", "--db", str(db_path)], cwd=tmp_path)
    compare = run_attoswarm(["research", "compare", "run-ops", "exp-base", "exp-candidate", "--db", str(db_path)], cwd=tmp_path)

    for result in [inject, monitor, feed, hold, resume, kill, resume_after_kill, promote, compare]:
        _assert_ok(result)

    assert "Injected steering note" in inject.stdout
    assert "Candidates:" in monitor.stdout
    assert "progress=2/3" in monitor.stdout
    assert "Steering Notes:" in feed.stdout
    assert "push quantization" in feed.stdout
    assert "Held experiment exp-candidate" in hold.stdout
    assert "Resumed experiment exp-candidate" in resume.stdout
    assert "Killed experiment exp-candidate" in kill.stdout
    assert "Promoted experiment exp-candidate to accepted" in promote.stdout
    assert "Delta (B - A): raw=+1.0000, quality=+1.0000" in compare.stdout

    store = open_store(db_path)
    try:
        candidate = store.get_experiment("run-ops", "exp-candidate")
        checkpoint = store.load_checkpoint("run-ops")
    finally:
        store.close()

    assert candidate is not None
    assert candidate.status == "accepted"
    assert candidate.accepted is True
    assert checkpoint is not None
    assert checkpoint.accepted_count == 2


def test_research_cli_resume_reuses_existing_run(tmp_path: Path) -> None:
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
            "resume me",
            "-e",
            build_eval_command(eval_script),
            "--config",
            str(swarm_config),
            "--working-dir",
            str(repo),
            "--max-experiments",
            "1",
        ],
        cwd=repo,
    )
    _assert_ok(first)
    run_id = parse_run_id(first.stdout)

    second = run_attoswarm(
        [
            "research",
            "start",
            "resume me",
            "-e",
            build_eval_command(eval_script),
            "--config",
            str(swarm_config),
            "--working-dir",
            str(repo),
            "--max-experiments",
            "2",
            "--resume",
            run_id,
        ],
        cwd=repo,
    )
    _assert_ok(second)
    assert parse_run_id(second.stdout) == run_id

    store = open_store(repo / ".agent" / "research" / "research.db")
    try:
        experiments = store.get_experiments(run_id)
    finally:
        store.close()

    assert len(experiments) == 2


def test_research_cli_reproduce_from_experiment_real_cli(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    head = init_repo(repo, {"target.txt": "base\nbetter\n"})

    db_path = tmp_path / "research.db"
    store = open_store(db_path)
    try:
        store.create_run(
            "run-repro",
            "improve metric",
            config={
                "metric_name": "score",
                "metric_direction": "maximize",
                "working_dir": str(repo),
                "eval_command": build_eval_command(tmp_path / "eval_metric.py"),
            },
        )
        store.save_experiment(
            "run-repro",
            Experiment(
                experiment_id="exp-best",
                iteration=1,
                hypothesis="best branch",
                status="accepted",
                strategy="explore",
                metric_value=1.0,
                accepted=True,
                commit_hash=head,
                branch="research/exp-best",
            ),
        )
        store.save_checkpoint(
            "run-repro",
            ResearchState(
                run_id="run-repro",
                goal="improve metric",
                metric_name="score",
                metric_direction="maximize",
                baseline_value=1.0,
                best_value=1.0,
                best_experiment_id="exp-best",
                best_branch="research/exp-best",
                total_experiments=1,
                accepted_count=1,
            ),
        )
    finally:
        store.close()

    write_metric_evaluator(tmp_path / "eval_metric.py")
    result = run_attoswarm(
        ["research", "reproduce", "run-repro", "--experiment-id", "exp-best", "--db", str(db_path)],
        cwd=tmp_path,
    )
    _assert_ok(result)
    assert "Status: reproduced" in result.stdout

    store = open_store(db_path)
    try:
        experiments = store.get_experiments("run-repro")
    finally:
        store.close()

    assert len(experiments) == 2
    assert experiments[-1].strategy == "reproduce"
    assert experiments[-1].status == "reproduced"


def test_research_cli_reproduce_from_ref_and_import_patch_real_cli(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    head = init_repo(repo, {"target.txt": "base\n"})
    eval_script = tmp_path / "eval_metric.py"
    write_metric_evaluator(eval_script, token="patched")

    db_path = tmp_path / "research.db"
    store = open_store(db_path)
    try:
        store.create_run(
            "run-import",
            "import metric",
            config={
                "metric_name": "score",
                "metric_direction": "maximize",
                "working_dir": str(repo),
                "eval_command": build_eval_command(eval_script),
            },
        )
    finally:
        store.close()

    imported = run_attoswarm(
        ["research", "reproduce", "run-import", "--ref", head, "--db", str(db_path)],
        cwd=tmp_path,
    )
    _assert_ok(imported)
    assert "Status: accepted" in imported.stdout

    patch_path = tmp_path / "good.patch"
    make_patch(repo, relative_path="target.txt", new_content="base\npatched\n", patch_path=patch_path)
    imported_patch = run_attoswarm(
        ["research", "import-patch", "run-import", str(patch_path), "--db", str(db_path)],
        cwd=tmp_path,
    )
    _assert_ok(imported_patch)
    assert "Status: accepted" in imported_patch.stdout

    bad_patch = tmp_path / "bad.patch"
    bad_patch.write_text("diff --git a/nope.txt b/nope.txt\n@@\n-nope\n+still nope\n", encoding="utf-8")
    bad = run_attoswarm(
        ["research", "import-patch", "run-import", str(bad_patch), "--db", str(db_path)],
        cwd=tmp_path,
    )
    _assert_ok(bad)
    assert "Status: invalid" in bad.stdout

    store = open_store(db_path)
    try:
        experiments = store.get_experiments("run-import")
    finally:
        store.close()

    assert [exp.strategy for exp in experiments] == ["import", "import_patch", "import_patch"]
    assert experiments[0].accepted is True
    assert experiments[1].status == "accepted"
    assert experiments[2].status == "invalid"


def test_research_start_real_cli_records_constraint_failures(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo, {"target.txt": "base\n"})

    worker_script = tmp_path / "fake_worker.py"
    eval_script = tmp_path / "eval_metric.py"
    swarm_config = tmp_path / "swarm.yaml"
    write_fake_worker(worker_script)
    write_metric_evaluator(eval_script, fail_on_token="better")
    write_swarm_config(swarm_config, working_dir=repo, run_dir=repo / ".agent" / "research", worker_script=worker_script)

    result = run_attoswarm(
        [
            "research",
            "start",
            "improve target metric",
            "-e",
            build_eval_command(eval_script),
            "--config",
            str(swarm_config),
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
    assert experiments[0].status == "invalid"
    assert experiments[0].reject_reason == "constraint checks failed"
