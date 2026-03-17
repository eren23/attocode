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


# ── C3: --no-git-safety forwarding in start_command ──────────────────


def test_build_start_cmd_forwards_no_git_safety(tmp_path: Path, monkeypatch) -> None:
    """C3: _build_start_cmd() must include --no-git-safety when flag is set.

    Uses --detach mode so start_command exits immediately after Popen
    (avoids launching the TUI).
    """
    cfg = tmp_path / "swarm.yaml"
    _write_config(cfg)
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/claude")

    captured_cmds: list[list[str]] = []

    class FakePopen:
        pid = 12345
        returncode = 0

        def __init__(self, cmd, **kwargs):
            captured_cmds.append(list(cmd))

        def poll(self):
            return 0

        def wait(self, **kwargs):
            pass

    monkeypatch.setattr("subprocess.Popen", FakePopen)

    # Create the run dir so the log file can be opened
    run_dir = tmp_path / ".agent" / "hybrid-swarm"
    run_dir.mkdir(parents=True, exist_ok=True)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["start", str(cfg), "--no-git-safety", "--detach", "--skip-doctor", "test goal"],
    )
    # --detach uses Popen then exits immediately (no TUI)
    assert len(captured_cmds) >= 1
    cmd = captured_cmds[0]
    assert "--no-git-safety" in cmd


# ── L2: --preview --no-monitor falls back to dry_run ─────────────────


def test_quick_preview_no_monitor_falls_back_to_dry_run(tmp_path: Path, monkeypatch) -> None:
    """L2: quick --preview --no-monitor should fall back to dry_run."""
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/claude")
    monkeypatch.chdir(tmp_path)

    from unittest.mock import MagicMock

    class FakeOrch:
        _subagent_mgr = MagicMock()

        def __init__(self, cfg, goal, **kwargs):
            self.captured_approval = kwargs.get("approval_mode", "auto")
            self._subagent_mgr._spawn_fn = None

        async def run(self):
            return 0

    # quick_command does a local import inside the function body, so we
    # patch the module that it imports from
    monkeypatch.setattr(
        "attoswarm.coordinator.orchestrator.SwarmOrchestrator",
        FakeOrch,
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["quick", "--preview", "--no-monitor", "test goal"],
    )
    # The output should mention the fallback
    assert "dry-run" in result.output.lower() or "dry_run" in result.output.lower()


def test_start_preview_no_monitor_falls_back_to_dry_run(tmp_path: Path, monkeypatch) -> None:
    """L2: start --preview --no-monitor should fall back to dry_run."""
    cfg = tmp_path / "swarm.yaml"
    _write_config(cfg)
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/claude")

    from unittest.mock import MagicMock

    class FakeOrch:
        _subagent_mgr = MagicMock()

        def __init__(self, cfg, goal, **kwargs):
            self.captured_approval = kwargs.get("approval_mode", "auto")
            self._subagent_mgr._spawn_fn = None

        async def run(self):
            return 0

    monkeypatch.setattr(
        "attoswarm.coordinator.orchestrator.SwarmOrchestrator",
        FakeOrch,
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["start", str(cfg), "--preview", "--no-monitor", "--skip-doctor", "test goal"],
    )
    assert "dry-run" in result.output.lower() or "dry_run" in result.output.lower()

