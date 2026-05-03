"""Rule hygiene — auto-prune dead/noisy rules and report confidence drift.

Reads persistent state from :class:`FeedbackStore` (counts, calibrated
confidence) and the in-memory :class:`RuleRegistry` (current rule set
plus declared confidence) to produce a hygiene report and, optionally,
apply disable decisions.

Three categories:

- **Dead**: rule has been applied across at least ``min_scans`` separate
  analyze sessions but produced zero matches.
- **Noisy**: rule has at least ``min_samples`` TP/FP feedback observations
  with a false-positive rate above ``fp_threshold``.
- **Drift**: calibrated confidence diverges from the rule's declared
  confidence by more than ``drift_threshold``. Reported only — never
  auto-disabled (operators may want to recalibrate the YAML instead).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from attocode.code_intel.rules.profiling import FeedbackStore
    from attocode.code_intel.rules.registry import RuleRegistry


# Defaults match the Phase 1 roadmap entry for auto-pruning.
DEFAULT_MIN_SCANS = 10
DEFAULT_MIN_SAMPLES = 10
DEFAULT_FP_THRESHOLD = 0.5
DEFAULT_DRIFT_THRESHOLD = 0.2


@dataclass(slots=True, frozen=True)
class HygieneEntry:
    """One hygiene observation about a single rule."""

    rule_id: str
    reason: str  # "dead" | "noisy" | "drift"
    detail: str  # human-readable summary (counts, rates, deltas)
    scans: int = 0
    matches: int = 0
    tp: int = 0
    fp: int = 0
    declared_confidence: float = 0.0
    calibrated_confidence: float | None = None


@dataclass(slots=True)
class HygieneReport:
    """Aggregated hygiene findings across the registry."""

    dead: list[HygieneEntry] = field(default_factory=list)
    noisy: list[HygieneEntry] = field(default_factory=list)
    drift: list[HygieneEntry] = field(default_factory=list)
    rules_examined: int = 0

    @property
    def total_actionable(self) -> int:
        """Dead + noisy — entries that ``apply_hygiene`` will disable."""
        return len(self.dead) + len(self.noisy)


def compute_hygiene(
    store: FeedbackStore,
    registry: RuleRegistry,
    *,
    min_scans: int = DEFAULT_MIN_SCANS,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    fp_threshold: float = DEFAULT_FP_THRESHOLD,
    drift_threshold: float = DEFAULT_DRIFT_THRESHOLD,
) -> HygieneReport:
    """Compute dead/noisy/drift entries for all registered rules."""
    report = HygieneReport()
    for rule in registry.all_rules(enabled_only=False):
        qid = rule.qualified_id
        report.rules_examined += 1

        scans = store.get_scan_count(qid)
        matches = store.get_match_count(qid)
        feedback = store.get_feedback(qid)
        tp, fp = feedback["tp"], feedback["fp"]
        calibrated = store.get_calibrated_confidence(qid)

        # Dead: applied enough times, never fired.
        if matches == 0 and scans >= min_scans:
            report.dead.append(
                HygieneEntry(
                    rule_id=qid,
                    reason="dead",
                    detail=f"{scans} scans, 0 matches",
                    scans=scans,
                    matches=matches,
                    tp=tp,
                    fp=fp,
                    declared_confidence=rule.confidence,
                    calibrated_confidence=calibrated,
                )
            )
            continue

        # Noisy: enough feedback samples and FP rate too high.
        total_samples = tp + fp
        if total_samples >= min_samples:
            fp_rate = fp / total_samples
            if fp_rate > fp_threshold:
                report.noisy.append(
                    HygieneEntry(
                        rule_id=qid,
                        reason="noisy",
                        detail=f"{fp}/{total_samples} FP ({fp_rate:.0%})",
                        scans=scans,
                        matches=matches,
                        tp=tp,
                        fp=fp,
                        declared_confidence=rule.confidence,
                        calibrated_confidence=calibrated,
                    )
                )
                continue

        # Drift: calibrated confidence diverges from declared.
        if calibrated is not None:
            delta = calibrated - rule.confidence
            if abs(delta) >= drift_threshold:
                direction = "+" if delta > 0 else "-"
                report.drift.append(
                    HygieneEntry(
                        rule_id=qid,
                        reason="drift",
                        detail=(
                            f"declared {rule.confidence:.2f} → calibrated "
                            f"{calibrated:.2f} ({direction}{abs(delta):.2f})"
                        ),
                        scans=scans,
                        matches=matches,
                        tp=tp,
                        fp=fp,
                        declared_confidence=rule.confidence,
                        calibrated_confidence=calibrated,
                    )
                )

    return report


def apply_hygiene(
    report: HygieneReport,
    registry: RuleRegistry,
    store: FeedbackStore,
) -> int:
    """Disable dead and noisy rules; persist the decision in ``store``.

    Drift entries are not auto-disabled — they're informational. Returns
    the number of rules disabled.
    """
    disabled = 0
    for entry in [*report.dead, *report.noisy]:
        rule = registry.get(entry.rule_id)
        if rule is None:
            continue
        rule.enabled = False
        rule.disabled_reason = entry.reason
        store.set_disabled(entry.rule_id, entry.reason)
        disabled += 1
    return disabled


def apply_persistent_disable(
    registry: RuleRegistry,
    store: FeedbackStore,
) -> int:
    """Re-apply previously persisted hygiene-disable decisions on startup.

    Called by ``_get_registry`` after rules load so dead/noisy rules from
    prior sessions stay disabled. Returns the number of rules touched.
    """
    touched = 0
    for rule in registry.all_rules(enabled_only=False):
        qid = rule.qualified_id
        if store.is_disabled(qid):
            rule.enabled = False
            rule.disabled_reason = store.get_disabled_reason(qid) or "disabled"
            touched += 1
    return touched


def format_hygiene_report(report: HygieneReport) -> str:
    """Render a hygiene report as agent-friendly markdown."""
    if not (report.dead or report.noisy or report.drift):
        return (
            f"# Rule Hygiene\n\nNo issues across {report.rules_examined} rules. "
            "Run `analyze` and provide `rule_feedback` to gather more signal."
        )

    out: list[str] = [
        "# Rule Hygiene",
        "",
        f"Examined {report.rules_examined} rules. "
        f"Dead: {len(report.dead)}, Noisy: {len(report.noisy)}, "
        f"Drift: {len(report.drift)}.",
    ]

    if report.dead:
        out.append("\n## Dead rules — never matched\n")
        out.append("| Rule | Scans | Matches | TP | FP |")
        out.append("|------|-------|---------|----|----|")
        for e in report.dead:
            out.append(
                f"| `{e.rule_id}` | {e.scans} | {e.matches} | {e.tp} | {e.fp} |"
            )

    if report.noisy:
        out.append("\n## Noisy rules — high false-positive rate\n")
        out.append("| Rule | TP | FP | Rate |")
        out.append("|------|----|----|------|")
        for e in report.noisy:
            total = e.tp + e.fp
            rate = e.fp / total if total else 0.0
            out.append(f"| `{e.rule_id}` | {e.tp} | {e.fp} | {rate:.0%} |")

    if report.drift:
        out.append("\n## Confidence drift — calibrated diverges from declared\n")
        out.append("| Rule | Declared | Calibrated | Δ |")
        out.append("|------|----------|------------|---|")
        for e in report.drift:
            cal = e.calibrated_confidence or 0.0
            delta = cal - e.declared_confidence
            sign = "+" if delta >= 0 else "−"
            out.append(
                f"| `{e.rule_id}` | {e.declared_confidence:.2f} | "
                f"{cal:.2f} | {sign}{abs(delta):.2f} |"
            )

    if report.total_actionable:
        out.append(
            f"\n_Run `rule_hygiene(apply=True)` to disable "
            f"{report.total_actionable} dead/noisy rule(s)._"
        )
    return "\n".join(out)
