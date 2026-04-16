"""Unit tests for rule-bench scoring (severity-weighted F1, per-language agg)."""

from __future__ import annotations

import math

import pytest

from eval.meta_harness.rule_bench.scoring import (
    DEFAULT_SEVERITY_WEIGHTS,
    LanguageScore,
    RuleScore,
    aggregate_per_language,
    compute_composite,
    severity_weighted_f1,
)


def _approx(value: float) -> float:
    return round(value, 4)


class TestSeverityWeightedF1:
    def test_perfect_recall_perfect_precision(self) -> None:
        precision, recall, f1 = severity_weighted_f1(10.0, 0.0, 0.0)
        assert precision == 1.0
        assert recall == 1.0
        assert f1 == 1.0

    def test_zero_inputs_no_division_error(self) -> None:
        precision, recall, f1 = severity_weighted_f1(0.0, 0.0, 0.0)
        assert precision == 0.0
        assert recall == 0.0
        assert f1 == 0.0

    def test_only_false_positives(self) -> None:
        precision, recall, f1 = severity_weighted_f1(0.0, 5.0, 0.0)
        assert precision == 0.0
        assert recall == 0.0  # no positives to recall
        assert f1 == 0.0

    def test_only_false_negatives(self) -> None:
        precision, recall, f1 = severity_weighted_f1(0.0, 0.0, 5.0)
        assert precision == 0.0
        assert recall == 0.0
        assert f1 == 0.0

    def test_balanced_known_values(self) -> None:
        # 6 TP, 2 FP, 4 FN → precision = 6/8 = 0.75, recall = 6/10 = 0.6,
        # F1 = 2*0.75*0.6 / 1.35 = 0.6667
        precision, recall, f1 = severity_weighted_f1(6.0, 2.0, 4.0)
        assert math.isclose(precision, 0.75)
        assert math.isclose(recall, 0.6)
        assert math.isclose(f1, 2 * 0.75 * 0.6 / (0.75 + 0.6))


class TestAggregatePerLanguage:
    def test_empty_input_returns_empty(self) -> None:
        result = aggregate_per_language({})
        assert result == {}

    def test_single_rule_single_language(self) -> None:
        rules = {
            "py-foo": RuleScore(
                rule_id="py-foo", pack="python", language="python",
                severity="high", tp=3, fp=1, fn=2,
            ),
        }
        per_lang = aggregate_per_language(rules)
        assert set(per_lang.keys()) == {"python"}

        score = per_lang["python"]
        # high weight = 3.0, so tp_w = 9, fp_w = 3, fn_w = 6
        assert score.true_positives_weighted == 9.0
        assert score.false_positives_weighted == 3.0
        assert score.false_negatives_weighted == 6.0
        # precision = 9/(9+3) = 0.75, recall = 9/(9+6) = 0.6, F1 = 0.667
        assert math.isclose(score.precision, 0.75)
        assert math.isclose(score.recall, 0.6)
        assert math.isclose(score.weighted_f1, 2 * 0.75 * 0.6 / 1.35)
        assert score.rule_count == 1

    def test_critical_rule_outweighs_info_rule(self) -> None:
        # Critical rule (weight 4) with same TP/FN as info rule (weight 0.5)
        # should dominate the language score.
        rules = {
            "py-critical": RuleScore(
                rule_id="py-critical", pack="python", language="python",
                severity="critical", tp=2, fp=0, fn=0,
            ),
            "py-info": RuleScore(
                rule_id="py-info", pack="python", language="python",
                severity="info", tp=0, fp=0, fn=2,
            ),
        }
        per_lang = aggregate_per_language(rules)
        score = per_lang["python"]
        # tp_w = 2*4 = 8, fn_w = 2*0.5 = 1
        assert score.true_positives_weighted == 8.0
        assert score.false_negatives_weighted == 1.0
        # recall = 8/9 = 0.889 — info-rule misses barely register
        assert math.isclose(score.recall, 8.0 / 9.0)

    def test_multiple_languages_buckets_correctly(self) -> None:
        rules = {
            "py-r": RuleScore("py-r", "python", "python", "high", tp=3, fp=0, fn=1),
            "go-r": RuleScore("go-r", "go", "go", "medium", tp=2, fp=1, fn=1),
        }
        per_lang = aggregate_per_language(rules)
        assert set(per_lang.keys()) == {"python", "go"}
        assert per_lang["python"].rule_count == 1
        assert per_lang["go"].rule_count == 1

    def test_universal_rule_buckets_under_star(self) -> None:
        rules = {
            "any-r": RuleScore("any-r", "core", "", "high", tp=1, fp=0, fn=0),
        }
        per_lang = aggregate_per_language(rules)
        assert "*" in per_lang

    def test_zero_signal_rules_excluded(self) -> None:
        # A rule with no findings/expectations should not contribute.
        rules = {
            "py-real": RuleScore("py-real", "python", "python", "high", tp=1, fp=0, fn=0),
            "py-noise": RuleScore("py-noise", "python", "python", "high", tp=0, fp=0, fn=0),
        }
        per_lang = aggregate_per_language(rules)
        assert per_lang["python"].rule_count == 1

    def test_custom_severity_weights(self) -> None:
        rules = {
            "py-r": RuleScore("py-r", "python", "python", "high", tp=2, fp=0, fn=0),
        }
        # Custom weight: high = 10x
        per_lang = aggregate_per_language(rules, severity_weights={"high": 10.0})
        assert per_lang["python"].true_positives_weighted == 20.0


class TestComputeComposite:
    def test_empty_returns_zero(self) -> None:
        assert compute_composite({}) == 0.0

    def test_macro_average(self) -> None:
        per_lang = {
            "python": LanguageScore(language="python", weighted_f1=0.8),
            "go": LanguageScore(language="go", weighted_f1=0.6),
        }
        # Mean = 0.7 (macro, not weighted by rule count)
        assert math.isclose(compute_composite(per_lang), 0.7)

    def test_three_languages_macro(self) -> None:
        per_lang = {
            "python": LanguageScore(language="python", weighted_f1=0.9),
            "go": LanguageScore(language="go", weighted_f1=0.5),
            "rust": LanguageScore(language="rust", weighted_f1=0.7),
        }
        assert math.isclose(compute_composite(per_lang), (0.9 + 0.5 + 0.7) / 3)


class TestDefaults:
    def test_severity_weight_ordering(self) -> None:
        # critical > high > medium > low > info
        assert (
            DEFAULT_SEVERITY_WEIGHTS["critical"]
            > DEFAULT_SEVERITY_WEIGHTS["high"]
            > DEFAULT_SEVERITY_WEIGHTS["medium"]
            > DEFAULT_SEVERITY_WEIGHTS["low"]
            > DEFAULT_SEVERITY_WEIGHTS["info"]
        )

    def test_critical_is_4x_low(self) -> None:
        assert DEFAULT_SEVERITY_WEIGHTS["critical"] == 4 * DEFAULT_SEVERITY_WEIGHTS["low"]
