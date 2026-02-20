"""Basic sandbox - allowlist/blocklist command validation.

Fallback sandbox that validates commands against configurable
allowlists and blocklists without OS-level isolation.
"""

from __future__ import annotations

import asyncio
import shlex
from dataclasses import dataclass, field
from typing import Any


DEFAULT_ALLOWED_COMMANDS = frozenset({
    "ls", "cat", "head", "tail", "wc", "echo", "printf",
    "pwd", "which", "whoami", "date", "env",
    "file", "stat", "du", "df",
    "git", "python", "python3", "pip", "pip3",
    "node", "npm", "npx", "yarn", "pnpm",
    "make", "cmake", "cargo", "go", "javac", "java",
    "grep", "rg", "find", "fd", "ag",
    "sort", "uniq", "cut", "tr", "sed", "awk",
    "curl", "wget",
    "mkdir", "cp", "mv", "touch",
    "tar", "zip", "unzip", "gzip", "gunzip",
    "diff", "patch",
    "pytest", "mypy", "ruff", "black", "isort",
    "tsc", "eslint", "prettier",
})

DEFAULT_BLOCKED_COMMANDS = frozenset({
    "rm", "rmdir", "sudo", "su", "chmod", "chown",
    "kill", "killall", "pkill",
    "mkfs", "dd", "fdisk", "mount", "umount",
    "shutdown", "reboot", "halt",
    "iptables", "ufw",
    "systemctl", "service",
})


@dataclass(slots=True)
class SandboxOptions:
    """Configuration for the basic sandbox."""

    allowed_commands: frozenset[str] = DEFAULT_ALLOWED_COMMANDS
    blocked_commands: frozenset[str] = DEFAULT_BLOCKED_COMMANDS
    writable_paths: list[str] = field(default_factory=lambda: ["."])
    readable_paths: list[str] = field(default_factory=lambda: ["/"])
    network_allowed: bool = True
    timeout: float = 300.0
    max_output_bytes: int = 1_000_000


@dataclass(slots=True)
class SandboxResult:
    """Result of a sandbox validation check."""

    allowed: bool
    reason: str = ""
    command: str = ""


@dataclass
class BasicSandbox:
    """Basic sandbox using allowlist/blocklist validation.

    No OS-level isolation - just validates commands against
    configured lists before execution.
    """

    options: SandboxOptions = field(default_factory=SandboxOptions)

    def validate(self, command: str) -> SandboxResult:
        """Check if a command is allowed.

        Args:
            command: The full command string.

        Returns:
            SandboxResult indicating if the command is allowed.
        """
        stripped = command.strip()
        if not stripped:
            return SandboxResult(allowed=True, command=command)

        # Extract base command
        try:
            parts = shlex.split(stripped)
            base_cmd = parts[0] if parts else ""
        except ValueError:
            parts = stripped.split()
            base_cmd = parts[0] if parts else ""

        # Strip path prefixes
        if "/" in base_cmd:
            base_cmd = base_cmd.rsplit("/", 1)[-1]

        # Check blocklist first (higher priority)
        if base_cmd in self.options.blocked_commands:
            return SandboxResult(
                allowed=False,
                reason=f"Command '{base_cmd}' is blocked by sandbox policy",
                command=command,
            )

        # Check allowlist
        if base_cmd in self.options.allowed_commands:
            return SandboxResult(allowed=True, command=command)

        # Unknown command: block by default
        return SandboxResult(
            allowed=False,
            reason=f"Command '{base_cmd}' is not in the allowed commands list",
            command=command,
        )

    async def execute(
        self,
        command: str,
        *,
        working_dir: str | None = None,
        env: dict[str, str] | None = None,
    ) -> tuple[str, int]:
        """Validate and execute a command.

        Args:
            command: The command to execute.
            working_dir: Working directory for execution.
            env: Extra environment variables.

        Returns:
            Tuple of (output, exit_code).

        Raises:
            PermissionError: If the command is blocked.
        """
        check = self.validate(command)
        if not check.allowed:
            raise PermissionError(check.reason)

        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.options.timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return f"Command timed out after {self.options.timeout}s", -1

        output = stdout.decode(errors="replace")
        if stderr:
            err_text = stderr.decode(errors="replace")
            if err_text:
                output = f"{output}\n{err_text}" if output else err_text

        # Truncate large output
        if len(output) > self.options.max_output_bytes:
            output = output[: self.options.max_output_bytes] + "\n... (truncated)"

        return output, proc.returncode or 0
