"""Bash execution tool with safety features.

Enhanced bash tool matching TS reference implementation:
- TERM=dumb environment variable
- SIGTERM then SIGKILL timeout chain (3s grace period)
- Timeout normalization (< 300 = seconds, >= 300 = milliseconds)
- Dynamic danger level classification via bash_policy
- 100KB output cap with truncation message
- Environment sanitization (strip sensitive vars)
- Working directory validation
"""

from __future__ import annotations

import asyncio
import os
import signal
from typing import Any

from attocode.tools.base import Tool, ToolSpec
from attocode.types.messages import DangerLevel

DEFAULT_TIMEOUT = 120.0
MAX_OUTPUT = 100_000
SIGTERM_GRACE_SECONDS = 3.0

# Environment variables to strip from child processes
SENSITIVE_ENV_VARS = frozenset({
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "NPM_TOKEN",
    "PYPI_TOKEN",
    "DATABASE_URL",
    "DB_PASSWORD",
})


def _normalize_timeout(timeout: float) -> float:
    """Normalize timeout value.

    Values < 300 are treated as seconds.
    Values >= 300 are treated as milliseconds and converted to seconds.
    """
    if timeout >= 300:
        return timeout / 1000.0
    return timeout


def _sanitize_env() -> dict[str, str]:
    """Create a sanitized environment for child processes."""
    env = dict(os.environ)
    env["TERM"] = "dumb"
    for var in SENSITIVE_ENV_VARS:
        env.pop(var, None)
    return env


def classify_danger_level(command: str) -> DangerLevel:
    """Classify a command's danger level using bash policy.

    Bridges to bash_policy.classify_command() and converts
    CommandRisk to DangerLevel.
    """
    try:
        from attocode.integrations.safety.bash_policy import CommandRisk, classify_command
        result = classify_command(command)
        if result.risk == CommandRisk.BLOCK:
            return DangerLevel.DANGEROUS
        if result.risk == CommandRisk.WARN:
            return DangerLevel.MODERATE
        return DangerLevel.SAFE
    except ImportError:
        return DangerLevel.MODERATE


async def _kill_process(proc: asyncio.subprocess.Process) -> None:
    """Kill a process with SIGTERM → SIGKILL chain.

    Sends SIGTERM first, waits up to SIGTERM_GRACE_SECONDS,
    then sends SIGKILL if process is still alive.
    """
    try:
        proc.terminate()  # SIGTERM
    except ProcessLookupError:
        return

    try:
        await asyncio.wait_for(proc.wait(), timeout=SIGTERM_GRACE_SECONDS)
    except asyncio.TimeoutError:
        # Process didn't exit gracefully, force kill
        try:
            proc.kill()  # SIGKILL
        except ProcessLookupError:
            pass
        try:
            await proc.wait()
        except Exception:
            pass


async def execute_bash(
    args: dict[str, Any],
    working_dir: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    sandbox: Any = None,
) -> str:
    """Execute a bash command with safety features.

    Args:
        args: Tool arguments containing 'command' and optional 'timeout'.
        working_dir: Working directory for execution.
        timeout: Default timeout in seconds.
        sandbox: Optional sandbox instance for command validation.

    Returns:
        Command output string.
    """
    command = args["command"]
    raw_timeout = args.get("timeout", timeout)
    cmd_timeout = _normalize_timeout(raw_timeout)
    cwd = working_dir or os.getcwd()

    # Validate working directory
    if not os.path.isdir(cwd):
        return f"Error: Working directory does not exist: {cwd}"

    # Sandbox validation
    if sandbox is not None:
        check = sandbox.validate(command)
        if not check.allowed:
            return f"Error: Command blocked by sandbox — {check.reason}"

    # Sanitized environment
    env = _sanitize_env()

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=cmd_timeout)
        except asyncio.TimeoutError:
            await _kill_process(proc)
            return f"Error: Command timed out after {cmd_timeout:.0f}s"

        stdout_str = stdout.decode("utf-8", errors="replace") if stdout else ""
        stderr_str = stderr.decode("utf-8", errors="replace") if stderr else ""

        parts: list[str] = []
        if stdout_str:
            parts.append(stdout_str)
        if stderr_str:
            parts.append(f"STDERR:\n{stderr_str}")

        output = "\n".join(parts)

        # Truncate large output
        if len(output) > MAX_OUTPUT:
            total_len = len(output)
            output = output[:MAX_OUTPUT] + f"\n... (truncated, {total_len:,} total chars)"

        # Prepend exit code for non-zero returns
        if proc.returncode != 0:
            output = f"Exit code: {proc.returncode}\n{output}"

        return output.strip() or "(no output)"
    except OSError as e:
        return f"Error executing command: {e}"


def create_bash_tool(
    working_dir: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    sandbox: Any = None,
) -> Tool:
    """Create a bash tool instance.

    Args:
        working_dir: Default working directory.
        timeout: Default timeout in seconds.
        sandbox: Optional sandbox for command validation.

    Returns:
        Configured Tool instance.
    """
    async def _execute(args: dict[str, Any]) -> Any:
        return await execute_bash(args, working_dir, timeout, sandbox=sandbox)

    return Tool(
        spec=ToolSpec(
            name="bash",
            description="Execute a bash command.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The bash command to execute"},
                    "timeout": {
                        "type": "number",
                        "description": (
                            "Timeout in seconds (< 300) or milliseconds (>= 300). "
                            "Default: 120 seconds."
                        ),
                        "default": DEFAULT_TIMEOUT,
                    },
                },
                "required": ["command"],
            },
            danger_level=DangerLevel.DANGEROUS,
        ),
        execute=_execute,
        tags=["bash", "exec"],
    )
