"""Benchmark the LLM FP filter against rule accuracy ground truth.

Evaluates:
- LLM classification accuracy (does it correctly identify TP/FP?)
- Cost per classification
- Latency overhead
- Precision/recall of the LLM filter itself
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eval.llm_fp_filter.filter import FPClassification, FPVerdict, classify_finding

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FilterBenchmarkResult:
    """Benchmark result for the LLM FP filter."""

    total_findings: int = 0
    classified: int = 0
    correct: int = 0
    incorrect: int = 0
    uncertain: int = 0

    # LLM filter's own precision/recall
    filter_tp: int = 0  # LLM says TP and it IS TP
    filter_fp: int = 0  # LLM says TP but it's FP
    filter_tn: int = 0  # LLM says FP and it IS FP
    filter_fn: int = 0  # LLM says FP but it's TP

    total_tokens: int = 0
    total_latency_ms: float = 0.0
    classifications: list[FPClassification] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return self.correct / self.classified if self.classified > 0 else 0.0

    @property
    def filter_precision(self) -> float:
        """Precision of the LLM's TP predictions."""
        denom = self.filter_tp + self.filter_fp
        return self.filter_tp / denom if denom > 0 else 0.0

    @property
    def filter_recall(self) -> float:
        """Recall of the LLM's TP predictions."""
        denom = self.filter_tp + self.filter_fn
        return self.filter_tp / denom if denom > 0 else 0.0

    @property
    def cost_estimate_usd(self) -> float:
        """Estimated cost based on Haiku pricing."""
        # Haiku: ~$0.25/M input, ~$1.25/M output tokens
        # Rough estimate: 80% input, 20% output
        input_tokens = int(self.total_tokens * 0.8)
        output_tokens = int(self.total_tokens * 0.2)
        return (input_tokens * 0.25 + output_tokens * 1.25) / 1_000_000

    @property
    def mean_latency_ms(self) -> float:
        return self.total_latency_ms / self.classified if self.classified > 0 else 0.0


def run_filter_benchmark(
    *,
    model: str = "claude-haiku-4-5-20251001",
    api_key: str = "",
    max_findings: int = 0,
) -> FilterBenchmarkResult:
    """Run the LLM FP filter against the rule accuracy corpus ground truth.

    Loads the corpus, runs rules, then classifies each finding with the
    LLM and compares against the ground truth annotations.

    Args:
        model: LLM model to use.
        api_key: API key (falls back to env).
        max_findings: Limit findings to classify (0 = all).

    Returns:
        FilterBenchmarkResult with accuracy, cost, and per-finding details.
    """
    from attocode.code_intel.rules.loader import load_builtin_rules
    from attocode.code_intel.rules.packs.pack_loader import list_example_packs, load_pack
    from attocode.code_intel.rules.executor import execute_rules
    from attocode.code_intel.rules.filters.pipeline import run_pipeline
    from eval.rule_accuracy.runner import CORPUS_DIR, _parse_file_annotations, discover_corpus

    # Load rules
    rules = load_builtin_rules()
    for m in list_example_packs():
        rules.extend(load_pack(m))

    # Discover corpus and build ground truth
    corpus_files = discover_corpus()
    ground_truth: dict[tuple[str, int], bool] = {}  # (file, line) -> is_tp

    for file_path, language, cwe in corpus_files:
        # Key by relative path from CORPUS_DIR (matches execute_rules output)
        try:
            rel_path = os.path.relpath(file_path, str(CORPUS_DIR))
        except ValueError:
            rel_path = file_path

        expectations, is_tn = _parse_file_annotations(file_path)
        for line_no, rule_id in expectations.items():
            ground_truth[(rel_path, line_no)] = True  # annotated = TP
        if is_tn:
            # All lines in TN files are expected to be FP if flagged
            try:
                line_count = len(Path(file_path).read_text().splitlines())
                for ln in range(1, line_count + 1):
                    if (rel_path, ln) not in ground_truth:
                        ground_truth[(rel_path, ln)] = False
            except OSError:
                pass

    # Run rules against corpus — use CORPUS_DIR as project_dir so
    # relative paths preserve the language/cwe/ directory structure
    all_files = [f for f, _, _ in corpus_files]
    findings = execute_rules(all_files, rules, project_dir=str(CORPUS_DIR))
    findings = run_pipeline(findings, min_confidence=0.0)

    if max_findings > 0:
        findings = findings[:max_findings]

    result = FilterBenchmarkResult(total_findings=len(findings))

    # Classify each finding
    for finding in findings:
        # Build context — finding.file is relative to CORPUS_DIR
        code_context = "\n".join(finding.context_before + [finding.code_snippet] + finding.context_after)

        classification = classify_finding(
            rule_id=finding.rule_id,
            severity=finding.severity,
            description=finding.description,
            cwe=finding.cwe,
            file=finding.file,
            line=finding.line,
            matched_line=finding.code_snippet,
            code_context=code_context or finding.code_snippet,
            explanation=finding.explanation,
            model=model,
            api_key=api_key,
        )

        result.classifications.append(classification)
        result.total_tokens += classification.tokens_used
        result.total_latency_ms += classification.latency_ms

        if classification.verdict == FPVerdict.UNCERTAIN:
            result.uncertain += 1
            continue

        result.classified += 1

        # Compare against ground truth (keyed by relative path from CORPUS_DIR)
        is_actually_tp = ground_truth.get((finding.file, finding.line))
        if is_actually_tp is None:
            # No ground truth for this line — skip
            result.uncertain += 1
            result.classified -= 1
            continue

        llm_says_tp = classification.verdict == FPVerdict.TRUE_POSITIVE

        if llm_says_tp == is_actually_tp:
            result.correct += 1
        else:
            result.incorrect += 1

        if llm_says_tp and is_actually_tp:
            result.filter_tp += 1
        elif llm_says_tp and not is_actually_tp:
            result.filter_fp += 1
        elif not llm_says_tp and not is_actually_tp:
            result.filter_tn += 1
        elif not llm_says_tp and is_actually_tp:
            result.filter_fn += 1

    return result


def format_filter_benchmark(result: FilterBenchmarkResult) -> str:
    """Format benchmark results as markdown."""
    lines = ["# LLM FP Filter Benchmark\n"]

    lines.append(f"**Findings evaluated**: {result.total_findings}")
    lines.append(f"**Classified**: {result.classified} (uncertain: {result.uncertain})")
    lines.append(f"**Accuracy**: {result.accuracy:.1%}")
    lines.append(f"**Filter Precision**: {result.filter_precision:.1%}")
    lines.append(f"**Filter Recall**: {result.filter_recall:.1%}")
    lines.append(f"**Cost**: ~${result.cost_estimate_usd:.4f}")
    lines.append(f"**Mean Latency**: {result.mean_latency_ms:.0f}ms per finding")
    lines.append(f"**Total Tokens**: {result.total_tokens}\n")

    lines.append("## Confusion Matrix\n")
    lines.append("|  | Actually TP | Actually FP |")
    lines.append("|--|------------|------------|")
    lines.append(f"| LLM says TP | {result.filter_tp} | {result.filter_fp} |")
    lines.append(f"| LLM says FP | {result.filter_fn} | {result.filter_tn} |")

    # Per-finding details for errors
    errors = [c for c in result.classifications if c.verdict != FPVerdict.UNCERTAIN]
    if errors:
        lines.append("\n## Classification Details\n")
        for c in errors[:20]:
            lines.append(f"- `{c.rule_id}` {c.file}:{c.line} → **{c.verdict}** ({c.confidence:.0%}) — {c.reasoning}")

    return "\n".join(lines)
