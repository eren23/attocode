"""Tests for rule accuracy benchmark modules."""
from __future__ import annotations

import tempfile
import json
from pathlib import Path

import pytest

from eval.rule_accuracy.runner import RuleAccuracyResult, BenchmarkResult
from eval.rule_accuracy.castle_score import (
    compute_castle_score,
    compute_castle_scores,
    CASTLEResult,
)
from eval.rule_accuracy.calibration import (
    compute_calibration,
    format_calibration_report,
    CalibrationResult,
)
from eval.rule_accuracy.regression import (
    save_baseline,
    load_baseline,
    check_regression,
)


# ---------------------------------------------------------------------------
# TestRuleAccuracyResult
# ---------------------------------------------------------------------------


class TestRuleAccuracyResult:
    """Test precision / recall / F1 calculations on RuleAccuracyResult."""

    def test_basic_metrics(self):
        r = RuleAccuracyResult(
            rule_id="test",
            true_positives=8,
            false_positives=2,
            false_negatives=3,
        )
        assert r.precision == pytest.approx(0.8)
        assert r.recall == pytest.approx(8 / 11)  # 0.7272...
        assert r.f1 == pytest.approx(2 * 0.8 * (8 / 11) / (0.8 + 8 / 11), rel=1e-3)

    def test_zero_denominator(self):
        r = RuleAccuracyResult(
            rule_id="empty",
            true_positives=0,
            false_positives=0,
            false_negatives=0,
        )
        assert r.precision == 0.0
        assert r.recall == 0.0
        assert r.f1 == 0.0


# ---------------------------------------------------------------------------
# TestCASTLEScore
# ---------------------------------------------------------------------------


class TestCASTLEScore:
    """Test the CASTLE Score computation."""

    def test_perfect_recall_no_fp(self):
        acc = RuleAccuracyResult(
            rule_id="perfect",
            true_positives=10,
            false_negatives=0,
            false_positives=0,
            true_negatives=5,
        )
        result = compute_castle_score(acc, severity="medium")
        # recall = 10/10 = 1.0, fp_rate = 0/(0+5) = 0.0
        assert result.castle_score == pytest.approx(1.0)
        assert result.recall == pytest.approx(1.0)
        assert result.fp_rate == pytest.approx(0.0)

    def test_all_fps(self):
        acc = RuleAccuracyResult(
            rule_id="noisy",
            true_positives=0,
            false_negatives=5,
            false_positives=10,
            true_negatives=0,
        )
        result = compute_castle_score(acc, severity="medium")
        # recall = 0/(0+5) = 0.0, fp_rate = 10/(10+0) = 1.0
        # castle = 0.0 - 1.0 * 1.0 = -1.0
        assert result.recall == pytest.approx(0.0)
        assert result.fp_rate == pytest.approx(1.0)
        assert result.castle_score < 0

    def test_explicit_alpha(self):
        acc = RuleAccuracyResult(
            rule_id="custom",
            true_positives=8,
            false_negatives=2,
            false_positives=3,
            true_negatives=7,
        )
        result = compute_castle_score(acc, alpha=0.5)
        # recall = 8/10 = 0.8, fp_rate = 3/10 = 0.3
        # castle = 0.8 - 0.5 * 0.3 = 0.65
        assert result.recall == pytest.approx(0.8)
        assert result.fp_rate == pytest.approx(0.3)
        assert result.castle_score == pytest.approx(0.65)
        assert result.alpha == 0.5

    def test_compute_castle_scores_multiple_rules(self):
        per_rule = {
            "rule-a": RuleAccuracyResult(
                rule_id="rule-a",
                true_positives=10,
                false_negatives=0,
                false_positives=0,
                true_negatives=5,
            ),
            "rule-b": RuleAccuracyResult(
                rule_id="rule-b",
                true_positives=5,
                false_negatives=5,
                false_positives=5,
                true_negatives=5,
            ),
        }
        results = compute_castle_scores(per_rule, rule_severities={"rule-a": "high", "rule-b": "low"})
        assert "rule-a" in results
        assert "rule-b" in results
        assert results["rule-a"].castle_score == pytest.approx(1.0)
        # rule-b: recall=0.5, fp_rate=0.5, alpha=2.0 (low) => 0.5 - 2.0*0.5 = -0.5
        assert results["rule-b"].castle_score == pytest.approx(-0.5)


# ---------------------------------------------------------------------------
# TestCalibration
# ---------------------------------------------------------------------------


