from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from attoswarm.cli import main


def _write_config(path: Path) -> None:
    path.write_text(
        """version: 1
run:
  working_dir: .
  run_dir: .agent/hybrid-swarm
roles:
  - role_id: impl
    role_type: worker
    backend: claude
    model: claude-sonnet-4-20250514
""",
        encoding="utf-8",
    )


def test_init_interactive_minimal_existing_repo(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    runner = CliRunner()
    # Input order: setup_target, profile, workers, budget, runtime,
    #              workspace, quality, advanced?, output_mode, task_decomposition?
    result = runner.invoke(
        main,
        ["init", str(tmp_path)],
        input="existing-repo\n2cc\n2\n2\n2\nshared\nstandard\nn\nminimal\nn\n",
    )
    assert result.exit_code == 0
    assert (tmp_path / ".attocode" / "swarm.hybrid.yaml").exists()
    assert not (tmp_path / "tasks").exists()


def test_init_interactive_demo_scaffold(tmp_path: Path) -> None:
    runner = CliRunner()
    # --mode and --profile are passed as flags; remaining interactive prompts:
    # setup_target, workers, budget, runtime, workspace, quality, advanced?, task_decomposition?
    result = runner.invoke(
        main,
        ["init", str(tmp_path), "--mode", "demo", "--profile", "cc-codex"],
        input="demo-project\n2\n2\n2\nshared\nstandard\nn\nn\n",
    )
    # Note: --mode skips the output_mode prompt, so task_decomposition? is the last prompt
    assert result.exit_code == 0
    assert (tmp_path / ".attocode" / "swarm.hybrid.yaml").exists()
    assert (tmp_path / "tasks" / "goal.md").exists()
    assert (tmp_path / "scripts" / "run-swarm.sh").exists()
    assert (tmp_path / "README.swarm.md").exists()


def test_doctor_fails_when_binary_missing(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    cfg = tmp_path / "swarm.yaml"
    _write_config(cfg)
    monkeypatch.setattr("shutil.which", lambda _: None)
    runner = CliRunner()
    result = runner.invoke(main, ["doctor", str(cfg)])
    assert result.exit_code == 1
    assert "[FAIL]" in result.output

