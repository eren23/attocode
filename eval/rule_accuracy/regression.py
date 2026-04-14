"""Rule accuracy regression detection.

Saves/loads baseline snapshots and detects regressions when
per-rule F1 drops by more than a threshold or FP count increases.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path

from eval.rule_accuracy.runner import BenchmarkResult, RuleAccuracyResult

logger = logging.getLogger(__name__)

BASELINE_PATH = Path(__file__).parent / "baseline.json"


def save_baseline(result: BenchmarkResult, path: str | Path = BASELINE_PATH) -> None:
    """Save a benchmark result as the regression baseline."""
    snapshot: dict[str, dict] = {}
    for rule_id, r in result.per_rule.items():
        snapshot[rule_id] = {
            "tp": r.true_positives,
            "fp": r.false_positives,
            "fn": r.false_negatives,
            "f1": round(r.f1, 4),
            "precision": round(r.precision, 4),
            "recall": round(r.recall, 4),
        }

    Path(path).write_text(
        json.dumps(snapshot, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    logger.info("Saved baseline with %d rules to %s", len(snapshot), path)


def load_baseline(path: str | Path = BASELINE_PATH) -> dict[str, dict]:
    """Load a previously saved baseline."""
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load baseline: %s", exc)
        return {}


def check_regression(
    result: BenchmarkResult,
    baseline_path: str | Path = BASELINE_PATH,
    *,
    f1_threshold: float = 0.05,
) -> list[str]:
    """Compare current results against baseline and report regressions.

    Args:
        result: Current benchmark result.
        baseline_path: Path to baseline JSON.
        f1_threshold: Maximum allowed F1 drop before flagging regression.

    Returns:
        List of regression messages (empty = no regressions).
    """
    baseline = load_baseline(baseline_path)
    if not baseline:
        return ["No baseline found — run with --update-baseline first."]

    regressions: list[str] = []

    for rule_id, current in result.per_rule.items():
        prev = baseline.get(rule_id)
        if prev is None:
            continue  # new rule, no baseline

        prev_f1 = prev.get("f1", 0.0)
        if current.f1 < prev_f1 - f1_threshold:
            regressions.append(
                f"REGRESSION: {rule_id} F1 dropped {prev_f1:.3f} -> {current.f1:.3f} "
                f"(delta={current.f1 - prev_f1:+.3f}, threshold={f1_threshold})"
            )

        prev_fp = prev.get("fp", 0)
        if current.false_positives > prev_fp:
            regressions.append(
                f"FP INCREASE: {rule_id} FP count {prev_fp} -> {current.false_positives}"
            )

    # Check for removed rules (in baseline but not in current)
    for rule_id in baseline:
        if rule_id not in result.per_rule:
            regressions.append(f"REMOVED: {rule_id} was in baseline but has no corpus coverage now")

    return regressions
