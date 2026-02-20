"""Seatbelt sandbox for macOS.

Uses macOS sandbox-exec with dynamically generated profiles
to provide filesystem and network isolation for command execution.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class SeatbeltOptions:
    """Options for the Seatbelt sandbox."""

    writable_paths: list[str] = field(default_factory=lambda: ["."])
    readable_paths: list[str] = field(default_factory=lambda: ["/"])
    network_allowed: bool = False
    timeout: float = 300.0
    max_output_bytes: int = 1_000_000


@dataclass(slots=True)
class SeatbeltResult:
    """Result of a seatbelt sandbox validation or execution."""

    allowed: bool
    reason: str = ""
    command: str = ""


def _generate_profile(options: SeatbeltOptions, working_dir: str) -> str:
    """Generate a sandbox-exec profile from options.

    Args:
        options: Sandbox configuration.
        working_dir: The working directory (always writable).

    Returns:
        Sandbox profile string.
    """
    rules: list[str] = [
        "(version 1)",
        "(deny default)",
        "",
        "; Allow basic process operations",
        "(allow process-exec)",
        "(allow process-fork)",
        "(allow signal)",
        "(allow sysctl-read)",
        "(allow mach-lookup)",
        "",
        "; Allow reading common system paths",
        '(allow file-read* (subpath "/usr"))',
        '(allow file-read* (subpath "/bin"))',
        '(allow file-read* (subpath "/sbin"))',
        '(allow file-read* (subpath "/Library"))',
        '(allow file-read* (subpath "/System"))',
        '(allow file-read* (subpath "/private/tmp"))',
        '(allow file-read* (subpath "/private/var"))',
        '(allow file-read* (subpath "/opt/homebrew"))',
        '(allow file-read* (subpath "/dev"))',
        '(allow file-write* (subpath "/dev/null"))',
        '(allow file-write* (subpath "/dev/tty"))',
        '(allow file-write* (subpath "/private/tmp"))',
        "",
    ]

    # Readable paths
    for rpath in options.readable_paths:
        resolved = str(Path(rpath).resolve())
        rules.append(f'(allow file-read* (subpath "{resolved}"))')

    rules.append("")

    # Writable paths
    for wpath in options.writable_paths:
        resolved = str(Path(wpath).resolve()) if wpath != "." else working_dir
        rules.append(f'(allow file-read* (subpath "{resolved}"))')
        rules.append(f'(allow file-write* (subpath "{resolved}"))')

    # Always allow writing to working directory
    rules.append(f'(allow file-read* (subpath "{working_dir}"))')
    rules.append(f'(allow file-write* (subpath "{working_dir}"))')
    rules.append("")

    # Network
    if options.network_allowed:
        rules.append("; Allow network access")
        rules.append("(allow network*)")
    else:
        rules.append("; Network access denied")

    return "\n".join(rules)


@dataclass
class SeatbeltSandbox:
    """macOS Seatbelt sandbox using sandbox-exec.

    Generates a sandbox profile dynamically and wraps command
    execution with sandbox-exec for OS-level isolation.
    """

    options: SeatbeltOptions = field(default_factory=SeatbeltOptions)

    @staticmethod
    def is_available() -> bool:
        """Check if seatbelt is available on this platform."""
        if sys.platform != "darwin":
            return False
        return os.path.exists("/usr/bin/sandbox-exec")

    def validate(self, command: str) -> SeatbeltResult:
        """Validate a command (always allowed - sandbox-exec handles isolation)."""
        if not self.is_available():
            return SeatbeltResult(
                allowed=False,
                reason="Seatbelt not available (requires macOS with sandbox-exec)",
                command=command,
            )
        return SeatbeltResult(allowed=True, command=command)

    async def execute(
        self,
        command: str,
        *,
        working_dir: str | None = None,
        env: dict[str, str] | None = None,
    ) -> tuple[str, int]:
        """Execute a command inside the seatbelt sandbox.

        Args:
            command: The command to execute.
            working_dir: Working directory.
            env: Extra environment variables.

        Returns:
            Tuple of (output, exit_code).
        """
        if not self.is_available():
            raise RuntimeError("Seatbelt sandbox not available on this platform")

        cwd = working_dir or os.getcwd()
        profile = _generate_profile(self.options, cwd)

        # Write profile to temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sb", delete=False, prefix="attocode_sandbox_"
        ) as f:
            f.write(profile)
            profile_path = f.name

        try:
            # Build sandboxed command
            sandboxed_cmd = f'/usr/bin/sandbox-exec -f "{profile_path}" /bin/bash -c {_shell_quote(command)}'

            exec_env = dict(os.environ)
            exec_env["TERM"] = "dumb"
            if env:
                exec_env.update(env)

            proc = await asyncio.create_subprocess_shell(
                sandboxed_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=exec_env,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self.options.timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                return f"Command timed out after {self.options.timeout}s", -1

            output = stdout.decode(errors="replace")
            err = stderr.decode(errors="replace")

            # Filter out sandbox denial messages from stderr
            if err:
                filtered_err = "\n".join(
                    line for line in err.splitlines()
                    if "deny" not in line.lower() or "sandbox" not in line.lower()
                )
                if filtered_err.strip():
                    output = f"{output}\n{filtered_err}" if output else filtered_err

            if len(output) > self.options.max_output_bytes:
                output = output[: self.options.max_output_bytes] + "\n... (truncated)"

            return output, proc.returncode or 0

        finally:
            # Clean up profile file
            try:
                os.unlink(profile_path)
            except OSError:
                pass


def _shell_quote(s: str) -> str:
    """Quote a string for safe shell inclusion."""
    return "'" + s.replace("'", "'\\''") + "'"
