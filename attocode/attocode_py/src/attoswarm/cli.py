"""CLI entrypoint for attoswarm."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import shutil
from pathlib import Path
from typing import Any

import click

from attoswarm.config.loader import load_swarm_yaml
from attoswarm.config.schema import SwarmYamlConfig
from attoswarm.coordinator.loop import HybridCoordinator
from attoswarm.protocol.io import read_json
from attoswarm.tui.app import AttoswarmApp


@click.group()
def main() -> None:
    """Attoswarm hybrid swarm orchestrator."""


def _doctor_rows(cfg: SwarmYamlConfig) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for role in cfg.roles:
        binary = role.command[0] if role.command else role.backend
        found = shutil.which(binary) is not None
        details = "ok" if found else f"missing binary `{binary}`"
        if role.backend == "codex" and found:
            try:
                probe = subprocess.run(
                    [binary, "--help"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if probe.returncode != 0:
                    details = f"{binary} --help exited {probe.returncode}"
            except Exception as exc:  # pragma: no cover - defensive
                details = f"probe failed: {exc}"
                found = False
        rows.append(
            {
                "role": role.role_id,
                "backend": role.backend,
                "binary": binary,
                "ok": found,
                "details": details,
            }
        )
    return rows


def _print_doctor(rows: list[dict[str, Any]]) -> bool:
    click.echo("Backend preflight:")
    all_ok = True
    for row in rows:
        icon = "OK" if row["ok"] else "FAIL"
        click.echo(
            f"  [{icon}] role={row['role']} backend={row['backend']} binary={row['binary']} - {row['details']}"
        )
        all_ok = all_ok and bool(row["ok"])
    return all_ok


@main.command("run")
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("goal", nargs=-1)
@click.option("--run-dir", default=None, help="Override run directory from config")
@click.option("--resume", "resume_flag", is_flag=True, help="Resume existing run directory state")
@click.option("--observe", is_flag=True, help="Open TUI after run exits")
@click.option("--debug", "debug_flag", is_flag=True, help="Enable debug markers in shell wrapper and coordinator events")
def run_command(
    config_path: Path,
    goal: tuple[str, ...],
    run_dir: str | None,
    resume_flag: bool,
    observe: bool,
    debug_flag: bool,
) -> None:
    """Run swarm with YAML config and goal."""
    cfg = load_swarm_yaml(config_path)
    if run_dir:
        cfg.run.run_dir = run_dir
    if debug_flag:
        cfg.run.debug = True
    goal_text = " ".join(goal).strip()
    if not goal_text:
        raise click.ClickException("Goal text is required")
    code = asyncio.run(HybridCoordinator(cfg, goal_text, resume=resume_flag).run())
    if observe:
        AttoswarmApp(cfg.run.run_dir).run()
    raise SystemExit(code)


@main.command("start")
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("goal", nargs=-1)
@click.option("--run-dir", default=None, help="Override run directory from config")
@click.option("--resume", "resume_flag", is_flag=True, help="Resume existing run directory state")
@click.option("--monitor/--no-monitor", default=True, help="Open monitor while coordinator runs")
@click.option("--detach", is_flag=True, help="Start coordinator and return immediately")
@click.option("--skip-doctor", is_flag=True, help="Skip backend preflight checks")
@click.option("--debug", "debug_flag", is_flag=True, help="Enable debug markers in shell wrapper and coordinator events")
def start_command(
    config_path: Path,
    goal: tuple[str, ...],
    run_dir: str | None,
    resume_flag: bool,
    monitor: bool,
    detach: bool,
    skip_doctor: bool,
    debug_flag: bool,
) -> None:
    """Single launcher: run coordinator and monitor with one command."""
    cfg = load_swarm_yaml(config_path)
    if run_dir:
        cfg.run.run_dir = run_dir
    if debug_flag:
        cfg.run.debug = True
    goal_text = " ".join(goal).strip()
    if not goal_text:
        raise click.ClickException("Goal text is required")

    if not skip_doctor:
        rows = _doctor_rows(cfg)
        if not _print_doctor(rows):
            raise click.ClickException("Doctor check failed. Fix missing backends or use --skip-doctor")

    if detach:
        cmd = [
            sys.executable,
            "-m",
            "attoswarm",
            "run",
            str(config_path),
            goal_text,
        ]
        if run_dir:
            cmd.extend(["--run-dir", run_dir])
        if resume_flag:
            cmd.append("--resume")
        if debug_flag:
            cmd.append("--debug")
        log_path = Path(cfg.run.run_dir) / "coordinator.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_fh = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
        proc = subprocess.Popen(cmd, stdout=log_fh, stderr=log_fh)
        click.echo(f"Coordinator started in background (pid={proc.pid})")
        click.echo(f"Reattach: attoswarm tui {cfg.run.run_dir}")
        raise SystemExit(0)

    if not monitor:
        code = asyncio.run(HybridCoordinator(cfg, goal_text, resume=resume_flag).run())
        raise SystemExit(code)

    cmd = [
        sys.executable,
        "-m",
        "attoswarm",
        "run",
        str(config_path),
        goal_text,
    ]
    if run_dir:
        cmd.extend(["--run-dir", run_dir])
    if resume_flag:
        cmd.append("--resume")
    if debug_flag:
        cmd.append("--debug")
    log_path = Path(cfg.run.run_dir) / "coordinator.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
    proc = subprocess.Popen(cmd, stdout=log_fh, stderr=log_fh)
    AttoswarmApp(cfg.run.run_dir).run()
    if proc.poll() is None:
        click.echo(
            f"Monitor exited; coordinator still running in background (pid={proc.pid}).\n"
            f"Reattach: attoswarm tui {cfg.run.run_dir}"
        )
        raise SystemExit(0)
    raise SystemExit(proc.returncode or 0)


@main.command("tui")
@click.argument("run_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
def tui_command(run_dir: Path) -> None:
    """Open TUI dashboard for an existing run directory."""
    AttoswarmApp(str(run_dir)).run()


@main.command("resume")
@click.argument("run_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
def resume_command(run_dir: Path) -> None:
    """Resume execution from an existing run directory."""
    manifest = run_dir / "swarm.manifest.json"
    if not manifest.exists():
        raise click.ClickException(f"Missing manifest: {manifest}")
    cfg = (
        load_swarm_yaml(run_dir / "swarm.yaml")
        if (run_dir / "swarm.yaml").exists()
        else SwarmYamlConfig()
    )
    cfg.run.run_dir = str(run_dir)
    goal = read_json(manifest, default={}).get("goal", "Resume swarm run")
    code = asyncio.run(HybridCoordinator(cfg, str(goal), resume=True).run())
    raise SystemExit(code)


@main.command("inspect")
@click.argument("run_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--tail", default=30, help="How many recent events to show")
@click.option("--agent", default=None, help="Filter by agent id")
@click.option("--task", "task_id", default=None, help="Filter by task id")
def inspect_command(run_dir: Path, tail: int, agent: str | None, task_id: str | None) -> None:
    """Inspect recent swarm events and state summaries."""
    state = read_json(run_dir / "swarm.state.json", default={})
    click.echo(f"phase={state.get('phase')} budget={state.get('budget', {})}")
    events_path = run_dir / "swarm.events.jsonl"
    if not events_path.exists():
        click.echo("No swarm.events.jsonl yet")
        return
    lines = events_path.read_text(encoding="utf-8", errors="replace").splitlines()
    show = lines[-max(tail, 1):]
    for line in show:
        try:
            item = json.loads(line)
        except Exception:
            continue
        payload = item.get("payload", {}) if isinstance(item.get("payload"), dict) else {}
        if agent and payload.get("agent_id") != agent:
            continue
        if task_id and payload.get("task_id") != task_id:
            continue
        click.echo(line)


@main.command("doctor")
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def doctor_command(config_path: Path) -> None:
    """Validate backend binaries and basic runtime readiness."""
    cfg = load_swarm_yaml(config_path)
    ok = _print_doctor(_doctor_rows(cfg))
    raise SystemExit(0 if ok else 1)


@main.command("init")
@click.argument("target_dir", type=click.Path(path_type=Path), required=False)
@click.option("--profile", type=click.Choice(["2cc", "cc-codex", "custom"]), default=None)
@click.option("--mode", type=click.Choice(["minimal", "demo"]), default=None)
def init_command(target_dir: Path | None, profile: str | None, mode: str | None) -> None:
    """Interactive starter generator for hybrid swarm."""
    base = target_dir or Path.cwd()
    attocode_dir = base / ".attocode"
    attocode_dir.mkdir(parents=True, exist_ok=True)

    has_repo = (base / ".git").exists() or (base / "pyproject.toml").exists() or (base / "package.json").exists()
    click.echo(f"Detected context: {'existing repository' if has_repo else 'fresh directory'} at {base}")
    setup_target = click.prompt(
        "Select setup target",
        type=click.Choice(["existing-repo", "demo-project"]),
        default="existing-repo" if has_repo else "demo-project",
    )
    if mode is None:
        mode = click.prompt(
            "Select output mode",
            type=click.Choice(["minimal", "demo"]),
            default="minimal" if setup_target == "existing-repo" else "demo",
        )
    if profile is None:
        profile = click.prompt(
            "Select backend profile",
            type=click.Choice(["2cc", "cc-codex", "custom"]),
            default="2cc",
        )

    path = attocode_dir / "swarm.hybrid.yaml"
    if profile == "2cc":
        yaml_text = """version: 1
