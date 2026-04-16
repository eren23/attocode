"""Per-language floor predicate for the rule-bench harness.

A candidate is accepted only when:

1. Its composite score strictly improves on the current best, AND
2. No language drops below 95% of its baseline F1.

This guards against the "win-Python-break-Go" pattern observed in the
search-bench experiments — global improvements that hide a regression
on one language. The 5% slack accounts for measurement noise.
"""

from __future__ import annotations

from typing import Any

from attoswarm.research.evaluator import EvalResult

# Default slack: a candidate may dip up to 5% below the per-language
# baseline before being rejected. Tuneable via ``floor_ratio`` arg.
DEFAULT_FLOOR_RATIO = 0.95


def make_rule_accept_predicate(floor_ratio: float = DEFAULT_FLOOR_RATIO):
    """Build an accept predicate closure with a configurable floor.

    Returned predicate signature matches ``AcceptPredicate`` in
    :mod:`eval.meta_harness.meta_loop`.
    """

    def predicate(
        result: EvalResult,
        baseline_result: EvalResult | None,
        current_best: float,
    ) -> tuple[bool, str]:
        score = result.metric_value

        # Pull per-language scalars off the candidate result. Missing means
        # the evaluator didn't populate them — fall back to strict score check.
        candidate_per_lang: dict[str, float] = {}
        if result.metadata:
            raw = result.metadata.get("per_language") or {}
            if isinstance(raw, dict):
                candidate_per_lang = {
                    str(k): float(v) for k, v in raw.items()
                }

        baseline_per_lang: dict[str, float] = {}
        if baseline_result is not None and baseline_result.metadata:
            raw = baseline_result.metadata.get("per_language") or {}
            if isinstance(raw, dict):
                baseline_per_lang = {
                    str(k): float(v) for k, v in raw.items()
                }

        # Floor check first — a regression on any language is a hard reject
        # even if the global score went up.
        for lang, base_f1 in baseline_per_lang.items():
            if base_f1 <= 0.0:
                continue  # nothing to floor against
            floor = base_f1 * floor_ratio
            cand_f1 = candidate_per_lang.get(lang, 0.0)
            if cand_f1 < floor:
                return (
                    False,
                    f"floor_violation:{lang} {cand_f1:.4f} < {floor:.4f} "
                    f"(baseline {base_f1:.4f})",
                )

        if score <= current_best:
            return (
                False,
                f"no_improvement: {score:.4f} <= {current_best:.4f}",
            )

        return True, "improved"

    return predicate


# Convenience alias for the default 5% floor.
rule_accept_predicate = make_rule_accept_predicate()


def _stub_eval_result(
    *,
    metric_value: float,
    per_language: dict[str, float] | None = None,
) -> EvalResult:
    """Test helper — build an EvalResult with the metadata shape we expect."""
    metadata: dict[str, Any] = {}
    if per_language is not None:
        metadata["per_language"] = dict(per_language)
    return EvalResult(metric_value=metric_value, metadata=metadata, success=True)
