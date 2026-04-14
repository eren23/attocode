"""Rule performance profiler — measures per-rule execution time, match rate, and effectiveness.

Runs every rule individually against the corpus to produce:
- Per-rule timing (total, mean per file)
- Match count and match rate (matches per KLOC)
- Effectiveness index: (TP_rate * severity_weight) / execution_time_ms
- Dead rule detection: rules with zero matches across all corpus files
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from attocode.code_intel.rules.executor import execute_rules
from attocode.code_intel.rules.model import RuleSeverity, UnifiedRule

logger = logging.getLogger(__name__)

_SEVERITY_WEIGHT = {
    RuleSeverity.CRITICAL: 5.0,
    RuleSeverity.HIGH: 4.0,
    RuleSeverity.MEDIUM: 3.0,
    RuleSeverity.LOW: 2.0,
    RuleSeverity.INFO: 1.0,
}


@dataclass(slots=True)
class RuleProfile:
    """Performance profile for a single rule."""

    rule_id: str
    severity: str = ""
    total_time_ms: float = 0.0
    files_scanned: int = 0
    match_count: int = 0
    total_lines_scanned: int = 0

    # From accuracy benchmark (if available)
    true_positives: int = 0
    false_positives: int = 0

    @property
    def mean_time_per_file_ms(self) -> float:
        return self.total_time_ms / self.files_scanned if self.files_scanned > 0 else 0.0

    @property
    def matches_per_kloc(self) -> float:
        if self.total_lines_scanned == 0:
            return 0.0
        return (self.match_count / self.total_lines_scanned) * 1000

    @property
    def false_positive_rate(self) -> float | None:
        total = self.true_positives + self.false_positives
        return self.false_positives / total if total > 0 else None

    @property
    def effectiveness_index(self) -> float:
        """Higher = more effective rule. Combines TP rate, severity, and speed."""
        sev_weight = _SEVERITY_WEIGHT.get(RuleSeverity(self.severity), 2.0) if self.severity else 2.0
        tp_total = self.true_positives + self.false_positives
        tp_rate = self.true_positives / tp_total if tp_total > 0 else 0.5  # assume 50% if no data
        time_factor = 1.0 / max(self.total_time_ms, 0.1)  # avoid div by zero
        return tp_rate * sev_weight * time_factor * 1000  # scale to readable range

    @property
    def is_dead(self) -> bool:
        return self.match_count == 0 and self.files_scanned > 0


@dataclass(slots=True)
class ProfilingResult:
    """Full profiling result across all rules."""

    profiles: list[RuleProfile] = field(default_factory=list)
    total_rules: int = 0
    total_time_ms: float = 0.0
    total_files: int = 0

    @property
    def dead_rules(self) -> list[RuleProfile]:
        return [p for p in self.profiles if p.is_dead]

    @property
    def slowest(self) -> list[RuleProfile]:
        return sorted(self.profiles, key=lambda p: p.total_time_ms, reverse=True)

    @property
    def highest_fp_rate(self) -> list[RuleProfile]:
        rated = [p for p in self.profiles if p.false_positive_rate is not None and p.false_positive_rate > 0]
        return sorted(rated, key=lambda p: p.false_positive_rate or 0, reverse=True)

    @property
    def by_effectiveness(self) -> list[RuleProfile]:
        return sorted(self.profiles, key=lambda p: p.effectiveness_index, reverse=True)


def profile_rules(
    corpus_dir: str = "",
    *,
    accuracy_data: dict | None = None,
) -> ProfilingResult:
    """Profile all rules against the corpus or project files.

    Args:
        corpus_dir: Directory to scan. Default: rule accuracy corpus.
        accuracy_data: Optional per-rule TP/FP counts from rule accuracy benchmark.

    Returns:
        ProfilingResult with per-rule profiles.
    """
    from attocode.code_intel.rules.loader import load_builtin_rules
    from attocode.code_intel.rules.packs.pack_loader import list_example_packs, load_pack

    # Load all rules
    all_rules = load_builtin_rules()
    for manifest in list_example_packs():
        all_rules.extend(load_pack(manifest))

    # Collect files to scan
    if not corpus_dir:
        corpus_dir = str(Path(__file__).parent.parent / "rule_accuracy" / "corpus")

    files: list[str] = []
    corpus_path = Path(corpus_dir)
    if corpus_path.is_dir():
        for f in corpus_path.rglob("*"):
            if f.is_file() and f.suffix in {".py", ".go", ".js", ".ts", ".java", ".rs", ".rb", ".php", ".c", ".cpp"}:
                files.append(str(f))

    if not files:
        return ProfilingResult()

    # Count total lines
    total_lines = 0
    for f in files:
        try:
            total_lines += len(Path(f).read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            pass

    result = ProfilingResult(total_files=len(files))

    # Profile each rule individually
    for rule in all_rules:
        start = time.monotonic()
        findings = execute_rules(files, [rule], project_dir=corpus_dir)
        elapsed_ms = (time.monotonic() - start) * 1000

        # Get accuracy data if available
        acc = (accuracy_data or {}).get(rule.qualified_id, {})

        profile = RuleProfile(
            rule_id=rule.qualified_id,
            severity=rule.severity,
            total_time_ms=elapsed_ms,
            files_scanned=len(files),
            match_count=len(findings),
            total_lines_scanned=total_lines,
            true_positives=acc.get("tp", 0),
            false_positives=acc.get("fp", 0),
        )
        result.profiles.append(profile)

    result.total_rules = len(result.profiles)
    result.total_time_ms = sum(p.total_time_ms for p in result.profiles)

    return result


def format_profiling_report(result: ProfilingResult) -> str:
    """Format profiling results as markdown."""
    lines: list[str] = []
    lines.append("# Rule Performance Profiling Report\n")
    lines.append(
        f"**Rules**: {result.total_rules} | "
        f"**Files**: {result.total_files} | "
        f"**Total time**: {result.total_time_ms:.0f}ms\n"
    )

    # Effectiveness ranking (top 20)
    lines.append("## Top Rules by Effectiveness\n")
    lines.append("| Rule | Severity | Time (ms) | Matches | Eff. Index |")
    lines.append("|------|----------|-----------|---------|------------|")
    for p in result.by_effectiveness[:20]:
        lines.append(
            f"| `{p.rule_id}` | {p.severity} | {p.total_time_ms:.1f} | "
            f"{p.match_count} | {p.effectiveness_index:.1f} |"
        )

    # Slowest rules
    lines.append("\n## Slowest Rules (optimization targets)\n")
    lines.append("| Rule | Time (ms) | Mean/File (ms) | Matches |")
    lines.append("|------|-----------|----------------|---------|")
    for p in result.slowest[:10]:
        lines.append(
            f"| `{p.rule_id}` | {p.total_time_ms:.1f} | "
            f"{p.mean_time_per_file_ms:.2f} | {p.match_count} |"
        )

    # Highest FP rate
    fp_rules = result.highest_fp_rate
    if fp_rules:
        lines.append("\n## Highest False Positive Rates (tuning targets)\n")
        lines.append("| Rule | FP Rate | TP | FP |")
        lines.append("|------|---------|----|----|")
        for p in fp_rules[:10]:
            fpr = p.false_positive_rate
            lines.append(
                f"| `{p.rule_id}` | {fpr:.0%} | {p.true_positives} | {p.false_positives} |"
            )

    # Dead rules
    dead = result.dead_rules
    if dead:
        lines.append(f"\n## Dead Rules ({len(dead)} rules with zero matches)\n")
        for p in dead[:20]:
            lines.append(f"- `{p.rule_id}` [{p.severity}]")
        if len(dead) > 20:
            lines.append(f"... and {len(dead) - 20} more")

    # Match density
    lines.append("\n## Match Density (matches per KLOC)\n")
    dense = sorted(
        [p for p in result.profiles if p.matches_per_kloc > 0],
        key=lambda p: p.matches_per_kloc, reverse=True,
    )
    if dense:
        lines.append("| Rule | Matches/KLOC | Total Matches |")
        lines.append("|------|-------------|---------------|")
        for p in dense[:10]:
            lines.append(f"| `{p.rule_id}` | {p.matches_per_kloc:.1f} | {p.match_count} |")

    return "\n".join(lines)
