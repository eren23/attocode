"""20-repo experiment: BEFORE vs AFTER meta-harness optimization.

Runs mcp_bench across all repos with two configurations:
- BEFORE: original pre-optimization defaults (`baseline_original.yaml`)
- AFTER: current optimized config (`best_config.yaml`)

Reports per-repo, per-category deltas to validate that gains on the
ground-truth eval set transfer to a broader benchmark.

Usage:
    python -m eval.meta_harness.experiment_20repos
    python -m eval.meta_harness.experiment_20repos --repos all
    python -m eval.meta_harness.experiment_20repos --categories semantic_search,symbol_search
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))
    sys.path.insert(0, _PROJECT_ROOT)

from eval.meta_harness.harness_config import HarnessConfig
from eval.meta_harness.paths import BASELINE_ORIGINAL_CONFIG, BEST_CONFIG_REFERENCE


@dataclass
class RunResult:
    label: str
    config_path: str
    suite: object  # BenchSuiteResult


def discover_local_repos() -> list[str]:
    """Find repos that exist on disk."""
    import yaml
    bench_dir = os.environ.get("BENCHMARK_REPOS_DIR", "/Users/eren/Documents/ai/benchmark-repos")

    with open(os.path.join(_PROJECT_ROOT, "eval", "mcp_bench", "repos.yaml")) as f:
        manifest = yaml.safe_load(f)

    available = []
    for r in manifest.get("repos", []):
        name = r["name"]
        if name == "attocode":
            available.append(name)
            continue
        local_path = r.get("local_path") or os.path.join(bench_dir, name)
        if os.path.isdir(local_path):
            available.append(name)
    return available


def run_mcp_bench_with_config(
    config: HarnessConfig,
    repos: list[str],
    categories: list[str] | None,
    timeout: float = 60.0,
) -> object:
    """Run mcp_bench after applying the harness config to each service.

    The mcp_bench runner calls CodeIntelService directly. We monkey-patch
    the service factory to apply our config to each instance.
    """
    from attocode.code_intel.service import CodeIntelService
    from eval.mcp_bench.mcp_runner import run_benchmark
    from eval.mcp_bench.schema import BenchConfig

    # Save original __init__ so we can wrap it
    original_init = CodeIntelService.__init__

    def patched_init(self, project_dir, *args, **kwargs):
        original_init(self, project_dir, *args, **kwargs)
        config.apply_to_service(self)

    CodeIntelService.__init__ = patched_init

    try:
        bench_config = BenchConfig(
            adapter="attocode",
            repos_filter=repos,
            categories_filter=categories or [],
            timeout_per_task=timeout,
        )
        suite = run_benchmark(bench_config)
        suite.compute_aggregates()
        return suite
    finally:
        CodeIntelService.__init__ = original_init


def format_comparison(before: object, after: object) -> str:
    """Format BEFORE vs AFTER comparison report."""
    lines = [
        "=" * 80,
        "20-REPO EXPERIMENT: BEFORE vs AFTER META-HARNESS OPTIMIZATION",
        "=" * 80,
        "",
        f"Tasks (BEFORE): {before.total_tasks}, completed: {before.completed_tasks}",
        f"Tasks (AFTER):  {after.total_tasks}, completed: {after.completed_tasks}",
        "",
        f"Mean score (0-5 scale):",
        f"  BEFORE: {before.mean_score:.3f}",
        f"  AFTER:  {after.mean_score:.3f}",
        f"  Delta:  {after.mean_score - before.mean_score:+.3f}",
        "",
        f"Mean latency:",
        f"  BEFORE: {before.mean_latency_ms:.0f}ms",
        f"  AFTER:  {after.mean_latency_ms:.0f}ms",
        "",
    ]

    # Per-category breakdown
    lines.append("PER-CATEGORY BREAKDOWN")
    lines.append(f"{'Category':<22} {'BEFORE':>8} {'AFTER':>8} {'Delta':>8} {'BEFORE%':>10} {'AFTER%':>10}")
    lines.append(f"{'-' * 22} {'-' * 8} {'-' * 8} {'-' * 8} {'-' * 10} {'-' * 10}")

    all_cats = sorted(set(before.per_category.keys()) | set(after.per_category.keys()))
    for cat in all_cats:
        b = before.per_category.get(cat, {})
        a = after.per_category.get(cat, {})
        b_score = b.get("mean_score", 0)
        a_score = a.get("mean_score", 0)
        delta = a_score - b_score
        b_pct = (b_score / 5.0) * 100
        a_pct = (a_score / 5.0) * 100
        sign = "+" if delta > 0 else ""
        lines.append(
            f"{cat:<22} {b_score:>8.2f} {a_score:>8.2f} {sign}{delta:>+7.2f} "
            f"{b_pct:>9.1f}% {a_pct:>9.1f}%"
        )

    # Per-repo breakdown
    by_repo_before: dict[str, list[float]] = defaultdict(list)
    by_repo_after: dict[str, list[float]] = defaultdict(list)
    for r in before.task_results:
        if not r.error:
            by_repo_before[r.repo].append(r.score)
    for r in after.task_results:
        if not r.error:
            by_repo_after[r.repo].append(r.score)

    lines.append("")
    lines.append("PER-REPO BREAKDOWN")
    lines.append(f"{'Repo':<18} {'Tasks':>6} {'BEFORE':>8} {'AFTER':>8} {'Delta':>8}")
    lines.append(f"{'-' * 18} {'-' * 6} {'-' * 8} {'-' * 8} {'-' * 8}")

    all_repos = sorted(set(by_repo_before.keys()) | set(by_repo_after.keys()))
    for repo in all_repos:
        b_scores = by_repo_before.get(repo, [])
        a_scores = by_repo_after.get(repo, [])
        n = max(len(b_scores), len(a_scores))
        b_avg = sum(b_scores) / len(b_scores) if b_scores else 0
        a_avg = sum(a_scores) / len(a_scores) if a_scores else 0
        delta = a_avg - b_avg
        sign = "+" if delta > 0 else ""
        marker = "  ⬆️" if delta > 0.1 else ("  ⬇️" if delta < -0.1 else "")
        lines.append(
            f"{repo:<18} {n:>6} {b_avg:>8.2f} {a_avg:>8.2f} {sign}{delta:>+7.2f}{marker}"
        )

    # Summary
    repo_deltas = []
    for repo in all_repos:
        b_avg = sum(by_repo_before.get(repo, [])) / max(len(by_repo_before.get(repo, [])), 1)
        a_avg = sum(by_repo_after.get(repo, [])) / max(len(by_repo_after.get(repo, [])), 1)
        repo_deltas.append(a_avg - b_avg)

    n_better = sum(1 for d in repo_deltas if d > 0.1)
    n_worse = sum(1 for d in repo_deltas if d < -0.1)
    n_same = sum(1 for d in repo_deltas if abs(d) <= 0.1)
    overall_delta = (after.mean_score - before.mean_score) / 5.0 * 100  # percentage points

    lines.extend([
        "",
        "SUMMARY",
        f"  Repos improved (delta > 0.1):  {n_better}/{len(repo_deltas)}",
        f"  Repos regressed (delta < -0.1): {n_worse}/{len(repo_deltas)}",
        f"  Repos unchanged (within 0.1):   {n_same}/{len(repo_deltas)}",
        f"  Overall improvement:            {overall_delta:+.1f} percentage points",
        "=" * 80,
    ])

    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repos", default="all", help="comma-separated or 'all'")
    parser.add_argument("--categories", default=None, help="comma-separated")
    parser.add_argument("--before-config", default=None,
                        help="path to BEFORE config (default: baseline_original.yaml)")
    parser.add_argument("--after-config", default=None,
                        help="path to AFTER config (default: best_config.yaml)")
    parser.add_argument("--output", default=None, help="save report to file")
    args = parser.parse_args()

    before_path = args.before_config or BASELINE_ORIGINAL_CONFIG
    after_path = args.after_config or BEST_CONFIG_REFERENCE

    if not os.path.isfile(before_path):
        print(f"Error: BEFORE config not found at {before_path}")
        sys.exit(1)
    if not os.path.isfile(after_path):
        print(f"Error: AFTER config not found at {after_path}")
        sys.exit(1)

    before_cfg = HarnessConfig.load_yaml(before_path)
    after_cfg = HarnessConfig.load_yaml(after_path)

    if args.repos == "all":
        repos = discover_local_repos()
    else:
        repos = [r.strip() for r in args.repos.split(",") if r.strip()]

    categories = None
    if args.categories:
        categories = [c.strip() for c in args.categories.split(",") if c.strip()]

    print(f"Repos: {repos}")
    print(f"Categories: {categories or 'all'}")
    print()

    print("Running BEFORE...")
    t0 = time.monotonic()
    before_suite = run_mcp_bench_with_config(before_cfg, repos, categories)
    print(f"  Done in {time.monotonic() - t0:.1f}s")
    print(f"  Mean score: {before_suite.mean_score:.3f}/5.0")
    print()

    print("Running AFTER...")
    t1 = time.monotonic()
    after_suite = run_mcp_bench_with_config(after_cfg, repos, categories)
    print(f"  Done in {time.monotonic() - t1:.1f}s")
    print(f"  Mean score: {after_suite.mean_score:.3f}/5.0")
    print()

    report = format_comparison(before_suite, after_suite)
    print(report)

    if args.output:
        with open(args.output, "w") as f:
            f.write(report)
        # Also save raw data
        raw_path = args.output.replace(".txt", "_raw.json")
        with open(raw_path, "w") as f:
            json.dump({
                "before": {
                    "mean_score": before_suite.mean_score,
                    "per_category": before_suite.per_category,
                },
                "after": {
                    "mean_score": after_suite.mean_score,
                    "per_category": after_suite.per_category,
                },
            }, f, indent=2)
        print(f"\nReport saved to: {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
