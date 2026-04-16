"""Severity-weighted scoring for the rule-bench harness.

We measure rule effectiveness as severity-weighted F1, then macro-average
across languages so a pack with one rule per language doesn't get drowned
out by a pack with twenty rules in another language. The composite score
fed to the optimizer is the macro mean of per-language F1s.

Why severity weighting:
    A missed ``critical`` security rule (FN) is much more painful than a
    missed ``info`` style nit. We weight precision and recall numerators
    + denominators by per-finding severity weight so the score reflects
    real-world impact rather than raw counts.

The companion floor predicate (see ``predicate.py``, Step 5) further
guards against per-language regressions: a candidate that improves the
mean composite while degrading any single language below 95% of baseline
is rejected.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from attocode.code_intel.rules.model import RuleSeverity

# Defaults match the brainstorming decision: critical 4x, high 3x,
# medium 2x, low 1x, info 0.5x.
DEFAULT_SEVERITY_WEIGHTS: dict[str, float] = {
    RuleSeverity.CRITICAL.value: 4.0,
    RuleSeverity.HIGH.value: 3.0,
    RuleSeverity.MEDIUM.value: 2.0,
    RuleSeverity.LOW.value: 1.0,
    RuleSeverity.INFO.value: 0.5,
}


@dataclass(slots=True)
class RuleScore:
    """Per-rule TP/FP/FN counts plus a weighted F1."""

    rule_id: str
    pack: str
    language: str
    severity: str  # RuleSeverity value
    tp: int = 0
    fp: int = 0
    fn: int = 0
    weighted_f1: float = 0.0
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "pack": self.pack,
            "language": self.language,
            "severity": self.severity,
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "weighted_f1": round(self.weighted_f1, 4),
            "enabled": self.enabled,
        }


@dataclass(slots=True)
class LanguageScore:
    """Per-language aggregate with severity-weighted F1."""

    language: str
    weighted_f1: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    true_positives_weighted: float = 0.0
    false_positives_weighted: float = 0.0
    false_negatives_weighted: float = 0.0
    rule_count: int = 0
    fixture_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "weighted_f1": round(self.weighted_f1, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "true_positives_weighted": round(self.true_positives_weighted, 3),
            "false_positives_weighted": round(self.false_positives_weighted, 3),
            "false_negatives_weighted": round(self.false_negatives_weighted, 3),
            "rule_count": self.rule_count,
            "fixture_count": self.fixture_count,
        }


@dataclass(slots=True)
class RuleBenchResult:
    """Full rule-bench evaluation output."""

    composite_score: float = 0.0
    weighted_f1: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    per_language: dict[str, LanguageScore] = field(default_factory=dict)
    per_rule: dict[str, RuleScore] = field(default_factory=dict)
    fixtures_total: int = 0
    annotations_total: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "composite_score": round(self.composite_score, 4),
            "weighted_f1": round(self.weighted_f1, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "per_language": {
                lang: score.to_dict() for lang, score in self.per_language.items()
            },
            "per_rule": {
                rule_id: score.to_dict() for rule_id, score in self.per_rule.items()
            },
            "fixtures_total": self.fixtures_total,
            "annotations_total": self.annotations_total,
        }

    def per_language_scalars(self) -> dict[str, float]:
        """Flat ``{language: weighted_f1}`` map for the floor predicate."""
        return {lang: score.weighted_f1 for lang, score in self.per_language.items()}


def severity_weighted_f1(
    tp_weighted: float,
    fp_weighted: float,
    fn_weighted: float,
) -> tuple[float, float, float]:
    """Compute (precision, recall, F1) from severity-weighted counts.

    Returns ``(0.0, 0.0, 0.0)`` cleanly when there's nothing to score —
    callers can rely on this never raising on empty corpora.
    """
    precision_denom = tp_weighted + fp_weighted
    precision = tp_weighted / precision_denom if precision_denom > 0 else 0.0

    recall_denom = tp_weighted + fn_weighted
    recall = tp_weighted / recall_denom if recall_denom > 0 else 0.0

    pr_sum = precision + recall
    f1 = 2 * precision * recall / pr_sum if pr_sum > 0 else 0.0
    return precision, recall, f1


def aggregate_per_language(
    rule_scores: dict[str, RuleScore],
    *,
    severity_weights: dict[str, float] | None = None,
    fixture_counts_by_language: dict[str, int] | None = None,
) -> dict[str, LanguageScore]:
    """Aggregate per-rule scores into per-language buckets.

    Each rule contributes its TP/FP/FN counts weighted by its own severity
    so a critical rule with 1 missed positive hurts more than an info rule
    with 4 missed positives.
    """
    weights = severity_weights or DEFAULT_SEVERITY_WEIGHTS
    fixture_counts = fixture_counts_by_language or {}

    by_lang: dict[str, LanguageScore] = {}
    rule_counts_by_lang: dict[str, int] = defaultdict(int)
    tp_w: dict[str, float] = defaultdict(float)
    fp_w: dict[str, float] = defaultdict(float)
    fn_w: dict[str, float] = defaultdict(float)

    for score in rule_scores.values():
        # Skip rules with no fixtures hitting them — they have no signal
        if score.tp + score.fp + score.fn == 0:
            continue
        weight = weights.get(score.severity, 1.0)
        # Universal rules (empty language) bucket under "*"
        lang = score.language or "*"
        rule_counts_by_lang[lang] += 1
        tp_w[lang] += score.tp * weight
        fp_w[lang] += score.fp * weight
        fn_w[lang] += score.fn * weight

    for lang in rule_counts_by_lang:
        precision, recall, f1 = severity_weighted_f1(tp_w[lang], fp_w[lang], fn_w[lang])
        by_lang[lang] = LanguageScore(
            language=lang,
            weighted_f1=f1,
            precision=precision,
            recall=recall,
            true_positives_weighted=tp_w[lang],
            false_positives_weighted=fp_w[lang],
            false_negatives_weighted=fn_w[lang],
            rule_count=rule_counts_by_lang[lang],
            fixture_count=fixture_counts.get(lang, 0),
        )

    return by_lang


def compute_composite(per_language: dict[str, LanguageScore]) -> float:
    """Macro-average per-language F1.

    Macro (not micro) so a sparsely-populated language can't be ignored
    just because it has fewer fixtures. Universal-rule scores ("*") are
    folded into the average too — they apply to every file.
    """
    if not per_language:
        return 0.0
    return sum(s.weighted_f1 for s in per_language.values()) / len(per_language)
