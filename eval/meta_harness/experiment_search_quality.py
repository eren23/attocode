"""Search quality experiment: BEFORE vs AFTER meta-harness optimization.

Uses rank-sensitive metrics (MRR, NDCG, P@k, R@k) on the 5 ground-truth
repos to measure ranking improvements that mcp_bench misses.

Usage:
    python -m eval.meta_harness.experiment_search_quality
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))
    sys.path.insert(0, _PROJECT_ROOT)

from attocode.code_intel.service import CodeIntelService

from eval.meta_harness.harness_config import HarnessConfig
from eval.meta_harness.paths import BASELINE_ORIGINAL_CONFIG, BEST_CONFIG_REFERENCE
from eval.metrics import (
    compute_mrr,
    compute_ndcg,
    compute_precision_at_k,
    compute_recall_at_k,
)
from eval.search_quality import REPO_CONFIGS, load_ground_truth, parse_search_results


@dataclass
class RepoMetrics:
    repo: str
    n_queries: int
    mrr: float
    ndcg: float
    precision: float
    recall: float
    avg_latency_ms: float


def evaluate_with_config(
    config: HarnessConfig,
    repos: list[str],
    nl_mode_override: str | None = None,
) -> list[RepoMetrics]:
    """Run search quality eval on each repo with the given config applied.

    Args:
        config: Harness config to apply.
        repos: List of repo names with ground truth.
        nl_mode_override: If set, override SemanticSearchManager nl_mode
                          (e.g., "none" to simulate pre-NL-default behavior).
    """
    results: list[RepoMetrics] = []

    for repo in repos:
        path = REPO_CONFIGS.get(repo)
        if not path or not os.path.isdir(path):
            print(f"  SKIP {repo}: path not found")
            continue

        queries = load_ground_truth(repo)
        if not queries:
            print(f"  SKIP {repo}: no ground truth")
            continue

        # Fresh service so we don't leak per-query state
        svc = CodeIntelService(path)
        config.apply_to_service(svc)

        # Override nl_mode if requested (force keyword-only path for true BEFORE)
        if nl_mode_override is not None:
            mgr = svc._get_semantic_search()
            mgr.nl_mode = nl_mode_override

        mrrs, ndcgs, precs, recs, latencies = [], [], [], [], []
        for entry in queries:
            q = entry["query"]
            relevant = set(entry["relevant_files"])
            t0 = time.perf_counter()
            output = svc.semantic_search(q)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            retrieved = parse_search_results(output, max_results=20)

            mrrs.append(compute_mrr(retrieved, relevant, k=10))
            ndcgs.append(compute_ndcg(retrieved, relevant, k=10))
            precs.append(compute_precision_at_k(retrieved, relevant, k=10))
            recs.append(compute_recall_at_k(retrieved, relevant, k=20))
            latencies.append(elapsed_ms)

        n = len(mrrs)
        results.append(RepoMetrics(
            repo=repo,
            n_queries=n,
            mrr=sum(mrrs) / n if n else 0,
            ndcg=sum(ndcgs) / n if n else 0,
            precision=sum(precs) / n if n else 0,
            recall=sum(recs) / n if n else 0,
            avg_latency_ms=sum(latencies) / n if n else 0,
        ))

    return results


def format_comparison(
    before: list[RepoMetrics],
    after: list[RepoMetrics],
    before_label: str = "BEFORE",
    after_label: str = "AFTER",
) -> str:
    """Format BEFORE vs AFTER comparison report."""
    by_repo_b = {r.repo: r for r in before}
    by_repo_a = {r.repo: r for r in after}
    repos = sorted(set(by_repo_b.keys()) | set(by_repo_a.keys()))

    lines = [
        "=" * 95,
        f"SEARCH QUALITY EXPERIMENT: {before_label} vs {after_label}",
        "=" * 95,
        "",
        f"{'Repo':<12} {'N':>4} | "
        f"{'B-MRR':>6} {'A-MRR':>6} {'ΔMRR':>7} | "
        f"{'B-NDCG':>7} {'A-NDCG':>7} {'ΔNDCG':>7} | "
        f"{'B-R@20':>7} {'A-R@20':>7}",
        f"{'-' * 12} {'-' * 4}-+-"
        f"{'-' * 6} {'-' * 6} {'-' * 7}-+-"
        f"{'-' * 7} {'-' * 7} {'-' * 7}-+-"
        f"{'-' * 7} {'-' * 7}",
    ]

    total_n = 0
    weighted_b_mrr = 0
    weighted_a_mrr = 0
    weighted_b_ndcg = 0
    weighted_a_ndcg = 0
    weighted_b_rec = 0
    weighted_a_rec = 0

    n_better = n_worse = n_same = 0

    for repo in repos:
        b = by_repo_b.get(repo)
        a = by_repo_a.get(repo)
        if not b or not a:
            continue
        n = max(b.n_queries, a.n_queries)
        d_mrr = a.mrr - b.mrr
        d_ndcg = a.ndcg - b.ndcg

        marker = ""
        if d_mrr > 0.05:
            marker = " ⬆️"
            n_better += 1
        elif d_mrr < -0.05:
            marker = " ⬇️"
            n_worse += 1
        else:
            n_same += 1

        lines.append(
            f"{repo:<12} {n:>4} | "
            f"{b.mrr:>6.3f} {a.mrr:>6.3f} {d_mrr:>+7.3f} | "
            f"{b.ndcg:>7.3f} {a.ndcg:>7.3f} {d_ndcg:>+7.3f} | "
            f"{b.recall:>7.3f} {a.recall:>7.3f}{marker}"
        )

        total_n += n
        weighted_b_mrr += b.mrr * n
        weighted_a_mrr += a.mrr * n
        weighted_b_ndcg += b.ndcg * n
        weighted_a_ndcg += a.ndcg * n
        weighted_b_rec += b.recall * n
        weighted_a_rec += a.recall * n

    if total_n > 0:
        ovr_b_mrr = weighted_b_mrr / total_n
        ovr_a_mrr = weighted_a_mrr / total_n
        ovr_b_ndcg = weighted_b_ndcg / total_n
        ovr_a_ndcg = weighted_a_ndcg / total_n
        ovr_b_rec = weighted_b_rec / total_n
        ovr_a_rec = weighted_a_rec / total_n

        lines.append(f"{'-' * 12} {'-' * 4}-+-"
                     f"{'-' * 6} {'-' * 6} {'-' * 7}-+-"
                     f"{'-' * 7} {'-' * 7} {'-' * 7}-+-"
                     f"{'-' * 7} {'-' * 7}")
        lines.append(
            f"{'OVERALL':<12} {total_n:>4} | "
            f"{ovr_b_mrr:>6.3f} {ovr_a_mrr:>6.3f} {ovr_a_mrr - ovr_b_mrr:>+7.3f} | "
            f"{ovr_b_ndcg:>7.3f} {ovr_a_ndcg:>7.3f} {ovr_a_ndcg - ovr_b_ndcg:>+7.3f} | "
            f"{ovr_b_rec:>7.3f} {ovr_a_rec:>7.3f}"
        )

        rel_mrr = (ovr_a_mrr - ovr_b_mrr) / ovr_b_mrr * 100 if ovr_b_mrr > 0 else 0
        lines.extend([
            "",
            "SUMMARY",
            f"  Repos improved (ΔMRR > 0.05): {n_better}/{len(repos)}",
            f"  Repos regressed (ΔMRR < -0.05): {n_worse}/{len(repos)}",
            f"  Repos unchanged: {n_same}/{len(repos)}",
            f"  MRR: {ovr_b_mrr:.3f} → {ovr_a_mrr:.3f} ({rel_mrr:+.1f}% relative)",
            f"  NDCG: {ovr_b_ndcg:.3f} → {ovr_a_ndcg:.3f}",
            f"  Recall@20: {ovr_b_rec:.3f} → {ovr_a_rec:.3f}",
        ])

    lines.append("=" * 95)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repos", default=None, help="comma-separated (default: all available)")
    parser.add_argument("--before-config", default=None)
    parser.add_argument("--after-config", default=None)
    parser.add_argument("--before-label", default="BEFORE (original defaults, no vectors)")
    parser.add_argument("--after-label", default="AFTER (optimized + adaptive fusion)")
    parser.add_argument("--no-nl-override", action="store_true",
                        help="Don't force nl_mode=none for BEFORE (use config as-is)")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    before_path = args.before_config or BASELINE_ORIGINAL_CONFIG
    after_path = args.after_config or BEST_CONFIG_REFERENCE

    before_cfg = HarnessConfig.load_yaml(before_path)
    after_cfg = HarnessConfig.load_yaml(after_path)

    if args.repos:
        repos = [r.strip() for r in args.repos.split(",")]
    else:
        # Discover repos with both ground truth and a local path
        from eval.search_quality import discover_repos_with_ground_truth
        repos = discover_repos_with_ground_truth()

    print(f"Repos: {repos}")
    print()

    print(f"Running {args.before_label}...")
    t0 = time.monotonic()
    nl_override = None if args.no_nl_override else "none"
    before_results = evaluate_with_config(before_cfg, repos, nl_mode_override=nl_override)
    print(f"  Done in {time.monotonic() - t0:.1f}s")
    print()

    print(f"Running {args.after_label}...")
    t1 = time.monotonic()
    after_results = evaluate_with_config(after_cfg, repos, nl_mode_override=None)
    print(f"  Done in {time.monotonic() - t1:.1f}s")
    print()

    report = format_comparison(before_results, after_results,
                                args.before_label, args.after_label)
    print(report)

    if args.output:
        with open(args.output, "w") as f:
            f.write(report)
        raw = {
            "before": [r.__dict__ for r in before_results],
            "after": [r.__dict__ for r in after_results],
            "before_label": args.before_label,
            "after_label": args.after_label,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(args.output.replace(".txt", "_raw.json"), "w") as f:
            json.dump(raw, f, indent=2)
        print(f"\nReport saved to: {args.output}")


if __name__ == "__main__":
    main()
