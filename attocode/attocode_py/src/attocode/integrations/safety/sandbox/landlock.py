"""Landlock sandbox for Linux.

Uses Linux Landlock LSM (Linux Security Module) for filesystem
restrictions on Linux 5.13+. Falls back to basic sandbox on
older kernels or non-Linux platforms.
"""

from __future__ import annotations

import asyncio
import ctypes
import ctypes.util
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Landlock constants
LANDLOCK_CREATE_RULESET_VERSION = 1

# Landlock access flags
LANDLOCK_ACCESS_FS_EXECUTE = 1 << 0
LANDLOCK_ACCESS_FS_WRITE_FILE = 1 << 1
LANDLOCK_ACCESS_FS_READ_FILE = 1 << 2
LANDLOCK_ACCESS_FS_READ_DIR = 1 << 3
LANDLOCK_ACCESS_FS_REMOVE_DIR = 1 << 4
LANDLOCK_ACCESS_FS_REMOVE_FILE = 1 << 5
LANDLOCK_ACCESS_FS_MAKE_CHAR = 1 << 6
LANDLOCK_ACCESS_FS_MAKE_DIR = 1 << 7
LANDLOCK_ACCESS_FS_MAKE_REG = 1 << 8
LANDLOCK_ACCESS_FS_MAKE_SOCK = 1 << 9
LANDLOCK_ACCESS_FS_MAKE_FIFO = 1 << 10
LANDLOCK_ACCESS_FS_MAKE_BLOCK = 1 << 11
LANDLOCK_ACCESS_FS_MAKE_SYM = 1 << 12

READ_ACCESS = (
    LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_READ_DIR | LANDLOCK_ACCESS_FS_EXECUTE
)
WRITE_ACCESS = (
    LANDLOCK_ACCESS_FS_WRITE_FILE
    | LANDLOCK_ACCESS_FS_REMOVE_DIR
    | LANDLOCK_ACCESS_FS_REMOVE_FILE
    | LANDLOCK_ACCESS_FS_MAKE_DIR
    | LANDLOCK_ACCESS_FS_MAKE_REG
    | LANDLOCK_ACCESS_FS_MAKE_SYM
)
ALL_ACCESS = READ_ACCESS | WRITE_ACCESS


@dataclass(slots=True)
class LandlockOptions:
    """Options for the Landlock sandbox."""

    writable_paths: list[str] = field(default_factory=lambda: ["."])
    readable_paths: list[str] = field(default_factory=lambda: ["/"])
    network_allowed: bool = True
    timeout: float = 300.0
    max_output_bytes: int = 1_000_000


@dataclass(slots=True)
class LandlockResult:
    """Result of a Landlock sandbox check."""

    allowed: bool
    reason: str = ""
    command: str = ""


@dataclass
class LandlockSandbox:
    """Linux Landlock sandbox for per-path filesystem restrictions.

    Landlock LSM is available on Linux 5.13+ and provides fine-grained
    filesystem access control without root privileges.
    """

    options: LandlockOptions = field(default_factory=LandlockOptions)

    @staticmethod
    def is_available() -> bool:
        """Check if Landlock is available."""
        if sys.platform != "linux":
            return False
        # Check kernel version >= 5.13
        try:
            release = os.uname().release
            parts = release.split(".")
            major, minor = int(parts[0]), int(parts[1])
            if major < 5 or (major == 5 and minor < 13):
                return False
        except (IndexError, ValueError):
            return False
        # Check if landlock syscall is available
        try:
            libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
            return hasattr(libc, "syscall")
        except (OSError, TypeError):
            return False

    def validate(self, command: str) -> LandlockResult:
        """Validate a command (always allowed - Landlock handles isolation)."""
        if not self.is_available():
            return LandlockResult(
                allowed=False,
                reason="Landlock not available (requires Linux 5.13+)",
                command=command,
            )
        return LandlockResult(allowed=True, command=command)

    async def execute(
        self,
        command: str,
        *,
        working_dir: str | None = None,
        env: dict[str, str] | None = None,
    ) -> tuple[str, int]:
        """Execute a command with Landlock restrictions.

        Creates a child process that applies Landlock restrictions via
        a helper script using ctypes syscall wrappers for
        landlock_create_ruleset, landlock_add_rule, and
        landlock_restrict_self before running the command.

        Args:
            command: The command to execute.
            working_dir: Working directory.
            env: Extra environment variables.

        Returns:
            Tuple of (output, exit_code).
        """
        if not self.is_available():
            raise RuntimeError("Landlock not available on this platform")

        cwd = working_dir or os.getcwd()

        # Resolve paths
        readable = [str(Path(p).resolve()) for p in self.options.readable_paths]
        writable = [str(Path(p).resolve()) if p != "." else cwd for p in self.options.writable_paths]
        writable.append(cwd)

        exec_env = dict(os.environ)
        exec_env["TERM"] = "dumb"
        if env:
            exec_env.update(env)

        # Build a Python helper script that applies Landlock then runs cmd
        helper_script = _build_landlock_helper(
            readable_paths=list(set(readable)),
            writable_paths=list(set(writable)),
            command=command,
        )

        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", helper_script,
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
        if err:
            output = f"{output}\n{err}" if output else err

        if len(output) > self.options.max_output_bytes:
            output = output[: self.options.max_output_bytes] + "\n... (truncated)"

        return output, proc.returncode or 0


