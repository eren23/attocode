"""Evaluation metrics and statistical analysis.

Computes pass rates, token efficiency, cost analysis, and
provides statistical comparison between eval runs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from eval.harness import InstanceStatus, RunResult


# =============================================================================
# Metric Types
# =============================================================================


@dataclass(slots=True)
class EvalMetrics:
    """Aggregate metrics for an evaluation run."""

    total_instances: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    timeouts: int = 0
    skipped: int = 0

    # Rates
    pass_rate: float = 0.0
    error_rate: float = 0.0

    # Token metrics
    total_tokens: int = 0
    avg_tokens_per_instance: float = 0.0
    median_tokens: float = 0.0
    p95_tokens: float = 0.0

    # Cost metrics
    total_cost_usd: float = 0.0
    avg_cost_per_instance: float = 0.0

    # Time metrics
    total_wall_time_seconds: float = 0.0
    avg_wall_time_seconds: float = 0.0
    median_wall_time_seconds: float = 0.0

    # Iteration metrics
    avg_iterations: float = 0.0
    avg_tool_calls: float = 0.0

    # Per-status breakdown
    status_counts: dict[str, int] = field(default_factory=dict)

    # Model info
    model: str = ""


@dataclass(slots=True)
class ComparisonResult:
    """Result of comparing two evaluation runs."""

    run_a_id: str
    run_b_id: str
    pass_rate_a: float
    pass_rate_b: float
    pass_rate_delta: float
    p_value: float
    is_significant: bool  # p < 0.05
    tokens_delta_pct: float  # % change in avg tokens
    cost_delta_pct: float  # % change in avg cost
    wall_time_delta_pct: float  # % change in avg wall time
    improved_instances: list[str] = field(default_factory=list)
    regressed_instances: list[str] = field(default_factory=list)


# =============================================================================
# Metric Computation
# =============================================================================


def compute_metrics(results: list[RunResult]) -> EvalMetrics:
    """Compute aggregate metrics from a list of run results."""
    if not results:
        return EvalMetrics()

    total = len(results)
    passed = sum(1 for r in results if r.status == InstanceStatus.PASSED)
    failed = sum(1 for r in results if r.status == InstanceStatus.FAILED)
    errors = sum(1 for r in results if r.status == InstanceStatus.ERROR)
    timeouts = sum(1 for r in results if r.status == InstanceStatus.TIMEOUT)
    skipped = sum(1 for r in results if r.status == InstanceStatus.SKIPPED)

    tokens = [r.tokens_used for r in results if r.tokens_used > 0]
    costs = [r.cost_usd for r in results if r.cost_usd > 0]
    times = [r.wall_time_seconds for r in results if r.wall_time_seconds > 0]

    status_counts: dict[str, int] = {}
    for r in results:
        status_counts[r.status.value] = status_counts.get(r.status.value, 0) + 1

    return EvalMetrics(
        total_instances=total,
        passed=passed,
        failed=failed,
        errors=errors,
        timeouts=timeouts,
        skipped=skipped,
        pass_rate=passed / total if total > 0 else 0.0,
        error_rate=(errors + timeouts) / total if total > 0 else 0.0,
        total_tokens=sum(tokens),
        avg_tokens_per_instance=sum(tokens) / len(tokens) if tokens else 0.0,
        median_tokens=_median(tokens),
        p95_tokens=_percentile(tokens, 0.95),
        total_cost_usd=sum(costs),
        avg_cost_per_instance=sum(costs) / len(costs) if costs else 0.0,
        total_wall_time_seconds=sum(times),
        avg_wall_time_seconds=sum(times) / len(times) if times else 0.0,
        median_wall_time_seconds=_median(times),
        avg_iterations=sum(r.iterations for r in results) / total,
        avg_tool_calls=sum(r.tool_calls for r in results) / total,
        status_counts=status_counts,
        model=results[0].model if results else "",
    )


def compare_runs(
    results_a: list[RunResult],
    results_b: list[RunResult],
    run_a_id: str = "A",
    run_b_id: str = "B",
) -> ComparisonResult:
    """Compare two evaluation runs with statistical significance testing.

    Uses a two-proportion z-test to determine if the difference in
    pass rates is statistically significant at p < 0.05.
    """
    metrics_a = compute_metrics(results_a)
    metrics_b = compute_metrics(results_b)

    # Build instance-level comparison
    results_a_map = {r.instance_id: r for r in results_a}
    results_b_map = {r.instance_id: r for r in results_b}

    common_ids = set(results_a_map.keys()) & set(results_b_map.keys())

    improved: list[str] = []
    regressed: list[str] = []

    for iid in common_ids:
        ra = results_a_map[iid]
        rb = results_b_map[iid]
        if ra.status != InstanceStatus.PASSED and rb.status == InstanceStatus.PASSED:
            improved.append(iid)
        elif ra.status == InstanceStatus.PASSED and rb.status != InstanceStatus.PASSED:
            regressed.append(iid)

    # Two-proportion z-test
    p_value = _two_proportion_z_test(
        metrics_a.passed, metrics_a.total_instances,
        metrics_b.passed, metrics_b.total_instances,
    )

    # Delta percentages
    def _pct_delta(a: float, b: float) -> float:
        if a == 0:
            return 0.0 if b == 0 else 100.0
        return ((b - a) / a) * 100

    return ComparisonResult(
        run_a_id=run_a_id,
        run_b_id=run_b_id,
        pass_rate_a=metrics_a.pass_rate,
        pass_rate_b=metrics_b.pass_rate,
        pass_rate_delta=metrics_b.pass_rate - metrics_a.pass_rate,
        p_value=p_value,
        is_significant=p_value < 0.05,
        tokens_delta_pct=_pct_delta(
            metrics_a.avg_tokens_per_instance,
            metrics_b.avg_tokens_per_instance,
        ),
        cost_delta_pct=_pct_delta(
            metrics_a.avg_cost_per_instance,
            metrics_b.avg_cost_per_instance,
        ),
        wall_time_delta_pct=_pct_delta(
            metrics_a.avg_wall_time_seconds,
            metrics_b.avg_wall_time_seconds,
        ),
        improved_instances=improved,
        regressed_instances=regressed,
    )


# =============================================================================
# Reporting
# =============================================================================


def format_report(metrics: EvalMetrics) -> str:
    """Format metrics into a human-readable text report."""
    lines = [
        "=" * 60,
        "EVALUATION REPORT",
        "=" * 60,
        "",
        f"Model: {metrics.model}",
        f"Total instances: {metrics.total_instances}",
        "",
        "--- Results ---",
        f"  Passed:   {metrics.passed:>4} ({metrics.pass_rate:.1%})",
        f"  Failed:   {metrics.failed:>4}",
        f"  Errors:   {metrics.errors:>4}",
        f"  Timeouts: {metrics.timeouts:>4}",
        f"  Skipped:  {metrics.skipped:>4}",
        "",
        "--- Tokens ---",
        f"  Total:    {metrics.total_tokens:>12,}",
        f"  Average:  {metrics.avg_tokens_per_instance:>12,.0f}",
        f"  Median:   {metrics.median_tokens:>12,.0f}",
        f"  P95:      {metrics.p95_tokens:>12,.0f}",
        "",
        "--- Cost ---",
        f"  Total:    ${metrics.total_cost_usd:>10.2f}",
        f"  Average:  ${metrics.avg_cost_per_instance:>10.4f}",
        "",
        "--- Time ---",
        f"  Total:    {metrics.total_wall_time_seconds:>10.1f}s",
        f"  Average:  {metrics.avg_wall_time_seconds:>10.1f}s",
        f"  Median:   {metrics.median_wall_time_seconds:>10.1f}s",
        "",
        "--- Agent ---",
        f"  Avg iterations: {metrics.avg_iterations:.1f}",
        f"  Avg tool calls: {metrics.avg_tool_calls:.1f}",
        "",
        "=" * 60,
    ]
    return "\n".join(lines)


def format_comparison(comp: ComparisonResult) -> str:
    """Format a comparison result into a text report."""
    sig = "SIGNIFICANT" if comp.is_significant else "not significant"
    direction = "improvement" if comp.pass_rate_delta > 0 else "regression"

    lines = [
        "=" * 60,
        f"COMPARISON: {comp.run_a_id} vs {comp.run_b_id}",
        "=" * 60,
        "",
        f"Pass rate A: {comp.pass_rate_a:.1%}",
        f"Pass rate B: {comp.pass_rate_b:.1%}",
        f"Delta:       {comp.pass_rate_delta:+.1%} ({direction})",
        f"p-value:     {comp.p_value:.4f} ({sig})",
        "",
        f"Token change:    {comp.tokens_delta_pct:+.1f}%",
        f"Cost change:     {comp.cost_delta_pct:+.1f}%",
        f"Time change:     {comp.wall_time_delta_pct:+.1f}%",
        "",
        f"Improved:  {len(comp.improved_instances)} instances",
        f"Regressed: {len(comp.regressed_instances)} instances",
    ]

    if comp.improved_instances:
        lines.append("")
        lines.append("Improved instances:")
        for iid in comp.improved_instances[:10]:
            lines.append(f"  + {iid}")

    if comp.regressed_instances:
        lines.append("")
        lines.append("Regressed instances:")
        for iid in comp.regressed_instances[:10]:
            lines.append(f"  - {iid}")

    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)


# =============================================================================
# Statistical Helpers
# =============================================================================


def _median(values: list[float | int]) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n % 2 == 0:
        return (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2
    return float(sorted_vals[n // 2])


def _percentile(values: list[float | int], p: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = p * (len(sorted_vals) - 1)
    lower = int(math.floor(idx))
    upper = min(lower + 1, len(sorted_vals) - 1)
    weight = idx - lower
    return sorted_vals[lower] * (1 - weight) + sorted_vals[upper] * weight


def _two_proportion_z_test(
    successes_a: int,
    total_a: int,
    successes_b: int,
    total_b: int,
) -> float:
    """Two-proportion z-test. Returns p-value.

    Tests whether two proportions are significantly different.
    """
    if total_a == 0 or total_b == 0:
        return 1.0

    p_a = successes_a / total_a
    p_b = successes_b / total_b
    p_pool = (successes_a + successes_b) / (total_a + total_b)

    if p_pool == 0 or p_pool == 1:
        return 1.0

    se = math.sqrt(p_pool * (1 - p_pool) * (1 / total_a + 1 / total_b))
    if se == 0:
        return 1.0

    z = abs(p_a - p_b) / se

    # Approximate p-value using standard normal CDF
    # Using the Abramowitz and Stegun approximation
    return 2 * (1 - _normal_cdf(z))


def _normal_cdf(x: float) -> float:
    """Approximate standard normal CDF using error function."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))
