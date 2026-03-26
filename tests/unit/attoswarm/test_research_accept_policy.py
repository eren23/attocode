from __future__ import annotations

from attoswarm.research.accept_policy import (
    NeverRegressPolicy,
    StatisticalPolicy,
    ThresholdPolicy,
    _z_for_confidence,
)


def test_threshold_policy_handles_maximize_minimize_and_no_change() -> None:
    policy = ThresholdPolicy(threshold=0.05)

    accepted, reason = policy.should_accept(1.0, 1.2, "maximize", [1.0])
    assert accepted is True
    assert "exceeds threshold" in reason

    accepted, reason = policy.should_accept(1.0, 0.92, "minimize", [1.0])
    assert accepted is True
    assert "exceeds threshold" in reason

    accepted, reason = policy.should_accept(1.0, 1.0, "maximize", [1.0])
    assert accepted is False
    assert reason == "No change from baseline"


def test_statistical_policy_falls_back_before_min_samples() -> None:
    policy = StatisticalPolicy(confidence=0.95, min_samples=5)

    accepted, reason = policy.should_accept(1.0, 1.2, "maximize", [1.0, 1.1])
    assert accepted is True
    assert "insufficient samples" in reason

    accepted, reason = policy.should_accept(1.0, 0.9, "maximize", [1.0, 1.1])
    assert accepted is False
    assert "No improvement" in reason


def test_statistical_policy_uses_z_test_with_zero_variance_guard() -> None:
    policy = StatisticalPolicy(confidence=0.95, min_samples=3)

    accepted, reason = policy.should_accept(1.0, 1.01, "maximize", [1.0, 1.0, 1.0])
    assert accepted is True
    assert "Statistically significant" in reason

    accepted, reason = policy.should_accept(1.0, 1.025, "maximize", [1.0, 1.02, 1.01])
    assert accepted is False
    assert "Not significant" in reason

    accepted, reason = policy.should_accept(1.0, 0.985, "minimize", [1.0, 0.99, 1.01])
    assert accepted is False
    assert "Not significant" in reason


def test_never_regress_policy_covers_both_directions() -> None:
    policy = NeverRegressPolicy()

    accepted, reason = policy.should_accept(1.0, 1.1, "maximize", [1.0])
    assert accepted is True
    assert "Improved" in reason

    accepted, reason = policy.should_accept(1.0, 1.0, "maximize", [1.0])
    assert accepted is False
    assert reason == "No change"

    accepted, reason = policy.should_accept(1.0, 0.9, "maximize", [1.0])
    assert accepted is False
    assert "Regression" in reason

    accepted, reason = policy.should_accept(1.0, 0.9, "minimize", [1.0])
    assert accepted is True
    assert "Improved" in reason


def test_z_for_confidence_uses_known_and_default_values() -> None:
    assert _z_for_confidence(0.90) == 1.645
    assert _z_for_confidence(0.95) == 1.960
    assert _z_for_confidence(0.99) == 2.576
    assert _z_for_confidence(0.975) == 1.960
