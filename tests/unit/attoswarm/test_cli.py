from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

import attoswarm.cli as cli_mod
from attoswarm.cli import (
    _detect_modified_files,
    _print_run_summary,
    _snapshot_file_state,
    _tui_refresh_interval_s,
    main,
)
from attoswarm.config.schema import SwarmYamlConfig


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


def _write_parent_run(path: Path, run_id: str = "parent-123") -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "swarm.manifest.json").write_text(
        json.dumps({
            "run_id": run_id,
            "goal": "parent goal",
            "lineage": {"run_id": run_id, "root_run_id": run_id, "continuation_mode": "fresh"},
            "tasks": [{"task_id": "t1"}],
        }),
        encoding="utf-8",
    )
    (path / "swarm.state.json").write_text(
        json.dumps({
            "run_id": run_id,
            "goal": "parent goal",
            "phase": "completed",
            "dag_summary": {"done": 1, "failed": 0},
            "dag": {"nodes": [{"task_id": "t1", "status": "done"}]},
        }),
        encoding="utf-8",
    )
    (path / "git_safety.json").write_text(
        json.dumps({
            "swarm_branch": f"attoswarm/{run_id}",
            "result_ref": f"attoswarm/{run_id}",
            "result_commit": "abc123",
            "finalization_mode": "keep",
        }),
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


def test_tui_refresh_interval_uses_fastest_poll_setting() -> None:
    cfg = SwarmYamlConfig()
    cfg.run.poll_interval_ms = 250
    cfg.ui.poll_ms = 500
    assert _tui_refresh_interval_s(cfg) == 0.25


def test_research_monitor_uses_configured_refresh_interval(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    cfg_path = tmp_path / "swarm.yaml"
    _write_config(cfg_path)

    captured: dict[str, object] = {}

    class FakePopen:
        pid = 9999

        def __init__(self, cmd, **kwargs):
            self.returncode = 0

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            self.returncode = 0

        def kill(self):
            self.returncode = 1

    class FakeApp:
        def __init__(self, run_dir, coordinator_pid=None, research_mode=False, refresh_interval_s=0.0):
            captured["run_dir"] = run_dir
            captured["coordinator_pid"] = coordinator_pid
            captured["research_mode"] = research_mode
            captured["refresh_interval_s"] = refresh_interval_s

        def run(self):
            return None

    monkeypatch.setattr("subprocess.Popen", FakePopen)
    monkeypatch.setattr("attoswarm.cli.AttoswarmApp", FakeApp)

    with pytest.raises(SystemExit) as exc:
        cli_mod._run_research_with_monitor(
            goal="test research",
            eval_command="echo ok",
            target_files=(),
            max_experiments=1,
            max_parallel=1,
            experiment_timeout=30.0,
            metric_direction="maximize",
            metric_name="score",
            max_cost=1.0,
            baseline_repeats=1,
            promotion_repeats=1,
            resume="",
            config_path=cfg_path,
            db=None,
            working_dir=tmp_path,
            experiment_mode="auto",
        )

    assert exc.value.code == 0
    assert captured["research_mode"] is True
    assert captured["refresh_interval_s"] == 0.25


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


def test_start_monitor_detach_leaves_coordinator_running(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    cfg = tmp_path / "swarm.yaml"
    _write_config(cfg)
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/claude")

    proc_holder: dict[str, object] = {}

    class FakePopen:
        pid = 4321

        def __init__(self, cmd, **kwargs):
            self.returncode = None
            self.terminate_calls = 0
            self.wait_calls: list[int | None] = []
            proc_holder["proc"] = self

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.wait_calls.append(timeout)
            return 0

        def terminate(self):
            self.terminate_calls += 1
            self.returncode = 0

        def kill(self):
            self.returncode = 1

    class FakeApp:
        def __init__(self, run_dir, coordinator_pid=None):
            self.exit_intent = "detach"

        def run(self):
            return None

    monkeypatch.setattr("subprocess.Popen", FakePopen)
    monkeypatch.setattr("attoswarm.cli.AttoswarmApp", FakeApp)

    run_dir = tmp_path / ".agent" / "hybrid-swarm"
    run_dir.mkdir(parents=True, exist_ok=True)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["start", str(cfg), "--skip-doctor", "test goal"],
    )

    assert result.exit_code == 0
    assert "Dashboard detached; coordinator still running" in result.output
    proc = proc_holder["proc"]
    assert getattr(proc, "terminate_calls") == 0


def test_start_monitor_stop_waits_for_coordinator(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    cfg = tmp_path / "swarm.yaml"
    _write_config(cfg)
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/claude")

    proc_holder: dict[str, object] = {}

    class FakePopen:
        pid = 4321

        def __init__(self, cmd, **kwargs):
            self.returncode = None
            self.terminate_calls = 0
            self.wait_calls: list[int | None] = []
            proc_holder["proc"] = self

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.wait_calls.append(timeout)
            self.returncode = 0
            return 0

        def terminate(self):
            self.terminate_calls += 1
            self.returncode = 0

        def kill(self):
            self.returncode = 1

    class FakeApp:
        def __init__(self, run_dir, coordinator_pid=None):
            self.exit_intent = "stop"

        def run(self):
            return None

    monkeypatch.setattr("subprocess.Popen", FakePopen)
    monkeypatch.setattr("attoswarm.cli.AttoswarmApp", FakeApp)

    run_dir = tmp_path / ".agent" / "hybrid-swarm"
    run_dir.mkdir(parents=True, exist_ok=True)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["start", str(cfg), "--skip-doctor", "test goal"],
    )

    assert result.exit_code == 0
    assert "Waiting for coordinator shutdown..." in result.output
    proc = proc_holder["proc"]
    assert getattr(proc, "wait_calls") == [8]
    assert getattr(proc, "terminate_calls") == 0


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


def test_quick_monitor_detach_leaves_coordinator_running(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/claude")
    monkeypatch.chdir(tmp_path)

    proc_holder: dict[str, object] = {}

    class FakePopen:
        pid = 9876

        def __init__(self, cmd, **kwargs):
            self.returncode = None
            self.terminate_calls = 0
            proc_holder["proc"] = self

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            self.terminate_calls += 1
            self.returncode = 0

        def kill(self):
            self.returncode = 1

    class FakeApp:
        def __init__(self, run_dir, coordinator_pid=None):
            self.exit_intent = "detach"

        def run(self):
            return None

    monkeypatch.setattr("subprocess.Popen", FakePopen)
    monkeypatch.setattr("attoswarm.cli.AttoswarmApp", FakeApp)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["quick", "test goal"],
    )

    assert result.exit_code == 0
    assert "Dashboard detached; coordinator still running" in result.output
    proc = proc_holder["proc"]
    assert getattr(proc, "terminate_calls") == 0


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


def test_start_continue_from_builds_child_lineage(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / "swarm.yaml"
    _write_config(cfg)
    parent_run = tmp_path / ".agent" / "hybrid-swarm" / "parent"
    _write_parent_run(parent_run)
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/claude")

    from unittest.mock import MagicMock

    captured: dict[str, object] = {}

    class FakeOrch:
        _subagent_mgr = MagicMock()

        def __init__(self, cfg, goal, **kwargs):
            captured["run_dir"] = cfg.run.run_dir
            captured["lineage"] = kwargs.get("lineage")
            captured["launcher"] = kwargs.get("launcher")
            self._subagent_mgr._spawn_fn = None
            self.aot_graph = MagicMock(summary=lambda: {"done": 0, "failed": 0, "total": 0})
            self.budget = MagicMock(used_cost_usd=0.0)
            self._change_manifest = None
            self._git_safety = None
            self._on_agent_activity = MagicMock()

        async def run(self):
            return 0

    monkeypatch.setattr("attoswarm.coordinator.orchestrator.SwarmOrchestrator", FakeOrch)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["start", str(cfg), "--continue-from", str(parent_run), "--no-monitor", "--skip-doctor", "child goal"],
    )

    assert result.exit_code == 0
    lineage = captured["lineage"]
    assert getattr(lineage, "parent_run_id") == "parent-123"
    assert getattr(lineage, "continuation_mode") == "child"
    assert getattr(lineage, "base_ref") == "attoswarm/parent-123"
    assert getattr(lineage, "base_commit") == "abc123"
    assert Path(str(captured["run_dir"])) != parent_run


def test_start_continue_from_allows_commit_only_parent(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / "swarm.yaml"
    _write_config(cfg)
    parent_run = tmp_path / ".agent" / "hybrid-swarm" / "parent"
    _write_parent_run(parent_run)
    (parent_run / "git_safety.json").write_text(
        json.dumps(
            {
                "swarm_branch": "",
                "result_ref": "",
                "result_commit": "abc123",
                "finalization_mode": "keep",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/claude")

    from unittest.mock import MagicMock

    captured: dict[str, object] = {}

    class FakeOrch:
        _subagent_mgr = MagicMock()

        def __init__(self, cfg, goal, **kwargs):
            captured["lineage"] = kwargs.get("lineage")
            self._subagent_mgr._spawn_fn = None
            self.aot_graph = MagicMock(summary=lambda: {"done": 0, "failed": 0, "total": 0})
            self.budget = MagicMock(used_cost_usd=0.0)
            self._change_manifest = None
            self._git_safety = None
            self._on_agent_activity = MagicMock()

        async def run(self):
            return 0

    monkeypatch.setattr("attoswarm.coordinator.orchestrator.SwarmOrchestrator", FakeOrch)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["start", str(cfg), "--continue-from", str(parent_run), "--no-monitor", "--skip-doctor", "child goal"],
    )

    assert result.exit_code == 0
    lineage = captured["lineage"]
    assert getattr(lineage, "base_ref") == ""
    assert getattr(lineage, "base_commit") == "abc123"


def test_continue_command_invokes_child_run(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / "swarm.yaml"
    _write_config(cfg)
    parent_run = tmp_path / ".agent" / "hybrid-swarm" / "parent"
    _write_parent_run(parent_run)
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/claude")

    from unittest.mock import MagicMock

    captured: dict[str, object] = {}

    class FakeOrch:
        _subagent_mgr = MagicMock()

        def __init__(self, cfg, goal, **kwargs):
            captured["lineage"] = kwargs.get("lineage")
            self._subagent_mgr._spawn_fn = None
            self.aot_graph = MagicMock(summary=lambda: {"done": 0, "failed": 0, "total": 0})
            self.budget = MagicMock(used_cost_usd=0.0)
            self._change_manifest = None
            self._git_safety = None
            self._on_agent_activity = MagicMock()

        async def run(self):
            return 0

    monkeypatch.setattr("attoswarm.coordinator.orchestrator.SwarmOrchestrator", FakeOrch)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["continue", str(parent_run), "--config", str(cfg), "--no-monitor", "--skip-doctor", "child goal"],
    )

    assert result.exit_code == 0
    assert getattr(captured["lineage"], "parent_run_id") == "parent-123"


def test_continue_monitor_uses_same_child_run_dir_for_subprocess_and_tui(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / "swarm.yaml"
    _write_config(cfg)
    parent_run = tmp_path / ".agent" / "hybrid-swarm" / "parent"
    _write_parent_run(parent_run)
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/claude")

    captured: dict[str, object] = {}

    class FakePopen:
        pid = 2468

        def __init__(self, cmd, **kwargs):
            self.returncode = None
            captured["cmd"] = list(cmd)

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            self.returncode = 0

        def kill(self):
            self.returncode = 1

    class FakeApp:
        def __init__(self, run_dir, coordinator_pid=None):
            captured["monitor_run_dir"] = run_dir
            self.exit_intent = "detach"

        def run(self):
            return None

    monkeypatch.setattr("subprocess.Popen", FakePopen)
    monkeypatch.setattr("attoswarm.cli.AttoswarmApp", FakeApp)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["continue", str(parent_run), "--config", str(cfg), "--skip-doctor", "child goal"],
    )

    assert result.exit_code == 0
    cmd = captured["cmd"]
    assert "--run-dir" in cmd
    run_dir_arg = cmd[cmd.index("--run-dir") + 1]
    assert captured["monitor_run_dir"] == run_dir_arg


def test_print_run_summary_uses_git_fallback_for_modified_files(tmp_path: Path, monkeypatch, capsys) -> None:
    class FakeGraph:
        @staticmethod
        def summary() -> dict[str, int]:
            return {"done": 4, "failed": 0, "pending": 7}

    class FakeBudget:
        used_cost_usd = 0.0

    class FakeOrch:
        aot_graph = FakeGraph()
        budget = FakeBudget()
        _phase = "shutdown"
        _start_time = time.time()
        _change_manifest = None
        _run_dir = tmp_path / ".agent" / "hybrid-swarm"

        @staticmethod
        def get_state() -> dict[str, object]:
            return {"phase": "shutdown"}

    monkeypatch.setattr("attoswarm.cli.collect_modified_files", lambda run_dir, state: ["a.py", "b.py"])

    _print_run_summary(FakeOrch())
    out = capsys.readouterr().out

    assert "Stopped: 4/11 completed" in out
    assert "Files: 2 modified" in out


def test_print_run_summary_labels_planning_failure(tmp_path: Path, capsys) -> None:
    class FakeGraph:
        @staticmethod
        def summary() -> dict[str, int]:
            return {"done": 0, "failed": 0, "pending": 0}

    class FakeBudget:
        used_cost_usd = 0.0

    class FakeOrch:
        aot_graph = FakeGraph()
        budget = FakeBudget()
        _phase = "planning_failed"
        _start_time = time.time()
        _change_manifest = None
        _run_dir = tmp_path / ".agent" / "hybrid-swarm"

    _print_run_summary(FakeOrch())
    out = capsys.readouterr().out

    assert "Planning failed: 0/0 completed" in out


# ── File tracking: _snapshot_file_state / _detect_modified_files ─────


def _init_git_repo(path: Path) -> None:
    """Initialise a minimal git repo with one committed file."""
    subprocess.run(["git", "init"], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=path, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=path, capture_output=True, check=True,
    )
    (path / "initial.txt").write_text("init", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=path, capture_output=True, check=True,
    )


# ── _snapshot_file_state ─────────────────────────────────────────────


def test_snapshot_file_state_returns_modified_and_untracked(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)

    # Create one modified (tracked) file and one untracked file.
    (tmp_path / "initial.txt").write_text("changed", encoding="utf-8")
    (tmp_path / "new_file.py").write_text("x = 1", encoding="utf-8")

    result = _snapshot_file_state(str(tmp_path))

    assert isinstance(result, set)
    assert "initial.txt" in result
    assert "new_file.py" in result


def test_snapshot_file_state_returns_empty_for_non_git_dir(tmp_path: Path) -> None:
    # tmp_path is not a git repo.
    result = _snapshot_file_state(str(tmp_path))
    assert result == set()


def test_snapshot_file_state_returns_empty_on_error(tmp_path: Path, monkeypatch) -> None:
    """If subprocess raises, the function catches the error and returns empty set."""
    import subprocess as _sp

    original_run = _sp.run

    def _boom(*args, **kwargs):
        raise OSError("simulated failure")

    monkeypatch.setattr("subprocess.run", _boom)
    result = _snapshot_file_state(str(tmp_path))
    assert result == set()


# ── _detect_modified_files ───────────────────────────────────────────


def test_detect_modified_files_without_before_returns_all(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "a.py").write_text("a", encoding="utf-8")
    (tmp_path / "b.py").write_text("b", encoding="utf-8")

    result = _detect_modified_files(str(tmp_path))

    assert isinstance(result, list)
    assert "a.py" in result
    assert "b.py" in result


def test_detect_modified_files_with_before_returns_only_new(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)

    # Pre-existing dirty file.
    (tmp_path / "old.py").write_text("old", encoding="utf-8")
    before = _snapshot_file_state(str(tmp_path))
    assert "old.py" in before

    # Add a new file after the snapshot.
    (tmp_path / "new.py").write_text("new", encoding="utf-8")

    result = _detect_modified_files(str(tmp_path), before=before)

    assert "new.py" in result
    assert "old.py" not in result


def test_detect_modified_files_with_before_no_new_files(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)

    (tmp_path / "existing.py").write_text("x", encoding="utf-8")
    before = _snapshot_file_state(str(tmp_path))

    # No new changes after the snapshot.
    result = _detect_modified_files(str(tmp_path), before=before)

    assert result == []


def test_detect_modified_files_returns_sorted_list(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    # Create files in reverse alphabetical order.
    for name in ["z.py", "m.py", "a.py"]:
        (tmp_path / name).write_text(name, encoding="utf-8")

    result = _detect_modified_files(str(tmp_path))

    assert result == sorted(result)
