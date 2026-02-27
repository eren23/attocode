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
import shutil
import time
from typing import Any

from attocode.integrations.swarm.types import (
    SpawnResult,
    SwarmTask,
    SwarmWorkerSpec,
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

    return SpawnResult(
        success=not is_error,
        output=result_text or "",
        tool_calls=tool_calls,
        files_modified=files_modified or None,
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
        except asyncio.TimeoutError:
            # Kill the process
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
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
