"""CASTLE Score implementation for rule accuracy evaluation.

The CASTLE Score penalizes false positives proportionally to triage
burden, providing a more realistic measure of rule effectiveness than
raw F1.

Reference: https://arxiv.org/abs/2503.09433

Formula:
    CASTLE_Score = Recall - alpha * FP_Rate

Where alpha depends on severity (triage burden):
    critical/high: alpha = 0.5  (devs tolerate more FPs for critical issues)
    medium:        alpha = 1.0
    low/info:      alpha = 2.0  (devs waste more time triaging low-severity noise)
"""

from __future__ import annotations

from dataclasses import dataclass

from eval.rule_accuracy.runner import RuleAccuracyResult

# Default alpha values by severity
DEFAULT_ALPHA: dict[str, float] = {
    "critical": 0.5,
    "high": 0.5,
    "medium": 1.0,
    "low": 2.0,
    "info": 2.0,
}


@dataclass(slots=True)
class CASTLEResult:
    """CASTLE Score result for a single rule or group."""

    rule_id: str
    recall: float
    fp_rate: float
    alpha: float
    castle_score: float
    severity: str = ""


def compute_castle_score(
    accuracy: RuleAccuracyResult,
    severity: str = "medium",
    alpha: float | None = None,
) -> CASTLEResult:
    """Compute the CASTLE Score for a rule accuracy result.

    Args:
        accuracy: TP/FP/FN/TN counts.
        severity: Rule severity for alpha selection.
        alpha: Override alpha value. If None, uses severity-based default.

    Returns:
        CASTLEResult with recall, FP rate, alpha, and final score.
    """
    if alpha is None:
        alpha = DEFAULT_ALPHA.get(severity.lower(), 1.0)

    # Recall = TP / (TP + FN)
    recall_denom = accuracy.true_positives + accuracy.false_negatives
    recall = accuracy.true_positives / recall_denom if recall_denom > 0 else 0.0

    # FP Rate = FP / (FP + TN)
    fp_denom = accuracy.false_positives + accuracy.true_negatives
    fp_rate = accuracy.false_positives / fp_denom if fp_denom > 0 else 0.0

    castle = recall - alpha * fp_rate

    return CASTLEResult(
        rule_id=accuracy.rule_id,
        recall=recall,
        fp_rate=fp_rate,
        alpha=alpha,
        castle_score=castle,
        severity=severity,
    )


def compute_castle_scores(
    per_rule: dict[str, RuleAccuracyResult],
    rule_severities: dict[str, str] | None = None,
) -> dict[str, CASTLEResult]:
    """Compute CASTLE Scores for all rules.

    Args:
        per_rule: Per-rule accuracy results.
        rule_severities: Map of rule_id -> severity string.

    Returns:
        Map of rule_id -> CASTLEResult.
    """
    results: dict[str, CASTLEResult] = {}
    for rule_id, accuracy in per_rule.items():
        severity = (rule_severities or {}).get(rule_id, "medium")
        results[rule_id] = compute_castle_score(accuracy, severity=severity)
    return results
