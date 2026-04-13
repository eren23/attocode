"""Tests for rule profiling and confidence calibration."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest

from attocode.code_intel.rules.profiling import (
    FeedbackStore,
    RuleProfiler,
    RuleStats,
    format_rule_stats,
)


class TestRuleStats:
    def test_calibrated_confidence_insufficient_data(self):
        s = RuleStats(rule_id="r1", true_positives=3, false_positives=1)
        assert s.calibrated_confidence is None  # < 5 samples

    def test_calibrated_confidence_sufficient_data(self):
        s = RuleStats(rule_id="r1", true_positives=8, false_positives=2)
        assert s.calibrated_confidence == pytest.approx(0.8)

    def test_false_positive_rate(self):
        s = RuleStats(rule_id="r1", true_positives=7, false_positives=3)
        assert s.false_positive_rate == pytest.approx(0.3)

    def test_false_positive_rate_no_data(self):
        s = RuleStats(rule_id="r1")
        assert s.false_positive_rate is None


class TestRuleProfiler:
    def test_timing(self):
        p = RuleProfiler()
        p.start("r1")
        time.sleep(0.01)
        p.stop("r1")
        stats = p.get_stats("r1")
        assert "r1" in stats
        assert stats["r1"].total_time_ms > 0

    def test_match_count(self):
        p = RuleProfiler()
        p.record_match("r1")
        p.record_match("r1")
        p.record_match("r1")
        assert p.get_stats("r1")["r1"].match_count == 3

    def test_feedback(self):
        p = RuleProfiler()
        p.record_feedback("r1", is_true_positive=True)
        p.record_feedback("r1", is_true_positive=False)
        s = p.get_stats("r1")["r1"]
        assert s.true_positives == 1
        assert s.false_positives == 1

    def test_get_stats_nonexistent(self):
        p = RuleProfiler()
        assert p.get_stats("nonexistent") == {}

    def test_get_all_stats(self):
        p = RuleProfiler()
        p.record_match("r1")
        p.record_match("r2")
        all_stats = p.get_stats()
        assert "r1" in all_stats
        assert "r2" in all_stats

    def test_stop_without_start(self):
        p = RuleProfiler()
        p.stop("r1")  # should not crash

    def test_reset(self):
        p = RuleProfiler()
        p.record_match("r1")
        p.reset()
        assert p.get_stats() == {}


class TestFeedbackStore:
    def test_record_and_retrieve(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = FeedbackStore(tmpdir)
            store.record("r1", is_true_positive=True)
            store.record("r1", is_true_positive=True)
            store.record("r1", is_true_positive=False)

            fb = store.get_feedback("r1")
            assert fb["tp"] == 2
            assert fb["fp"] == 1

    def test_calibration_threshold(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = FeedbackStore(tmpdir)
            for _ in range(4):
                store.record("r1", is_true_positive=True)
            # 4 samples — not enough
            assert store.get_calibrated_confidence("r1") is None

            store.record("r1", is_true_positive=False)
            # 5 samples — calibrated
            cal = store.get_calibrated_confidence("r1")
            assert cal is not None
            assert cal == pytest.approx(0.8)

    def test_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store1 = FeedbackStore(tmpdir)
            for _ in range(5):
                store1.record("r1", is_true_positive=True)

            # Reload from disk
            store2 = FeedbackStore(tmpdir)
            assert store2.get_calibrated_confidence("r1") == pytest.approx(1.0)

    def test_nonexistent_rule(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = FeedbackStore(tmpdir)
            assert store.get_calibrated_confidence("nonexistent") is None
            fb = store.get_feedback("nonexistent")
            assert fb["tp"] == 0

    def test_corrupt_json_handled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fb_dir = Path(tmpdir) / ".attocode"
            fb_dir.mkdir()
            (fb_dir / "rule_feedback.json").write_text("{bad json")

            store = FeedbackStore(tmpdir)
            assert store.all_feedback() == {}


class TestFormatRuleStats:
    def test_empty_stats(self):
        result = format_rule_stats({})
        assert "No profiling data" in result

    def test_with_stats(self):
        stats = {
            "r1": RuleStats(
                rule_id="r1", total_time_ms=100.5,
                match_count=10, true_positives=8, false_positives=2,
            ),
        }
        result = format_rule_stats(stats)
        assert "r1" in result
        assert "100.5" in result
        assert "10" in result