run:
  working_dir: .
  run_dir: .agent/hybrid-swarm
  poll_interval_ms: 250
  max_runtime_seconds: 300
roles:
  - role_id: orchestrator
    role_type: orchestrator
    backend: claude
    model: claude-sonnet-4-20250514
    count: 1
    task_kinds: [analysis, design]
  - role_id: impl
    role_type: worker
    backend: claude
    model: claude-sonnet-4-20250514
    count: 2
    write_access: true
    workspace_mode: worktree
    task_kinds: [implement, test, integrate]
  - role_id: judge
    role_type: judge
    backend: claude
    model: claude-sonnet-4-20250514
    count: 1
    task_kinds: [judge]
  - role_id: critic
    role_type: critic
    backend: claude
    model: claude-sonnet-4-20250514
    count: 1
    task_kinds: [critic]
  - role_id: merger
    role_type: merger
    backend: claude
    model: claude-sonnet-4-20250514
    count: 1
    write_access: true
    workspace_mode: worktree
    task_kinds: [merge]
merge:
  authority_role: merger
  quality_threshold: 0.7
orchestration:
  decomposition: llm
  max_tasks: 24
"""
    elif profile == "cc-codex":
        yaml_text = """version: 1
run:
  working_dir: .
  run_dir: .agent/hybrid-swarm
  poll_interval_ms: 250
  max_runtime_seconds: 300
