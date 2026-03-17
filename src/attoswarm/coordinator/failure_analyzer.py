"""Failure classification and root-cause analysis for swarm tasks.

Taxonomy of failure causes:
- timeout: task exceeded wall-clock limit
- budget: token/cost budget exceeded
- crash: unhandled exception in worker
- dep_failure: upstream dependency failed
- coordination: file claim conflict or OCC error
- agent_error: LLM refusal, malformed output, etc.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class FailureAttribution:
    """Attribution of a task failure to a root cause."""

    task_id: str
    cause: str  # timeout|budget|crash|dep_failure|coordination|agent_error
    confidence: float = 0.0  # 0.0-1.0
    evidence: str = ""
    root_task_id: str = ""  # if caused by another task's failure
    chain: list[str] = field(default_factory=list)  # task_id chain to root

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "cause": self.cause,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "root_task_id": self.root_task_id,
            "chain": self.chain,
        }


# Pattern matchers for error classification
_TIMEOUT_PATTERNS = re.compile(
    r"(?:timed?\s*out|timeout|exceeded.*(?:seconds|timeout|limit)|"
    r"deadline\s*exceeded|watchdog|stale\s*agent)",
    re.IGNORECASE,
)
_BUDGET_PATTERNS = re.compile(
    r"(?:budget\s*exceeded|token\s*limit|cost\s*limit|max_tokens|"
    r"rate\s*limit|quota\s*exceeded)",
    re.IGNORECASE,
)
_CLAIM_PATTERNS = re.compile(
    r"(?:could\s*not\s*claim|OCC\s*conflict|file\s*locked|"
    r"claim\s*failed|concurrent\s*write|merge\s*conflict)",
    re.IGNORECASE,
)
_AGENT_ERROR_PATTERNS = re.compile(
    r"(?:refused|cannot\s*assist|malformed|parse\s*error|JSON|"
    r"invalid\s*response|empty\s*response|no\s*output|API\s*error|"
    r"overloaded|500|503|529)",
    re.IGNORECASE,
)
_CRASH_PATTERNS = re.compile(
    r"(?:traceback|exception|error|segfault|killed|signal|SIGTERM|SIGKILL|"
    r"exit\s*code\s*[^0]|non-zero|panic|abort)",
    re.IGNORECASE,
)


class FailureAnalyzer:
    """Classifies task failures and traces root causes."""

    def classify_failure(
        self,
        task_id: str,
        error_str: str,
        duration_s: float = 0.0,
        tokens_used: int = 0,
    ) -> FailureAttribution:
        """Classify a single task failure by pattern-matching the error string."""
        error = error_str or ""

        # Timeout detection (highest confidence if duration is near limit)
        if _TIMEOUT_PATTERNS.search(error) or duration_s >= 580:
            return FailureAttribution(
                task_id=task_id,
                cause="timeout",
                confidence=0.95 if duration_s >= 580 else 0.8,
                evidence=f"Duration: {duration_s:.0f}s. Error: {error[:200]}",
            )

        # Budget exceeded
        if _BUDGET_PATTERNS.search(error):
            return FailureAttribution(
                task_id=task_id,
                cause="budget",
                confidence=0.9,
                evidence=f"Tokens: {tokens_used}. Error: {error[:200]}",
            )

        # Coordination / OCC conflict
        if _CLAIM_PATTERNS.search(error):
            return FailureAttribution(
                task_id=task_id,
                cause="coordination",
                confidence=0.85,
                evidence=error[:200],
            )

        # Agent error (LLM-level issues)
        if _AGENT_ERROR_PATTERNS.search(error):
            return FailureAttribution(
                task_id=task_id,
                cause="agent_error",
                confidence=0.7,
                evidence=error[:200],
            )

        # Crash (catch-all for unhandled exceptions)
        if _CRASH_PATTERNS.search(error):
            return FailureAttribution(
                task_id=task_id,
                cause="crash",
                confidence=0.6,
                evidence=error[:200],
            )

        # Unknown — default to agent_error with low confidence
        return FailureAttribution(
            task_id=task_id,
            cause="agent_error",
            confidence=0.3,
            evidence=error[:200] if error else "No error details",
        )

    def trace_root_cause(
        self,
        task_id: str,
        aot_graph: Any,
        failure_cache: dict[str, FailureAttribution] | None = None,
    ) -> FailureAttribution:
        """Walk the DAG backwards to find the root cause of a failure.

        Uses memoization via ``failure_cache`` to avoid repeated traversals.
        """
        if failure_cache and task_id in failure_cache:
            return failure_cache[task_id]

        node = aot_graph.get_node(task_id) if aot_graph else None
        if not node:
            return FailureAttribution(task_id=task_id, cause="agent_error", confidence=0.2)

        # Check if this failure was caused by a failed dependency
        chain: list[str] = [task_id]
        for dep_id in node.depends_on:
            dep_node = aot_graph.get_node(dep_id)
            if dep_node and dep_node.status in ("failed", "skipped"):
                # Recurse to find root
                root = self.trace_root_cause(dep_id, aot_graph, failure_cache)
                chain = [task_id] + root.chain
                attr = FailureAttribution(
                    task_id=task_id,
                    cause="dep_failure",
                    confidence=0.9,
                    evidence=f"Caused by failed dependency: {dep_id}",
                    root_task_id=root.root_task_id or dep_id,
                    chain=chain,
                )
                if failure_cache is not None:
                    failure_cache[task_id] = attr
                return attr

        # No failed deps — this is a direct failure
        attr = FailureAttribution(
            task_id=task_id,
            cause="agent_error",
            confidence=0.5,
            root_task_id=task_id,
            chain=chain,
        )
        if failure_cache is not None:
            failure_cache[task_id] = attr
        return attr

    @staticmethod
    def generate_suggestion(attr: FailureAttribution) -> str:
        """Generate an actionable suggestion for a failure."""
        suggestions = {
            "timeout": "Increase task timeout or split into smaller subtasks.",
            "budget": "Increase budget limit or reduce task scope.",
            "crash": "Check worker logs for stack trace. May need error handling.",
            "dep_failure": f"Fix upstream task {attr.root_task_id} first.",
            "coordination": "Reduce file overlap between parallel tasks or serialize.",
            "agent_error": "Review task prompt for clarity. Check model availability.",
        }
        return suggestions.get(attr.cause, "Investigate task logs for details.")
