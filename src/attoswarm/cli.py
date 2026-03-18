"""CLI entrypoint for attoswarm."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import click

from attoswarm.config.loader import load_swarm_yaml, save_swarm_yaml
from attoswarm.config.schema import RoleConfig, SwarmYamlConfig
from attoswarm.coordinator.loop import HybridCoordinator
from attoswarm.protocol.io import read_json
from attoswarm.protocol.models import LauncherInfo, LineageSpec
from attoswarm.tui.app import AttoswarmApp

logger = logging.getLogger(__name__)


def _make_trace_collector(cfg: SwarmYamlConfig) -> Any:
    """Create a TraceCollector for the run if tracing is enabled. Returns None on failure."""
    try:
        from attocode.tracing.collector import TraceCollector

        trace_dir = Path(cfg.run.run_dir) / "traces"
        collector = TraceCollector(output_dir=str(trace_dir), buffer_size=1)
        collector.start_session(goal="swarm")
        return collector
    except Exception as exc:
        logger.debug("Trace collector init failed: %s", exc)
        return None

# ── Activity label parsing for agent stdout ──────────────────────────

_ACTIVITY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?:Read|Reading)\s+(?:tool\s+)?['\"]?(\S+)", re.IGNORECASE), "Reading {0}"),
    (re.compile(r"(?:Edit|Editing)\s+(?:tool\s+)?['\"]?(\S+)", re.IGNORECASE), "Editing {0}"),
    (re.compile(r"(?:Write|Writing)\s+(?:tool\s+)?['\"]?(\S+)", re.IGNORECASE), "Writing {0}"),
    (re.compile(r"(?:Bash|Running)\s+(?:tool\s+)?['\"]?(.+?)(?:['\"]|$)", re.IGNORECASE), "Running {0}"),
    (re.compile(r"(?:Grep|Searching)\s+(?:for\s+)?['\"]?(\S+)", re.IGNORECASE), "Searching {0}"),
    (re.compile(r"(?:Glob|Finding)\s+['\"]?(\S+)", re.IGNORECASE), "Finding {0}"),
]


def _parse_activity_label(line: str) -> str:
    """Extract a human-readable activity label from a stdout line."""
    line = line.strip()
    if not line:
        return ""
    for pattern, template in _ACTIVITY_PATTERNS:
        m = pattern.search(line)
        if m:
            target = m.group(1)[:60]
            # Shorten file paths
            if "/" in target:
                target = target.rsplit("/", 1)[-1]
            return template.format(target)
    return ""


def _write_activity(run_dir: str, task_id: str, label: str) -> None:
    """Write a current-activity sidecar file for TUI consumption."""
    try:
        p = Path(run_dir) / "agents" / f"agent-{task_id}.activity.txt"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(label, encoding="utf-8")
    except Exception:
        pass


# Env vars that interfere with nested agent processes (e.g. running from
# within Claude Code would set CLAUDECODE=1 causing claude subprocess to
# refuse with "cannot launch inside another session").
_STRIP_ENV_VARS = {
    "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_REPL",
    "CLAUDE_CODE_PACKAGE_DIR",
}


@click.group()
def main() -> None:
    """Attoswarm engine CLI. Canonical user entrypoint: `attocode swarm ...`."""


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


def _unwrap_codex_jsonl(raw: str) -> str:
    """Extract LLM message from codex exec --json JSONL output.

    Codex ``exec --json`` emits JSONL events.  The actual LLM response
    lives in ``item.completed`` events where ``item.type == "agent_message"``.
    We return the last such message text (multi-turn conversations produce
    multiple ``item.completed`` events).
    """
    messages: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (ValueError, json.JSONDecodeError):
            continue
        if not isinstance(obj, dict):
            continue
        # Current format: item.completed with agent_message
        if obj.get("type") == "item.completed":
            item = obj.get("item", {})
            if isinstance(item, dict) and item.get("type") == "agent_message":
                text = item.get("text", "")
                if text:
                    messages.append(text)
        # Legacy format
        elif obj.get("status") == "completed":
            msg = obj.get("message", "")
            if msg:
                messages.append(msg)

    return messages[-1] if messages else raw


def _build_backend_cmd_stdin(backend: str, model: str, prompt: str) -> tuple[list[str], str]:
    """Build subprocess command + stdin text, piping prompt via stdin.

    Returns ``(cmd, stdin_text)`` where *stdin_text* is the prompt to write
    to the process's stdin.  This avoids OS argument-length limits for large
    prompts.

    Backends that accept stdin for the prompt (claude, codex) get the prompt
    piped.  Others (aider, attocode) still receive the prompt as a CLI arg.
    """
    if backend == "claude":
        cmd = ["claude", "-p", "--dangerously-skip-permissions"]
        if model:
            cmd.extend(["--model", model])
        # claude -p reads from stdin when no positional prompt is given
        return cmd, prompt
    if backend == "codex":
        cmd = [
            "codex", "exec", "--json", "--skip-git-repo-check",
            "--sandbox", "workspace-write",
        ]
        if model:
            cmd.extend(["--model", model])
        cmd.append(prompt)
        return cmd, ""
    if backend == "aider":
        cmd = ["aider"]
        if model:
            cmd.extend(["--model", model])
        cmd.extend(["--message", prompt])
        return cmd, ""
    if backend == "attocode":
        cmd = ["attocode"]
        if model:
            cmd.extend(["--model", model])
        cmd.extend(["--non-interactive", prompt])
        return cmd, ""
    raise ValueError(f"Unsupported backend: {backend!r}")


def _make_subprocess_spawn_fn(
    cfg: SwarmYamlConfig,
    process_registry: Any = None,
    event_callback: Any = None,
):  # noqa: ANN202
    """Build a spawn function that delegates to backend CLIs as subprocesses.

    Selects the correct backend (claude, codex, aider, attocode) based on the
    task's ``role_hint`` field, falling back to the first configured role's
    backend (or ``"claude"`` if no roles are defined).

    Strips CLAUDECODE env vars to prevent nested-session errors.

    If *process_registry* (a SubagentManager) is provided, spawned processes
    are registered/unregistered for graceful shutdown.

    If *event_callback* is provided, it is called with each parsed
    ``AgentActivityEvent`` from Claude stream-json output.
    """
    from attoswarm.adapters.stream_parser import AgentActivityEvent, parse_stream_json_line
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
        is_claude = backend == "claude"
        if is_claude:
            # Inject stream-json only for worker spawns (not decompose);
            # --verbose is required by claude CLI when combining -p with stream-json
            cmd = cmd[:-1] + ["--verbose", "--output-format", "stream-json"] + cmd[-1:]
        task_id = task["task_id"]

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
            if process_registry is not None:
                process_registry.register_process(proc)
            worker_timeout = max(cfg.run.max_runtime_seconds or 600, 600)

            # Accumulated structured events for result enrichment
            activity_events: list[AgentActivityEvent] = []
            final_tokens = 0
            final_cost = 0.0

            # Stream stdout — use stream-json parser for claude, regex for others
            async def _read_stdout() -> bytes:
                nonlocal final_tokens, final_cost
                if proc.stdout is None:
                    raise RuntimeError("Process stdout not available (subprocess created without PIPE)")
                buf = bytearray()
                remainder = ""
                while True:
                    chunk = await proc.stdout.read(4096)
                    if not chunk:
                        # Process any remaining partial line
                        if remainder.strip():
                            _process_line(remainder, task_id, is_claude, activity_events)
                        break
                    buf.extend(chunk)
                    text = remainder + chunk.decode("utf-8", errors="replace")
                    lines = text.split("\n")
                    # Last element may be incomplete — save as remainder
                    remainder = lines[-1]
                    for line in lines[:-1]:
                        _process_line(line, task_id, is_claude, activity_events)
                # Extract final tokens/cost from result events
                for evt in activity_events:
                    if evt.event_kind == "result":
                        final_tokens = max(final_tokens, evt.tokens_used)
                        final_cost = max(final_cost, evt.cost_usd)
                return bytes(buf)

            def _process_line(
                line: str,
                tid: str,
                use_stream_json: bool,
                events: list[AgentActivityEvent],
            ) -> None:
                if use_stream_json:
                    evt = parse_stream_json_line(line, tid)
                    if evt:
                        events.append(evt)
                        # Backward-compat: write activity sidecar
                        if evt.event_kind == "tool_call" and evt.tool_name:
                            _write_activity(cfg.run.run_dir, tid, f"{evt.tool_name} {evt.tool_input_summary[:40]}")
                        elif evt.event_kind == "text" and evt.text_preview:
                            _write_activity(cfg.run.run_dir, tid, evt.text_preview[:60])
                        # Invoke event_callback for real-time observability
                        if event_callback is not None:
                            try:
                                event_callback(evt)
                            except Exception:
                                pass
                else:
                    # Legacy regex path for non-Claude backends
                    label = _parse_activity_label(line)
                    if label:
                        _write_activity(cfg.run.run_dir, tid, label)

            async def _read_stderr() -> bytes:
                if proc.stderr is None:
                    raise RuntimeError("Process stderr not available (subprocess created without PIPE)")
                return await proc.stderr.read()

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    asyncio.gather(_read_stdout(), _read_stderr()),
                    timeout=worker_timeout,
                )
            except TimeoutError:
                proc.kill()
                raise

            await proc.wait()
            if process_registry is not None:
                process_registry.unregister_process(proc)
            elapsed = _time.monotonic() - t0
            stdout_text = (stdout_bytes or b"").decode("utf-8", errors="replace")
            stderr_text = (stderr_bytes or b"").decode("utf-8", errors="replace")

            if proc.returncode == 0:
                return _TaskResult(
                    task_id=task_id,
                    success=True,
                    result_summary=stdout_text[:4000],
                    tokens_used=final_tokens,
                    cost_usd=final_cost,
                    duration_s=elapsed,
                )
            else:
                return _TaskResult(
                    task_id=task_id,
                    success=False,
                    result_summary=stdout_text[:2000],
                    error=stderr_text[:2000] or f"{cmd[0]} exited with code {proc.returncode}",
                    tokens_used=final_tokens,
                    cost_usd=final_cost,
                    duration_s=elapsed,
                )
        except TimeoutError:
            return _TaskResult(
                task_id=task_id,
                success=False,
                error=f"Subprocess timed out after {cfg.run.max_runtime_seconds}s",
                duration_s=_time.monotonic() - t0,
            )
        except FileNotFoundError:
            return _TaskResult(
                task_id=task_id,
                success=False,
                error=f"'{cmd[0]}' CLI not found. Install it or add it to PATH.",
                duration_s=_time.monotonic() - t0,
            )
        except Exception as exc:
            return _TaskResult(
                task_id=task_id,
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

    logger.info(
        "Decomposer using backend=%s model=%s",
        backend,
        model or "(default)",
    )

    max_tasks = cfg.orchestration.max_tasks or 20

    # Build role descriptions for the prompt
    role_descriptions = "\n".join(
        f"  - role_id={r.role_id}, role_type={r.role_type}, task_kinds={r.task_kinds}"
        for r in cfg.roles
    )

    clean_env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV_VARS}

    custom_instructions = (cfg.orchestration.custom_instructions or "").strip()

    # No codex preamble needed — codex decomposes fine when output is
    # correctly unwrapped from JSONL events.

    def _build_decompose_prompt(goal: str, complexity: str = "", codebase_context: str = "") -> str:
        from attoswarm.coordinator.decompose import build_decompose_prompt, classify_goal_complexity
        if not complexity:
            complexity = classify_goal_complexity(goal)
        prompt = build_decompose_prompt(
            goal,
            complexity=complexity,
            max_tasks=max_tasks,
            role_descriptions=role_descriptions,
            custom_instructions=custom_instructions,
            codebase_context=codebase_context,
        )
        return prompt

    def _build_retry_prompt(goal: str, complexity: str = "") -> str:
        from attoswarm.coordinator.decompose import build_retry_prompt, classify_goal_complexity
        if not complexity:
            complexity = classify_goal_complexity(goal)
        prompt = build_retry_prompt(
            goal,
            complexity=complexity,
            custom_instructions=custom_instructions,
        )
        return prompt

    def _parse_tasks(raw: str) -> list[_TaskSpec]:
        """Parse JSON output into TaskSpec list with validation."""
        from attoswarm.coordinator.task_parser import extract_json_array

        data = extract_json_array(raw)
        if len(data) < 2:
            raise ValueError("Expected array with >=2 tasks, got %d items" % len(data))

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

    # _unwrap_codex_jsonl is at module level (no closure deps)

    async def _run_decompose(prompt: str) -> list[_TaskSpec]:
        """Run a single decomposition attempt via subprocess."""
        cmd, stdin_text = _build_backend_cmd_stdin(backend, model, prompt)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE if stdin_text else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cfg.run.working_dir or ".",
            env=clean_env,
            start_new_session=True,
        )
        decompose_timeout = min(cfg.run.max_runtime_seconds or 300, 300)
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=stdin_text.encode() if stdin_text else None),
                timeout=decompose_timeout,
            )
        except (asyncio.TimeoutError, TimeoutError):
            proc.kill()
            await proc.wait()
            raise RuntimeError(
                f"Decomposition subprocess timed out after {decompose_timeout}s"
            )
        stdout_text = (stdout_bytes or b"").decode("utf-8", errors="replace")

        if proc.returncode != 0:
            stderr_text = (stderr_bytes or b"").decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Decomposition subprocess exited {proc.returncode}: {stderr_text[:500]}"
            )

        # Codex --json wraps the LLM response in JSONL events; unwrap it
        if backend == "codex":
            stdout_text = _unwrap_codex_jsonl(stdout_text)

        return _parse_tasks(stdout_text)

    async def decompose_fn(
        goal: str, *, ast_service: Any = None, config: Any = None,
        codebase_context: str = "",
    ) -> list[_TaskSpec]:
        """Decompose a goal into TaskSpecs via subprocess LLM call."""
        from attoswarm.coordinator.decompose import classify_goal_complexity, validate_decomposition

        complexity = classify_goal_complexity(goal)
        logger.info("Goal complexity: %s (word_count=%d)", complexity, len(goal.split()))

        # First attempt with complexity-aware prompt
        try:
            tasks = await _run_decompose(_build_decompose_prompt(goal, complexity, codebase_context))
            warnings = validate_decomposition(
                [{"task_id": t.task_id, "title": t.title, "description": t.description} for t in tasks],
                complexity,
            )
            for w in warnings:
                logger.warning("Decomposition: %s", w.get("message", ""))
            return tasks
        except Exception as exc:
            logger.warning("Decomposition attempt 1 failed: %s", exc)

        # Retry with simpler prompt
        return await _run_decompose(_build_retry_prompt(goal, complexity))

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


def _print_run_summary(orch: Any) -> None:
    """Print a post-run summary to the terminal."""
    summary = orch.aot_graph.summary()
    done = summary.get("done", 0)
    total = sum(summary.values()) if isinstance(summary, dict) else 0
    failed = summary.get("failed", 0)
    cost = orch.budget.used_cost_usd

    elapsed_s = 0.0
    if hasattr(orch, '_start_time') and orch._start_time:
        import time as _t
        elapsed_s = _t.time() - orch._start_time
    mins = int(elapsed_s) // 60
    secs = int(elapsed_s) % 60
    elapsed_str = f"{mins}m{secs:02d}s" if mins else f"{secs}s"

    click.echo(f"\n{'=' * 50}")
    click.echo(f"  Tasks: {done}/{total} completed" + (f" ({failed} failed)" if failed else ""))
    click.echo(f"  Cost:  ${cost:.2f}")
    click.echo(f"  Time:  {elapsed_str}")

    # Change manifest summary
    if hasattr(orch, '_change_manifest') and orch._change_manifest:
        ms = orch._change_manifest.get_summary()
        if ms.get("total_changes"):
            click.echo(f"  Files: {len(ms.get('files_modified', []))} modified ({ms['total_changes']} changes)")
    click.echo(f"{'=' * 50}")


def _prompt_git_finalization(orch: Any) -> None:
    """Prompt user for git finalization if git safety was used."""
    if not hasattr(orch, '_git_safety') or not orch._git_safety:
        return
    gs = orch._git_safety
    if not gs.state.is_git_repo:
        return

    click.echo(f"\nSwarm branch: {gs.state.swarm_branch}")
    if gs.state.stash_ref:
        click.echo(f"Pre-run stash: {gs.state.stash_ref}")

    try:
        choice = click.prompt(
            "Git finalization",
            type=click.Choice(["merge", "keep", "discard"]),
            default="keep",
        )
        import asyncio as _asyncio
        _asyncio.run(gs.finalize(choice))
        click.echo(f"Git finalized: {choice}")
    except (click.Abort, EOFError):
        click.echo("Skipped git finalization (branch preserved)")


def _launcher_info_from_env() -> LauncherInfo:
    return LauncherInfo(
        started_via=os.environ.get("ATTO_SWARM_STARTED_VIA", "attoswarm"),
        command_family=os.environ.get("ATTO_SWARM_COMMAND_FAMILY", "attoswarm"),
    )


def _read_run_metadata(run_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = read_json(run_dir / "swarm.manifest.json", default={})
    state = read_json(run_dir / "swarm.state.json", default={})
    return (
        manifest if isinstance(manifest, dict) else {},
        state if isinstance(state, dict) else {},
    )


def _summarize_parent_run(parent_run_dir: Path) -> dict[str, Any]:
    manifest, state = _read_run_metadata(parent_run_dir)
    dag_summary = state.get("dag_summary", {})
    if not isinstance(dag_summary, dict):
        dag_summary = {}

    unresolved: list[str] = []
    dag_nodes = state.get("dag", {}).get("nodes", []) if isinstance(state.get("dag"), dict) else []
    if isinstance(dag_nodes, list):
        for node in dag_nodes:
            if not isinstance(node, dict):
                continue
            if str(node.get("status", "")) not in {"done", "completed"}:
                task_id = str(node.get("task_id", ""))
                if task_id:
                    unresolved.append(task_id)

    changed_files: list[str] = []
    raw_changes = read_json(parent_run_dir / "changes.json", default=[])
    if isinstance(raw_changes, list):
        seen: set[str] = set()
        for item in raw_changes:
            if not isinstance(item, dict):
                continue
            file_path = str(item.get("file_path", ""))
            if file_path and file_path not in seen:
                seen.add(file_path)
                changed_files.append(file_path)

    return {
        "goal": manifest.get("goal", state.get("goal", "")),
        "phase": state.get("phase", ""),
        "completed_tasks": int(dag_summary.get("done", 0)),
        "failed_tasks": int(dag_summary.get("failed", 0)),
        "changed_files": changed_files[:20],
        "unresolved_tasks": unresolved[:20],
    }


def _build_continuation_lineage(parent_run_dir: Path) -> LineageSpec:
    manifest, state = _read_run_metadata(parent_run_dir)
    parent_run_id = str(manifest.get("run_id", state.get("run_id", parent_run_dir.name)))
    parent_lineage = LineageSpec.from_dict(manifest.get("lineage", {}) or state.get("lineage", {}))
    git_safety = read_json(parent_run_dir / "git_safety.json", default={})
    if not isinstance(git_safety, dict):
        git_safety = {}

    if str(git_safety.get("finalization_mode", "")) == "discard":
        raise click.ClickException(f"Cannot continue from {parent_run_dir}: parent swarm was discarded")

    base_ref = str(
        git_safety.get("result_ref")
        or git_safety.get("swarm_branch")
        or git_safety.get("result_commit")
        or ""
    )
    base_commit = str(
        git_safety.get("result_commit")
        or git_safety.get("base_commit")
        or git_safety.get("pre_run_head")
        or ""
    )
    if not base_ref:
        raise click.ClickException(
            f"Cannot continue from {parent_run_dir}: no preserved swarm branch or result commit found"
        )

    return LineageSpec(
        parent_run_id=parent_run_id,
        parent_run_dir=str(parent_run_dir),
        root_run_id=parent_lineage.root_run_id or parent_run_id,
        continuation_mode="child",
        base_ref=base_ref,
        base_commit=base_commit,
        parent_summary=_summarize_parent_run(parent_run_dir),
    )


def _default_child_run_dir(parent_run_dir: Path) -> str:
    manifest, state = _read_run_metadata(parent_run_dir)
    parent_run_id = str(manifest.get("run_id", state.get("run_id", parent_run_dir.name)))
    stamp = time.strftime("%Y%m%d-%H%M%S")
    short_id = uuid.uuid4().hex[:4]
    return str(parent_run_dir.parent / f"{parent_run_id}-child-{stamp}-{short_id}")


def _apply_continuation(
    cfg: SwarmYamlConfig,
    continue_from: Path,
    run_dir: str | None,
    resume_flag: bool,
) -> LineageSpec:
    """Validate --continue-from and return lineage + mutate cfg.run.run_dir."""
    if resume_flag:
        raise click.ClickException("--resume cannot be combined with --continue-from")
    continue_root = continue_from.resolve()
    lineage = _build_continuation_lineage(continue_root)
    cfg.run.run_dir = run_dir or _default_child_run_dir(continue_root)
    if Path(cfg.run.run_dir).resolve() == continue_root:
        raise click.ClickException("Child runs must use a different run directory than the parent run")
    return lineage


@main.command("run")
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("goal", nargs=-1)
@click.option("--run-dir", default=None, help="Override run directory from config")
@click.option("--resume", "resume_flag", is_flag=True, help="Resume existing run directory state")
@click.option(
    "--continue-from",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Start a new child swarm from a previous swarm run directory",
)
@click.option("--observe", is_flag=True, help="Open TUI after run exits")
@click.option("--debug", "debug_flag", is_flag=True, help="Enable debug markers in shell wrapper and coordinator events")
@click.option(
    "--workspace-mode",
    type=click.Choice(["shared", "worktree"]),
    default=None,
    help="Override workspace mode: 'shared' (AoT+OCC) or 'worktree' (legacy)",
)
@click.option("--trace", "trace_flag", is_flag=True, help="Enable trace collection for post-hoc analysis")
@click.option("--no-git-safety", is_flag=True, help="Disable git stash/branch safety net")
@click.option("--approval-mode", type=click.Choice(["auto", "preview", "dry_run"]), default="auto", help="Approval mode for task execution")
def run_command(
    config_path: Path,
    goal: tuple[str, ...],
    run_dir: str | None,
    resume_flag: bool,
    continue_from: Path | None,
    observe: bool,
    debug_flag: bool,
    workspace_mode: str | None,
    trace_flag: bool,
    no_git_safety: bool,
    approval_mode: str,
) -> None:
    """Run swarm with YAML config and goal."""
    cfg = load_swarm_yaml(config_path)
    launcher = _launcher_info_from_env()
    lineage = _apply_continuation(cfg, continue_from, run_dir, resume_flag) if continue_from else LineageSpec()
    if not continue_from and run_dir:
        cfg.run.run_dir = run_dir
    if debug_flag:
        cfg.run.debug = True
    if workspace_mode:
        cfg.workspace.mode = workspace_mode
    if no_git_safety:
        cfg.workspace.git_safety = False
    goal_text = " ".join(goal).strip()
    if not goal_text:
        raise click.ClickException("Goal text is required")

    collector = _make_trace_collector(cfg) if trace_flag else None

    # Route to appropriate coordinator
    if cfg.workspace.mode == "shared":
        from attoswarm.coordinator.orchestrator import SwarmOrchestrator
        orch = SwarmOrchestrator(
            cfg, goal_text, resume=resume_flag,
            decompose_fn=_make_subprocess_decompose_fn(cfg),
            spawn_fn=_make_subprocess_spawn_fn(cfg, process_registry=None),
            trace_collector=collector,
            approval_mode=approval_mode,
            lineage=lineage,
            launcher=launcher,
        )
        # Wire process registry + event_callback: spawn_fn uses orchestrator's subagent manager
        orch._subagent_mgr._spawn_fn = _make_subprocess_spawn_fn(
            cfg, process_registry=orch._subagent_mgr,
            event_callback=orch._on_agent_activity,
        )
        code = asyncio.run(orch.run())
        _print_run_summary(orch)
        _prompt_git_finalization(orch)
    else:
        code = asyncio.run(HybridCoordinator(
            cfg, goal_text, resume=resume_flag, lineage=lineage, launcher=launcher,
        ).run())

    if observe:
        AttoswarmApp(cfg.run.run_dir).run()
    raise SystemExit(code)


@main.command("start")
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("goal", nargs=-1)
@click.option("--run-dir", default=None, help="Override run directory from config")
@click.option("--resume", "resume_flag", is_flag=True, help="Resume existing run directory state")
@click.option(
    "--continue-from",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Start a new child swarm from a previous swarm run directory",
)
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
@click.option(
    "--tasks-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Pre-defined task decomposition file (YAML or Markdown)",
)
@click.option("--trace", "trace_flag", is_flag=True, help="Enable trace collection for post-hoc analysis")
@click.option("--no-git-safety", is_flag=True, help="Disable git stash/branch safety net")
@click.option("--preview", is_flag=True, help="Review task plan before execution starts")
@click.option("--dry-run", is_flag=True, help="Decompose only — show tasks without executing")
def start_command(
    config_path: Path,
    goal: tuple[str, ...],
    run_dir: str | None,
    resume_flag: bool,
    continue_from: Path | None,
    monitor: bool,
    detach: bool,
    skip_doctor: bool,
    debug_flag: bool,
    workspace_mode: str | None,
    tasks_file: Path | None,
    trace_flag: bool,
    no_git_safety: bool,
    preview: bool,
    dry_run: bool,
) -> None:
    """Canonical user entrypoint: initialize, run, or continue a swarm."""
    cfg = load_swarm_yaml(config_path)
    launcher = _launcher_info_from_env()
    lineage = _apply_continuation(cfg, continue_from, run_dir, resume_flag) if continue_from else LineageSpec()
    if not continue_from and run_dir:
        cfg.run.run_dir = run_dir
    if debug_flag:
        cfg.run.debug = True
    if workspace_mode:
        cfg.workspace.mode = workspace_mode
    if no_git_safety:
        cfg.workspace.git_safety = False
    goal_text = " ".join(goal).strip()
    if not goal_text:
        raise click.ClickException("Goal text is required")

    # Copy tasks file into run dir for orchestrator auto-detection
    if tasks_file:
        run_path = Path(cfg.run.run_dir)
        run_path.mkdir(parents=True, exist_ok=True)
        dest = run_path / f"tasks{tasks_file.suffix}"
        shutil.copy2(tasks_file, dest)
        click.echo(f"Tasks file copied to {dest}")

    if not skip_doctor:
        rows = _doctor_rows(cfg)
        if not _print_doctor(rows):
            raise click.ClickException("Doctor check failed. Fix missing backends or use --skip-doctor")

    # Determine approval mode
    approval_mode = "dry_run" if dry_run else ("preview" if preview else "auto")

    def _build_start_cmd() -> list[str]:
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
        if continue_from:
            cmd.extend(["--continue-from", str(continue_from)])
        if debug_flag:
            cmd.append("--debug")
        if trace_flag:
            cmd.append("--trace")
        if no_git_safety:
            cmd.append("--no-git-safety")
        if approval_mode != "auto":
            cmd.extend(["--approval-mode", approval_mode])
        return cmd

    if detach:
        cmd = _build_start_cmd()
        log_path = Path(cfg.run.run_dir) / "coordinator.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_fh = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
        proc = subprocess.Popen(cmd, stdout=log_fh, stderr=log_fh)
        click.echo(f"Coordinator started in background (pid={proc.pid})")
        click.echo(f"Reattach: attocode swarm tui {cfg.run.run_dir}")
        raise SystemExit(0)

    collector = _make_trace_collector(cfg) if trace_flag else None

    # --preview without TUI has no way to approve — fall back to dry_run
    if approval_mode == "preview" and not monitor:
        click.echo("Note: --preview without --monitor defaults to --dry-run (no TUI to approve)")
        approval_mode = "dry_run"

    if not monitor:
        if cfg.workspace.mode == "shared":
            from attoswarm.coordinator.orchestrator import SwarmOrchestrator
            orch = SwarmOrchestrator(
                cfg, goal_text, resume=resume_flag,
                decompose_fn=_make_subprocess_decompose_fn(cfg),
                spawn_fn=_make_subprocess_spawn_fn(cfg, process_registry=None),
                trace_collector=collector,
                approval_mode=approval_mode,
                lineage=lineage,
                launcher=launcher,
            )
            orch._subagent_mgr._spawn_fn = _make_subprocess_spawn_fn(
                cfg, process_registry=orch._subagent_mgr,
                event_callback=orch._on_agent_activity,
            )
            code = asyncio.run(orch.run())
            _print_run_summary(orch)
            _prompt_git_finalization(orch)
        else:
            code = asyncio.run(HybridCoordinator(
                cfg, goal_text, resume=resume_flag, lineage=lineage, launcher=launcher,
            ).run())
        raise SystemExit(code)

    cmd = _build_start_cmd()
    log_path = Path(cfg.run.run_dir) / "coordinator.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
    proc = subprocess.Popen(cmd, stdout=log_fh, stderr=log_fh)
    try:
        AttoswarmApp(cfg.run.run_dir, coordinator_pid=proc.pid).run()
    finally:
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
            except Exception:
                pass
    raise SystemExit(proc.returncode or 0)


@main.command("continue")
@click.argument("parent_run_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("goal", nargs=-1)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=Path(".attocode/swarm.hybrid.yaml"),
    show_default=True,
    help="Swarm config path",
)
@click.option("--run-dir", default=None, help="Override child run directory")
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
@click.option("--trace", "trace_flag", is_flag=True, help="Enable trace collection for post-hoc analysis")
@click.option("--no-git-safety", is_flag=True, help="Disable git stash/branch safety net")
@click.option("--preview", is_flag=True, help="Review task plan before execution starts")
@click.option("--dry-run", is_flag=True, help="Decompose only — show tasks without executing")
@click.pass_context
def continue_command(
    ctx: click.Context,
    parent_run_dir: Path,
    goal: tuple[str, ...],
    config_path: Path,
    run_dir: str | None,
    monitor: bool,
    detach: bool,
    skip_doctor: bool,
    debug_flag: bool,
    workspace_mode: str | None,
    trace_flag: bool,
    no_git_safety: bool,
    preview: bool,
    dry_run: bool,
) -> None:
    """Start a new child swarm on top of a previous swarm's output."""
    ctx.invoke(
        start_command,
        config_path=config_path,
        goal=goal,
        run_dir=run_dir,
        resume_flag=False,
        continue_from=parent_run_dir,
        monitor=monitor,
        detach=detach,
        skip_doctor=skip_doctor,
        debug_flag=debug_flag,
        workspace_mode=workspace_mode,
        tasks_file=None,
        trace_flag=trace_flag,
        no_git_safety=no_git_safety,
        preview=preview,
        dry_run=dry_run,
    )


