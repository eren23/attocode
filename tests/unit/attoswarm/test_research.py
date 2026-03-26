from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

from attoswarm.cli import main
from attoswarm.research.config import ResearchConfig
from attoswarm.research.evaluator import CommandEvaluator, EvalResult
from attoswarm.research.experiment import Experiment, FindingRecord, SteeringNote
from attoswarm.research.experiment_db import ExperimentDB
from attoswarm.research.research_orchestrator import ResearchOrchestrator


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
