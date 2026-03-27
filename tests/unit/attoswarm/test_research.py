from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from attoswarm.cli import main
from attoswarm.research.config import ResearchConfig
from attoswarm.research.evaluator import CommandEvaluator, EvalResult
from attoswarm.research.experiment import Experiment, FindingRecord, SteeringNote
from attoswarm.research.experiment_db import ExperimentDB
from attoswarm.research.research_orchestrator import ResearchOrchestrator


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


def test_command_evaluator_parses_structured_json() -> None:
    evaluator = CommandEvaluator(
        "python -c \"import json; print(json.dumps({'primary_metric': 1.25, 'secondary_metrics': {'aux': 0.5}, 'constraint_checks': {'artifact_ok': True}, 'artifacts': ['model.bin'], 'seed': 7}))\""
    )
    result = asyncio.run(evaluator.evaluate("."))
    assert result.success is True
    assert result.metric_value == 1.25
    assert result.metrics == {"aux": 0.5}
    assert result.constraint_checks == {"artifact_ok": True}
    assert result.artifacts == ["model.bin"]
    assert result.seed == 7


def test_experiment_db_stores_campaign_records(tmp_path: Path) -> None:
    db = ExperimentDB(tmp_path / "research.db")
    try:
        db.create_run("run-1", "optimize metric", config={"foo": "bar"})
        experiment = Experiment(
            experiment_id="exp-1",
            iteration=1,
            hypothesis="try a change",
            related_experiment_ids=["exp-0"],
            status="accepted",
            strategy="explore",
            metric_value=1.1,
            accepted=True,
            metrics={"primary_metric": 1.1},
            artifacts=["artifact.bin"],
        )
        db.save_experiment("run-1", experiment)
        db.add_finding(
            "run-1",
            FindingRecord(
                finding_id="finding-1",
                experiment_id="exp-1",
                claim="improves metric",
                confidence=0.8,
            ),
        )
        db.add_steering_note(
            SteeringNote(
                note_id="note-1",
                run_id="run-1",
                content="focus on compression wins",
                scope="global",
            ),
        )

        best = db.get_best_experiment("run-1", direction="maximize")
        findings = db.list_findings("run-1")
        notes = db.list_active_steering_notes("run-1")
    finally:
        db.close()

    assert best is not None
    assert best.experiment_id == "exp-1"
    assert best.related_experiment_ids == ["exp-0"]
    assert findings[0].claim == "improves metric"
    assert notes[0].content == "focus on compression wins"


def test_research_orchestrator_runs_in_isolated_worktrees(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "target.txt"
    target.write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "target.txt"], cwd=repo, check=True, capture_output=True, text=True)
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

    class FileEvaluator:
        async def evaluate(self, working_dir: str) -> EvalResult:
            text = Path(working_dir, "target.txt").read_text(encoding="utf-8")
            return EvalResult(metric_value=float(text.count("better")))

    async def spawn_fn(task: dict) -> SimpleNamespace:
        worktree_target = Path(task["working_dir"]) / "target.txt"
        worktree_target.write_text("base\nbetter\n", encoding="utf-8")
        return SimpleNamespace(result_summary="updated target", tokens_used=12, cost_usd=0.2)

    cfg = ResearchConfig(
        working_dir=str(repo),
        run_dir=str(tmp_path / "runs"),
        eval_command="",
        total_max_experiments=2,
        max_parallel_experiments=2,
        promotion_repeats=1,
        target_files=["target.txt"],
    )
    orchestrator = ResearchOrchestrator(
        cfg,
        "improve target metric",
        evaluator=FileEvaluator(),
        spawn_fn=spawn_fn,
    )

    state = asyncio.run(orchestrator.run())
    scoreboard = orchestrator.get_scoreboard()

    assert state.accepted_count >= 1
    assert target.read_text(encoding="utf-8") == "base\n"
    assert "Best branch:" in scoreboard.render_summary()
    assert any(exp.worktree_path for exp in orchestrator._experiments)


