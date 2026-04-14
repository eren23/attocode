"""Report generation for code-intel-bench results."""

from __future__ import annotations

import json
from typing import Any

from eval.mcp_bench.schema import BenchSuiteResult, TaskResult


def format_report(result: BenchSuiteResult) -> str:
    """Format benchmark results as markdown."""
    lines: list[str] = []

    lines.append("# code-intel-bench Results\n")
    lines.append(f"**Adapter**: {result.config.adapter}")
    lines.append(f"**Tasks**: {result.completed_tasks}/{result.total_tasks} completed")
    lines.append(f"**Mean Score**: {result.mean_score:.2f}/5.0")
    lines.append(f"**Median Score**: {result.median_score:.2f}/5.0")
    lines.append(f"**Mean Latency**: {result.mean_latency_ms:.0f}ms\n")

    # Per-category breakdown
    if result.per_category:
        lines.append("## Per-Category Scores\n")
        lines.append("| Category | Mean Score | Tasks | Perfect (>=4.5) |")
        lines.append("|----------|-----------|-------|-----------------|")
        for cat in sorted(result.per_category.keys()):
            stats = result.per_category[cat]
            lines.append(
                f"| {cat} | {stats['mean_score']:.2f} | "
                f"{int(stats['count'])} | {int(stats['perfect'])} |"
            )

    # Top/bottom tasks
    scored = [r for r in result.task_results if not r.error]
    if scored:
        scored.sort(key=lambda r: r.score, reverse=True)

        lines.append("\n## Top Performing Tasks\n")
        for r in scored[:5]:
            lines.append(f"- {r.task_id}: **{r.score:.1f}**/5 ({r.total_latency_ms:.0f}ms)")

        bottom = [r for r in scored if r.score < 3.0]
        if bottom:
            bottom.sort(key=lambda r: r.score)
            lines.append("\n## Needs Improvement (score < 3.0)\n")
            for r in bottom[:10]:
                lines.append(f"- {r.task_id}: **{r.score:.1f}**/5")

    # Errors
    errored = [r for r in result.task_results if r.error]
    if errored:
        lines.append(f"\n## Errors ({len(errored)} tasks)\n")
        for r in errored[:10]:
            lines.append(f"- {r.task_id}: {r.error[:80]}")

    return "\n".join(lines)


def results_to_json(result: BenchSuiteResult) -> str:
    """Serialize results to JSON for comparison."""
    data: dict[str, Any] = {
        "adapter": result.config.adapter,
        "total_tasks": result.total_tasks,
        "completed_tasks": result.completed_tasks,
        "errored_tasks": result.errored_tasks,
        "mean_score": result.mean_score,
        "median_score": result.median_score,
        "mean_latency_ms": result.mean_latency_ms,
        "per_category": result.per_category,
        "tasks": [
            {
                "task_id": r.task_id,
                "category": r.category,
                "repo": r.repo,
                "score": r.score,
                "deterministic_score": r.deterministic_score,
                "latency_ms": r.total_latency_ms,
                "error": r.error,
                "tool_calls": len(r.tool_calls),
            }
            for r in result.task_results
        ],
    }
    return json.dumps(data, indent=2)


def compare_results(a_json: str, b_json: str) -> str:
    """Compare two benchmark result JSON files."""
    a = json.loads(a_json)
    b = json.loads(b_json)

    lines = ["# code-intel-bench Comparison\n"]
    lines.append(f"| Metric | {a.get('adapter', 'A')} | {b.get('adapter', 'B')} | Delta |")
    lines.append("|--------|---|---|-------|")

    for metric in ["mean_score", "median_score", "mean_latency_ms"]:
        va = a.get(metric, 0)
        vb = b.get(metric, 0)
        delta = vb - va
        sign = "+" if delta >= 0 else ""
        lines.append(f"| {metric} | {va:.2f} | {vb:.2f} | {sign}{delta:.2f} |")

    # Per-category comparison
    cats_a = a.get("per_category", {})
    cats_b = b.get("per_category", {})
    all_cats = sorted(set(cats_a.keys()) | set(cats_b.keys()))

    if all_cats:
        lines.append("\n## Per-Category Comparison\n")
        lines.append(f"| Category | {a.get('adapter', 'A')} | {b.get('adapter', 'B')} | Delta |")
        lines.append("|----------|---|---|-------|")
        for cat in all_cats:
            sa = cats_a.get(cat, {}).get("mean_score", 0)
            sb = cats_b.get(cat, {}).get("mean_score", 0)
            delta = sb - sa
            sign = "+" if delta >= 0 else ""
            lines.append(f"| {cat} | {sa:.2f} | {sb:.2f} | {sign}{delta:.2f} |")

    return "\n".join(lines)
