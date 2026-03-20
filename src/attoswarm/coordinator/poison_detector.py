"""Poison task detector — identifies fundamentally broken tasks.

A "poison" task is one that will never succeed regardless of retries,
wasting budget and time.  Detection signals:

1. Failure mode variation: 3+ attempts each with DIFFERENT cause
2. Escalating resource usage: each retry uses more tokens but still fails
3. Zero-progress pattern: files_modified empty across all attempts
4. Model-agnostic failure: same error class across different models
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PoisonReport:
    """Report on whether a task is poisonous."""

    task_id: str
    is_poison: bool = False
    reason: str = ""
    recommendation: str = ""  # "skip" | "split" | "increase_timeout" | "change_model"
    signals: list[str] = field(default_factory=list)
    confidence: float = 0.0  # 0.0 - 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "is_poison": self.is_poison,
            "reason": self.reason,
            "recommendation": self.recommendation,
            "signals": self.signals,
            "confidence": round(self.confidence, 3),
        }


class PoisonDetector:
    """Detects fundamentally broken tasks before they burn all retries.

    Usage::

        detector = PoisonDetector(max_varying_failures=3)
        report = detector.check(task_id, attempt_history)
        if report.is_poison:
            skip_task(task_id, reason=report.reason)
    """

    def __init__(self, max_varying_failures: int = 3) -> None:
        self._max_varying = max_varying_failures

    def check(
        self,
        task_id: str,
        attempt_history: list[dict[str, Any]],
    ) -> PoisonReport:
        """Analyze attempt history to determine if a task is poisonous.

        Args:
            task_id: Task identifier.
            attempt_history: List of dicts with keys: attempt, error,
                duration_s, tokens_used, failure_cause, files_modified.
        """
        if len(attempt_history) < 2:
            return PoisonReport(task_id=task_id)

        signals: list[str] = []
        recommendation = ""

        # Signal 1: Failure mode variation (different causes each time)
        causes = [h.get("failure_cause", "") for h in attempt_history if h.get("failure_cause")]
        unique_causes = set(causes)
        if len(unique_causes) >= self._max_varying:
            signals.append(
                f"varying_failures: {len(unique_causes)} different failure causes "
                f"({', '.join(sorted(unique_causes))})"
            )
            recommendation = "skip"

        # Signal 2: Escalating resource usage
        token_series = [h.get("tokens_used", 0) for h in attempt_history]
        if len(token_series) >= 2 and all(t > 0 for t in token_series):
            increasing = all(
                token_series[i] >= token_series[i - 1] * 0.9  # allow 10% variance
                for i in range(1, len(token_series))
            )
            if increasing and token_series[-1] > token_series[0] * 1.5:
                signals.append(
                    f"escalating_tokens: {token_series[0]} -> {token_series[-1]} "
                    f"({token_series[-1] / max(token_series[0], 1):.1f}x)"
                )
                if not recommendation:
                    recommendation = "split"

        # Signal 3: Zero-progress pattern
        all_empty_files = all(
            not h.get("files_modified", [])
            for h in attempt_history
        )
        has_tokens = any(h.get("tokens_used", 0) > 0 for h in attempt_history)
        if all_empty_files and has_tokens and len(attempt_history) >= 2:
            signals.append("zero_progress: no files modified across all attempts despite token usage")
            if not recommendation:
                recommendation = "split"

        # Signal 4: Model-agnostic failure
        models_used = set(h.get("model", "") for h in attempt_history if h.get("model"))
        if len(models_used) >= 2:
            # Check if all models produced same error class
            error_classes = set()
            for h in attempt_history:
                cause = h.get("failure_cause", "")
                if cause:
                    error_classes.add(cause)
            if len(error_classes) == 1:
                signals.append(
                    f"model_agnostic: same failure '{next(iter(error_classes))}' "
                    f"across {len(models_used)} models"
                )
                if not recommendation:
                    recommendation = "skip"

        # Determine if poisonous
        is_poison = len(signals) >= 2 or (
            len(signals) == 1 and "zero_progress" in signals[0]
        )

        # Calculate confidence from signal count and strength
        confidence = min(1.0, len(signals) * 0.35)
        if is_poison and len(attempt_history) >= 3:
            confidence = min(1.0, confidence + 0.15)

        if not recommendation:
            recommendation = "skip" if is_poison else ""

        reason = "; ".join(signals) if signals else ""

        return PoisonReport(
            task_id=task_id,
            is_poison=is_poison,
            reason=reason,
            recommendation=recommendation,
            signals=signals,
            confidence=confidence,
        )
