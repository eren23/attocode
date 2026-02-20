"""Self-improvement protocol for tool failure diagnosis.

Diagnoses tool call failures, suggests fixes, tracks success
patterns, and persists recurring failures as learnings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


class FailureCategory:
    """Tool failure categories (distinct from failure_evidence categories)."""

    WRONG_ARGS = "wrong_args"
    MISSING_ARGS = "missing_args"
    FILE_NOT_FOUND = "file_not_found"
    PERMISSION = "permission"
    TIMEOUT = "timeout"
    SYNTAX_ERROR = "syntax_error"
    STATE_ERROR = "state_error"
    UNKNOWN = "unknown"


@dataclass
class ToolCallDiagnosis:
    """Diagnosis of a tool call failure."""

    tool_name: str
    original_args: dict[str, Any]
    error: str
    diagnosis: str
    suggested_fix: str
    category: str = FailureCategory.UNKNOWN
    improved_args: dict[str, Any] | None = None


@dataclass
class SuccessPattern:
    """A recorded pattern from successful tool calls."""

    tool_name: str
    arg_pattern: dict[str, str]
    context: str
    count: int = 1


@dataclass
class SelfImprovementConfig:
    """Configuration for self-improvement."""

    enable_diagnosis: bool = True
    max_diagnosis_cache: int = 50


# Error pattern rules: (regex, category, diagnosis, fix template)
_ERROR_PATTERNS: list[tuple[re.Pattern[str], str, str, str]] = [
    (
        re.compile(r"ENOENT|no such file|FileNotFoundError", re.IGNORECASE),
        FailureCategory.FILE_NOT_FOUND,
        "File or directory does not exist",
        "Verify path exists before accessing. Use glob/list_files to find correct path.",
    ),
    (
        re.compile(r"EACCES|permission denied|PermissionError", re.IGNORECASE),
        FailureCategory.PERMISSION,
        "Insufficient permissions to perform this operation",
        "Check file permissions or run with appropriate access level.",
    ),
    (
        re.compile(r"timeout|ETIMEDOUT|timed? ?out", re.IGNORECASE),
        FailureCategory.TIMEOUT,
        "Operation timed out",
        "Try a simpler command, reduce scope, or increase timeout.",
    ),
    (
        re.compile(r"syntax error|unexpected token|SyntaxError", re.IGNORECASE),
        FailureCategory.SYNTAX_ERROR,
        "Syntax error in the provided code or command",
        "Check syntax carefully. Verify quoting and escaping.",
    ),
    (
        re.compile(r"required|missing|undefined is not", re.IGNORECASE),
        FailureCategory.MISSING_ARGS,
        "Required argument is missing or undefined",
        "Check required parameters. Provide all mandatory fields.",
    ),
    (
        re.compile(r"invalid|type error|TypeError", re.IGNORECASE),
        FailureCategory.WRONG_ARGS,
        "Invalid argument type or value",
        "Check argument types match expected schema.",
    ),
    (
        re.compile(r"not found in file|no match|old_string", re.IGNORECASE),
        FailureCategory.STATE_ERROR,
        "Content to find/replace does not match current file state",
        "Re-read the file to get current content before editing.",
    ),
    (
        re.compile(r"not in allowlist|command blocked|blocked", re.IGNORECASE),
        FailureCategory.PERMISSION,
        "Command is blocked by security policy",
        "Use an allowed alternative or request permission.",
    ),
    (
        re.compile(r"Expected string, received|Expected .+, received", re.IGNORECASE),
        FailureCategory.WRONG_ARGS,
        "Argument type mismatch (schema validation error)",
        "Check argument types in tool schema. Strings vs objects vs arrays.",
    ),
]


class SelfImprovementProtocol:
    """Diagnoses tool failures and tracks success patterns.

    Provides enhanced error messages with actionable suggestions
    and detects when tools are repeatedly failing.
    """

    def __init__(self, config: SelfImprovementConfig | None = None) -> None:
        self._config = config or SelfImprovementConfig()
        self._failure_counts: dict[str, int] = {}
        self._diagnosis_cache: dict[str, ToolCallDiagnosis] = {}
        self._success_patterns: dict[str, list[SuccessPattern]] = {}

    def diagnose_tool_failure(
        self,
        tool_name: str,
        args: dict[str, Any],
        error: str,
    ) -> ToolCallDiagnosis:
        """Diagnose a tool call failure."""
        # Increment failure count
        self._failure_counts[tool_name] = self._failure_counts.get(tool_name, 0) + 1

        # Check cache
        cache_key = f"{tool_name}:{error[:80]}"
        if cache_key in self._diagnosis_cache:
            return self._diagnosis_cache[cache_key]

        # Pattern match
        category = FailureCategory.UNKNOWN
        diagnosis = "Unknown error occurred"
        suggested_fix = "Review the error message and try a different approach."

        for pattern, cat, diag, fix in _ERROR_PATTERNS:
            if pattern.search(error):
                category = cat
                diagnosis = diag
                suggested_fix = fix
                break

        result = ToolCallDiagnosis(
            tool_name=tool_name,
            original_args=args,
            error=error,
            diagnosis=diagnosis,
            suggested_fix=suggested_fix,
            category=category,
        )

        # Cache with eviction
        self._diagnosis_cache[cache_key] = result
        if len(self._diagnosis_cache) > self._config.max_diagnosis_cache:
            # Evict first 10 entries
            keys = list(self._diagnosis_cache.keys())[:10]
            for k in keys:
                del self._diagnosis_cache[k]

        return result

    def record_success(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: str = "",
    ) -> None:
        """Record a successful tool call."""
        # Reset failure count
        self._failure_counts[tool_name] = 0

        # Track arg pattern (types only, not values)
        arg_pattern = {k: type(v).__name__ for k, v in args.items()}

        if tool_name not in self._success_patterns:
            self._success_patterns[tool_name] = []

        # Check for existing matching pattern
        for p in self._success_patterns[tool_name]:
            if p.arg_pattern == arg_pattern:
                p.count += 1
                return

        self._success_patterns[tool_name].append(
            SuccessPattern(
                tool_name=tool_name,
                arg_pattern=arg_pattern,
                context=context,
            )
        )

    def get_failure_count(self, tool_name: str) -> int:
        """Get current failure count for a tool."""
        return self._failure_counts.get(tool_name, 0)

    def is_repeatedly_failing(self, tool_name: str) -> bool:
        """Check if a tool is repeatedly failing (3+ times)."""
        return self._failure_counts.get(tool_name, 0) >= 3

    def enhance_error_message(
        self,
        tool_name: str,
        error: str,
        args: dict[str, Any],
    ) -> str:
        """Enhance an error message with diagnosis and suggestions."""
        if not self._config.enable_diagnosis:
            return error

        diagnosis = self.diagnose_tool_failure(tool_name, args, error)

        parts = [error]

        if diagnosis.category != FailureCategory.UNKNOWN:
            parts.append(f"\nDiagnosis: {diagnosis.diagnosis}")
            parts.append(f"Suggestion: {diagnosis.suggested_fix}")

        count = self._failure_counts.get(tool_name, 0)
        if count >= 3:
            parts.append(
                f"\nWarning: {tool_name} has failed {count} times. "
                "Consider a different approach."
            )

        return "\n".join(parts)

    def get_success_patterns(self, tool_name: str) -> list[SuccessPattern]:
        """Get recorded success patterns for a tool."""
        return list(self._success_patterns.get(tool_name, []))
