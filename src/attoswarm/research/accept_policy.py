"""Accept/reject policies for research experiments."""

from __future__ import annotations

import math
from typing import Protocol, runtime_checkable


@runtime_checkable
class AcceptPolicy(Protocol):
    """Protocol for accept/reject decisions."""

    def should_accept(
        self,
        baseline: float,
        candidate: float,
        direction: str,
        history: list[float],
    ) -> tuple[bool, str]: ...


class ThresholdPolicy:
    """Accept if improvement exceeds a threshold."""

    def __init__(self, threshold: float = 0.0) -> None:
        self._threshold = threshold

    def should_accept(
        self,
        baseline: float,
        candidate: float,
        direction: str,
        history: list[float],
    ) -> tuple[bool, str]:
        if direction == "minimize":
            delta = baseline - candidate
        else:
            delta = candidate - baseline

        if delta > self._threshold:
            return True, f"Improvement of {delta:.4f} exceeds threshold {self._threshold}"
        if delta == 0:
            return False, "No change from baseline"
        return False, f"Improvement {delta:.4f} below threshold {self._threshold}"


class StatisticalPolicy:
    """Accept based on statistical significance (z-test).

    Requires at least 5 history samples before applying the test.
    Falls back to threshold comparison with fewer samples.
    """

    def __init__(self, confidence: float = 0.95, min_samples: int = 5) -> None:
        self._z_threshold = _z_for_confidence(confidence)
        self._min_samples = min_samples

    def should_accept(
        self,
        baseline: float,
        candidate: float,
        direction: str,
        history: list[float],
    ) -> tuple[bool, str]:
        if len(history) < self._min_samples:
            # Fall back to simple comparison
            if direction == "minimize":
                improved = candidate < baseline
            else:
                improved = candidate > baseline
            if improved:
                return True, f"Improved (insufficient samples for z-test, n={len(history)})"
            return False, f"No improvement (insufficient samples, n={len(history)})"

        # Compute z-score
        mean = sum(history) / len(history)
        variance = sum((x - mean) ** 2 for x in history) / len(history)
        std = math.sqrt(variance) if variance > 0 else 0.001

        if direction == "minimize":
            z = (mean - candidate) / std
        else:
            z = (candidate - mean) / std

        if z >= self._z_threshold:
            return True, f"Statistically significant (z={z:.2f} >= {self._z_threshold:.2f})"
        return False, f"Not significant (z={z:.2f} < {self._z_threshold:.2f})"


class NeverRegressPolicy:
    """Accept any improvement, reject any regression."""

    def should_accept(
        self,
        baseline: float,
        candidate: float,
        direction: str,
        history: list[float],
    ) -> tuple[bool, str]:
        if direction == "minimize":
            if candidate < baseline:
                return True, f"Improved: {baseline:.4f} -> {candidate:.4f}"
            if candidate == baseline:
                return False, "No change"
            return False, f"Regression: {baseline:.4f} -> {candidate:.4f}"
        else:
            if candidate > baseline:
                return True, f"Improved: {baseline:.4f} -> {candidate:.4f}"
            if candidate == baseline:
                return False, "No change"
            return False, f"Regression: {baseline:.4f} -> {candidate:.4f}"


def _z_for_confidence(confidence: float) -> float:
    """Approximate z-score for a given confidence level."""
    # Common values
    table = {0.90: 1.645, 0.95: 1.960, 0.99: 2.576}
    return table.get(confidence, 1.960)
