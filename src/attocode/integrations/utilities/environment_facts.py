"""System environment information.

Gathers facts about the runtime environment: OS, shell, Python
version, git status, available tools, etc. Used for system prompt
context and capability detection.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class EnvironmentFacts:
    """Collected facts about the runtime environment."""

    os_name: str = ""
    os_version: str = ""
    platform: str = ""  # darwin, linux, win32
    arch: str = ""
    shell: str = ""
    python_version: str = ""
    node_version: str = ""
    git_available: bool = False
    git_branch: str = ""
    git_root: str = ""
    cwd: str = ""
    user: str = ""
    home: str = ""
    available_tools: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_prompt_context(self) -> str:
        """Format as a string suitable for system prompt injection."""
        lines = [
            f"- Platform: {self.platform} ({self.arch})",
            f"- OS: {self.os_name} {self.os_version}",
            f"- Shell: {self.shell}",
            f"- Python: {self.python_version}",
            f"- Working directory: {self.cwd}",
        ]
        if self.git_available:
            lines.append(f"- Git branch: {self.git_branch or '(detached)'}")
            lines.append(f"- Git root: {self.git_root}")
        if self.node_version:
            lines.append(f"- Node.js: {self.node_version}")
        if self.available_tools:
            lines.append(f"- Available tools: {', '.join(self.available_tools)}")
        return "\n".join(lines)


def _run_cmd(cmd: list[str], timeout: float = 5.0) -> str:
    """Run a command and return stripped stdout, or '' on failure."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def gather_environment_facts(cwd: str | Path | None = None) -> EnvironmentFacts:
    """Gather environment facts from the system.

    Args:
        cwd: Working directory to check git status in.

    Returns:
        An :class:`EnvironmentFacts` instance.
    """
    facts = EnvironmentFacts(
        os_name=platform.system(),
        os_version=platform.release(),
        platform=sys.platform,
        arch=platform.machine(),
        shell=os.environ.get("SHELL", ""),
        python_version=platform.python_version(),
        cwd=str(cwd or os.getcwd()),
        user=os.environ.get("USER", os.environ.get("USERNAME", "")),
        home=str(Path.home()),
    )

    # Node.js version
    facts.node_version = _run_cmd(["node", "--version"])

    # Git info
    git_path = shutil.which("git")
    facts.git_available = git_path is not None

    if facts.git_available:
        work_dir = str(cwd) if cwd else None
        facts.git_branch = _run_cmd(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        )
        facts.git_root = _run_cmd(
            ["git", "rev-parse", "--show-toplevel"],
        )

    # Available tools
    tool_names = [
        "git", "node", "npm", "npx", "python3", "pip",
        "ruff", "mypy", "pytest", "docker", "cargo", "go",
    ]
    facts.available_tools = [t for t in tool_names if shutil.which(t)]

    return facts
