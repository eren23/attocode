"""Report generator for rule accuracy benchmark results."""

from __future__ import annotations

from eval.rule_accuracy.castle_score import CASTLEResult, compute_castle_scores
from eval.rule_accuracy.runner import BenchmarkResult, RuleAccuracyResult


def _metrics_row(r: RuleAccuracyResult, castle: CASTLEResult | None = None) -> str:
    """Format a single metrics row."""
    castle_str = f"{castle.castle_score:.3f}" if castle else "—"
    return (
        f"| `{r.rule_id}` | {r.true_positives} | {r.false_positives} | "
        f"{r.false_negatives} | {r.precision:.2f} | {r.recall:.2f} | "
        f"{r.f1:.2f} | {castle_str} |"
    )


def format_accuracy_report(
    result: BenchmarkResult,
    rule_severities: dict[str, str] | None = None,
) -> str:
    """Format the full accuracy benchmark report as markdown."""
    lines: list[str] = []

    # Header
    o = result.overall
    status = "PASS" if o.f1 >= 0.5 else "NEEDS IMPROVEMENT"
    lines.append(f"# Rule Accuracy Benchmark: {status}\n")
    lines.append(
        f"**Overall**: P={o.precision:.2f} R={o.recall:.2f} F1={o.f1:.2f} "
        f"| TP={o.true_positives} FP={o.false_positives} FN={o.false_negatives}"
    )
    lines.append(f"**Files scanned**: {len(result.file_results)}\n")

    # CASTLE scores
    castle_scores = compute_castle_scores(result.per_rule, rule_severities)

    # Per-rule table (sorted by F1 descending)
    lines.append("## Per-Rule Metrics\n")
    lines.append("| Rule | TP | FP | FN | Precision | Recall | F1 | CASTLE |")
    lines.append("|------|----|----|----|-----------|---------|----|--------|")

    sorted_rules = sorted(
        result.per_rule.values(),
        key=lambda r: r.f1,
        reverse=True,
    )
    for r in sorted_rules:
        lines.append(_metrics_row(r, castle_scores.get(r.rule_id)))

    # Per-CWE table
    if result.per_cwe:
        lines.append("\n## Per-CWE Metrics\n")
        lines.append("| CWE | TP | FP | FN | Precision | Recall | F1 | CASTLE |")
        lines.append("|-----|----|----|----|-----------|--------|----|--------|")
        for cwe in sorted(result.per_cwe.keys()):
            r = result.per_cwe[cwe]
            lines.append(_metrics_row(r))

    # Per-language table
    if result.per_language:
        lines.append("\n## Per-Language Metrics\n")
        lines.append("| Language | TP | FP | FN | Precision | Recall | F1 | CASTLE |")
        lines.append("|----------|----|----|----|-----------|--------|----|--------|")
        for lang in sorted(result.per_language.keys()):
            r = result.per_language[lang]
            lines.append(_metrics_row(r))

    # FP hotlist
    fp_rules = [r for r in sorted_rules if r.false_positives > 0]
    if fp_rules:
        fp_rules.sort(key=lambda r: r.false_positives, reverse=True)
        lines.append("\n## False Positive Hotlist\n")
        for r in fp_rules[:10]:
            lines.append(f"- `{r.rule_id}`: {r.false_positives} FPs (precision={r.precision:.2f})")

    # Coverage gaps (CWEs with no TP)
    no_tp_cwes = [cwe for cwe, r in result.per_cwe.items() if r.true_positives == 0]
    if no_tp_cwes:
        lines.append("\n## Coverage Gaps (CWEs with 0 true positives)\n")
        for cwe in sorted(no_tp_cwes):
            lines.append(f"- {cwe}")

    # Per-file details for failures
    failed_files = [
        fr for fr in result.file_results
        if fr.fn_lines or fr.fp_lines
    ]
    if failed_files:
        lines.append("\n## File Details (failures only)\n")
        for fr in failed_files[:20]:
            name = fr.file_path.split("/")[-1]
            lines.append(f"### {name} ({fr.language}/{fr.cwe})")
            if fr.fn_lines:
                lines.append(f"  Missing (FN): lines {fr.fn_lines}")
            if fr.fp_lines:
                lines.append(f"  Unexpected (FP): lines {fr.fp_lines}")

    return "\n".join(lines)
