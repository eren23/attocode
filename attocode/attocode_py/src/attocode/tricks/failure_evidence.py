"""Failure evidence preservation (Trick S).

Tracks tool failures, detects patterns, generates suggestions,
and formats failure context for LLM injection.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable


class FailureCategory(StrEnum):
    """Categories of failures."""

    PERMISSION = "permission"
    NOT_FOUND = "not_found"
    SYNTAX = "syntax"
    TYPE = "type"
    RUNTIME = "runtime"
    NETWORK = "network"
    TIMEOUT = "timeout"
    VALIDATION = "validation"
    LOGIC = "logic"
    RESOURCE = "resource"
    UNKNOWN = "unknown"


@dataclass
class Failure:
    """A recorded failure."""

    id: str
    timestamp: float
    action: str
    error: str
    category: FailureCategory = FailureCategory.UNKNOWN
    args: dict[str, Any] | None = None
    stack_trace: str | None = None
    iteration: int | None = None
    intent: str | None = None
    suggestion: str | None = None
    resolved: bool = False
    repeat_count: int = 1


@dataclass
class FailureInput:
    """Input for recording a failure."""

    action: str
    error: str | Exception
    args: dict[str, Any] | None = None
    category: FailureCategory | None = None
    iteration: int | None = None
    intent: str | None = None


@dataclass
class FailurePattern:
    """A detected failure pattern."""

    type: str  # repeated_action, repeated_error, category_cluster, escalating
    description: str
    failure_ids: list[str]
    confidence: float = 0.5
    suggestion: str | None = None


@dataclass
class FailureTrackerConfig:
    """Configuration for failure tracking."""

    max_failures: int = 50
    preserve_stack_traces: bool = True
    categorize_errors: bool = True
    detect_repeats: bool = True
    repeat_warning_threshold: int = 3


FailureEventListener = Callable[[str, dict[str, Any]], None]

# Categorization patterns
_CATEGORY_PATTERNS: list[tuple[re.Pattern[str], FailureCategory]] = [
    (re.compile(r"EACCES|permission denied|PermissionError|forbidden", re.IGNORECASE), FailureCategory.PERMISSION),
    (re.compile(r"ENOENT|not found|FileNotFoundError|no such file", re.IGNORECASE), FailureCategory.NOT_FOUND),
    (re.compile(r"syntax error|SyntaxError|unexpected token|parse error", re.IGNORECASE), FailureCategory.SYNTAX),
    (re.compile(r"type error|TypeError|invalid type|wrong type", re.IGNORECASE), FailureCategory.TYPE),
    (re.compile(r"network|ECONNREFUSED|EHOSTUNREACH|DNS|ConnectionError", re.IGNORECASE), FailureCategory.NETWORK),
    (re.compile(r"timeout|ETIMEDOUT|timed? ?out|TimeoutError", re.IGNORECASE), FailureCategory.TIMEOUT),
    (re.compile(r"validation|invalid|ValueError|required field", re.IGNORECASE), FailureCategory.VALIDATION),
    (re.compile(r"out of memory|ENOMEM|MemoryError|disk full", re.IGNORECASE), FailureCategory.RESOURCE),
    (re.compile(r"RuntimeError|runtime|assertion|AssertionError", re.IGNORECASE), FailureCategory.RUNTIME),
]


class FailureTracker:
    """Tracks and analyzes agent failures.

    Records failures, auto-categorizes them, detects repeat
    patterns, and generates actionable suggestions.
    """

    def __init__(self, config: FailureTrackerConfig | None = None) -> None:
        self._config = config or FailureTrackerConfig()
        self._failures: list[Failure] = []
        self._listeners: list[FailureEventListener] = []

    def record_failure(self, input: FailureInput) -> Failure:
        """Record a new failure."""
        # Extract error string and stack trace
        if isinstance(input.error, Exception):
            error_str = str(input.error)
            stack_trace = None
            if self._config.preserve_stack_traces and hasattr(input.error, "__traceback__"):
                import traceback
                stack_trace = "".join(traceback.format_exception(type(input.error), input.error, input.error.__traceback__))
        else:
            error_str = input.error
            stack_trace = None

        # Categorize
        category = input.category or (
            categorize_error(error_str) if self._config.categorize_errors
            else FailureCategory.UNKNOWN
        )

        # Detect repeats
        repeat_count = 1
        if self._config.detect_repeats:
            prefix = error_str[:50].lower()
            repeat_count = 1 + sum(
                1 for f in self._failures
                if f.action == input.action
                and f.error[:50].lower() == prefix
                and not f.resolved
            )

        failure = Failure(
            id=f"fail-{uuid.uuid4().hex[:8]}",
            timestamp=time.time(),
            action=input.action,
            error=error_str,
            category=category,
            args=input.args,
            stack_trace=stack_trace,
            iteration=input.iteration,
            intent=input.intent,
            repeat_count=repeat_count,
            suggestion=None,
        )

        # Generate suggestion
        failure.suggestion = generate_suggestion(failure)

        # Enforce max
        if len(self._failures) >= self._config.max_failures:
            evicted = self._failures.pop(0)
            self._emit("failure.evicted", {"failure_id": evicted.id})

        self._failures.append(failure)
        self._emit("failure.recorded", {"failure_id": failure.id, "category": category})

        if repeat_count >= self._config.repeat_warning_threshold:
            self._emit("failure.repeated", {
                "failure_id": failure.id,
                "action": failure.action,
                "count": repeat_count,
            })

        # Detect patterns
        self._detect_patterns()

        return failure

    def resolve_failure(self, failure_id: str) -> bool:
        """Mark a failure as resolved."""
        for f in self._failures:
            if f.id == failure_id:
                f.resolved = True
                self._emit("failure.resolved", {"failure_id": failure_id})
                return True
        return False

    def get_unresolved_failures(self) -> list[Failure]:
        """Get all unresolved failures."""
        return [f for f in self._failures if not f.resolved]

    def get_failures_by_category(self, category: FailureCategory) -> list[Failure]:
        """Get failures by category."""
        return [f for f in self._failures if f.category == category]

    def get_failures_by_action(self, action: str) -> list[Failure]:
        """Get failures for a specific action/tool."""
        return [f for f in self._failures if f.action == action]

    def get_recent_failures(self, count: int = 10) -> list[Failure]:
        """Get the most recent failures."""
        return self._failures[-count:]

    def get_failure_context(
        self,
        max_failures: int = 5,
        include_resolved: bool = False,
        include_stack_traces: bool = False,
    ) -> str:
        """Get formatted failure context for LLM injection."""
        failures = (
            self._failures if include_resolved
            else [f for f in self._failures if not f.resolved]
        )

        if not failures:
            return ""

        return format_failure_context(
            failures[-max_failures:],
            include_stack_traces=include_stack_traces,
        )

    def has_recent_failure(self, action: str, within_ms: float = 60000) -> bool:
        """Check if a recent failure exists for an action."""
        cutoff = time.time() - (within_ms / 1000)
        return any(
            f.action == action and f.timestamp >= cutoff
            for f in self._failures
        )

    def get_stats(self) -> dict[str, Any]:
        """Get failure statistics."""
        by_category: dict[str, int] = {}
        action_counts: dict[str, int] = {}

        for f in self._failures:
            by_category[f.category] = by_category.get(f.category, 0) + 1
            action_counts[f.action] = action_counts.get(f.action, 0) + 1

        # Top 5 most-failed actions
        most_failed = sorted(action_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        return {
            "total": len(self._failures),
            "unresolved": sum(1 for f in self._failures if not f.resolved),
            "by_category": by_category,
            "most_failed_actions": most_failed,
        }

    def clear(self) -> None:
        """Clear all failures."""
        self._failures.clear()

    def on(self, listener: FailureEventListener) -> Callable[[], None]:
        """Subscribe to failure events."""
        self._listeners.append(listener)

        def unsubscribe() -> None:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass

        return unsubscribe

    def _detect_patterns(self) -> None:
        """Detect failure patterns."""
        unresolved = [f for f in self._failures if not f.resolved]

        # Repeated action pattern
        action_groups: dict[str, list[Failure]] = {}
        for f in unresolved:
            if f.action not in action_groups:
                action_groups[f.action] = []
            action_groups[f.action].append(f)

        for action, failures in action_groups.items():
            if len(failures) >= 3:
                pattern = FailurePattern(
                    type="repeated_action",
                    description=f"'{action}' has failed {len(failures)} times",
                    failure_ids=[f.id for f in failures],
                    confidence=min(0.9, 0.3 + len(failures) * 0.1),
                    suggestion=f"Consider a different approach than '{action}'",
                )
                self._emit("pattern.detected", {"pattern": pattern})

        # Category cluster pattern
        recent = self._failures[-10:] if len(self._failures) >= 10 else self._failures
        cat_counts: dict[str, list[str]] = {}
        for f in recent:
            if f.category not in cat_counts:
                cat_counts[f.category] = []
            cat_counts[f.category].append(f.id)

        for cat, ids in cat_counts.items():
            if len(ids) >= 5:
                pattern = FailurePattern(
                    type="category_cluster",
                    description=f"{len(ids)} recent '{cat}' failures",
                    failure_ids=ids,
                    confidence=0.7,
                    suggestion=f"Systematic '{cat}' issue detected - investigate root cause",
                )
                self._emit("pattern.detected", {"pattern": pattern})

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        for listener in self._listeners:
            try:
                listener(event, data)
            except Exception:
                pass


def categorize_error(error: str) -> FailureCategory:
    """Categorize an error string."""
    for pattern, category in _CATEGORY_PATTERNS:
        if pattern.search(error):
            return category
    return FailureCategory.UNKNOWN


def generate_suggestion(failure: Failure) -> str:
    """Generate a suggestion based on failure category."""
    suggestions: dict[FailureCategory, str] = {
        FailureCategory.PERMISSION: "Check file permissions or use an allowed alternative.",
        FailureCategory.NOT_FOUND: "Verify the path exists. Use glob/search to find the correct location.",
        FailureCategory.SYNTAX: "Check syntax carefully. Review quoting and escaping.",
        FailureCategory.TYPE: "Check argument types match the expected schema.",
        FailureCategory.NETWORK: "Check network connectivity. Retry with backoff.",
        FailureCategory.TIMEOUT: "Try a simpler command or reduce scope.",
        FailureCategory.VALIDATION: "Check required fields and value constraints.",
        FailureCategory.RESOURCE: "Reduce memory/disk usage or free resources.",
        FailureCategory.RUNTIME: "Review the logic and check for edge cases.",
        FailureCategory.LOGIC: "Re-examine the approach and assumptions.",
    }
    return suggestions.get(failure.category, "Review the error and try a different approach.")


def format_failure_context(
    failures: list[Failure],
    include_stack_traces: bool = False,
) -> str:
    """Format failures for LLM context injection."""
    if not failures:
        return ""

    lines = ["[Previous Failures - Learn from these]"]
    for f in failures:
        status = "resolved" if f.resolved else "unresolved"
        lines.append(f"- [{f.category}] {f.action}: {f.error[:100]} ({status})")
        if f.suggestion:
            lines.append(f"  Suggestion: {f.suggestion}")
        if include_stack_traces and f.stack_trace:
            lines.append(f"  Stack: {f.stack_trace[:200]}")
    return "\n".join(lines)


def create_repeat_warning(action: str, count: int, suggestion: str | None = None) -> str:
    """Create a warning message for repeated failures."""
    msg = f"Warning: '{action}' has failed {count} times."
    if suggestion:
        msg += f" {suggestion}"
    return msg


@dataclass
class FailureCascade:
    """A detected cascade where one failure triggers others."""

    root_failure_id: str
    root_action: str
    downstream_failures: list[str]
    total_impact: int
    description: str


def detect_cascades(failures: list[Failure], time_window_seconds: float = 60.0) -> list[FailureCascade]:
    """Detect failure cascades — sequences of related failures.

    A cascade is when a failure in one action is quickly followed
    by failures in related actions (same file, same module, etc.).
    """
    if len(failures) < 3:
        return []

    cascades: list[FailureCascade] = []
    unresolved = [f for f in failures if not f.resolved]

    for i, root in enumerate(unresolved):
        downstream: list[str] = []
        for j in range(i + 1, len(unresolved)):
            candidate = unresolved[j]
            # Within time window?
            if candidate.timestamp - root.timestamp > time_window_seconds:
                break
            # Related? (same category or args overlap)
            if candidate.category == root.category:
                downstream.append(candidate.id)
            elif root.args and candidate.args:
                # Check for overlapping file paths
                root_files = {v for v in (root.args or {}).values() if isinstance(v, str) and "/" in v}
                cand_files = {v for v in (candidate.args or {}).values() if isinstance(v, str) and "/" in v}
                if root_files & cand_files:
                    downstream.append(candidate.id)

        if len(downstream) >= 2:
            cascades.append(FailureCascade(
                root_failure_id=root.id,
                root_action=root.action,
                downstream_failures=downstream,
                total_impact=1 + len(downstream),
                description=(
                    f"Cascade from '{root.action}' ({root.category}): "
                    f"{len(downstream)} downstream failures within {time_window_seconds}s"
                ),
            ))

    return cascades


def detect_cross_iteration_patterns(
    failures: list[Failure],
    min_iterations_span: int = 3,
) -> list[FailurePattern]:
    """Detect patterns that span multiple iterations.

    Identifies recurring failures across iterations, suggesting
    systemic issues rather than one-off errors.
    """
    patterns: list[FailurePattern] = []
    if not failures:
        return patterns

    # Group by action+category
    groups: dict[str, list[Failure]] = {}
    for f in failures:
        if f.iteration is not None:
            key = f"{f.action}:{f.category}"
            groups.setdefault(key, []).append(f)

    for key, group in groups.items():
        iterations = sorted({f.iteration for f in group if f.iteration is not None})
        if len(iterations) >= min_iterations_span:
            span = iterations[-1] - iterations[0]
            action, category = key.split(":", 1)
            patterns.append(FailurePattern(
                type="cross_iteration",
                description=(
                    f"'{action}' ({category}) failing across {len(iterations)} iterations "
                    f"(span: {span} iterations)"
                ),
                failure_ids=[f.id for f in group],
                confidence=min(0.95, 0.4 + len(iterations) * 0.1),
                suggestion=(
                    f"Systemic '{category}' issue with '{action}'. "
                    "Consider fundamentally changing the approach."
                ),
            ))

    return patterns


def build_failure_summary(
    failures: list[Failure],
    max_lines: int = 10,
) -> str:
    """Build a compact failure summary suitable for system prompts."""
    if not failures:
        return ""

    unresolved = [f for f in failures if not f.resolved]
    if not unresolved:
        return ""

    lines = [f"[{len(unresolved)} unresolved failures]"]

    # Category breakdown
    cats: dict[str, int] = {}
    for f in unresolved:
        cats[f.category] = cats.get(f.category, 0) + 1
    cat_summary = ", ".join(f"{c}: {n}" for c, n in sorted(cats.items(), key=lambda x: -x[1]))
    lines.append(f"Categories: {cat_summary}")

    # Most recent failures (compact)
    for f in unresolved[-min(max_lines - 2, len(unresolved)):]:
        line = f"- {f.action}: {f.error[:60]}"
        if f.suggestion:
            line += f" → {f.suggestion[:40]}"
        lines.append(line)

    return "\n".join(lines)