roles:
  - role_id: orchestrator
    role_type: orchestrator
    backend: claude
    model: claude-sonnet-4-20250514
    count: 1
    task_kinds: [analysis, design]
  - role_id: impl
    role_type: worker
    backend: claude
    model: claude-sonnet-4-20250514
    count: 1
    write_access: true
    workspace_mode: worktree
    task_kinds: [implement, test, integrate]
  - role_id: judge
    role_type: judge
    backend: codex
    model: o3
    count: 1
    task_kinds: [judge]
  - role_id: critic
    role_type: critic
    backend: claude
    model: claude-sonnet-4-20250514
    count: 1
    task_kinds: [critic]
  - role_id: merger
    role_type: merger
    backend: codex
    model: o3
    count: 1
    write_access: true
    workspace_mode: worktree
    task_kinds: [merge]
merge:
  authority_role: merger
  quality_threshold: 0.7
orchestration:
  decomposition: llm
  max_tasks: 24
"""
    else:
        yaml_text = """version: 1
run:
  working_dir: .
  run_dir: .agent/hybrid-swarm
roles: []
orchestration:
  decomposition: heuristic
"""

    path.write_text(yaml_text, encoding="utf-8")
    click.echo(f"Created {path}")
    if mode == "demo":
        tasks_dir = base / "tasks"
        scripts_dir = base / "scripts"
        tests_dir = base / "tests" / "swarm_smoke"
        tasks_dir.mkdir(parents=True, exist_ok=True)
        scripts_dir.mkdir(parents=True, exist_ok=True)
        tests_dir.mkdir(parents=True, exist_ok=True)
        (tasks_dir / "goal.md").write_text(
            "# Swarm Goal\n\nBuild a small feature with tests and report merge summary.\n",
            encoding="utf-8",
        )
        (scripts_dir / "run-swarm.sh").write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\nattocode swarm start .attocode/swarm.hybrid.yaml \"$(cat tasks/goal.md)\"\n",
            encoding="utf-8",
        )
        (tests_dir / "test_placeholder.txt").write_text(
            "placeholder for swarm smoke artifacts\n",
            encoding="utf-8",
        )
        readme_path = base / "README.swarm.md"
        readme_path.write_text(
            "# Swarm Demo\n\n"
            "Run:\n"
            "`attocode swarm start .attocode/swarm.hybrid.yaml \"$(cat tasks/goal.md)\"`\n\n"
            "Inspect:\n"
            "`attoswarm inspect .agent/hybrid-swarm --tail 80`\n",
            encoding="utf-8",
        )
        try:
            (scripts_dir / "run-swarm.sh").chmod(0o755)
        except OSError:
            pass
        click.echo("Created demo scaffold: tasks/, scripts/, tests/swarm_smoke/, README.swarm.md")
    click.echo("Next steps:")
    click.echo(f"  attocode swarm start {path} \"Implement a feature with tests\"")
    click.echo(f"  attocode swarm doctor {path}")
    click.echo("  attocode swarm monitor .agent/hybrid-swarm")


if __name__ == "__main__":
    main()
