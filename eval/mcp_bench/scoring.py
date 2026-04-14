"""Scoring pipeline for code-intel-bench.

Two-tier scoring:
1. Deterministic scoring — reuses eval/quality_scorers.py pattern matchers
2. Ground truth matching — keyword presence, file path matching
"""

from __future__ import annotations

import re
from typing import Any

from eval.mcp_bench.schema import BenchTask, TaskResult


# ---------------------------------------------------------------------------
# Deterministic scorers (reuse from existing quality_scorers)
# ---------------------------------------------------------------------------

def _safe_import_task_scorers() -> dict:
    """Import TASK_SCORERS from quality_scorers, falling back to empty."""
    try:
        from eval.quality_scorers import TASK_SCORERS
        return TASK_SCORERS
    except ImportError:
        return {}


_SCORER_CATEGORY_MAP = {
    "orientation": "bootstrap",
    "symbol_search": "symbol_discovery",
    "semantic_search": "semantic_search",
    "dependency_tracing": "dependency_tracing",
    "impact_analysis": "dependency_tracing",  # closest scorer
    "architecture": "architecture",
    "security_scanning": None,  # custom scorer below
    "dead_code": "dead_code",
}


def score_deterministic(task: BenchTask, output: str) -> float:
    """Score task output using deterministic pattern-based rubrics.

    Returns a score from 0.0 to 5.0.
    """
    task_scorers = _safe_import_task_scorers()
    scorer_key = _SCORER_CATEGORY_MAP.get(task.category)

    if scorer_key and scorer_key in task_scorers:
        data = {"output_preview": output[:2000], "output_len": len(output)}
        return float(task_scorers[scorer_key](data))

    # Custom scorers for categories not in quality_scorers
    if task.category == "security_scanning":
        return _score_security(task, output)

    # Fallback: basic output quality check
    return _score_generic(output)


def _score_security(task: BenchTask, output: str) -> float:
    """Score security scanning output."""
    score = 0
    gt = task.ground_truth

    # Check for expected CWEs
    expected_cwes = gt.get("expected_cwes", [])
    if expected_cwes:
        found = sum(1 for cwe in expected_cwes if cwe in output)
        if found == len(expected_cwes):
            score += 2
        elif found > 0:
            score += 1

    # Check for minimum findings
    min_findings = gt.get("min_findings", 0)
    if min_findings > 0:
        # Count finding-like patterns in output
        finding_count = len(re.findall(r"(?:severity|finding|issue|vulnerability)", output, re.IGNORECASE))
        if finding_count >= min_findings:
            score += 1

    # Check for file references
    if re.search(r"\w+\.\w+:\d+", output):
        score += 1

    # Check for explanations/recommendations
    if "explanation" in output.lower() or "recommendation" in output.lower():
        score += 1

    return min(score, 5)


def _score_generic(output: str) -> float:
    """Generic output quality scorer."""
    if not output or len(output) < 10:
        return 0.0
    score = 1.0
    if len(output) > 100:
        score += 1
    if re.search(r"\w+\.\w+:\d+", output):  # file:line references
        score += 1
    if len(output) > 500:
        score += 1
    if any(kw in output.lower() for kw in ["function", "class", "module", "import"]):
        score += 1
    return min(score, 5.0)


# ---------------------------------------------------------------------------
# Ground truth matching
# ---------------------------------------------------------------------------


def match_ground_truth(task: BenchTask, output: str) -> dict[str, Any]:
    """Check output against task ground truth criteria.

    Returns a dict of criterion -> {matched: bool, detail: str}.
    """
    gt = task.ground_truth
    results: dict[str, Any] = {}

    # must_contain: list of strings that must appear
    must_contain = gt.get("must_contain", [])
    for term in must_contain:
        found = term.lower() in output.lower()
        results[f"contains:{term}"] = {"matched": found}

    # must_mention_files: list of file paths
    must_files = gt.get("must_mention_files", [])
    for fpath in must_files:
        # Check for the filename or the full path
        fname = fpath.rsplit("/", 1)[-1]
        found = fname in output or fpath in output
        results[f"file:{fpath}"] = {"matched": found}

    # expected_cwes: list of CWE IDs
    expected_cwes = gt.get("expected_cwes", [])
    for cwe in expected_cwes:
        found = cwe in output
        results[f"cwe:{cwe}"] = {"matched": found}

    # min_findings: minimum number of findings
    min_findings = gt.get("min_findings", 0)
    if min_findings > 0:
        count = output.lower().count("finding") + output.lower().count("issue")
        results["min_findings"] = {
            "matched": count >= min_findings,
            "detail": f"{count} found, {min_findings} required",
        }

    return results


# ---------------------------------------------------------------------------
# Combined scoring
# ---------------------------------------------------------------------------


def score_task(task: BenchTask, output: str) -> TaskResult:
    """Score a task using the full pipeline.

    Combines deterministic score with ground truth matching.
    """
    det_score = score_deterministic(task, output)
    gt_match = match_ground_truth(task, output)

    # Ground truth bonus/penalty
    if gt_match:
        matched = sum(1 for v in gt_match.values() if v.get("matched"))
        total = len(gt_match)
        gt_ratio = matched / total if total > 0 else 1.0
        # Blend: 70% deterministic, 30% ground truth match
        weight = task.scoring_rubric.get("deterministic_weight", 0.7)
        final = weight * det_score + (1 - weight) * (gt_ratio * 5.0)
    else:
        final = det_score

    return TaskResult(
        task_id=task.task_id,
        category=task.category,
        repo=task.repo,
        score=round(final, 2),
        deterministic_score=det_score,
        output_text=output,
        ground_truth_match=gt_match,
    )
