"""Leaderboard + comparison reports for SWE-bench evaluations.

Generates formatted reports comparing runs and tracking progress
against published SWE-bench leaderboard results.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from eval.harness import ResultsDB, RunResult, InstanceStatus
from eval.metrics import compute_metrics, compare_runs, format_comparison, EvalMetrics
from eval.swebench.efficiency import EfficiencyMetrics


# Published leaderboard entries for comparison
PUBLISHED_LEADERBOARD: list[dict[str, Any]] = [
    {"name": "SWE-agent + GPT-4", "pass_rate": 0.127, "source": "SWE-bench Lite"},
    {"name": "AutoCodeRover", "pass_rate": 0.193, "source": "SWE-bench Lite"},
    {"name": "Aider + GPT-4o", "pass_rate": 0.267, "source": "SWE-bench Lite"},
    {"name": "Devin", "pass_rate": 0.138, "source": "SWE-bench Lite"},
    {"name": "OpenHands + Claude 3.5", "pass_rate": 0.267, "source": "SWE-bench Lite"},
]


@dataclass
class LeaderboardEntry:
    """A single entry in the leaderboard."""
    name: str
    pass_rate: float
    resolved: int = 0
    total: int = 300
    avg_cost: float = 0.0
    avg_tokens: int = 0
    source: str = ""


def generate_leaderboard(
    our_results: list[RunResult],
    run_label: str = "Attoswarm",
    include_published: bool = True,
) -> str:
    """Generate a leaderboard table comparing our results to published ones."""
    metrics = compute_metrics(our_results)

    entries: list[LeaderboardEntry] = []

    # Our entry
    entries.append(LeaderboardEntry(
        name=run_label,
        pass_rate=metrics.pass_rate,
        resolved=metrics.passed,
        total=metrics.total_instances,
        avg_cost=metrics.avg_cost_per_instance,
        avg_tokens=int(metrics.avg_tokens_per_instance),
        source="This run",
    ))

    # Published entries
    if include_published:
        for pub in PUBLISHED_LEADERBOARD:
            entries.append(LeaderboardEntry(
                name=pub["name"],
                pass_rate=pub["pass_rate"],
                total=300,
                resolved=int(pub["pass_rate"] * 300),
                source=pub.get("source", "Published"),
            ))

    # Sort by pass rate descending
    entries.sort(key=lambda e: -e.pass_rate)

    lines = [
        "# SWE-bench Lite Leaderboard",
        "",
        "| Rank | Agent | Pass Rate | Resolved | Avg Cost | Source |",
        "|------|-------|-----------|----------|----------|--------|",
    ]

    for i, e in enumerate(entries, 1):
        display_name = f"**{e.name}**" if e.source == "This run" else e.name
        cost_str = f"${e.avg_cost:.2f}" if e.avg_cost > 0 else "N/A"
        lines.append(
            f"| {i} | {display_name} | {e.pass_rate:.1%} | "
            f"{e.resolved}/{e.total} | {cost_str} | {e.source} |"
        )

    return "\n".join(lines)


def generate_comparison_report(
    results_a: list[RunResult],
    results_b: list[RunResult],
    label_a: str = "Baseline",
    label_b: str = "Current",
) -> str:
    """Generate a detailed comparison between two runs."""
    comp = compare_runs(results_a, results_b, label_a, label_b)
    return format_comparison(comp)


def generate_efficiency_comparison(
    efficiency_a: EfficiencyMetrics,
    efficiency_b: EfficiencyMetrics,
    label_a: str = "Baseline",
    label_b: str = "Current",
) -> str:
    """Compare swarm efficiency between two runs."""
    lines = [
        f"# Efficiency Comparison: {label_a} vs {label_b}",
        "",
        f"| Metric | {label_a} | {label_b} | Delta |",
        "|--------|" + "-" * (len(label_a) + 2) + "|" + "-" * (len(label_b) + 2) + "|-------|",
    ]

    comparisons = [
        ("Task Completion", efficiency_a.task_completion_rate, efficiency_b.task_completion_rate, "%"),
        ("Parallelism", efficiency_a.parallelism_utilization, efficiency_b.parallelism_utilization, "%"),
        ("Budget Accuracy", efficiency_a.budget_accuracy, efficiency_b.budget_accuracy, "%"),
        ("Retry Success", efficiency_a.retry_success_rate, efficiency_b.retry_success_rate, "%"),
        ("Wall Time (s)", efficiency_a.wall_time_seconds, efficiency_b.wall_time_seconds, "s"),
    ]

    for name, val_a, val_b, unit in comparisons:
        delta = val_b - val_a
        if unit == "%":
            lines.append(
                f"| {name} | {val_a:.0%} | {val_b:.0%} | {delta:+.1%} |"
            )
        else:
            lines.append(
                f"| {name} | {val_a:.0f}{unit} | {val_b:.0f}{unit} | {delta:+.0f}{unit} |"
            )

    return "\n".join(lines)


def generate_per_repo_breakdown(
    results: list[RunResult],
) -> str:
    """Break down results by repository."""
    # Group by repo
    by_repo: dict[str, list[RunResult]] = {}
    for r in results:
        repo = r.instance_id.split("__")[0] if "__" in r.instance_id else "unknown"
        by_repo.setdefault(repo, []).append(r)

    lines = [
        "# Per-Repository Breakdown",
        "",
        "| Repository | Total | Passed | Failed | Pass Rate |",
        "|------------|-------|--------|--------|-----------|",
    ]

    for repo in sorted(by_repo.keys()):
        repo_results = by_repo[repo]
        total = len(repo_results)
        passed = sum(1 for r in repo_results if r.status == InstanceStatus.PASSED)
        failed = sum(1 for r in repo_results if r.status == InstanceStatus.FAILED)
        rate = passed / total if total > 0 else 0
        lines.append(f"| {repo} | {total} | {passed} | {failed} | {rate:.1%} |")

    return "\n".join(lines)
