"""Confidence calibration measurement.

Evaluates whether rule confidence scores are well-calibrated:
does confidence=0.8 actually mean 80% of findings are true positives?

Computes Expected Calibration Error (ECE) and per-bin accuracy.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class CalibrationBin:
    """A single confidence bin."""

    bin_start: float
    bin_end: float
    count: int = 0
    true_positives: int = 0
    false_positives: int = 0

    @property
    def actual_accuracy(self) -> float:
        total = self.true_positives + self.false_positives
        return self.true_positives / total if total > 0 else 0.0

    @property
    def expected_accuracy(self) -> float:
        return (self.bin_start + self.bin_end) / 2

    @property
    def gap(self) -> float:
        return abs(self.actual_accuracy - self.expected_accuracy)


@dataclass(slots=True)
class CalibrationResult:
    """Full calibration analysis."""

    bins: list[CalibrationBin] = field(default_factory=list)
    ece: float = 0.0  # Expected Calibration Error
    total_findings: int = 0

    @property
    def is_well_calibrated(self) -> bool:
        return self.ece < 0.10


def compute_calibration(
    findings_with_labels: list[tuple[float, bool]],
    n_bins: int = 10,
) -> CalibrationResult:
    """Compute calibration metrics from labeled findings.

    Args:
        findings_with_labels: List of (confidence, is_true_positive) pairs.
        n_bins: Number of calibration bins.

    Returns:
        CalibrationResult with per-bin stats and ECE.
    """
    # Create bins
    bins = [
        CalibrationBin(
            bin_start=i / n_bins,
            bin_end=(i + 1) / n_bins,
        )
        for i in range(n_bins)
    ]

    # Assign findings to bins
    for confidence, is_tp in findings_with_labels:
        bin_idx = min(int(confidence * n_bins), n_bins - 1)
        bins[bin_idx].count += 1
        if is_tp:
            bins[bin_idx].true_positives += 1
        else:
            bins[bin_idx].false_positives += 1

    total = len(findings_with_labels)
    if total == 0:
        return CalibrationResult(bins=bins)

    # Compute ECE: weighted sum of |accuracy - confidence| per bin
    ece = sum(
        (b.count / total) * b.gap
        for b in bins if b.count > 0
    )

    return CalibrationResult(bins=bins, ece=ece, total_findings=total)


def format_calibration_report(result: CalibrationResult) -> str:
    """Format calibration results as markdown."""
    lines = ["# Confidence Calibration Report\n"]

    status = "WELL CALIBRATED" if result.is_well_calibrated else "NEEDS TUNING"
    lines.append(f"**Status**: {status} (ECE = {result.ece:.4f})")
    lines.append(f"**Total findings**: {result.total_findings}\n")

    lines.append("| Confidence Range | Count | Actual Accuracy | Expected | Gap |")
    lines.append("|-----------------|-------|-----------------|----------|-----|")

    for b in result.bins:
        if b.count == 0:
            continue
        lines.append(
            f"| {b.bin_start:.1f}–{b.bin_end:.1f} | {b.count} | "
            f"{b.actual_accuracy:.1%} | {b.expected_accuracy:.1%} | "
            f"{b.gap:.1%} |"
        )

    lines.append(f"\n**ECE**: {result.ece:.4f} (target: < 0.10, aspirational: < 0.05)")

    return "\n".join(lines)