def test_research_cli_leaderboard_and_inject(tmp_path: Path) -> None:
    db_path = tmp_path / "research.db"
    store = ExperimentDB(db_path)
    try:
        store.create_run("run-2", "improve metric")
        store.save_experiment(
            "run-2",
            Experiment(
                experiment_id="exp-2",
                iteration=1,
                hypothesis="test hypothesis",
                status="accepted",
                strategy="explore",
                metric_value=2.0,
                accepted=True,
            ),
        )
    finally:
        store.close()

    runner = CliRunner()
    inject = runner.invoke(main, ["research", "inject", "run-2", "push on quantization", "--db", str(db_path)])
    leaderboard = runner.invoke(main, ["research", "leaderboard", "--run-id", "run-2", "--db", str(db_path)])

    assert inject.exit_code == 0
    assert "Injected steering note" in inject.output
    assert leaderboard.exit_code == 0
    assert "Research Run: run-2" in leaderboard.output
    assert "test hypothesis" in leaderboard.output


def test_research_cli_feed(tmp_path: Path) -> None:
    db_path = tmp_path / "research.db"
    store = ExperimentDB(db_path)
    try:
        store.create_run(
            "run-feed",
            "improve metric",
            config={"metric_name": "val_bpb", "metric_direction": "minimize"},
        )
        store.save_experiment(
            "run-feed",
            Experiment(
                experiment_id="exp-feed",
                iteration=1,
                hypothesis="compose quantization with EMA",
                status="accepted",
                strategy="compose",
                metric_value=1.123,
                accepted=True,
            ),
        )
        store.add_finding(
            "run-feed",
            FindingRecord(
                finding_id="finding-feed",
                experiment_id="exp-feed",
                claim="compose improved val_bpb",
                confidence=0.85,
                status="validated",
            ),
        )
        store.add_steering_note(
            SteeringNote(
                note_id="note-feed",
                run_id="run-feed",
                content="prefer orthogonal export-time improvements",
                scope="strategy",
                target="compose",
            ),
        )
    finally:
        store.close()

    runner = CliRunner()
    result = runner.invoke(main, ["research", "feed", "--run-id", "run-feed", "--db", str(db_path)])

    assert result.exit_code == 0
    assert "Metric: val_bpb (minimize)" in result.output
    assert "Findings:" in result.output
    assert "Steering Notes:" in result.output
    assert "prefer orthogonal export-time improvements" in result.output


def test_research_cli_monitor_hold_and_promote(tmp_path: Path) -> None:
    db_path = tmp_path / "research.db"
    store = ExperimentDB(db_path)
    try:
        store.create_run(
            "run-monitor",
            "improve metric",
            config={"metric_name": "score", "metric_direction": "maximize", "promotion_repeats": 3},
        )
        store.save_experiment(
            "run-monitor",
            Experiment(
                experiment_id="exp-candidate",
                iteration=1,
                hypothesis="candidate branch",
                status="candidate",
                strategy="compose",
                metric_value=2.5,
                branch="research/exp-candidate",
            ),
        )
        store.save_experiment(
            "run-monitor",
            Experiment(
                experiment_id="exp-validate",
                iteration=2,
                hypothesis="validation pass",
                parent_experiment_id="exp-candidate",
                status="validated",
                strategy="reproduce",
                metric_value=2.4,
                branch="research/exp-validate",
            ),
        )
    finally:
        store.close()

    runner = CliRunner()
    monitor = runner.invoke(main, ["research", "monitor", "--run-id", "run-monitor", "--db", str(db_path)])
    hold = runner.invoke(main, ["research", "hold", "run-monitor", "exp-validate", "--reason", "needs review", "--db", str(db_path)])
    promote = runner.invoke(main, ["research", "promote", "run-monitor", "exp-candidate", "--db", str(db_path)])

    assert monitor.exit_code == 0
    assert "Candidates:" in monitor.output
    assert "progress=2/3" in monitor.output
    assert hold.exit_code == 0
    assert "Held experiment exp-candidate" in hold.output
    assert promote.exit_code == 0
    assert "Promoted experiment exp-candidate to accepted" in promote.output

    store = ExperimentDB(db_path)
    try:
        experiments = store.get_experiments("run-monitor")
        state = store.load_checkpoint("run-monitor")
    finally:
        store.close()

    root = next(exp for exp in experiments if exp.experiment_id == "exp-candidate")
    child = next(exp for exp in experiments if exp.experiment_id == "exp-validate")
    assert root.status == "accepted"
    assert root.accepted is True
    assert child.status == "validated"
    assert state is not None
    assert state.accepted_count == 1
    assert state.candidate_count == 1


