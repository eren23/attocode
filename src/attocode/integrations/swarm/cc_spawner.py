"""Claude Code CLI subprocess spawner for swarm workers.

Spawns real Claude Code instances as subprocesses to execute swarm tasks.
Each worker runs ``claude -p <prompt> --output-format json`` and the JSON
output is parsed into a :class:`SpawnResult`.

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

# Default allowed tools for workers (broad set for implementation tasks)
_DEFAULT_ALLOWED_TOOLS = [
    "Read",
    "Write",
    "Edit",
    "Bash",
    "Glob",
    "Grep",
]


def _find_claude_binary() -> str | None:
    """Locate the ``claude`` CLI binary on PATH."""
    return shutil.which("claude")


def _build_cli_args(
    task: SwarmTask,
    worker: SwarmWorkerSpec,
    system_prompt: str,
    *,
    working_dir: str = "",
    max_iterations: int = 15,
    timeout_ms: int = 120_000,
) -> list[str]:
    """Build the CLI argument list for a ``claude`` subprocess.

    Uses exec-style argv list (no shell interpolation) to prevent injection.
    """
    claude_bin = _find_claude_binary()
    if not claude_bin:
        raise FileNotFoundError(
            "claude CLI binary not found on PATH. "
            "Install it with: npm install -g @anthropic-ai/claude-code"
        )

    # Build the task prompt with context
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

    # Compute max turns from iterations
    max_turns = max(5, max_iterations)

    args: list[str] = [
        claude_bin,
        "-p", full_prompt,
        "--output-format", "json",
        "--max-turns", str(max_turns),
        "--dangerously-skip-permissions",
    ]

    # Model override
    if worker.model:
        args.extend(["--model", worker.model])

    # Working directory
    if working_dir:
        args.extend(["--cwd", working_dir])

    # Allowed tools
    allowed = worker.allowed_tools or _DEFAULT_ALLOWED_TOOLS
    if allowed:
        args.extend(["--allowedTools", ",".join(allowed)])

    return args


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
    """Check whether a command string looks like a test runner invocation."""
    return any(p.search(cmd) for p in _TEST_COMMAND_PATTERNS)


def _extract_tool_actions(result_text: str) -> list[ToolAction]:
    """Extract structured tool actions from subagent output text.

    Parses bash command blocks, $ command patterns, and file operations
    to create ToolAction records for transparency.
    """
    actions: list[ToolAction] = []
    seen_commands: set[str] = set()

    # Parse fenced bash blocks
    for match in _BASH_BLOCK_RE.finditer(result_text):
        cmd = match.group(1).strip()
        output = (match.group(2) or "").strip()
        if cmd and cmd not in seen_commands:
            seen_commands.add(cmd)
            is_test = _is_test_command(cmd)
            actions.append(ToolAction(
                tool_name="Bash",
                arguments_summary=cmd[:300],
                output_summary=output[:1000],
                is_test_execution=is_test,
            ))

    # Parse $ command patterns
    for match in _DOLLAR_CMD_RE.finditer(result_text):
        cmd = match.group(1).strip()
        output = match.group(2).strip()
        if cmd and cmd not in seen_commands:
            seen_commands.add(cmd)
            is_test = _is_test_command(cmd)
            actions.append(ToolAction(
                tool_name="Bash",
                arguments_summary=cmd[:300],
                output_summary=output[:1000],
                is_test_execution=is_test,
            ))

    # Parse file operations
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
    """Concatenate output from test execution actions."""
    parts: list[str] = []
    for a in actions:
        if a.is_test_execution and a.output_summary:
            parts.append(f"$ {a.arguments_summary}\n{a.output_summary}")
    if not parts:
        return None
    combined = "\n\n".join(parts)
    return combined[:5000]


def _parse_cc_output(raw: str) -> SpawnResult:
    """Parse the JSON output from ``claude --output-format json``.

    Expected schema::

        {
            "result": "...",
            "total_cost_usd": 0.05,
            "usage": {"input_tokens": N, "output_tokens": N},
            "num_turns": N,
            "is_error": false,
            "session_id": "..."
        }
    """
    if not raw.strip():
        return SpawnResult(
            success=False,
            output="Empty output from Claude Code worker",
        )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Might be multi-line with non-JSON preamble; try last line
        for line in reversed(raw.strip().splitlines()):
            try:
                data = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
        else:
            return SpawnResult(
                success=False,
                output=f"Failed to parse CC output: {raw[:500]}",
            )

    is_error = data.get("is_error", False)
    result_text = data.get("result", "")
    total_cost = data.get("total_cost_usd", 0.0)
    num_turns = data.get("num_turns", 0)
    session_id = data.get("session_id", "")

    # Extract token usage
    usage = data.get("usage", {})
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    total_tokens = input_tokens + output_tokens

    # Extract files modified from result text (heuristic)
    files_modified = _extract_files_modified(result_text)

    # Count tool calls from num_turns (rough proxy)
    tool_calls = max(0, num_turns - 1) if num_turns > 0 else 0

    # Extract per-tool-call actions for transparency
    tool_actions = _extract_tool_actions(result_text)
    test_output = _extract_test_output(tool_actions)

    return SpawnResult(
        success=not is_error,
        output=result_text or "",
        tool_calls=tool_calls,
        files_modified=files_modified or None,
        tool_actions=tool_actions or None,
        test_output=test_output,
        metrics={
            "tokens": total_tokens,
            "cost": total_cost,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "num_turns": num_turns,
            "session_id": session_id,
        },
        session_id=session_id,
        num_turns=num_turns,
    )


def _extract_files_modified(output: str) -> list[str]:
    """Extract file paths from output that look like they were modified."""
    import re

    files: list[str] = []
    # Match patterns like "Created file: path" or "Wrote to path" or "Modified path"
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


async def spawn_cc_worker(
    task: SwarmTask,
    worker: SwarmWorkerSpec,
    system_prompt: str,
    *,
    working_dir: str = "",
    max_tokens: int = 50_000,
    timeout_ms: int = 120_000,
    max_iterations: int = 15,
) -> SpawnResult:
    """Spawn a Claude Code CLI subprocess for the given task.

    Uses ``asyncio.create_subprocess_exec`` (safe argv, no shell) to run
    the ``claude`` CLI with structured JSON output.
    """
    started_at = time.monotonic()

    try:
        args = _build_cli_args(
            task,
            worker,
            system_prompt,
            working_dir=working_dir,
            max_iterations=max_iterations,
            timeout_ms=timeout_ms,
        )
    except FileNotFoundError as exc:
        return SpawnResult(
            success=False,
            output=str(exc),
        )

    logger.info(
        "Spawning CC worker for task %s (model=%s, cwd=%s)",
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
            env={**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL": "1"},
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_s,
            )
        except TimeoutError:
            # Kill the process with a bounded wait
            try:
                proc.kill()
            except OSError:
                pass  # Process already exited
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
                output=f"CC process exited with code {proc.returncode}: {stderr[:500]}",
            )

        result = _parse_cc_output(stdout)

        # Preserve stderr on result and log warnings
        if stderr.strip():
            result.stderr = stderr
            logger.debug("CC worker stderr for task %s: %s", task.id, stderr[:200])

        return result

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        logger.error(
            "CC worker spawn error for task %s: %s", task.id, exc
        )
        return SpawnResult(
            success=False,
            output=f"Spawn error: {exc}",
            metrics={"duration": elapsed_ms},
        )


def create_cc_spawn_fn(
    working_dir: str = "",
    default_model: str = "",
    max_iterations: int = 15,
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
        return await spawn_cc_worker(
            task,
            worker,
            system_prompt,
            working_dir=working_dir,
            max_tokens=max_tokens,
            timeout_ms=timeout_ms,
            max_iterations=max_iterations,
        )

    return spawn_fn
