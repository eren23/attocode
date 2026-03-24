"""OpenCode CLI subprocess spawner for swarm workers.

Spawns ``opencode run`` instances with ``--format json`` for structured JSONL
output.  Parses ``step_start``, ``text``, and ``step_finish`` events into a
:class:`SpawnResult`.

Security: Uses ``asyncio.create_subprocess_exec`` (not shell=True) to avoid
command injection.  All arguments are passed as a safe argv list.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import time
from typing import Any

from attocode.integrations.swarm.types import (
    SpawnResult,
    SwarmTask,
    SwarmWorkerSpec,
    ToolAction,
)

logger = logging.getLogger(__name__)


def _find_opencode_binary() -> str | None:
    """Locate the ``opencode`` CLI binary on PATH."""
    return shutil.which("opencode")


# Patterns that indicate a test runner command
_TEST_COMMAND_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bpytest\b"),
    re.compile(r"\bnpm\s+test\b"),
    re.compile(r"\bgo\s+test\b"),
    re.compile(r"\bcargo\s+test\b"),
    re.compile(r"\bjest\b"),
    re.compile(r"\bvitest\b"),
    re.compile(r"\bmocha\b"),
    re.compile(r"\brspec\b"),
    re.compile(r"\bpython\s+-m\s+(?:pytest|unittest)\b"),
    re.compile(r"\bmake\s+test\b"),
]

# Regex for fenced bash blocks: ```bash\n<cmd>\n```\n<output>
_BASH_BLOCK_RE = re.compile(
    r"```(?:bash|sh|shell|console)?\s*\n(.+?)\n```"
    r"(?:\s*\n((?:(?!```)[\s\S])*?)(?=\n```|\n##|\Z))?",
    re.MULTILINE,
)

# Regex for $ command patterns: $ <cmd>\n<output>
_DOLLAR_CMD_RE = re.compile(
    r"^\$\s+(.+?)$\n((?:(?!\$\s).*\n)*)",
    re.MULTILINE,
)

# Regex for file operations in narrative
_FILE_OP_RE = re.compile(
    r"(?:Created|Wrote|Modified|Edited|Updated|Deleted)\s+(?:file:?\s+)?`?([^\s`,]+\.\w+)`?",
    re.IGNORECASE,
)


def _is_test_command(cmd: str) -> bool:
    return any(p.search(cmd) for p in _TEST_COMMAND_PATTERNS)


def _extract_tool_actions(result_text: str) -> list[ToolAction]:
    """Extract structured tool actions from subagent output text."""
    actions: list[ToolAction] = []
    seen_commands: set[str] = set()

    for match in _BASH_BLOCK_RE.finditer(result_text):
        cmd = match.group(1).strip()
        output = (match.group(2) or "").strip()
        if cmd and cmd not in seen_commands:
            seen_commands.add(cmd)
            actions.append(ToolAction(
                tool_name="Bash",
                arguments_summary=cmd[:300],
                output_summary=output[:1000],
                is_test_execution=_is_test_command(cmd),
            ))

    for match in _DOLLAR_CMD_RE.finditer(result_text):
        cmd = match.group(1).strip()
        output = match.group(2).strip()
        if cmd and cmd not in seen_commands:
            seen_commands.add(cmd)
            actions.append(ToolAction(
                tool_name="Bash",
                arguments_summary=cmd[:300],
                output_summary=output[:1000],
                is_test_execution=_is_test_command(cmd),
            ))

    for match in _FILE_OP_RE.finditer(result_text):
        fpath = match.group(1).strip("'\"")
        op_text = match.group(0).strip()
        actions.append(ToolAction(
            tool_name="Write" if "creat" in op_text.lower() else "Edit",
            arguments_summary=fpath[:300],
            output_summary=op_text[:200],
        ))

    return actions


def _extract_test_output(actions: list[ToolAction]) -> str | None:
    parts: list[str] = []
    for a in actions:
        if a.is_test_execution and a.output_summary:
            parts.append(f"$ {a.arguments_summary}\n{a.output_summary}")
    if not parts:
        return None
    combined = "\n\n".join(parts)
    return combined[:5000]


def _extract_files_modified(output: str) -> list[str]:
    files: list[str] = []
    patterns = [
        re.compile(r"(?:created|wrote|modified|edited|updated)\s+(?:file:?\s+)?([^\s,]+\.\w+)", re.IGNORECASE),
        re.compile(r"(?:File|Path):\s*([^\s,]+\.\w+)"),
    ]
    for pattern in patterns:
        for match in pattern.finditer(output):
            path = match.group(1).strip("'\"")
            if path and path not in files:
                files.append(path)
    return files


def _build_opencode_args(
    task: SwarmTask,
    worker: SwarmWorkerSpec,
    system_prompt: str,
    *,
    working_dir: str = "",
) -> list[str]:
    """Build the CLI argument list for an ``opencode run`` subprocess.

    Uses exec-style argv list (no shell interpolation) to prevent injection.
    """
    opencode_bin = _find_opencode_binary()
    if not opencode_bin:
        raise FileNotFoundError(
            "opencode CLI binary not found on PATH. "
            "Install it with: brew install opencode-ai/tap/opencode"
        )

    prompt_parts: list[str] = [system_prompt, "", task.description]

    if task.target_files:
        prompt_parts.append(
            f"\n\nTarget files: {', '.join(task.target_files)}"
        )
    if task.read_files:
        prompt_parts.append(
            f"\nReference files: {', '.join(task.read_files)}"
        )
    if task.dependency_context:
        prompt_parts.append(
            f"\n\nContext from completed dependencies:\n{task.dependency_context}"
        )
    if task.retry_context:
        rc = task.retry_context
        prompt_parts.append(
            f"\n\nThis is retry attempt {rc.attempt + 1}."
        )
        if rc.previous_feedback:
            prompt_parts.append(
                f"Previous feedback: {rc.previous_feedback[:1000]}"
            )

    full_prompt = "\n".join(prompt_parts)

    args: list[str] = [opencode_bin, "run"]

    if worker.model:
        args.extend(["--model", worker.model])

    args.extend(["--format", "json"])
    args.append(full_prompt)

    return args


def _parse_opencode_output(raw: str) -> SpawnResult:
    """Parse the JSONL output from ``opencode run --format json``.

    Events:
    - ``step_start``: new LLM call beginning
    - ``text``: content chunks (``part.text``)
    - ``step_finish``: call completed with token/cost data
    """
    if not raw.strip():
        return SpawnResult(
            success=False,
            output="Empty output from OpenCode worker",
        )

    text_parts: list[str] = []
    total_input = 0
    total_output = 0
    total_reasoning = 0
    total_cost = 0.0

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except (ValueError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue

        event_type = data.get("type", "")
        part = data.get("part", {})
        if not isinstance(part, dict):
            continue

        if event_type == "text":
            text = part.get("text", "")
            if text:
                text_parts.append(text)

        elif event_type == "step_finish":
            tokens = part.get("tokens", {})
            if isinstance(tokens, dict):
                total_input += tokens.get("input", 0)
                total_output += tokens.get("output", 0)
                total_reasoning += tokens.get("reasoning", 0)
            cost = part.get("cost")
            if isinstance(cost, (int, float)):
                total_cost += float(cost)

    result_text = "".join(text_parts)
    total_tokens = total_input + total_output + total_reasoning

    if not result_text:
        return SpawnResult(
            success=False,
            output=f"No text output from OpenCode worker. Raw: {raw[:500]}",
        )

    files_modified = _extract_files_modified(result_text)
    tool_actions = _extract_tool_actions(result_text)
    test_output = _extract_test_output(tool_actions)
    tool_calls = len(tool_actions)

    return SpawnResult(
        success=True,
        output=result_text,
        tool_calls=tool_calls,
        files_modified=files_modified or None,
        tool_actions=tool_actions or None,
        test_output=test_output,
        metrics={
            "tokens": total_tokens,
            "cost": total_cost,
            "input_tokens": total_input,
            "output_tokens": total_output,
            "reasoning_tokens": total_reasoning,
        },
    )


async def spawn_opencode_worker(
    task: SwarmTask,
    worker: SwarmWorkerSpec,
    system_prompt: str,
    *,
    working_dir: str = "",
    max_tokens: int = 50_000,
    timeout_ms: int = 120_000,
) -> SpawnResult:
    """Spawn an OpenCode CLI subprocess for the given task.

    Uses ``asyncio.create_subprocess_exec`` (safe argv, no shell) to run
    the ``opencode`` CLI with structured JSON output.
    """
    started_at = time.monotonic()

    try:
        args = _build_opencode_args(
            task,
            worker,
            system_prompt,
            working_dir=working_dir,
        )
    except FileNotFoundError as exc:
        return SpawnResult(
            success=False,
            output=str(exc),
        )

    logger.info(
        "Spawning OpenCode worker for task %s (model=%s, cwd=%s)",
        task.id,
        worker.model,
        working_dir or ".",
    )

    timeout_s = timeout_ms / 1000.0

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir or None,
            env={**os.environ},
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_s,
            )
        except TimeoutError:
            try:
                proc.kill()
            except OSError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except TimeoutError:
                logger.warning("Process for task %s did not exit after kill", task.id)
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            return SpawnResult(
                success=False,
                output=f"Worker timed out after {elapsed_ms}ms",
                metrics={"duration": elapsed_ms},
            )

        stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

        if proc.returncode != 0 and not stdout.strip():
            return SpawnResult(
                success=False,
                output=f"OpenCode process exited with code {proc.returncode}: {stderr[:500]}",
            )

        result = _parse_opencode_output(stdout)

        if stderr.strip():
            result.stderr = stderr
            logger.debug("OpenCode worker stderr for task %s: %s", task.id, stderr[:200])

        return result

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        logger.error(
            "OpenCode worker spawn error for task %s: %s", task.id, exc
        )
        return SpawnResult(
            success=False,
            output=f"Spawn error: {exc}",
            metrics={"duration": elapsed_ms},
        )


def create_opencode_spawn_fn(
    working_dir: str = "",
    default_model: str = "",
) -> Any:
    """Create a spawn function suitable for SwarmWorkerPool.

    Returns an async callable matching the ``SpawnAgentFn`` signature
    expected by the worker pool.
    """

    async def spawn_fn(
        task: SwarmTask,
        worker: SwarmWorkerSpec,
        system_prompt: str,
        max_tokens: int = 50_000,
        timeout_ms: int = 120_000,
        **_kwargs: Any,
    ) -> SpawnResult:
        return await spawn_opencode_worker(
            task,
            worker,
            system_prompt,
            working_dir=working_dir,
            max_tokens=max_tokens,
            timeout_ms=timeout_ms,
        )

    return spawn_fn
