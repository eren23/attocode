"""Swarm failure classifier.

Classifies worker failures into actionable categories for retry
and remediation logic. Determines whether failures are retryable
and maps them to appropriate recovery strategies.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from attocode.integrations.swarm.types import TaskFailureMode


class SwarmFailureClass(StrEnum):
    """Classification of swarm worker failures."""

    POLICY_BLOCKED = "policy_blocked"
    INVALID_TOOL_ARGS = "invalid_tool_args"
    MISSING_TARGET_PATH = "missing_target_path"
    PERMISSION_REQUIRED = "permission_required"
    PROVIDER_SPEND_LIMIT = "provider_spend_limit"
    PROVIDER_AUTH = "provider_auth"
    RATE_LIMITED = "rate_limited"
    PROVIDER_TRANSIENT = "provider_transient"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


# Non-retryable failure classes
NON_RETRYABLE: frozenset[SwarmFailureClass] = frozenset({
    SwarmFailureClass.POLICY_BLOCKED,
    SwarmFailureClass.INVALID_TOOL_ARGS,
    SwarmFailureClass.MISSING_TARGET_PATH,
    SwarmFailureClass.PERMISSION_REQUIRED,
    SwarmFailureClass.PROVIDER_SPEND_LIMIT,
    SwarmFailureClass.PROVIDER_AUTH,
})


@dataclass(slots=True)
class FailureClassification:
    """Result of failure classification."""

    failure_class: SwarmFailureClass
    retryable: bool
    error_type: str  # "429", "402", "timeout", "error"
    failure_mode: TaskFailureMode
    reason: str


def _has_any(text: str, patterns: list[str]) -> bool:
    """Case-insensitive check if text contains any pattern."""
    text_lower = text.lower()
    return any(p.lower() in text_lower for p in patterns)


def classify_swarm_failure(
    raw_output: str,
    tool_calls: int | None = None,
) -> FailureClassification:
    """Classify a swarm worker failure into an actionable category.

    Analyzes error messages using pattern matching to determine the
    failure class, whether it's retryable, and the appropriate
    recovery strategy.
    """
    # Rate limited (429)
    if _has_any(raw_output, ["429", "rate limit", "rate_limited", "too many requests"]):
        return FailureClassification(
            failure_class=SwarmFailureClass.RATE_LIMITED,
            retryable=True,
            error_type="429",
            failure_mode=TaskFailureMode.RECOVERABLE,
            reason="Rate limited by provider",
        )

    # Spend limit (402)
    if _has_any(raw_output, ["402", "spend limit", "billing", "payment required", "insufficient_quota"]):
        return FailureClassification(
            failure_class=SwarmFailureClass.PROVIDER_SPEND_LIMIT,
            retryable=False,
            error_type="402",
            failure_mode=TaskFailureMode.TERMINAL,
            reason="Provider spend limit exceeded",
        )

    # Auth errors (401/403)
    if _has_any(raw_output, ["401", "403", "unauthorized", "forbidden", "invalid api key", "authentication"]):
        return FailureClassification(
            failure_class=SwarmFailureClass.PROVIDER_AUTH,
            retryable=False,
            error_type="error",
            failure_mode=TaskFailureMode.TERMINAL,
            reason="Authentication/authorization failure",
        )

    # Timeout
    if _has_any(raw_output, ["timeout", "timed out", "deadline exceeded", "SIGTERM"]):
        return FailureClassification(
            failure_class=SwarmFailureClass.TIMEOUT,
            retryable=True,
            error_type="timeout",
            failure_mode=TaskFailureMode.RECOVERABLE,
            reason="Worker timed out",
        )

    # Policy blocked
    if _has_any(raw_output, ["policy", "blocked by policy", "not allowed", "policy_blocked"]):
        return FailureClassification(
            failure_class=SwarmFailureClass.POLICY_BLOCKED,
            retryable=False,
            error_type="error",
            failure_mode=TaskFailureMode.TERMINAL,
            reason="Action blocked by safety policy",
        )

    # Invalid tool args
    if _has_any(raw_output, ["invalid arguments", "invalid_tool_args", "malformed json", "schema validation"]):
        return FailureClassification(
            failure_class=SwarmFailureClass.INVALID_TOOL_ARGS,
            retryable=False,
            error_type="error",
            failure_mode=TaskFailureMode.TERMINAL,
            reason="Tool arguments invalid",
        )

    # Missing path
    if _has_any(raw_output, ["file not found", "no such file", "ENOENT", "path does not exist"]):
        return FailureClassification(
            failure_class=SwarmFailureClass.MISSING_TARGET_PATH,
            retryable=False,
            error_type="error",
            failure_mode=TaskFailureMode.TERMINAL,
            reason="Target file/path not found",
        )

    # Permission required
    if _has_any(raw_output, ["permission denied", "EACCES", "requires approval", "permission_required"]):
        return FailureClassification(
            failure_class=SwarmFailureClass.PERMISSION_REQUIRED,
            retryable=False,
            error_type="error",
            failure_mode=TaskFailureMode.TERMINAL,
            reason="Permission or approval required",
        )

    # Provider transient (5xx, network)
    if _has_any(raw_output, ["500", "502", "503", "504", "server error", "network error", "connection"]):
        return FailureClassification(
            failure_class=SwarmFailureClass.PROVIDER_TRANSIENT,
            retryable=True,
            error_type="error",
            failure_mode=TaskFailureMode.RECOVERABLE,
            reason="Transient provider/network error",
        )

    # Unknown
    return FailureClassification(
        failure_class=SwarmFailureClass.UNKNOWN,
        retryable=True,  # Default to retryable
        error_type="error",
        failure_mode=TaskFailureMode.RECOVERABLE,
        reason=f"Unclassified failure: {raw_output[:200]}",
    )
