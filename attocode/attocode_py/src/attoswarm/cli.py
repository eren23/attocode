"""CLI entrypoint for attoswarm."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import shutil
from pathlib import Path
from typing import Any

import click

from attoswarm.config.loader import load_swarm_yaml
from attoswarm.config.schema import RoleConfig, SwarmYamlConfig
from attoswarm.coordinator.loop import HybridCoordinator
from attoswarm.protocol.io import read_json
from attoswarm.tui.app import AttoswarmApp


logger = logging.getLogger(__name__)

# Env vars that interfere with nested agent processes (e.g. running from
# within Claude Code would set CLAUDECODE=1 causing claude subprocess to
# refuse with "cannot launch inside another session").
_STRIP_ENV_VARS = {
    "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_REPL",
    "CLAUDE_CODE_PACKAGE_DIR",
}


@click.group()
def main() -> None:
    """Attoswarm hybrid swarm orchestrator."""


def _build_backend_cmd(backend: str, model: str, prompt: str) -> list[str]:
    """Build subprocess command list for a given backend.

    Mirrors the logic in ``HybridCoordinator._default_command`` but returns
    a flat argv list suitable for ``asyncio.create_subprocess_exec``.
    """
    if backend == "claude":
        cmd = ["claude", "-p", "--dangerously-skip-permissions"]
        if model:
            cmd.extend(["--model", model])
        cmd.append(prompt)
        return cmd
    if backend == "codex":
        cmd = [
            "codex", "exec", "--json", "--skip-git-repo-check",
            "--sandbox", "workspace-write",
        ]
        if model:
            cmd.extend(["--model", model])
        cmd.append(prompt)
        return cmd
    if backend == "aider":
        cmd = ["aider"]
        if model:
            cmd.extend(["--model", model])
        cmd.extend(["--message", prompt])
        return cmd
    if backend == "attocode":
        cmd = ["attocode"]
        if model:
            cmd.extend(["--model", model])
        cmd.extend(["--non-interactive", prompt])
        return cmd
    raise ValueError(f"Unsupported backend: {backend!r}")


def _make_subprocess_spawn_fn(cfg: SwarmYamlConfig):  # noqa: ANN202
    """Build a spawn function that delegates to backend CLIs as subprocesses.

    Selects the correct backend (claude, codex, aider, attocode) based on the
    task's ``role_hint`` field, falling back to the first configured role's
    backend (or ``"claude"`` if no roles are defined).

    Strips CLAUDECODE env vars to prevent nested-session errors.
    """
    from attoswarm.coordinator.subagent_manager import TaskResult as _TaskResult

    # Pre-build role_hint -> RoleConfig lookup
    role_map: dict[str, RoleConfig] = {r.role_id: r for r in cfg.roles}
    fallback_backend = cfg.roles[0].backend if cfg.roles else "claude"
    fallback_model = cfg.roles[0].model if cfg.roles else ""

    # Build a clean env without CLAUDECODE vars
    clean_env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV_VARS}

    async def _spawn_agent(task: dict) -> _TaskResult:
        import time as _time

        wd = cfg.run.working_dir or "."

        # Resolve backend + model from role_hint
        role_hint = task.get("role_hint", "")
        role_cfg = role_map.get(role_hint)
        if role_cfg:
            backend = role_cfg.backend
            model = role_cfg.model
        else:
            backend = fallback_backend
            model = fallback_model

        target_files = task.get("target_files", [])
        read_files = task.get("read_files", [])
        prompt_parts = [f"# Task: {task.get('title', '')}", "", task.get("description", "")]
        if target_files:
            prompt_parts.append(f"\nTarget files: {', '.join(target_files)}")
        if read_files:
            prompt_parts.append(f"\nReference files: {', '.join(read_files)}")
        prompt = "\n".join(prompt_parts)

        cmd = _build_backend_cmd(backend, model, prompt)

        t0 = _time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=wd,
                env=clean_env,
                start_new_session=True,
            )
            worker_timeout = max(cfg.run.max_runtime_seconds or 600, 600)
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=worker_timeout,
            )
            elapsed = _time.monotonic() - t0
            stdout_text = (stdout_bytes or b"").decode("utf-8", errors="replace")
            stderr_text = (stderr_bytes or b"").decode("utf-8", errors="replace")

            if proc.returncode == 0:
                return _TaskResult(
                    task_id=task["task_id"],
                    success=True,
                    result_summary=stdout_text[:4000],
                    duration_s=elapsed,
                )
            else:
                return _TaskResult(
                    task_id=task["task_id"],
                    success=False,
                    result_summary=stdout_text[:2000],
                    error=stderr_text[:2000] or f"{cmd[0]} exited with code {proc.returncode}",
                    duration_s=elapsed,
                )
        except asyncio.TimeoutError:
            return _TaskResult(
                task_id=task["task_id"],
                success=False,
                error=f"Subprocess timed out after {cfg.run.max_runtime_seconds}s",
                duration_s=_time.monotonic() - t0,
            )
        except FileNotFoundError:
            return _TaskResult(
                task_id=task["task_id"],
                success=False,
                error=f"'{cmd[0]}' CLI not found. Install it or add it to PATH.",
                duration_s=_time.monotonic() - t0,
            )
        except Exception as exc:
            return _TaskResult(
                task_id=task["task_id"],
                success=False,
                error=f"Subprocess spawn failed: {exc}",
                duration_s=_time.monotonic() - t0,
            )

    return _spawn_agent


def _make_subprocess_decompose_fn(cfg: SwarmYamlConfig):  # noqa: ANN202
    """Build a decompose function that calls a backend CLI to split the goal into tasks.

    Uses the orchestrator role's backend/model to invoke LLM-based decomposition.
    Returns a coroutine matching the ``decompose_fn`` signature expected by
    ``SwarmOrchestrator._decompose_goal()``.
    """
    from attoswarm.protocol.models import TaskSpec as _TaskSpec

    # Pick orchestrator role, falling back to first role or defaults
    orch_role = next((r for r in cfg.roles if r.role_type == "orchestrator"), None)
    if orch_role:
        backend = orch_role.backend
        model = orch_role.model
    elif cfg.roles:
        backend = cfg.roles[0].backend
        model = cfg.roles[0].model
    else:
        backend = "claude"
        model = ""

    max_tasks = cfg.orchestration.max_tasks or 20

    # Build role descriptions for the prompt
    role_descriptions = "\n".join(
        f"  - role_id={r.role_id}, role_type={r.role_type}, task_kinds={r.task_kinds}"
        for r in cfg.roles
    )

    clean_env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV_VARS}

    def _build_decompose_prompt(goal: str) -> str:
        return (
            "You are a task decomposition engine for a multi-agent coding swarm.\n\n"
            "Given the following goal, decompose it into a DAG of concrete, actionable tasks.\n\n"
            f"## Goal\n{goal}\n\n"
            f"## Available Roles\n{role_descriptions or '  (none configured -- omit role_hint)'}\n\n"
            "## Constraints\n"
            f"- Produce between 2 and {max_tasks} tasks.\n"
            "- Each task should be completable by a single agent in one pass.\n"
            "- Tasks should have clear boundaries -- avoid overlapping target files.\n"
            "- Use deps to express dependencies (task_id references).\n"
            "- Assign role_hint matching an available role_id when appropriate.\n\n"
            "## Output Format\n"
            "Respond with ONLY a JSON array (no markdown fences, no explanation):\n"
            "[\n"
            '  {\n'
            '    "task_id": "task-1",\n'
            '    "title": "Short title",\n'
            '    "description": "Detailed description of what to do",\n'
            '    "deps": [],\n'
            '    "target_files": ["src/foo.py"],\n'
            '    "role_hint": "impl",\n'
            '    "task_kind": "implement"\n'
            "  }\n"
            "]\n\n"
            "task_kind should be one of: analysis, design, implement, test, integrate, judge, critic, merge"
        )

    def _build_retry_prompt(goal: str) -> str:
        return (
            "Decompose this goal into 2-4 coding tasks. Return ONLY a JSON array.\n\n"
            f"Goal: {goal}\n\n"
            'Format: [{{"task_id": "task-1", "title": "...", "description": "...", '
            '"deps": [], "target_files": [], "role_hint": "", "task_kind": "implement"}}]'
        )

    def _parse_tasks(raw: str) -> list[_TaskSpec]:
        """Parse JSON output into TaskSpec list with validation."""
        text = raw.strip()
        # Strip <thinking>...</thinking> tags (Claude extended thinking)
        text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL)
        # Strip markdown fences (```json ... ``` or ``` ... ```)
        text = re.sub(r"```(?:json|JSON)?\s*\n?", "", text)
        text = text.strip()
        # Extract first JSON array from the text
        match = re.search(r"\[.*\]", text, flags=re.DOTALL)
        if not match:
            raise ValueError(f"No JSON array found in output ({len(raw)} chars)")
        text = match.group(0)

        data = json.loads(text)
        if not isinstance(data, list) or len(data) < 2:
            raise ValueError(
                f"Expected array with >=2 tasks, got {len(data) if isinstance(data, list) else 0} items"
            )

        # Validate task_ids are unique
        ids = [t["task_id"] for t in data]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Duplicate task_ids: {ids}")

        # Validate dep references
        id_set = set(ids)
        for t in data:
            for dep in t.get("deps", []):
                if dep not in id_set:
                    raise ValueError(f"Task {t['task_id']} depends on unknown task {dep}")

        return [
            _TaskSpec(
                task_id=t["task_id"],
                title=t.get("title", t["task_id"]),
                description=t.get("description", ""),
                deps=t.get("deps", []),
                target_files=t.get("target_files", []),
                role_hint=t.get("role_hint") or None,
                task_kind=t.get("task_kind", "implement"),
            )
            for t in data
        ]

    async def _run_decompose(prompt: str) -> list[_TaskSpec]:
        """Run a single decomposition attempt via subprocess."""
        cmd = _build_backend_cmd(backend, model, prompt)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cfg.run.working_dir or ".",
            env=clean_env,
            start_new_session=True,
        )
        decompose_timeout = min(cfg.run.max_runtime_seconds or 120, 120)
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=decompose_timeout,
        )
        stdout_text = (stdout_bytes or b"").decode("utf-8", errors="replace")

        if proc.returncode != 0:
            stderr_text = (stderr_bytes or b"").decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Decomposition subprocess exited {proc.returncode}: {stderr_text[:500]}"
            )

        return _parse_tasks(stdout_text)

    async def decompose_fn(
        goal: str, *, ast_service: Any = None, config: Any = None,
    ) -> list[_TaskSpec]:
        """Decompose a goal into TaskSpecs via subprocess LLM call."""
        # First attempt with full prompt
        try:
            return await _run_decompose(_build_decompose_prompt(goal))
        except Exception as exc:
            logger.warning("Decomposition attempt 1 failed: %s", exc)

        # Retry with simpler prompt
        return await _run_decompose(_build_retry_prompt(goal))

    return decompose_fn


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
@click.option(
    "--workspace-mode",
    type=click.Choice(["shared", "worktree"]),
    default=None,
    help="Override workspace mode: 'shared' (AoT+OCC) or 'worktree' (legacy)",
)
def run_command(
    config_path: Path,
    goal: tuple[str, ...],
    run_dir: str | None,
    resume_flag: bool,
    observe: bool,
    debug_flag: bool,
    workspace_mode: str | None,
) -> None:
    """Run swarm with YAML config and goal."""
    cfg = load_swarm_yaml(config_path)
    if run_dir:
        cfg.run.run_dir = run_dir
    if debug_flag:
        cfg.run.debug = True
    if workspace_mode:
        cfg.workspace.mode = workspace_mode
    goal_text = " ".join(goal).strip()
    if not goal_text:
        raise click.ClickException("Goal text is required")

    # Route to appropriate coordinator
    if cfg.workspace.mode == "shared":
        from attoswarm.coordinator.orchestrator import SwarmOrchestrator
        code = asyncio.run(SwarmOrchestrator(
            cfg, goal_text, resume=resume_flag,
            decompose_fn=_make_subprocess_decompose_fn(cfg),
            spawn_fn=_make_subprocess_spawn_fn(cfg),
        ).run())
    else:
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
@click.option(
    "--workspace-mode",
    type=click.Choice(["shared", "worktree"]),
    default=None,
    help="Override workspace mode: 'shared' (AoT+OCC) or 'worktree' (legacy)",
)
def start_command(
    config_path: Path,
    goal: tuple[str, ...],
    run_dir: str | None,
    resume_flag: bool,
    monitor: bool,
    detach: bool,
    skip_doctor: bool,
    debug_flag: bool,
    workspace_mode: str | None,
) -> None:
    """Single launcher: run coordinator and monitor with one command."""
    cfg = load_swarm_yaml(config_path)
    if run_dir:
        cfg.run.run_dir = run_dir
    if debug_flag:
        cfg.run.debug = True
    if workspace_mode:
        cfg.workspace.mode = workspace_mode
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
        if cfg.workspace.mode == "shared":
            from attoswarm.coordinator.orchestrator import SwarmOrchestrator
            code = asyncio.run(SwarmOrchestrator(
                cfg, goal_text, resume=resume_flag,
                decompose_fn=_make_subprocess_decompose_fn(cfg),
                spawn_fn=_make_subprocess_spawn_fn(cfg),
            ).run())
        else:
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
