"""Bash command classification and safety policy.

Classifies bash commands into safety levels and provides
approval/denial decisions based on command content.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from enum import StrEnum


class CommandRisk(StrEnum):
    """Risk level of a bash command."""

    SAFE = "safe"
    WARN = "warn"
    BLOCK = "block"


@dataclass(slots=True)
class CommandClassification:
    """Classification of a bash command."""

    risk: CommandRisk
    reason: str = ""
    command: str = ""


# Commands that are always safe (read-only)
SAFE_COMMANDS = frozenset({
    "ls", "cat", "head", "tail", "wc", "echo", "printf",
    "pwd", "which", "whoami", "date", "env", "printenv",
    "file", "stat", "du", "df",
    "git status", "git log", "git diff", "git branch",
    "git show", "git remote", "git tag",
    "python --version", "node --version", "npm --version",
    "pip list", "pip show", "pip freeze",
})

# Command prefixes that are safe
SAFE_PREFIXES = (
    "ls ", "cat ", "head ", "tail ", "wc ",
    "echo ", "printf ", "test ", "[ ",
    "git log ", "git diff ", "git show ", "git status",
    "grep ", "rg ", "find ", "fd ",
    "python -c ", "python3 -c ",
)

# Patterns that should be blocked
BLOCKED_PATTERNS = [
    r"rm\s+-rf\s+/",
    r"rm\s+-rf\s+~",
    r"rm\s+-rf\s+\$HOME",
    r"mkfs\.",
    r"dd\s+if=.+of=/dev/",
    r":>\s*/",
    r">\s*/dev/sd",
    r"chmod\s+-R\s+777\s+/",
    r"curl\s+.*\|\s*(?:bash|sh|zsh)",
    r"wget\s+.*\|\s*(?:bash|sh|zsh)",
    r"sudo\s+rm",
    r"sudo\s+chmod",
    r"sudo\s+chown",
]

# Patterns that warrant a warning
WARN_PATTERNS = [
    r"\brm\b",
    r"\bsudo\b",
    r"\bchmod\b",
    r"\bchown\b",
    r"\bkill\b",
    r"\bpkill\b",
    r"\bgit\s+push",
    r"\bgit\s+reset",
    r"\bgit\s+checkout\s+\.",
    r"\bgit\s+clean",
    r"\bnpm\s+publish",
    r"\bpip\s+install(?!\s+--)",  # pip install without flags
    r"\bdocker\s+rm",
    r"\bdocker\s+rmi",
]

_blocked_re = [re.compile(p) for p in BLOCKED_PATTERNS]
_warn_re = [re.compile(p) for p in WARN_PATTERNS]


def classify_command(command: str) -> CommandClassification:
    """Classify a bash command by risk level.

    Args:
        command: The command string to classify.

    Returns:
        CommandClassification with risk level and reason.
    """
    stripped = command.strip()
    if not stripped:
        return CommandClassification(risk=CommandRisk.SAFE, command=command)

    # Check exact safe commands
    if stripped in SAFE_COMMANDS:
        return CommandClassification(risk=CommandRisk.SAFE, command=command)

    # Check safe prefixes
    for prefix in SAFE_PREFIXES:
        if stripped.startswith(prefix):
            return CommandClassification(risk=CommandRisk.SAFE, command=command)

    # Check blocked patterns
    for pattern in _blocked_re:
        if pattern.search(stripped):
            return CommandClassification(
                risk=CommandRisk.BLOCK,
                reason=f"Dangerous command pattern: {pattern.pattern}",
                command=command,
            )

    # Check warning patterns
    for pattern in _warn_re:
        if pattern.search(stripped):
            return CommandClassification(
                risk=CommandRisk.WARN,
                reason=f"Potentially dangerous: {pattern.pattern}",
                command=command,
            )

    # Default: warn for unknown commands
    return CommandClassification(
        risk=CommandRisk.WARN,
        reason="Unknown command requires review",
        command=command,
    )


def extract_command_name(command: str) -> str:
    """Extract the base command name from a command string."""
    stripped = command.strip()
    if not stripped:
        return ""
    try:
        parts = shlex.split(stripped)
        return parts[0] if parts else ""
    except ValueError:
        # Malformed shell string
        return stripped.split()[0] if stripped.split() else ""


@dataclass(slots=True)
class SandboxValidation:
    """Result of sandbox validation."""

    allowed: bool
    reason: str = ""


class BasicSandbox:
    """Basic sandbox that validates commands using classify_command().

    Blocks commands classified as BLOCK risk, allows SAFE,
    and allows WARN (policy engine handles approval for those).
    """

    def validate(self, command: str) -> SandboxValidation:
        """Validate a command against the sandbox rules."""
        result = classify_command(command)
        if result.risk == CommandRisk.BLOCK:
            return SandboxValidation(allowed=False, reason=result.reason)
        return SandboxValidation(allowed=True)