@main.command("tui")
@click.argument("run_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
def tui_command(run_dir: Path) -> None:
    """Open TUI dashboard for an existing run directory."""
    AttoswarmApp(str(run_dir)).run()


@main.command("resume")
@click.argument("run_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--workspace-mode",
    type=click.Choice(["shared", "worktree"]),
    default=None,
    help="Override workspace mode: 'shared' (AoT+OCC) or 'worktree' (legacy)",
)
@click.option("--trace", "trace_flag", is_flag=True, help="Enable trace collection for post-hoc analysis")
def resume_command(run_dir: Path, workspace_mode: str | None, trace_flag: bool) -> None:
    """Resume execution from an existing run directory."""
    manifest_path = run_dir / "swarm.manifest.json"
    state_path = run_dir / "swarm.state.json"
    if not manifest_path.exists() and not state_path.exists():
        raise click.ClickException(
            f"No manifest or state found in {run_dir}. Is this a valid run directory?"
        )

    # Try config from run dir, then parent, then defaults
    cfg_path = run_dir / "swarm.yaml"
    if not cfg_path.exists():
        # Check parent dirs for the original config
        for candidate in [
            run_dir.parent.parent / ".attocode" / "swarm.hybrid.yaml",
            Path.cwd() / ".attocode" / "swarm.hybrid.yaml",
        ]:
            if candidate.exists():
                cfg_path = candidate
                break
    cfg = load_swarm_yaml(cfg_path) if cfg_path.exists() else SwarmYamlConfig()
    cfg.run.run_dir = str(run_dir)
    if workspace_mode:
        cfg.workspace.mode = workspace_mode

    # Read goal from manifest or state
    manifest_data = read_json(manifest_path, default={})
    goal = manifest_data.get("goal", "")
    if not goal:
        state_data = read_json(state_path, default={})
        goal = state_data.get("goal", "Resume swarm run")

    collector = _make_trace_collector(cfg) if trace_flag else None
    launcher = _launcher_info_from_env()

    if cfg.workspace.mode == "shared":
        from attoswarm.coordinator.orchestrator import SwarmOrchestrator
        code = asyncio.run(SwarmOrchestrator(
            cfg, str(goal), resume=True,
            decompose_fn=_make_subprocess_decompose_fn(cfg),
            spawn_fn=_make_subprocess_spawn_fn(cfg),
            trace_collector=collector,
            launcher=launcher,
        ).run())
    else:
        code = asyncio.run(HybridCoordinator(cfg, str(goal), resume=True, launcher=launcher).run())
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


@main.command("research")
@click.argument("goal", type=str)
@click.option("--eval-command", "-e", type=str, required=True, help="Shell command that outputs numeric metric")
@click.option("--target-files", "-t", type=str, multiple=True, help="Files the agent should modify")
@click.option("--max-experiments", type=int, default=100, help="Maximum number of experiments")
@click.option("--experiment-timeout", type=float, default=300.0, help="Timeout per experiment (seconds)")
@click.option("--metric-direction", type=click.Choice(["maximize", "minimize"]), default="maximize")
@click.option("--metric-name", type=str, default="score", help="Name of the metric being optimized")
@click.option("--max-cost", type=float, default=50.0, help="Total cost budget (USD)")
@click.option("--resume", type=str, default="", help="Resume a previous research run by ID")
@click.option("--config", "config_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None)
@click.option("--db", type=click.Path(path_type=Path), default=None, help="Path to experiment database")
@click.option("--working-dir", "-w", type=click.Path(exists=True, path_type=Path), default=None)
def research_command(
    goal: str,
    eval_command: str,
    target_files: tuple[str, ...],
    max_experiments: int,
    experiment_timeout: float,
    metric_direction: str,
    metric_name: str,
    max_cost: float,
    resume: str,
    config_path: Path | None,
    db: Path | None,
    working_dir: Path | None,
) -> None:
    """Run iterative research experiments with numeric evaluation.

    The agent will repeatedly modify code, evaluate using --eval-command,
    and accept/reject changes based on whether the metric improves.

    Example:
        attoswarm research "improve test pass rate" -e "pytest --tb=no -q | tail -1"
    """
    from attoswarm.research.config import ResearchConfig as _ResearchConfig
    from attoswarm.research.research_orchestrator import ResearchOrchestrator

    wd = str(working_dir) if working_dir else "."
    run_dir = str(db.parent) if db else ".agent/research"

    research_cfg = _ResearchConfig(
        metric_name=metric_name,
        metric_direction=metric_direction,
        experiment_timeout_seconds=experiment_timeout,
        total_max_experiments=max_experiments,
        total_max_cost_usd=max_cost,
        eval_command=eval_command,
        target_files=list(target_files),
        working_dir=wd,
        run_dir=run_dir,
    )

    # Load swarm config for spawn_fn if available
    spawn_fn = None
    if config_path:
        cfg = load_swarm_yaml(config_path)
        spawn_fn = _make_subprocess_spawn_fn(cfg)

    orchestrator = ResearchOrchestrator(
        config=research_cfg,
        goal=goal,
        spawn_fn=spawn_fn,
    )

    click.echo(f"Starting research: {goal[:80]}")
    click.echo(f"Eval: {eval_command}")
    click.echo(f"Direction: {metric_direction} | Max experiments: {max_experiments} | Budget: ${max_cost}")

    state = asyncio.run(orchestrator.run(resume_run_id=resume))

    # Print scoreboard
    scoreboard = orchestrator.get_scoreboard()
    click.echo("\n" + "=" * 60)
    click.echo(scoreboard.render_summary())
    click.echo("\n" + scoreboard.render_table())
    click.echo("\n" + scoreboard.render_trend())

    raise SystemExit(0 if state.status == "completed" else 1)


def _detect_first_available_backend() -> str:
    """Auto-detect the first available backend CLI."""
    for name in ("claude", "codex", "aider", "attocode"):
        if shutil.which(name):
            return name
    return "claude"  # fallback


@main.command("quick")
@click.argument("goal", nargs=-1, required=True)
@click.option("--budget", type=float, default=10.0, help="Cost cap in USD (default $10)")
@click.option("--workers", type=int, default=2, help="Number of parallel workers (default 2)")
@click.option("--backend", type=str, default=None, help="Backend CLI (auto-detect if omitted)")
@click.option("--no-git-safety", is_flag=True, help="Disable git stash/branch safety")
@click.option("--trace", "trace_flag", is_flag=True, help="Enable trace collection")
@click.option("--monitor/--no-monitor", default=True, help="Open TUI dashboard (default: yes)")
@click.option("--detach", is_flag=True, help="Start in background and print reattach command")
@click.option("--preview", is_flag=True, help="Review task plan before execution starts")
@click.option("--dry-run", is_flag=True, help="Decompose only — show tasks without executing")
@click.option("--resume", "resume_flag", is_flag=True, help="Resume previous run (preserve artifacts)")
def quick_command(
    goal: tuple[str, ...],
    budget: float,
    workers: int,
    backend: str | None,
    no_git_safety: bool,
    trace_flag: bool,
    monitor: bool,
    detach: bool,
    preview: bool,
    dry_run: bool,
    resume_flag: bool,
) -> None:
    """Run swarm without a config file — sensible defaults.

    Examples:
        attoswarm quick "implement feature X"
        attoswarm quick --budget 5 --workers 3 "fix all tests"
        attoswarm quick --preview "add user auth"
        attoswarm quick --dry-run --no-monitor "refactor module X"
    """
    from attoswarm.config.schema import (
        BudgetConfig,
        OrchestrationConfig,
        RunConfig,
        WorkspaceConfig,
    )

    goal_text = " ".join(goal).strip()
    if not goal_text:
        raise click.ClickException("Goal text is required")

    if backend is None:
        backend = _detect_first_available_backend()
        click.echo(f"Auto-detected backend: {backend}")

    if not shutil.which(backend):
        raise click.ClickException(f"Backend '{backend}' not found in PATH")

    workers = max(1, min(workers, 8))

    # Build synthetic config
    orch_role = RoleConfig(
        role_id="orchestrator",
        role_type="orchestrator",
        backend=backend,
        model="",
        count=1,
        task_kinds=["analysis", "design"],
    )
    worker_role = RoleConfig(
        role_id="worker",
        role_type="worker",
        backend=backend,
        model="",
        count=workers,
        write_access=True,
        workspace_mode="shared_ro",
        task_kinds=["implement", "test", "integrate"],
    )

    cfg = SwarmYamlConfig(
        version=1,
        run=RunConfig(
            name="quick-run",
            working_dir=".",
            run_dir=".agent/hybrid-swarm",
            max_runtime_seconds=600,
        ),
        roles=[orch_role, worker_role],
        budget=BudgetConfig(
            max_tokens=5_000_000,
            max_cost_usd=budget,
        ),
        orchestration=OrchestrationConfig(
            decomposition="llm",
            max_tasks=20,
            max_depth=3,
        ),
        workspace=WorkspaceConfig(
            mode="shared",
            max_concurrent_writers=workers,
            git_safety=not no_git_safety,
        ),
    )

    click.echo(f"Quick start: {workers} workers, ${budget:.0f} budget, backend={backend}")
    click.echo(f"Goal: {goal_text[:100]}")

    # Save config for resume support
    run_path = Path(cfg.run.run_dir)
    run_path.mkdir(parents=True, exist_ok=True)
    config_path = run_path / "swarm.yaml"
    save_swarm_yaml(cfg, config_path)

    # Determine approval mode
    approval_mode = "dry_run" if dry_run else ("preview" if preview else "auto")

    if monitor and not dry_run:
        # Subprocess + TUI pattern (same as start_command)
        cmd = [sys.executable, "-m", "attoswarm", "run", str(config_path), goal_text]
        if trace_flag:
            cmd.append("--trace")
        if no_git_safety:
            cmd.append("--no-git-safety")
        if approval_mode != "auto":
            cmd.extend(["--approval-mode", approval_mode])
        if resume_flag:
            cmd.append("--resume")
        log_path = run_path / "coordinator.log"
        log_fh = open(log_path, "a", encoding="utf-8")  # noqa: SIM115

        if detach:
            proc = subprocess.Popen(cmd, stdout=log_fh, stderr=log_fh)
            click.echo(f"Coordinator started in background (pid={proc.pid})")
            click.echo(f"Reattach: attocode swarm tui {cfg.run.run_dir}")
            raise SystemExit(0)

        proc = subprocess.Popen(cmd, stdout=log_fh, stderr=log_fh)
        try:
            AttoswarmApp(cfg.run.run_dir, coordinator_pid=proc.pid).run()
        finally:
            if proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
                except Exception:
                    pass
        raise SystemExit(proc.returncode or 0)

    # Inline execution (--no-monitor or --dry-run)
    # --preview without TUI has no way to approve — fall back to dry_run
    if approval_mode == "preview" and not monitor:
        click.echo("Note: --preview without --monitor defaults to --dry-run (no TUI to approve)")
        approval_mode = "dry_run"

    collector = _make_trace_collector(cfg) if trace_flag else None
    launcher = _launcher_info_from_env()

    from attoswarm.coordinator.orchestrator import SwarmOrchestrator
    orch = SwarmOrchestrator(
        cfg, goal_text,
        resume=resume_flag,
        decompose_fn=_make_subprocess_decompose_fn(cfg),
        spawn_fn=_make_subprocess_spawn_fn(cfg, process_registry=None),
        trace_collector=collector,
        approval_mode=approval_mode,
        launcher=launcher,
    )
    orch._subagent_mgr._spawn_fn = _make_subprocess_spawn_fn(
        cfg, process_registry=orch._subagent_mgr,
        event_callback=orch._on_agent_activity,
    )

    code = asyncio.run(orch.run())

    # Dry-run: print decomposed task list and exit
    if dry_run:
        state = read_json(Path(cfg.run.run_dir) / "swarm.state.json", default={})
        tasks = state.get("dag", {}).get("nodes", [])
        click.echo(f"\nDecomposed into {len(tasks)} tasks:")
        for t in tasks:
            deps = ", ".join(t.get("deps", []) or [])
            click.echo(
                f"  [{t.get('task_kind', '')}] {t.get('task_id', '')}: {t.get('title', '')}"
                + (f" (deps: {deps})" if deps else "")
            )
        click.echo(f"\nReview with: attocode swarm tui {cfg.run.run_dir}")
        raise SystemExit(0)

    # Print summary
    summary = orch.aot_graph.summary()
    click.echo(f"\nDone: {summary.get('done', 0)}/{summary.get('total', 0)} tasks, ${orch.budget.used_cost_usd:.2f}")

    # Git safety finalization
    if orch._git_safety and orch._git_safety.state.is_git_repo:
        click.echo(f"\nSwarm branch: {orch._git_safety.state.swarm_branch}")
        if no_git_safety:
            pass
        else:
            choice = click.prompt(
                "Git finalization",
                type=click.Choice(["merge", "keep", "discard"]),
                default="keep",
            )
            asyncio.run(orch._git_safety.finalize(choice))
            click.echo(f"Git finalized: {choice}")

    raise SystemExit(0 if code else 1)


@main.command("doctor")
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def doctor_command(config_path: Path) -> None:
    """Validate backend binaries and basic runtime readiness."""
    cfg = load_swarm_yaml(config_path)
    ok = _print_doctor(_doctor_rows(cfg))
    raise SystemExit(0 if ok else 1)



@main.command("init")
@click.argument("target_dir", type=click.Path(path_type=Path), required=False)
@click.option("--profile", type=click.Choice(["2cc", "cc-codex", "cc-aider", "2codex", "codex-cc", "full-team", "custom"]), default=None)
@click.option("--mode", type=click.Choice(["minimal", "demo"]), default=None)
def init_command(target_dir: Path | None, profile: str | None, mode: str | None) -> None:
    """Interactive starter generator for hybrid swarm."""
    import yaml as _yaml

    base = target_dir or Path.cwd()
    attocode_dir = base / ".attocode"
    attocode_dir.mkdir(parents=True, exist_ok=True)

    # --- Step 1: Context detection ---
    has_repo = (base / ".git").exists() or (base / "pyproject.toml").exists() or (base / "package.json").exists()
    click.echo(f"Detected context: {'existing repository' if has_repo else 'fresh directory'} at {base}")
    setup_target = click.prompt(
        "Select setup target",
        type=click.Choice(["existing-repo", "demo-project"]),
        default="existing-repo" if has_repo else "demo-project",
    )

    # --- Step 2: Profile selection (enhanced) ---
    if profile is None:
        click.echo("\nBackend profiles:")
        click.echo("  [1] 2cc        - Two Claude Code agents (orchestrator + workers)")
        click.echo("  [2] cc-codex   - Claude orchestrator + Codex workers (fast + cheap)")
        click.echo("  [3] cc-aider   - Claude orchestrator + Aider workers")
        click.echo("  [4] 2codex     - Pure Codex (orchestrator + workers, no Anthropic key needed)")
        click.echo("  [5] codex-cc   - Codex orchestrator + Claude workers")
        click.echo("  [6] full-team  - Orchestrator + workers + judge + merger (quality-focused)")
        click.echo("  [7] custom     - Configure each role manually")
        profile = click.prompt(
            "Select backend profile",
            type=click.Choice(["2cc", "cc-codex", "cc-aider", "2codex", "codex-cc", "full-team", "custom"]),
            default="2cc",
        )

    # --- Step 3: Worker count ---
    worker_count = click.prompt("How many parallel workers?", type=int, default=2)
    worker_count = max(1, min(worker_count, 10))

    # --- Step 4: Budget ---
    click.echo("\nCost cap per run (USD):")
    click.echo("  [1] $5    - Quick tasks")
    click.echo("  [2] $25   - Standard")
    click.echo("  [3] $50   - Large features")
    click.echo("  [4] Custom amount")
    budget_choice = click.prompt("Select cost cap", type=click.Choice(["1", "2", "3", "4"]), default="2")
    budget_map = {"1": 5.0, "2": 25.0, "3": 50.0}
    if budget_choice in budget_map:
        cost_cap = budget_map[budget_choice]
    else:
        cost_cap = click.prompt("Enter cost cap (USD)", type=float, default=25.0)

    # --- Step 5: Max runtime per task ---
    click.echo("\nMax runtime per task (seconds):")
    click.echo("  [1] 120  - Fast (2 min)")
    click.echo("  [2] 300  - Standard (5 min)")
    click.echo("  [3] 600  - Long (10 min)")
    click.echo("  [4] Custom")
    runtime_choice = click.prompt("Select max runtime", type=click.Choice(["1", "2", "3", "4"]), default="2")
    runtime_map = {"1": 120, "2": 300, "3": 600}
    if runtime_choice in runtime_map:
        task_max_duration = runtime_map[runtime_choice]
    else:
        task_max_duration = click.prompt("Enter max runtime (seconds)", type=int, default=300)

    # --- Step 6: Workspace mode ---
    click.echo("\nWorkspace isolation:")
    click.echo("  [1] shared   - Faster, agents coordinate via file claims")
    click.echo("  [2] worktree - Safer, each agent gets isolated git worktree")
    workspace_mode = click.prompt(
        "Select workspace mode",
        type=click.Choice(["shared", "worktree"]),
        default="shared",
    )

    # --- Step 7: Quality level ---
    click.echo("\nQuality gates:")
    click.echo("  [1] relaxed  - No judges, auto-apply all results")
    click.echo("  [2] standard - Quality threshold scoring")
    click.echo("  [3] strict   - Judge + critic roles review all outputs")
    quality_level = click.prompt(
        "Select quality level",
        type=click.Choice(["relaxed", "standard", "strict"]),
        default="standard",
    )

    # --- Step 8: Advanced settings ---
    decomposition = "llm"
    max_tasks = 20
    max_depth = 3
    retry_attempts = 2
    quality_threshold = 0.75
    custom_instructions = ""

    if click.confirm("\nConfigure advanced settings?", default=False):
        decomposition = click.prompt(
            "Decomposition strategy",
            type=click.Choice(["llm", "parallel", "heuristic", "fast", "file"]),
            default="llm",
        )
        max_tasks = click.prompt("Max tasks", type=int, default=20)
        max_depth = click.prompt("Max DAG depth", type=int, default=3)
        retry_attempts = click.prompt("Retry attempts per task", type=int, default=2)
        quality_threshold = click.prompt("Quality threshold (0.0-1.0)", type=float, default=0.75)
        if click.confirm("Add custom orchestrator instructions?", default=False):
            click.echo("Enter instructions (empty line to finish):")
            lines: list[str] = []
            while True:
                line = click.prompt("", default="", prompt_suffix="")
                if not line:
                    break
                lines.append(line)
            custom_instructions = "\n".join(lines)

    # --- Step 9: Output mode ---
    if mode is None:
        mode = click.prompt(
            "Select output mode",
            type=click.Choice(["minimal", "demo"]),
            default="minimal" if setup_target == "existing-repo" else "demo",
        )

    # --- Build roles based on profile ---
    ws_mode = "worktree" if workspace_mode == "worktree" else "shared_ro"

    def _worker_role(role_id: str, backend: str, model: str, count: int, task_kinds: list[str]) -> dict[str, Any]:
        return {
            "role_id": role_id,
            "role_type": "worker",
            "backend": backend,
            "model": model,
            "count": count,
            "write_access": True,
            "workspace_mode": ws_mode,
            "task_kinds": task_kinds,
        }

    # Orchestrator backend: codex for codex-led profiles, claude otherwise
    orch_backend = "codex" if profile in ("2codex", "codex-cc") else "claude"
    orch_role: dict[str, Any] = {
        "role_id": "orchestrator",
        "role_type": "orchestrator",
        "backend": orch_backend,
        "model": "",
        "count": 1,
        "task_kinds": ["analysis", "design"],
    }

    impl_kinds = ["implement", "test", "integrate"]

    if profile == "2cc":
        roles = [orch_role, _worker_role("impl", "claude", "", worker_count, impl_kinds)]
    elif profile == "cc-codex":
        # Split workers: half claude, half codex
        if worker_count <= 1:
            # Single worker: use primary backend only
            roles = [orch_role, _worker_role("impl-codex", "codex", "", 1, impl_kinds)]
        else:
            codex_count = worker_count // 2
            claude_count = worker_count - codex_count
            roles = [
                orch_role,
                _worker_role("impl-claude", "claude", "", claude_count, impl_kinds),
                _worker_role("impl-codex", "codex", "", codex_count, impl_kinds),
            ]
    elif profile == "2codex":
        roles = [orch_role, _worker_role("impl", "codex", "", worker_count, impl_kinds)]
    elif profile == "codex-cc":
        # Codex orchestrator + Claude workers
        if worker_count <= 1:
            roles = [orch_role, _worker_role("impl-claude", "claude", "", 1, impl_kinds)]
        else:
            claude_count = worker_count // 2
            codex_count = worker_count - claude_count
            roles = [
                orch_role,
                _worker_role("impl-claude", "claude", "", claude_count, impl_kinds),
                _worker_role("impl-codex", "codex", "", codex_count, impl_kinds),
            ]
    elif profile == "cc-aider":
        if worker_count <= 1:
            # Single worker: use primary backend only
            roles = [orch_role, _worker_role("impl-aider", "aider", "", 1, impl_kinds)]
        else:
            aider_count = worker_count // 2
            claude_count = worker_count - aider_count
            roles = [
                orch_role,
                _worker_role("impl-claude", "claude", "", claude_count, impl_kinds),
                _worker_role("impl-aider", "aider", "", aider_count, impl_kinds),
            ]
    elif profile == "full-team":
        roles = [
            orch_role,
            _worker_role("impl", "claude", "", worker_count, impl_kinds),
            {
                "role_id": "judge",
                "role_type": "judge",
                "backend": "claude",
                "model": "",
                "count": 1,
                "task_kinds": ["judge", "critic"],
            },
            {
                "role_id": "merger",
                "role_type": "merger",
                "backend": "claude",
                "model": "",
                "count": 1,
                "write_access": True,
                "workspace_mode": ws_mode,
                "task_kinds": ["merge", "integrate"],
            },
        ]
    else:
        # custom: bare config, user fills in roles manually
        roles = []

    # --- Build config dict ---
    config: dict[str, Any] = {
        "version": 1,
        "run": {
            "working_dir": ".",
            "run_dir": ".agent/hybrid-swarm",
            "poll_interval_ms": 250,
            "max_runtime_seconds": task_max_duration * max(max_tasks, 5),
        },
        "roles": roles,
        "budget": {
            "max_cost_usd": cost_cap,
        },
        "orchestration": {
            "decomposition": decomposition,
            "max_tasks": max_tasks,
            "max_depth": max_depth,
        },
        "workspace": {
            "mode": workspace_mode,
        },
        "watchdog": {
            "task_max_duration_seconds": float(task_max_duration),
        },
        "retries": {
            "max_task_attempts": retry_attempts,
        },
    }

    if custom_instructions:
        config["orchestration"]["custom_instructions"] = custom_instructions

    # Quality-level-specific settings
    if quality_level == "relaxed":
        config["merge"] = {
            "quality_threshold": 0.0,
            "auto_apply_non_conflicting": True,
        }
    elif quality_level == "standard":
        config["merge"] = {
            "quality_threshold": quality_threshold,
            "auto_apply_non_conflicting": True,
        }
    elif quality_level == "strict":
        config["merge"] = {
            "quality_threshold": quality_threshold,
            "judge_policy": "quorum",
            "auto_apply_non_conflicting": False,
        }
        # Ensure judge role exists for strict mode even if profile didn't include it
        role_ids = {r["role_id"] for r in roles}
        if "judge" not in role_ids and profile != "custom":
            roles.append({
                "role_id": "judge",
                "role_type": "judge",
                "backend": "claude",
                "model": "",
                "count": 1,
                "task_kinds": ["judge", "critic"],
            })

    # --- Write YAML ---
    path = attocode_dir / "swarm.hybrid.yaml"
    yaml_text = _yaml.dump(config, default_flow_style=False, sort_keys=False, allow_unicode=True)
    path.write_text(yaml_text, encoding="utf-8")
    click.echo(f"\nCreated {path}")

    # --- Optional task decomposition file ---
    if click.confirm("\nCreate a task decomposition file? (for manual task control)", default=False):
        _interactive_task_builder(base, cfg=config)

    # --- Demo scaffold ---
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


def _interactive_task_builder(base_dir: Path, cfg: dict[str, Any]) -> None:
    """Guide the user through creating a task decomposition file."""
    import yaml as _yaml

    _has_api_key = bool(
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("OPENROUTER_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
    )

    click.echo("\nHow would you like to create tasks?")
    click.echo("  [1] Manual - define tasks one by one")
    if _has_api_key:
        click.echo("  [2] AI-assisted - describe your goal and let AI decompose it")
    choices = ["1", "2"] if _has_api_key else ["1"]
    method = click.prompt("Select method", type=click.Choice(choices), default="1")

    if method == "2" and _has_api_key:
        tasks = _ai_assisted_task_builder(base_dir, cfg)
    else:
        tasks = _manual_task_builder()

    if not tasks:
        click.echo("No tasks created.")
        return

    # Choose output format
    click.echo("\nSave as:")
    click.echo("  [1] YAML (tasks/tasks.yaml) - structured, machine-friendly")
    click.echo("  [2] Markdown (tasks/tasks.md) - human-friendly, easy to edit")
    fmt = click.prompt("Select format", type=click.Choice(["1", "2"]), default="1")

    tasks_dir = base_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    if fmt == "1":
        out_path = tasks_dir / "tasks.yaml"
        yaml_text = _yaml.dump(
            {"tasks": tasks},
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
        out_path.write_text(yaml_text, encoding="utf-8")
    else:
        out_path = tasks_dir / "tasks.md"
        md_lines: list[str] = []
        for t in tasks:
            md_lines.append(f"## {t['task_id']}: {t['title']}")
            md_lines.append(f"Kind: {t.get('task_kind', 'implement')}")
            if t.get("role_hint"):
                md_lines.append(f"Role: {t['role_hint']}")
            if t.get("deps"):
                md_lines.append(f"Depends on: {', '.join(t['deps'])}")
            if t.get("target_files"):
                md_lines.append(f"Target files: {', '.join(t['target_files'])}")
            md_lines.append("")
            md_lines.append(t.get("description", ""))
            md_lines.append("")
        out_path.write_text("\n".join(md_lines), encoding="utf-8")

    click.echo(f"Created {out_path}")
    click.echo(f"Use with: attocode swarm start <config> --tasks-file {out_path} \"<goal>\"")


def _manual_task_builder() -> list[dict[str, Any]]:
    """Interactively define tasks one by one."""
    tasks: list[dict[str, Any]] = []
    task_num = 0

    while True:
        task_num += 1
        default_id = f"task-{task_num}"
        click.echo(f"\n--- Task {task_num} ---")
        task_id = click.prompt("Task ID", default=default_id)
        title = click.prompt("Title")

        click.echo("Description (empty line to finish):")
        desc_lines: list[str] = []
        while True:
            line = click.prompt("", default="", prompt_suffix="")
            if not line:
                break
            desc_lines.append(line)
        description = "\n".join(desc_lines)

        task_kind = click.prompt(
            "Kind",
            type=click.Choice(["implement", "test", "integrate", "analysis", "design"]),
            default="implement",
        )

        target_files_str = click.prompt("Target files (comma-separated, optional)", default="")
        target_files = [f.strip() for f in target_files_str.split(",") if f.strip()] if target_files_str else []

        # Show existing task IDs for dep selection
        existing_ids = [t["task_id"] for t in tasks]
        deps: list[str] = []
        if existing_ids:
            deps_str = click.prompt(
                f"Dependencies (from: {', '.join(existing_ids)}, comma-separated, optional)",
                default="",
            )
            deps = [d.strip() for d in deps_str.split(",") if d.strip()] if deps_str else []

        tasks.append({
            "task_id": task_id,
            "title": title,
            "description": description,
            "task_kind": task_kind,
            "target_files": target_files,
            "deps": deps,
        })

        if not click.confirm("Add another task?", default=True):
            break

    return tasks


def _ai_assisted_task_builder(base_dir: Path, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Use LLM to decompose a goal into tasks."""
    click.echo("\nDescribe your goal (empty line to finish):")
    goal_lines: list[str] = []
    while True:
        line = click.prompt("", default="", prompt_suffix="")
        if not line:
            break
        goal_lines.append(line)
    goal_text = "\n".join(goal_lines)
    if not goal_text.strip():
        click.echo("No goal provided.")
        return []

    # Try to load config and call backend
    try:
        from attoswarm.coordinator.decompose import build_decompose_prompt, classify_goal_complexity
        from attoswarm.coordinator.task_parser import extract_json_array

        # Determine backend from roles config
        roles = cfg.get("roles", [])
        orch_role = next((r for r in roles if r.get("role_type") == "orchestrator"), None)
        if orch_role:
            backend = orch_role.get("backend", "claude")
            model = orch_role.get("model", "")
        elif roles:
            backend = roles[0].get("backend", "claude")
            model = roles[0].get("model", "")
        else:
            backend = "claude"
            model = ""

        complexity = classify_goal_complexity(goal_text)
        prompt = build_decompose_prompt(goal_text, complexity=complexity)
        cmd = _build_backend_cmd(backend, model, prompt)

        clean_env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV_VARS}
        click.echo("Calling AI to decompose goal...")
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(base_dir),
            env=clean_env,
        )

        if proc.returncode != 0:
            raise RuntimeError(f"Backend exited with code {proc.returncode}: {proc.stderr[:300]}")

        raw_tasks = extract_json_array(proc.stdout)

        # Display proposed tasks
        click.echo(f"\nProposed {len(raw_tasks)} tasks:")
        for i, t in enumerate(raw_tasks, 1):
            deps_str = f" (deps: {', '.join(t.get('deps', []))})" if t.get("deps") else ""
            click.echo(f"  {i}. [{t.get('task_kind', 'implement')}] {t.get('task_id', '?')}: {t.get('title', '?')}{deps_str}")

        choice = click.prompt("Accept these tasks?", type=click.Choice(["y", "edit", "n"]), default="y")
        if choice == "y":
            return raw_tasks
        elif choice == "edit":
            click.echo("Tasks saved as draft. Edit the file and re-run.")
            return raw_tasks
        else:
            click.echo("Falling back to manual builder.")
            return _manual_task_builder()

    except Exception as exc:
        click.echo(f"AI decomposition failed: {exc}")
        click.echo("Falling back to manual builder.")
        return _manual_task_builder()


if __name__ == "__main__":
    main()