def test_research_cli_kill_and_resume(tmp_path: Path) -> None:
    db_path = tmp_path / "research.db"
    store = ExperimentDB(db_path)
    try:
        store.create_run(
            "run-kill",
            "improve metric",
            config={"metric_name": "score", "metric_direction": "maximize", "promotion_repeats": 2},
        )
        store.save_experiment(
            "run-kill",
            Experiment(
                experiment_id="exp-candidate",
                iteration=1,
                hypothesis="candidate branch",
                status="candidate",
                strategy="explore",
                metric_value=2.0,
            ),
        )
    finally:
        store.close()

    runner = CliRunner()
    kill = runner.invoke(main, ["research", "kill", "run-kill", "exp-candidate", "--reason", "dead end", "--db", str(db_path)])
    resume = runner.invoke(main, ["research", "resume", "run-kill", "exp-candidate", "--db", str(db_path)])

    assert kill.exit_code == 0
    assert "Killed experiment exp-candidate" in kill.output
    assert resume.exit_code == 0
    assert "Resumed experiment exp-candidate" in resume.output

    store = ExperimentDB(db_path)
    try:
        exp = store.get_experiment("run-kill", "exp-candidate")
        state = store.load_checkpoint("run-kill")
    finally:
        store.close()

    assert exp is not None
    assert exp.status == "candidate"
    assert exp.reject_reason == ""
    assert state is not None
    assert state.killed_count == 0
    assert state.candidate_count == 1


def test_research_cli_compare(tmp_path: Path) -> None:
    db_path = tmp_path / "research.db"
    store = ExperimentDB(db_path)
    try:
        store.create_run(
            "run-compare",
            "improve metric",
            config={"metric_name": "val_bpb", "metric_direction": "minimize"},
        )
        store.save_experiment(
            "run-compare",
            Experiment(
                experiment_id="exp-a",
                iteration=1,
                hypothesis="baseline tweak",
                status="accepted",
                strategy="explore",
                metric_value=1.20,
                accepted=True,
            ),
        )
        store.save_experiment(
            "run-compare",
            Experiment(
                experiment_id="exp-b",
                iteration=2,
                hypothesis="better tweak",
                status="accepted",
                strategy="exploit",
                metric_value=1.10,
                accepted=True,
            ),
        )
    finally:
        store.close()

    runner = CliRunner()
    result = runner.invoke(main, ["research", "compare", "run-compare", "exp-a", "exp-b", "--db", str(db_path)])

    assert result.exit_code == 0
    assert "Metric: val_bpb (minimize)" in result.output
    assert "Delta (B - A): raw=-0.1000, quality=+0.1000" in result.output