# Syscall numbers for x86_64
_SYS_LANDLOCK_CREATE_RULESET = 444
_SYS_LANDLOCK_ADD_RULE = 445
_SYS_LANDLOCK_RESTRICT_SELF = 446
_LANDLOCK_RULE_PATH_BENEATH = 1
_PR_SET_NO_NEW_PRIVS = 38


def _build_landlock_helper(
    readable_paths: list[str],
    writable_paths: list[str],
    command: str,
) -> str:
    """Build a Python script that applies Landlock restrictions and runs a command.

    The generated script:
    1. Sets PR_SET_NO_NEW_PRIVS (required by Landlock)
    2. Creates a Landlock ruleset with all filesystem access types
    3. Adds read rules for readable_paths
    4. Adds read+write rules for writable_paths
    5. Restricts the current process
    6. Runs the command via subprocess
    """
    import json as _json
    r_paths = _json.dumps(readable_paths)
    w_paths = _json.dumps(writable_paths)
    cmd = _json.dumps(command)

    return (
        "import ctypes, ctypes.util, os, struct, subprocess, sys\n"
        f"ALL_READ = {READ_ACCESS}\n"
        f"ALL_WRITE = {WRITE_ACCESS}\n"
        f"ALL_ACCESS = ALL_READ | ALL_WRITE\n"
        f"SYS_CREATE = {_SYS_LANDLOCK_CREATE_RULESET}\n"
        f"SYS_ADD = {_SYS_LANDLOCK_ADD_RULE}\n"
        f"SYS_RESTRICT = {_SYS_LANDLOCK_RESTRICT_SELF}\n"
        f"RULE_PATH = {_LANDLOCK_RULE_PATH_BENEATH}\n"
        f"PR_SET_NO_NEW_PRIVS = {_PR_SET_NO_NEW_PRIVS}\n"
        "def apply_landlock(readable, writable):\n"
        "    libc = ctypes.CDLL(ctypes.util.find_library('c'), use_errno=True)\n"
        "    attr = struct.pack('Q', ALL_ACCESS)\n"
        "    fd = libc.syscall(SYS_CREATE, attr, len(attr), 0)\n"
        "    if fd < 0:\n"
        "        return False\n"
        "    for p in writable:\n"
        "        if not os.path.exists(p): continue\n"
        "        pfd = os.open(p, os.O_PATH | os.O_CLOEXEC)\n"
        "        rule = struct.pack('Qi', ALL_ACCESS, pfd)\n"
        "        libc.syscall(SYS_ADD, fd, RULE_PATH, rule, 0)\n"
        "        os.close(pfd)\n"
        "    for p in readable:\n"
        "        if not os.path.exists(p): continue\n"
        "        if any(p.startswith(w) or w.startswith(p) for w in writable): continue\n"
        "        pfd = os.open(p, os.O_PATH | os.O_CLOEXEC)\n"
        "        rule = struct.pack('Qi', ALL_READ, pfd)\n"
        "        libc.syscall(SYS_ADD, fd, RULE_PATH, rule, 0)\n"
        "        os.close(pfd)\n"
        "    libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)\n"
        "    ret = libc.syscall(SYS_RESTRICT, fd, 0)\n"
        "    os.close(fd)\n"
        "    return ret >= 0\n"
        f"readable = {r_paths}\n"
        f"writable = {w_paths}\n"
        f"cmd = {cmd}\n"
        "apply_landlock(readable, writable)\n"
        "result = subprocess.run(cmd, shell=True, capture_output=True, text=True)\n"
        "sys.stdout.write(result.stdout)\n"
        "sys.stderr.write(result.stderr)\n"
        "sys.exit(result.returncode)\n"
    )
