"""Persistent PTY shell.

Provides a persistent shell session that maintains state between
commands (working directory, environment, etc.) using asyncio
subprocess management.
"""

from __future__ import annotations

import asyncio
import os
import platform
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


# =============================================================================
# Types
# =============================================================================


@dataclass
class PTYShellConfig:
    """PTY shell configuration."""

    shell: str = ""  # Auto-detect if empty
    cwd: str = ""  # Default to cwd if empty
    env: dict[str, str] = field(default_factory=dict)
    timeout: float = 30.0  # Seconds
    max_output_size: int = 1_048_576  # 1MB
    prompt_pattern: str = "__CMD_DONE__"


@dataclass
class CommandResult:
    """Result of a shell command."""

    output: str
    exit_code: int | None
    duration: float  # Seconds
    timed_out: bool


@dataclass
class ShellState:
    """Current state of the shell."""

    cwd: str
    env: dict[str, str]
    history: list[str]
    is_running: bool
    pid: int | None = None


PTYEventListener = Callable[[str, dict[str, Any]], None]


# =============================================================================
# PTY Shell Manager
# =============================================================================


class PTYShellManager:
    """Manages a persistent shell session.

    Commands run in sequence in the same shell process,
    preserving environment and working directory between calls.
    Uses a sentinel marker to detect command completion.
    """

    def __init__(self, config: PTYShellConfig | None = None) -> None:
        cfg = config or PTYShellConfig()
        self._shell = cfg.shell or self._detect_shell()
        self._cwd = cfg.cwd or os.getcwd()
        self._base_env = {**os.environ, **cfg.env}
        self._timeout = cfg.timeout
        self._max_output_size = cfg.max_output_size
        self._prompt_pattern = cfg.prompt_pattern

        self._process: asyncio.subprocess.Process | None = None
        self._history: list[str] = []
        self._listeners: set[PTYEventListener] = set()

    @staticmethod
    def _detect_shell() -> str:
        """Auto-detect the user's shell."""
        user_shell = os.environ.get("SHELL")
        if user_shell:
            return user_shell
        if platform.system() == "Windows":
            return "cmd.exe"
        return "/bin/bash"

    async def start(self) -> None:
        """Start the persistent shell process."""
        if self._process is not None and self._process.returncode is None:
            return  # Already running

        env = {**self._base_env, "PS1": "$ ", "PROMPT_COMMAND": ""}

        self._process = await asyncio.create_subprocess_shell(
            self._shell,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=self._cwd,
            env=env,
        )

        # Give shell time to initialize
        await asyncio.sleep(0.1)

        if self._process.pid:
            self._emit("shell.started", {
                "pid": self._process.pid,
                "shell": self._shell,
            })
        else:
            raise RuntimeError("Failed to start shell")

    async def run_command(self, command: str) -> CommandResult:
        """Run a command in the persistent shell.

        Uses a sentinel marker pattern to detect when the command
        has completed and to capture the exit code.
        """
        if self._process is None or self._process.returncode is not None:
            await self.start()

        assert self._process is not None
        assert self._process.stdin is not None
        assert self._process.stdout is not None

        self._history.append(command)
        start_time = time.monotonic()
        self._emit("command.start", {"command": command})

        # Write command with end marker that echoes the exit code
        end_marker = f'\necho "{self._prompt_pattern} $?"\n'
        full_command = command + end_marker
        self._process.stdin.write(full_command.encode())
        await self._process.stdin.drain()

        # Read output until we see the marker
        output_parts: list[str] = []
        timed_out = False

        try:
            output = await asyncio.wait_for(
                self._read_until_marker(output_parts),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            timed_out = True
            output = "".join(output_parts)
            self._emit("command.timeout", {"command": command})

        duration = time.monotonic() - start_time

        # Parse exit code from marker line
        exit_code: int | None = None
        if not timed_out and self._prompt_pattern in output:
            marker_idx = output.rfind(self._prompt_pattern)
            after_marker = output[marker_idx + len(self._prompt_pattern):]
            parts = after_marker.strip().split()
            digits = "".join(c for c in parts[0] if c.isdigit()) if parts else ""
            exit_code = int(digits) if digits else None
            output = output[:marker_idx]

        # Clean up echo command from output
        lines = output.split("\n")
        cleaned: list[str] = []
        for line in lines:
            if f'echo "{self._prompt_pattern}' in line:
                continue
            cleaned.append(line)
        output = "\n".join(cleaned).strip()

        # Trim if too large
        if len(output) > self._max_output_size:
            output = output[-self._max_output_size:]

        result = CommandResult(
            output=output,
            exit_code=exit_code,
            duration=duration,
            timed_out=timed_out,
        )
        self._emit("command.complete", {"result": result})
        return result

    async def _read_until_marker(self, parts: list[str]) -> str:
        """Read from stdout until the prompt pattern is found."""
        assert self._process is not None
        assert self._process.stdout is not None

        buffer = ""
        while True:
            data = await self._process.stdout.read(4096)
            if not data:
                break
            chunk = data.decode(errors="replace")
            parts.append(chunk)
            buffer += chunk
            if self._prompt_pattern in buffer:
                break
        return buffer

    async def cd(self, directory: str) -> CommandResult:
        """Change working directory."""
        result = await self.run_command(f'cd "{directory}" && pwd')
        if result.exit_code == 0:
            self._cwd = result.output.strip()
        return result

    async def set_env(self, key: str, value: str) -> None:
        """Set an environment variable in the shell."""
        await self.run_command(f'export {key}="{value}"')
        self._base_env[key] = value

    def get_state(self) -> ShellState:
        """Get current shell state."""
        return ShellState(
            cwd=self._cwd,
            env=dict(self._base_env),
            history=list(self._history),
            is_running=(
                self._process is not None
                and self._process.returncode is None
            ),
            pid=self._process.pid if self._process else None,
        )

    def get_history(self) -> list[str]:
        """Get command history."""
        return list(self._history)

    def clear_history(self) -> None:
        """Clear command history."""
        self._history.clear()

    def on(self, listener: PTYEventListener) -> Callable[[], None]:
        """Subscribe to PTY events. Returns unsubscribe function."""
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    async def stop(self) -> None:
        """Stop the shell process."""
        if self._process is None:
            return

        if self._process.returncode is None:
            # Try graceful exit
            if self._process.stdin:
                try:
                    self._process.stdin.write(b"exit\n")
                    await self._process.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    pass

            try:
                await asyncio.wait_for(self._process.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()

        exit_code = self._process.returncode
        self._process = None
        self._emit("shell.stopped", {"exit_code": exit_code})

    async def cleanup(self) -> None:
        """Stop shell and clear listeners."""
        await self.stop()
        self._listeners.clear()

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        for listener in self._listeners:
            try:
                listener(event, data)
            except Exception:
                pass


def format_shell_state(state: ShellState) -> str:
    """Format shell state for display."""
    status = "Running" if state.is_running else "Stopped"
    pid_str = f" (PID: {state.pid})" if state.pid else ""
    lines = [
        f"Shell: {status}{pid_str}",
        f"CWD: {state.cwd}",
        f"History: {len(state.history)} commands",
    ]
    if state.history:
        lines.append("Recent commands:")
        for cmd in state.history[-5:]:
            lines.append(f"  $ {cmd}")
    return "\n".join(lines)
