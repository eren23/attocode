"""Docker sandbox for cross-platform container isolation.

Uses Docker to provide full container isolation for command execution.
Requires Docker to be installed and accessible.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class DockerOptions:
    """Options for the Docker sandbox."""

    image: str = "python:3.12-slim"
    writable_paths: list[str] = field(default_factory=lambda: ["."])
    readable_paths: list[str] = field(default_factory=lambda: ["/"])
    network_allowed: bool = False
    timeout: float = 300.0
    max_memory_mb: int = 512
    max_cpu_seconds: int = 30
    max_output_bytes: int = 1_000_000


@dataclass(slots=True)
class DockerResult:
    """Result of a Docker sandbox check."""

    allowed: bool
    reason: str = ""
    command: str = ""


@dataclass
class DockerSandbox:
    """Docker-based sandbox for full container isolation.

    Mounts the working directory and readable paths as volumes,
    applies resource limits, and optionally disables networking.
    """

    options: DockerOptions = field(default_factory=DockerOptions)

    @staticmethod
    def is_available() -> bool:
        """Check if Docker is available."""
        return shutil.which("docker") is not None

    def validate(self, command: str) -> DockerResult:
        """Validate a command (always allowed - Docker handles isolation)."""
        if not self.is_available():
            return DockerResult(
                allowed=False,
                reason="Docker not available",
                command=command,
            )
        return DockerResult(allowed=True, command=command)

    async def execute(
        self,
        command: str,
        *,
        working_dir: str | None = None,
        env: dict[str, str] | None = None,
    ) -> tuple[str, int]:
        """Execute a command inside a Docker container.

        Args:
            command: The command to execute.
            working_dir: Working directory (mounted as /workspace).
            env: Extra environment variables.

        Returns:
            Tuple of (output, exit_code).
        """
        if not self.is_available():
            raise RuntimeError("Docker not available")

        cwd = working_dir or os.getcwd()

        # Build docker run command
        docker_args = [
            "docker", "run", "--rm",
            f"--memory={self.options.max_memory_mb}m",
            "--cpus=1",
            f"-w=/workspace",
        ]

        # Mount working directory
        docker_args.extend(["-v", f"{cwd}:/workspace"])

        # Mount readable paths as read-only
        for rpath in self.options.readable_paths:
            resolved = str(Path(rpath).resolve())
            if resolved != "/" and os.path.exists(resolved):
                container_path = f"/mnt{resolved}"
                docker_args.extend(["-v", f"{resolved}:{container_path}:ro"])

        # Network
        if not self.options.network_allowed:
            docker_args.append("--network=none")

        # Environment
        docker_args.extend(["-e", "TERM=dumb"])
        if env:
            for key, value in env.items():
                docker_args.extend(["-e", f"{key}={value}"])

        # Image and command
        docker_args.append(self.options.image)
        docker_args.extend(["/bin/sh", "-c", command])

        proc = await asyncio.create_subprocess_exec(
            *docker_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.options.timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            # Also kill the container
            await asyncio.create_subprocess_exec(
                "docker", "kill", "--signal=KILL",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            return f"Command timed out after {self.options.timeout}s", -1

        output = stdout.decode(errors="replace")
        err = stderr.decode(errors="replace")
        if err:
            output = f"{output}\n{err}" if output else err

        if len(output) > self.options.max_output_bytes:
            output = output[: self.options.max_output_bytes] + "\n... (truncated)"

        return output, proc.returncode or 0
