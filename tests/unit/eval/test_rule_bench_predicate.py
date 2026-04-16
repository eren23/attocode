"""Unit tests for the per-language floor predicate."""

from __future__ import annotations

from attoswarm.research.evaluator import EvalResult

from eval.meta_harness.rule_bench.predicate import (
    DEFAULT_FLOOR_RATIO,
    make_rule_accept_predicate,
    rule_accept_predicate,
)


def _result(score: float, per_lang: dict[str, float] | None = None) -> EvalResult:
    md: dict = {}
    if per_lang is not None:
        md["per_language"] = dict(per_lang)
    return EvalResult(metric_value=score, metadata=md, success=True)


class TestRuleAcceptPredicate:
    def test_strict_improvement_no_per_lang_data_accepts(self) -> None:
        # Without per_language metadata the predicate falls back to score check.
        candidate = _result(0.7)
        baseline = _result(0.5)
        accepted, reason = rule_accept_predicate(candidate, baseline, current_best=0.5)
        assert accepted is True
        assert "improved" in reason

    def test_no_improvement_rejected(self) -> None:
        candidate = _result(0.5, {"python": 0.6, "go": 0.5})
        baseline = _result(0.5, {"python": 0.6, "go": 0.5})
        accepted, reason = rule_accept_predicate(candidate, baseline, current_best=0.6)
        assert accepted is False
        assert "no_improvement" in reason

    def test_floor_violation_rejects_even_when_score_up(self) -> None:
        baseline = _result(0.55, {"python": 0.6, "go": 0.5})
        # Composite up, but go drops 30% — floor breached
        candidate = _result(0.65, {"python": 0.95, "go": 0.35})
        accepted, reason = rule_accept_predicate(candidate, baseline, current_best=0.55)
        assert accepted is False
        assert "floor_violation:go" in reason

    def test_per_lang_above_floor_accepts(self) -> None:
        baseline = _result(0.55, {"python": 0.6, "go": 0.5})
        # go drops to 0.48 — within 5% of 0.5 (floor = 0.475), accepted
        candidate = _result(0.6, {"python": 0.72, "go": 0.48})
        accepted, reason = rule_accept_predicate(candidate, baseline, current_best=0.55)
        assert accepted is True
        assert reason == "improved"

    def test_zero_baseline_lang_skipped(self) -> None:
        # Baseline F1=0 for "rust" means there's no signal — never floor-fail
        baseline = _result(0.5, {"python": 0.6, "rust": 0.0})
        candidate = _result(0.7, {"python": 0.7, "rust": 0.0})
        accepted, reason = rule_accept_predicate(candidate, baseline, current_best=0.5)
        assert accepted is True
        assert reason == "improved"

    def test_missing_lang_treated_as_zero_signal(self) -> None:
        # Candidate doesn't expose "go" in per_language → treated as 0 → floor breach
        baseline = _result(0.55, {"python": 0.6, "go": 0.5})
        candidate = _result(0.7, {"python": 0.95})
        accepted, reason = rule_accept_predicate(candidate, baseline, current_best=0.55)
        assert accepted is False
        assert "floor_violation:go" in reason

    def test_custom_floor_ratio(self) -> None:
        # 80% floor — 0.5 * 0.8 = 0.4, so 0.42 should pass
        permissive = make_rule_accept_predicate(floor_ratio=0.8)
        baseline = _result(0.55, {"python": 0.6, "go": 0.5})
        candidate = _result(0.6, {"python": 0.78, "go": 0.42})
        accepted, reason = permissive(candidate, baseline, current_best=0.55)
        assert accepted is True

    def test_default_floor_ratio_is_95_percent(self) -> None:
        assert DEFAULT_FLOOR_RATIO == 0.95