class TestCalibration:
    """Test confidence calibration measurement."""

    def test_empty_input(self):
        result = compute_calibration([])
        assert result.ece == 0.0
        assert result.total_findings == 0

    def test_imperfect_calibration(self):
        # All assigned confidence=0.9, but one is FP.
        # They all land in the [0.8, 0.9] or [0.9, 1.0] bin.
        # Actual accuracy = 2/3 ≈ 0.667, expected midpoint is 0.95.
        # Gap is significant → ECE > 0.
        findings = [(0.9, True), (0.9, True), (0.9, False)]
        result = compute_calibration(findings)
        assert result.ece > 0
        assert result.total_findings == 3

    def test_format_report_contains_ece(self):
        result = compute_calibration([(0.5, True), (0.5, False)])
        report = format_calibration_report(result)
        assert isinstance(report, str)
        assert "ECE" in report

    def test_is_well_calibrated(self):
        # Perfectly calibrated: confidence 0.95, both are TP
        # They fall in bin 9 (0.9-1.0), actual accuracy=1.0, expected=0.95
        # gap = 0.05, weighted ECE = (2/2)*0.05 = 0.05 < 0.10
        result = compute_calibration([(0.95, True), (0.95, True)])
        assert result.is_well_calibrated is True


# ---------------------------------------------------------------------------
# TestRegression
# ---------------------------------------------------------------------------


class TestRegression:
    """Test regression detection against baseline snapshots."""

    def test_save_and_load_roundtrip(self, tmp_path: Path):
        benchmark = BenchmarkResult()
        benchmark.per_rule["rule-x"] = RuleAccuracyResult(
            rule_id="rule-x",
            true_positives=9,
            false_positives=1,
            false_negatives=2,
        )
        baseline_path = tmp_path / "baseline.json"
        save_baseline(benchmark, path=baseline_path)
        loaded = load_baseline(baseline_path)
        assert "rule-x" in loaded
        assert loaded["rule-x"]["tp"] == 9
        assert loaded["rule-x"]["fp"] == 1
        assert loaded["rule-x"]["fn"] == 2
        assert loaded["rule-x"]["f1"] == pytest.approx(
            benchmark.per_rule["rule-x"].f1, abs=1e-3
        )

    def test_load_nonexistent(self, tmp_path: Path):
        loaded = load_baseline(tmp_path / "nope.json")
        assert loaded == {}

    def test_load_corrupt_json(self, tmp_path: Path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{invalid json!!!", encoding="utf-8")
        loaded = load_baseline(bad_file)
        assert loaded == {}

    def test_detect_f1_regression(self, tmp_path: Path):
        # Baseline: rule-a has f1=0.9
        baseline = BenchmarkResult()
        baseline.per_rule["rule-a"] = RuleAccuracyResult(
            rule_id="rule-a",
            true_positives=9,
            false_positives=1,
            false_negatives=1,
        )
        baseline_path = tmp_path / "baseline.json"
        save_baseline(baseline, path=baseline_path)

        # Current: rule-a has worse metrics (f1 ~ 0.727)
        current = BenchmarkResult()
        current.per_rule["rule-a"] = RuleAccuracyResult(
            rule_id="rule-a",
            true_positives=8,
            false_positives=2,
            false_negatives=3,
        )
        messages = check_regression(current, baseline_path=baseline_path, f1_threshold=0.05)
        regression_msgs = [m for m in messages if "REGRESSION" in m]
        assert len(regression_msgs) >= 1
        assert "rule-a" in regression_msgs[0]

    def test_detect_fp_increase(self, tmp_path: Path):
        # Baseline: rule-b has fp=1
        baseline = BenchmarkResult()
        baseline.per_rule["rule-b"] = RuleAccuracyResult(
            rule_id="rule-b",
            true_positives=9,
            false_positives=1,
            false_negatives=1,
        )
        baseline_path = tmp_path / "baseline.json"
        save_baseline(baseline, path=baseline_path)

        # Current: rule-b has fp=5 (increase)
        current = BenchmarkResult()
        current.per_rule["rule-b"] = RuleAccuracyResult(
            rule_id="rule-b",
            true_positives=9,
            false_positives=5,
            false_negatives=1,
        )
        messages = check_regression(current, baseline_path=baseline_path)
        fp_msgs = [m for m in messages if "FP INCREASE" in m]
        assert len(fp_msgs) >= 1
        assert "rule-b" in fp_msgs[0]

    def test_no_baseline_message(self, tmp_path: Path):
        current = BenchmarkResult()
        current.per_rule["rule-c"] = RuleAccuracyResult(
            rule_id="rule-c",
            true_positives=5,
            false_positives=0,
            false_negatives=0,
        )
        messages = check_regression(current, baseline_path=tmp_path / "missing.json")
        assert len(messages) == 1
        assert "baseline" in messages[0].lower()
