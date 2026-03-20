"""Tests for PoisonDetector."""

from __future__ import annotations

from attoswarm.coordinator.poison_detector import PoisonDetector


class TestPoisonDetector:
    def test_not_poison_with_few_attempts(self) -> None:
        detector = PoisonDetector()
        report = detector.check("t1", [
            {"attempt": 1, "failure_cause": "timeout", "tokens_used": 100},
        ])
        assert not report.is_poison

    def test_varying_failures_detected(self) -> None:
        detector = PoisonDetector(max_varying_failures=3)
        report = detector.check("t1", [
            {"attempt": 1, "failure_cause": "timeout", "tokens_used": 100},
            {"attempt": 2, "failure_cause": "agent_error", "tokens_used": 200},
            {"attempt": 3, "failure_cause": "crash", "tokens_used": 300},
        ])
        assert report.is_poison
        assert "varying_failures" in report.signals[0]
        assert report.recommendation == "skip"

    def test_zero_progress_detected(self) -> None:
        detector = PoisonDetector()
        report = detector.check("t1", [
            {"attempt": 1, "tokens_used": 1000, "files_modified": []},
            {"attempt": 2, "tokens_used": 1500, "files_modified": []},
        ])
        assert report.is_poison
        assert any("zero_progress" in s for s in report.signals)

    def test_escalating_tokens(self) -> None:
        detector = PoisonDetector()
        report = detector.check("t1", [
            {"attempt": 1, "failure_cause": "timeout", "tokens_used": 1000, "files_modified": ["a.py"]},
            {"attempt": 2, "failure_cause": "timeout", "tokens_used": 2000, "files_modified": ["a.py"]},
            {"attempt": 3, "failure_cause": "timeout", "tokens_used": 3000, "files_modified": ["a.py"]},
        ])
        assert any("escalating_tokens" in s for s in report.signals)

    def test_model_agnostic_failure(self) -> None:
        detector = PoisonDetector()
        report = detector.check("t1", [
            {"attempt": 1, "failure_cause": "timeout", "model": "claude", "tokens_used": 100, "files_modified": ["a.py"]},
            {"attempt": 2, "failure_cause": "timeout", "model": "gpt4", "tokens_used": 100, "files_modified": ["a.py"]},
        ])
        assert any("model_agnostic" in s for s in report.signals)

    def test_not_poison_with_varying_success(self) -> None:
        detector = PoisonDetector()
        report = detector.check("t1", [
            {"attempt": 1, "failure_cause": "timeout", "tokens_used": 100, "files_modified": ["a.py"]},
            {"attempt": 2, "failure_cause": "timeout", "tokens_used": 100, "files_modified": ["b.py"]},
        ])
        # Same cause, files modified — not poisonous
        assert not report.is_poison