def test_research_cli_reproduce_from_ref(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "target.txt"
    target.write_text("base\nbetter\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "target.txt"], cwd=repo, check=True, capture_output=True, text=True)
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
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    db_path = tmp_path / "research.db"
    store = ExperimentDB(db_path)
    try:
        store.create_run(
            "run-repro",
            "improve metric",
            config={
                "metric_name": "score",
                "metric_direction": "maximize",
                "working_dir": str(repo),
                "eval_command": "python -c \"from pathlib import Path; print(Path('target.txt').read_text().count('better'))\"",
            },
        )
    finally:
        store.close()

    runner = CliRunner()
    result = runner.invoke(main, ["research", "reproduce", "run-repro", "--ref", head, "--db", str(db_path)])

    assert result.exit_code == 0
    assert "Stored experiment:" in result.output
    assert "Status: accepted" in result.output

    store = ExperimentDB(db_path)
    try:
        experiments = store.get_experiments("run-repro")
    finally:
        store.close()

    assert len(experiments) == 1
    assert experiments[0].strategy == "import"
    assert experiments[0].accepted is True


def test_research_cli_import_patch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "target.txt"
    target.write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "target.txt"], cwd=repo, check=True, capture_output=True, text=True)
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

    patch_repo = tmp_path / "patch_repo"
    subprocess.run(["git", "clone", str(repo), str(patch_repo)], check=True, capture_output=True, text=True)
    (patch_repo / "target.txt").write_text("base\npatched\n", encoding="utf-8")
    patch_text = subprocess.run(
        ["git", "diff", "--stat", "--patch"],
        cwd=patch_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    patch_path = tmp_path / "change.patch"
    patch_path.write_text(patch_text, encoding="utf-8")

    db_path = tmp_path / "research.db"
    store = ExperimentDB(db_path)
    try:
        store.create_run(
            "run-patch",
            "improve metric",
            config={
                "metric_name": "score",
                "metric_direction": "maximize",
                "working_dir": str(repo),
                "eval_command": "python -c \"from pathlib import Path; print(Path('target.txt').read_text().count('patched'))\"",
            },
        )
    finally:
        store.close()

    runner = CliRunner()
    result = runner.invoke(main, ["research", "import-patch", "run-patch", str(patch_path), "--db", str(db_path)])

    assert result.exit_code == 0
    assert "Stored experiment:" in result.output
    assert "Status: accepted" in result.output

    store = ExperimentDB(db_path)
    try:
        experiments = store.get_experiments("run-patch")
    finally:
        store.close()

    assert len(experiments) == 1
    assert experiments[0].strategy == "import_patch"
    assert experiments[0].accepted is True
    assert "target.txt" in experiments[0].files_modified


def test_research_orchestrator_plans_ablate_and_compose() -> None:
    cfg = ResearchConfig(
        eval_command="",
        total_max_experiments=10,
        max_parallel_experiments=4,
        strategy_mix={"ablate": 1, "compose": 1, "exploit": 1, "explore": 0, "reproduce": 0},
        steering_enabled=False,
    )
    orchestrator = ResearchOrchestrator(cfg, "improve metric")
    orchestrator._state.baseline_value = 1.2
    orchestrator._state.best_value = 1.1
    orchestrator._state.best_experiment_id = "exp-best"
    orchestrator._experiments = [
        Experiment(
            experiment_id="exp-best",
            iteration=1,
            hypothesis="best branch",
            status="accepted",
            strategy="exploit",
            metric_value=1.1,
            accepted=True,
            files_modified=["train_gpt.py"],
            diff="+ enable ema\n- old warmdown\n",
        ),
        Experiment(
            experiment_id="exp-alt",
            iteration=2,
            hypothesis="orthogonal quantization win",
            status="accepted",
            strategy="compose",
            metric_value=1.09,
            accepted=True,
            files_modified=["export.py"],
            diff="+ better clipping\n",
        ),
    ]

    batch = orchestrator._plan_batch()
    strategies = [spec.strategy for spec in batch]

    assert "ablate" in strategies
    assert "compose" in strategies
    compose_spec = next(spec for spec in batch if spec.strategy == "compose")
    assert compose_spec.parent_experiment_id == "exp-best"
    assert compose_spec.related_experiment_ids == ["exp-alt"]
    assert "Reference Experiments" in compose_spec.support_context


def test_research_orchestrator_compose_preapplies_related_patch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "best.txt").write_text("base\n", encoding="utf-8")
    (repo / "compose.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "best.txt", "compose.txt"], cwd=repo, check=True, capture_output=True, text=True)
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
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    (repo / "best.txt").write_text("base\nbest\n", encoding="utf-8")
    subprocess.run(["git", "add", "best.txt"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "best",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    best_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    subprocess.run(["git", "checkout", base], cwd=repo, check=True, capture_output=True, text=True)
    (repo / "compose.txt").write_text("base\nimported\n", encoding="utf-8")
    subprocess.run(["git", "add", "compose.txt"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "compose",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    compose_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    compose_diff = subprocess.run(
        ["git", "show", "--stat", "--patch", "--format=", compose_commit],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    subprocess.run(["git", "checkout", best_commit], cwd=repo, check=True, capture_output=True, text=True)

    class FileEvaluator:
        async def evaluate(self, working_dir: str) -> EvalResult:
            text = Path(working_dir, "compose.txt").read_text(encoding="utf-8")
            return EvalResult(metric_value=float("imported" in text))

    async def spawn_fn(task: dict) -> SimpleNamespace:
        assert "Workspace Preparation" in task["description"]
        text = Path(task["working_dir"], "compose.txt").read_text(encoding="utf-8")
        assert "imported" in text
        return SimpleNamespace(result_summary="compose verified", tokens_used=3, cost_usd=0.01)

    cfg = ResearchConfig(
        working_dir=str(repo),
        run_dir=str(tmp_path / "runs"),
        eval_command="",
        total_max_experiments=1,
        max_parallel_experiments=1,
        baseline_repeats=1,
        promotion_repeats=1,
        strategy_mix={"compose": 1, "explore": 0, "exploit": 0, "ablate": 0, "reproduce": 0},
        target_files=["best.txt", "compose.txt"],
        steering_enabled=False,
    )
    orchestrator = ResearchOrchestrator(
        cfg,
        "compose accepted techniques",
        evaluator=FileEvaluator(),
        spawn_fn=spawn_fn,
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
            files_modified=["best.txt"],
            diff="+best\n",
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
    assert "compose.txt" in exp.files_modified


def test_research_orchestrator_requires_validation_before_promotion(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "target.txt"
    target.write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "target.txt"], cwd=repo, check=True, capture_output=True, text=True)
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

    spawn_calls = {"count": 0}

    class FileEvaluator:
        async def evaluate(self, working_dir: str) -> EvalResult:
            text = Path(working_dir, "target.txt").read_text(encoding="utf-8")
            return EvalResult(metric_value=float(text.count("better")))

    async def spawn_fn(task: dict) -> SimpleNamespace:
        spawn_calls["count"] += 1
        Path(task["working_dir"], "target.txt").write_text("base\nbetter\n", encoding="utf-8")
        return SimpleNamespace(result_summary="candidate change", tokens_used=5, cost_usd=0.05)

    cfg = ResearchConfig(
        working_dir=str(repo),
        run_dir=str(tmp_path / "runs"),
        eval_command="",
        total_max_experiments=2,
        max_parallel_experiments=1,
        promotion_repeats=2,
        target_files=["target.txt"],
    )
    orchestrator = ResearchOrchestrator(
        cfg,
        "improve target metric",
        evaluator=FileEvaluator(),
        spawn_fn=spawn_fn,
    )

    state = asyncio.run(orchestrator.run())

    assert spawn_calls["count"] == 1
    assert state.accepted_count == 1
    assert state.candidate_count == 1
    assert state.best_experiment_id == orchestrator._experiments[0].experiment_id
    assert orchestrator._experiments[0].status == "accepted"
    assert orchestrator._experiments[0].accepted is True
    assert orchestrator._experiments[1].strategy == "reproduce"
    assert orchestrator._experiments[1].status == "validated"
    assert orchestrator._experiments[1].parent_experiment_id == orchestrator._experiments[0].experiment_id


def test_research_cli_legacy_invocation_routes_to_start(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, str] = {}

    def fake_run_research_campaign(**kwargs):
        captured["goal"] = kwargs["goal"]

    monkeypatch.setattr("attoswarm.cli._run_research_campaign", fake_run_research_campaign)
    runner = CliRunner()
    result = runner.invoke(main, ["research", "improve metric", "-e", "echo 1"])

    assert result.exit_code == 0
    assert captured["goal"] == "improve metric"


def test_experiment_db_ensure_column_rejects_bad_table(tmp_path: Path) -> None:
    from attoswarm.research.experiment_db import ExperimentDB
    db = ExperimentDB(tmp_path / "test.db")
    try:
        with pytest.raises(ValueError, match="Unknown table"):
            db._ensure_column("DROP TABLE x; --", "col", "TEXT")
    finally:
        db.close()


def test_experiment_db_ensure_column_rejects_bad_column(tmp_path: Path) -> None:
    from attoswarm.research.experiment_db import ExperimentDB
    db = ExperimentDB(tmp_path / "test.db")
    try:
        with pytest.raises(ValueError, match="Invalid column"):
            db._ensure_column("experiments", "col; DROP", "TEXT")
    finally:
        db.close()


def test_experiment_db_ensure_column_accepts_valid(tmp_path: Path) -> None:
    from attoswarm.research.experiment_db import ExperimentDB
    db = ExperimentDB(tmp_path / "test.db")
    try:
        # Should not raise
        db._ensure_column("experiments", "test_col", "TEXT DEFAULT ''")
    finally:
        db.close()


def test_refresh_state_uses_candidate_branch_not_head(tmp_path: Path) -> None:
    """When no accepted experiments exist, _refresh_state should use candidate's branch/id."""
    from attoswarm.research.config import ResearchConfig
    from attoswarm.research.experiment import Experiment

    repo = tmp_path / "repo"
    _init_repo(repo, {"target.txt": "base\n"})

    class DummyEvaluator:
        async def evaluate(self, working_dir: str) -> EvalResult:
            return EvalResult(metric_value=0.0)

    orchestrator = ResearchOrchestrator(
        ResearchConfig(
            working_dir=str(repo),
            run_dir=str(tmp_path / "runs"),
            eval_command="",
            total_max_experiments=0,
            target_files=["target.txt"],
        ),
        "test goal",
        evaluator=DummyEvaluator(),
    )
    from attoswarm.research.worktree_manager import WorktreeManager
    orchestrator._worktrees = WorktreeManager(repo, tmp_path / "runs")
    orchestrator._state.baseline_value = 0.0
    orchestrator._state.best_value = 0.0

    # Pre-seed a candidate experiment
    candidate = Experiment(
        experiment_id="exp-cand-01",
        iteration=1,
        hypothesis="test",
        strategy="explore",
        status="candidate",
        accepted=True,
        metric_value=5.0,
        branch="research/exp-cand-01",
    )
    orchestrator._experiments = [candidate]

    orchestrator._refresh_state()

    assert orchestrator._state.best_experiment_id == "exp-cand-01"
    assert orchestrator._state.best_branch == "research/exp-cand-01"
    assert orchestrator._state.best_value == 0.0  # stays at baseline


def test_research_orchestrator_cleans_worktree_on_no_spawn_fn_error(tmp_path: Path) -> None:
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
            total_max_experiments=1,
            preserve_worktrees=False,
            target_files=["target.txt"],
        ),
        "test cleanup",
        evaluator=StaticEvaluator(),
        spawn_fn=None,
    )

    state = asyncio.run(orchestrator.run())

    assert state.invalid_count == 1 or any(
        exp.status == "error" for exp in orchestrator._experiments
    )
    # Worktree should be cleaned up since preserve_worktrees=False
    for exp in orchestrator._experiments:
        if exp.status == "error":
            assert exp.worktree_path == "", f"Worktree not cleaned up: {exp.worktree_path}"


# ── Mini-swarm experiment mode tests ─────────────────────────────────────


def test_experiment_mode_auto_detects_simple_without_config() -> None:
    """No swarm_config → auto resolves to simple."""
    orch = ResearchOrchestrator(
        ResearchConfig(eval_command="echo 1"),
        "test",
    )
    assert orch._experiment_mode == "simple"


def test_experiment_mode_auto_detects_simple_with_one_role() -> None:
    """swarm_config with 1 role → auto resolves to simple."""
    fake_cfg = SimpleNamespace(roles=[SimpleNamespace(role_id="worker")])
    orch = ResearchOrchestrator(
        ResearchConfig(eval_command="echo 1"),
        "test",
        swarm_config=fake_cfg,
    )
    assert orch._experiment_mode == "simple"


def test_experiment_mode_auto_detects_swarm_with_two_roles() -> None:
    """swarm_config with 2+ roles → auto resolves to swarm."""
    fake_cfg = SimpleNamespace(roles=[
        SimpleNamespace(role_id="worker"),
        SimpleNamespace(role_id="reviewer"),
    ])
    orch = ResearchOrchestrator(
        ResearchConfig(eval_command="echo 1"),
        "test",
        swarm_config=fake_cfg,
    )
    assert orch._experiment_mode == "swarm"


def test_experiment_mode_explicit_override() -> None:
    """Explicit experiment_mode='simple' overrides auto-detection."""
    fake_cfg = SimpleNamespace(roles=[
        SimpleNamespace(role_id="worker"),
        SimpleNamespace(role_id="reviewer"),
    ])
    orch = ResearchOrchestrator(
        ResearchConfig(eval_command="echo 1"),
        "test",
        swarm_config=fake_cfg,
        experiment_mode="simple",
    )
    assert orch._experiment_mode == "simple"


def test_derive_experiment_config_overrides_fields() -> None:
    """_derive_experiment_config scales parent config to per-experiment limits."""
    from attoswarm.config.schema import (
        BudgetConfig,
        MergeConfig,
        OrchestrationConfig,
        RunConfig,
        SwarmYamlConfig,
        WatchdogConfig,
        WorkspaceConfig,
    )

    parent_cfg = SwarmYamlConfig(
        run=RunConfig(working_dir="/original", run_dir="/original/run", max_runtime_seconds=3600),
        roles=[],
        budget=BudgetConfig(max_tokens=5_000_000, max_cost_usd=50.0),
        merge=MergeConfig(),
        watchdog=WatchdogConfig(task_max_duration_seconds=600.0),
        orchestration=OrchestrationConfig(max_tasks=20),
        workspace=WorkspaceConfig(mode="worktree"),
    )
    orch = ResearchOrchestrator(
        ResearchConfig(
            eval_command="echo 1",
            experiment_timeout_seconds=120.0,
            experiment_max_tokens=200_000,
            experiment_max_cost_usd=1.0,
        ),
        "test",
        swarm_config=parent_cfg,
    )

    derived = orch._derive_experiment_config(Path("/tmp/worktree"), "exp-001")

    assert derived.run.working_dir == "/tmp/worktree"
    assert "exp-001/swarm" in derived.run.run_dir
    assert derived.run.max_runtime_seconds == 120
    assert derived.budget.max_tokens == 200_000
    assert derived.budget.max_cost_usd == 1.0
    assert derived.watchdog.task_max_duration_seconds == 96.0  # 120 * 0.8
    assert derived.orchestration.max_tasks == 5
    assert derived.workspace.mode == "shared"
    # Original should be unchanged
    assert parent_cfg.run.working_dir == "/original"
    assert parent_cfg.budget.max_tokens == 5_000_000


def test_run_agent_dispatches_to_simple_mode(tmp_path: Path) -> None:
    """In simple mode, _run_agent calls spawn_fn."""
    repo = tmp_path / "repo"
    _init_repo(repo, {"f.txt": "hello\n"})

    calls: list[dict] = []

    async def fake_spawn(task: dict) -> SimpleNamespace:
        calls.append(task)
        return SimpleNamespace(result_summary="done", tokens_used=10, cost_usd=0.01)

    orch = ResearchOrchestrator(
        ResearchConfig(
            working_dir=str(repo),
            run_dir=str(tmp_path / "runs"),
            eval_command="echo 1",
            target_files=["f.txt"],
        ),
        "test",
        spawn_fn=fake_spawn,
        experiment_mode="simple",
    )
    from attoswarm.research.research_orchestrator import CandidateSpec

    spec = CandidateSpec(
        experiment_id="test-exp",
        iteration=1,
        strategy="explore",
        hypothesis="test hypothesis",
    )
    result = asyncio.run(orch._run_agent(spec, repo))
    assert result is not None
    assert result.result_summary == "done"
    assert len(calls) == 1
    assert calls[0]["task_id"] == "research-test-exp"


def test_run_agent_dispatches_to_swarm_mode_with_mock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """In swarm mode, _run_agent calls _run_mini_swarm instead of spawn_fn."""
    repo = tmp_path / "repo"
    _init_repo(repo, {"f.txt": "hello\n"})

    fake_cfg = SimpleNamespace(roles=[
        SimpleNamespace(role_id="worker"),
        SimpleNamespace(role_id="reviewer"),
    ])

    mini_swarm_called = {"count": 0}

    async def mock_mini_swarm(spec, worktree_path):
        mini_swarm_called["count"] += 1
        return SimpleNamespace(result_summary="swarm done", tokens_used=100, cost_usd=0.5)

    orch = ResearchOrchestrator(
        ResearchConfig(
            working_dir=str(repo),
            run_dir=str(tmp_path / "runs"),
            eval_command="echo 1",
            target_files=["f.txt"],
        ),
        "test",
        swarm_config=fake_cfg,
        experiment_mode="swarm",
    )
    # Monkeypatch _run_mini_swarm to avoid real coordinator
    monkeypatch.setattr(orch, "_run_mini_swarm", mock_mini_swarm)

    from attoswarm.research.research_orchestrator import CandidateSpec

    spec = CandidateSpec(
        experiment_id="test-swarm",
        iteration=1,
        strategy="explore",
        hypothesis="test swarm hypothesis",
    )
    result = asyncio.run(orch._run_agent(spec, repo))
    assert result is not None
    assert result.result_summary == "swarm done"
    assert mini_swarm_called["count"] == 1


def test_build_learning_summary_includes_accepted_and_rejected() -> None:
    """Learning summary formats accepted and rejected experiments for agent context."""
    orch = ResearchOrchestrator(
        ResearchConfig(eval_command="echo 1"),
        "test",
    )
    orch._state.baseline_value = 10.0

    orch._experiments = [
        Experiment(
            experiment_id="exp-1",
            iteration=1,
            hypothesis="improve caching",
            strategy="explore",
            status="accepted",
            accepted=True,
            metric_value=15.0,
            files_modified=["cache.py"],
        ),
        Experiment(
            experiment_id="exp-2",
            iteration=2,
            hypothesis="rewrite parser",
            strategy="explore",
            status="rejected",
            accepted=False,
            metric_value=5.0,
            reject_reason="metric decreased",
            files_modified=["parser.py"],
        ),
        Experiment(
            experiment_id="exp-3",
            iteration=3,
            hypothesis="bad approach",
            strategy="explore",
            status="error",
            error="subprocess timed out",
        ),
    ]

    summary = orch._build_learning_summary()
    assert "What worked" in summary
    assert "improve caching" in summary
    assert "15.0" in summary
    assert "What failed" in summary
    assert "rewrite parser" in summary
    assert "DO NOT repeat" in summary
    assert "Errors to avoid" in summary
    assert "subprocess timed out" in summary
    assert "Baseline metric: 10.0" in summary


def test_build_rich_task_dict_includes_verification_and_symbols(tmp_path: Path) -> None:
    """Rich task dict includes eval command, baseline, symbols, and learning context."""
    repo = tmp_path / "repo"
    _init_repo(repo, {
        "target.py": "class Foo:\n    def bar(self):\n        pass\n",
    })

    orch = ResearchOrchestrator(
        ResearchConfig(
            working_dir=str(repo),
            run_dir=str(tmp_path / "runs"),
            eval_command="pytest -q",
            target_files=["target.py"],
        ),
        "test",
    )
    orch._state.baseline_value = 42.0

    from attoswarm.research.research_orchestrator import CandidateSpec

    spec = CandidateSpec(
        experiment_id="test-rich",
        iteration=1,
        strategy="explore",
        hypothesis="improve target",
    )
    task = orch._build_rich_task_dict(spec, repo)

    assert task["task_id"] == "research-test-rich"
    assert "pytest -q" in task["description"]
    assert "42.0" in task["description"]
    assert "IMPROVE" in task["description"]
    assert task["test_command"] == "pytest -q"
    assert any("Foo" in s for s in task["symbol_scope"])
    assert any("bar()" in s for s in task["symbol_scope"])


def test_preflight_check_fails_with_bad_eval_command(tmp_path: Path) -> None:
    """Pre-flight catches broken eval commands before baseline."""
    repo = tmp_path / "repo"
    _init_repo(repo, {"f.txt": "hello\n"})

    orch = ResearchOrchestrator(
        ResearchConfig(
            working_dir=str(repo),
            run_dir=str(tmp_path / "runs"),
            eval_command="false",  # always exits 1
            total_max_experiments=1,
            target_files=["f.txt"],
        ),
        "test preflight",
    )

    state = asyncio.run(orch.run())
    assert state.status == "error"
    assert state.error  # should have error message, not empty
    assert state.baseline_value is None
    assert state.total_experiments == 0


def test_catastrophic_regression_guard(tmp_path: Path) -> None:
    """Experiments with >50% metric drop are flagged as invalid."""
    repo = tmp_path / "repo"
    _init_repo(repo, {"target.txt": "base\n"})

    call_count = {"n": 0}

    class DroppingEvaluator:
        async def evaluate(self, working_dir: str) -> EvalResult:
            call_count["n"] += 1
            if call_count["n"] <= 2:
                # Pre-flight + baseline
                return EvalResult(metric_value=100.0)
            # Experiment eval — catastrophic drop
            return EvalResult(metric_value=10.0)

    async def noop_spawn(task: dict) -> SimpleNamespace:
        return SimpleNamespace(result_summary="done", tokens_used=1, cost_usd=0.0)

    orch = ResearchOrchestrator(
        ResearchConfig(
            working_dir=str(repo),
            run_dir=str(tmp_path / "runs"),
            eval_command="",
            total_max_experiments=1,
            target_files=["target.txt"],
        ),
        "test guard",
        evaluator=DroppingEvaluator(),
        spawn_fn=noop_spawn,
    )

    state = asyncio.run(orch.run())
    assert state.invalid_count >= 1
    exp = orch._experiments[0]
    assert exp.status == "invalid"
    assert "catastrophic regression" in exp.reject_reason


def test_event_log_written_during_campaign(tmp_path: Path) -> None:
    """Events JSONL file is written during campaign execution."""
    import json as _json

    repo = tmp_path / "repo"
    _init_repo(repo, {"f.txt": "hello\n"})

    class StaticEval:
        async def evaluate(self, working_dir: str) -> EvalResult:
            return EvalResult(metric_value=42.0)

    orch = ResearchOrchestrator(
        ResearchConfig(
            working_dir=str(repo),
            run_dir=str(tmp_path / "runs"),
            eval_command="",
            total_max_experiments=1,
            target_files=["f.txt"],
        ),
        "test events",
        evaluator=StaticEval(),
    )

    asyncio.run(orch.run())

    events_path = tmp_path / "runs" / "research.events.jsonl"
    assert events_path.exists()
    events = [_json.loads(line) for line in events_path.read_text().strip().splitlines()]
    event_types = [e["type"] for e in events]
    assert "baseline_complete" in event_types
    assert "campaign_complete" in event_types
