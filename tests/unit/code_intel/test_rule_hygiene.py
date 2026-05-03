"""Tests for rule hygiene — auto-prune dead/noisy rules + drift reporting."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import pytest

from attocode.code_intel.rules.hygiene import (
    DEFAULT_MIN_SAMPLES,
    DEFAULT_MIN_SCANS,
    apply_hygiene,
    apply_persistent_disable,
    compute_hygiene,
    format_hygiene_report,
)
from attocode.code_intel.rules.model import (
    RuleCategory,
    RuleSeverity,
    RuleSource,
    RuleTier,
    UnifiedRule,
)
from attocode.code_intel.rules.profiling import FeedbackStore
from attocode.code_intel.rules.registry import RuleRegistry


def _rule(qid: str, *, confidence: float = 0.8) -> UnifiedRule:
    """Build a minimal UnifiedRule under pack 'test' so qualified_id == 'test/<qid>'."""
    return UnifiedRule(
        id=qid,
        name=qid,
        description="",
        severity=RuleSeverity.MEDIUM,
        category=RuleCategory.SUSPICIOUS,
        pattern=re.compile(r"x"),
        source=RuleSource.USER,
        tier=RuleTier.REGEX,
        confidence=confidence,
        pack="test",
    )


@pytest.fixture
def project_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp


@pytest.fixture
def registry():
    reg = RuleRegistry()
    reg.register(_rule("dead-rule"))
    reg.register(_rule("noisy-rule"))
    reg.register(_rule("drifty-rule", confidence=0.9))
    reg.register(_rule("healthy-rule"))
    return reg


class TestFeedbackStoreSession:
    def test_record_session_increments_scans_and_matches(self, project_dir):
        store = FeedbackStore(project_dir)
        store.record_session(
            rule_ids=["a", "b"],
            matches={"a": 3},
            files_scanned=12,
        )
        assert store.get_scan_count("a") == 1
        assert store.get_match_count("a") == 3
        assert store.get_scan_count("b") == 1
        assert store.get_match_count("b") == 0

        store.record_session(rule_ids=["a"], matches={"a": 2})
        assert store.get_scan_count("a") == 2
        assert store.get_match_count("a") == 5

    def test_record_session_persists_across_instances(self, project_dir):
        FeedbackStore(project_dir).record_session(
            rule_ids=["a"], matches={"a": 1}, files_scanned=4,
        )
        # New instance — must read persisted state.
        again = FeedbackStore(project_dir)
        assert again.get_scan_count("a") == 1
        assert again.get_match_count("a") == 1

    def test_disable_roundtrip(self, project_dir):
        store = FeedbackStore(project_dir)
        store.set_disabled("a", "dead")
        assert store.is_disabled("a") is True
        assert store.get_disabled_reason("a") == "dead"

        store.clear_disabled("a")
        assert store.is_disabled("a") is False

    def test_record_feedback_still_works_with_extended_schema(self, project_dir):
        store = FeedbackStore(project_dir)
        for _ in range(3):
            store.record("a", is_true_positive=True)
        for _ in range(2):
            store.record("a", is_true_positive=False)
        assert store.get_calibrated_confidence("a") == pytest.approx(0.6)
        assert store.get_feedback("a") == {"tp": 3, "fp": 2}


class TestComputeHygiene:
    def test_dead_rule_detected(self, project_dir, registry):
        store = FeedbackStore(project_dir)
        for _ in range(DEFAULT_MIN_SCANS):
            store.record_session(rule_ids=["test/dead-rule"], matches={})

        report = compute_hygiene(store, registry)
        assert {e.rule_id for e in report.dead} == {"test/dead-rule"}
        assert report.noisy == []

    def test_below_min_scans_not_dead(self, project_dir, registry):
        store = FeedbackStore(project_dir)
        for _ in range(DEFAULT_MIN_SCANS - 1):
            store.record_session(rule_ids=["test/dead-rule"], matches={})

        report = compute_hygiene(store, registry)
        assert report.dead == []

    def test_noisy_rule_detected(self, project_dir, registry):
        store = FeedbackStore(project_dir)
        # 2 TP, 8 FP -> 80% FP rate, well above threshold
        for _ in range(2):
            store.record("test/noisy-rule", is_true_positive=True)
        for _ in range(8):
            store.record("test/noisy-rule", is_true_positive=False)

        report = compute_hygiene(store, registry)
        assert {e.rule_id for e in report.noisy} == {"test/noisy-rule"}

    def test_below_min_samples_not_noisy(self, project_dir, registry):
        store = FeedbackStore(project_dir)
        for _ in range(DEFAULT_MIN_SAMPLES - 1):
            store.record("test/noisy-rule", is_true_positive=False)

        report = compute_hygiene(store, registry)
        assert report.noisy == []

    def test_drift_detected(self, project_dir, registry):
        store = FeedbackStore(project_dir)
        # Declared confidence on 'drifty-rule' is 0.9.
        # Calibrated will be 0.5 from 5 TP / 5 FP -> delta 0.4 > 0.2.
        for _ in range(5):
            store.record("test/drifty-rule", is_true_positive=True)
        for _ in range(5):
            store.record("test/drifty-rule", is_true_positive=False)

        report = compute_hygiene(store, registry)
        # Above the 50% FP threshold? 5/10 = 0.5 — not strictly above, so not noisy.
        assert report.noisy == []
        assert {e.rule_id for e in report.drift} == {"test/drifty-rule"}

    def test_healthy_rule_not_flagged(self, project_dir, registry):
        store = FeedbackStore(project_dir)
        # Healthy: lots of matches, mostly TPs.
        for _ in range(DEFAULT_MIN_SCANS):
            store.record_session(
                rule_ids=["test/healthy-rule"], matches={"test/healthy-rule": 3},
            )
        for _ in range(8):
            store.record("test/healthy-rule", is_true_positive=True)
        for _ in range(2):
            store.record("test/healthy-rule", is_true_positive=False)

        report = compute_hygiene(store, registry)
        assert all(e.rule_id != "test/healthy-rule" for e in report.dead)
        assert all(e.rule_id != "test/healthy-rule" for e in report.noisy)
        assert all(e.rule_id != "test/healthy-rule" for e in report.drift)


class TestApplyHygiene:
    def test_apply_disables_dead_and_noisy_only(self, project_dir, registry):
        store = FeedbackStore(project_dir)
        for _ in range(DEFAULT_MIN_SCANS):
            store.record_session(rule_ids=["test/dead-rule"], matches={})
        for _ in range(2):
            store.record("test/noisy-rule", is_true_positive=True)
        for _ in range(8):
            store.record("test/noisy-rule", is_true_positive=False)
        # Drift only — should NOT auto-disable.
        for _ in range(5):
            store.record("test/drifty-rule", is_true_positive=True)
        for _ in range(5):
            store.record("test/drifty-rule", is_true_positive=False)

        report = compute_hygiene(store, registry)
        disabled = apply_hygiene(report, registry, store)

        assert disabled == 2
        assert registry.get("test/dead-rule").enabled is False
        assert registry.get("test/dead-rule").disabled_reason == "dead"
        assert registry.get("test/noisy-rule").enabled is False
        assert registry.get("test/noisy-rule").disabled_reason == "noisy"
        # Drift untouched.
        assert registry.get("test/drifty-rule").enabled is True
        # Persistence.
        assert store.is_disabled("test/dead-rule")
        assert store.get_disabled_reason("test/dead-rule") == "dead"

    def test_persistent_disable_reapplied_on_load(self, project_dir, registry):
        store = FeedbackStore(project_dir)
        store.set_disabled("test/dead-rule", "dead")
        store.set_disabled("test/noisy-rule", "noisy")

        # Fresh registry simulating server restart.
        fresh = RuleRegistry()
        fresh.register(_rule("dead-rule"))
        fresh.register(_rule("noisy-rule"))
        fresh.register(_rule("healthy-rule"))

        touched = apply_persistent_disable(fresh, FeedbackStore(project_dir))
        assert touched == 2
        assert fresh.get("test/dead-rule").enabled is False
        assert fresh.get("test/dead-rule").disabled_reason == "dead"
        assert fresh.get("test/healthy-rule").enabled is True


class TestFormatHygieneReport:
    def test_empty_report_returns_clean_message(self, project_dir, registry):
        store = FeedbackStore(project_dir)
        report = compute_hygiene(store, registry)
        text = format_hygiene_report(report)
        assert "No issues" in text
        assert str(report.rules_examined) in text

    def test_populated_report_lists_categories(self, project_dir, registry):
        store = FeedbackStore(project_dir)
        for _ in range(DEFAULT_MIN_SCANS):
            store.record_session(rule_ids=["test/dead-rule"], matches={})
        for _ in range(8):
            store.record("test/noisy-rule", is_true_positive=False)
        for _ in range(2):
            store.record("test/noisy-rule", is_true_positive=True)

        report = compute_hygiene(store, registry)
        text = format_hygiene_report(report)
        assert "Dead rules" in text
        assert "test/dead-rule" in text
        assert "Noisy rules" in text
        assert "test/noisy-rule" in text
        assert "rule_hygiene(apply=True)" in text


class TestPersistentDisableSurvivesRegistryReset:
    """T2 — auto-disabled rules must stay disabled when ``install_pack``
    (or any other path) clears the registry singleton and triggers a
    rebuild via ``_get_registry``."""

    def test_rebuild_reapplies_disable(
        self, monkeypatch: pytest.MonkeyPatch, project_dir,
    ):
        # Persist a hygiene-disable decision for a known builtin rule.
        store = FeedbackStore(project_dir)
        # Use any builtin rule id that the registry will load. Builtins
        # come from bug_finder/security; we pick a stable bare id and
        # match by suffix below.
        from attocode.code_intel.tools import rule_tools as rt

        monkeypatch.setenv("ATTOCODE_PROJECT_DIR", project_dir)
        monkeypatch.setattr(rt, "_registry", None)
        monkeypatch.setattr(rt, "_registry_loaded", False)
        reg_before = rt._get_registry()
        sample_id = next(
            (r.qualified_id for r in reg_before.all_rules(enabled_only=False)),
            None,
        )
        assert sample_id is not None, "registry should ship with builtin rules"

        store.set_disabled(sample_id, "dead")

        # Simulate install_pack clearing the singleton.
        monkeypatch.setattr(rt, "_registry", None)
        monkeypatch.setattr(rt, "_registry_loaded", False)
        reg_after = rt._get_registry()

        rule = reg_after.get(sample_id)
        assert rule is not None
        assert rule.enabled is False, "persistent disable was not reapplied"
        assert rule.disabled_reason == "dead"


class TestFeedbackStoreConcurrency:
    """T3 — concurrent ``record_session`` calls must not lose writes.
    Validates the threading.Lock added to FeedbackStore (R2)."""

    def test_concurrent_record_session_no_lost_writes(self, project_dir):
        import threading

        store = FeedbackStore(project_dir)
        n_threads = 16
        per_thread_calls = 5
        rule_ids = ["concurrent-rule-a", "concurrent-rule-b"]

        barrier = threading.Barrier(n_threads)

        def worker():
            barrier.wait()
            for _ in range(per_thread_calls):
                store.record_session(
                    rule_ids=list(rule_ids), matches={"concurrent-rule-a": 2},
                )

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        expected_scans = n_threads * per_thread_calls
        expected_matches_a = n_threads * per_thread_calls * 2

        assert store.get_scan_count("concurrent-rule-a") == expected_scans
        assert store.get_scan_count("concurrent-rule-b") == expected_scans
        assert store.get_match_count("concurrent-rule-a") == expected_matches_a
        assert store.get_match_count("concurrent-rule-b") == 0

        # Persisted JSON should reflect the same counts after a fresh load.
        reread = FeedbackStore(project_dir)
        assert reread.get_scan_count("concurrent-rule-a") == expected_scans


class TestFeedbackJsonSchema:
    """Ensure new fields land in the JSON file exactly as expected."""

    def test_session_and_disable_fields_persisted(self, project_dir):
        store = FeedbackStore(project_dir)
        store.record_session(
            rule_ids=["a"], matches={"a": 2}, files_scanned=5,
        )
        store.set_disabled("a", "dead")

        path = Path(project_dir) / ".attocode" / "rule_feedback.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        entry = data["a"]
        assert entry["scans"] == 1
        assert entry["matches"] == 2
        assert entry["files_scanned"] == 5
        assert entry["disabled"] is True
        assert entry["disabled_reason"] == "dead"
