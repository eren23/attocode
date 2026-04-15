"""CLI for meta-harness code-intel optimization.

Usage:
    python -m eval.meta_harness baseline              # Evaluate current defaults
    python -m eval.meta_harness run --iterations 10   # Run optimization loop
    python -m eval.meta_harness report                # Show results summary
    python -m eval.meta_harness evaluate config.yaml  # Evaluate a specific config
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))
    sys.path.insert(0, _PROJECT_ROOT)


def cmd_baseline(args: argparse.Namespace) -> None:
    """Evaluate current default config and save as baseline."""
    from eval.meta_harness.evaluator import CodeIntelBenchEvaluator
    from eval.meta_harness.harness_config import HarnessConfig

    print("Evaluating baseline (default scoring config)...")
    print()

    evaluator = CodeIntelBenchEvaluator(
        search_repos=args.search_repos.split(",") if args.search_repos else None,
        bench_repos=args.bench_repos.split(",") if args.bench_repos else None,
        split="" if args.no_split else "eval",
    )

    # Run evaluation
    result = asyncio.run(evaluator.evaluate(_PROJECT_ROOT))

    print(f"Composite score: {result.metric_value:.4f}")
    print()

    if result.metrics:
        print("Component scores:")
        for k, v in result.metrics.items():
            if v is not None:
                print(f"  {k}: {v:.4f}")
        print()

    if result.metadata:
        # Search quality details
        sq = result.metadata.get("search_quality", {})
        if sq and "per_repo" in sq:
            print("Search quality per repo:")
            for repo, metrics in sq["per_repo"].items():
                print(f"  {repo}: MRR={metrics['mrr']:.3f} NDCG={metrics['ndcg']:.3f} "
                      f"P@10={metrics['precision_at_10']:.3f} R@20={metrics['recall_at_20']:.3f}")
            print()

        # MCP bench details
        mb = result.metadata.get("mcp_bench", {})
        if mb and "per_category" in mb:
            print("MCP bench per category:")
            for cat, metrics in mb["per_category"].items():
                print(f"  {cat}: score={metrics['mean_score']:.2f}/5.0 ({metrics['count']} tasks)")
            print()

    # Save baseline
    output_dir = os.path.join(_PROJECT_ROOT, "eval", "meta_harness", "results")
    os.makedirs(output_dir, exist_ok=True)
    baseline_path = os.path.join(output_dir, "baseline.json")
    baseline_data = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "composite_score": result.metric_value,
        "metrics": result.metrics,
        "metadata": result.metadata,
        "config": HarnessConfig.default().to_dict(),
    }
    with open(baseline_path, "w") as f:
        json.dump(baseline_data, f, indent=2, default=str)
    print(f"Baseline saved to: {baseline_path}")


def cmd_evaluate(args: argparse.Namespace) -> None:
    """Evaluate a specific config file."""
    from eval.meta_harness.evaluator import CodeIntelBenchEvaluator
    from eval.meta_harness.harness_config import HarnessConfig

    config = HarnessConfig.load_yaml(args.config_file)
    errors = config.validate()
    if errors:
        print("Config validation errors:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print(f"Evaluating config from: {args.config_file}")
    print(f"Config: {json.dumps(config.to_dict(), indent=2)}")
    print()

    # Write config to temp location for evaluator
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        config.save_yaml(os.path.join(tmpdir, "harness_config.yaml"))

        evaluator = CodeIntelBenchEvaluator(
            search_repos=args.search_repos.split(",") if args.search_repos else None,
            bench_repos=args.bench_repos.split(",") if args.bench_repos else None,
            split="" if args.no_split else "eval",
        )
        result = asyncio.run(evaluator.evaluate(tmpdir))

    print(f"Composite score: {result.metric_value:.4f}")
    if result.metrics:
        for k, v in result.metrics.items():
            if v is not None:
                print(f"  {k}: {v:.4f}")


def cmd_report(args: argparse.Namespace) -> None:
    """Show summary of all evaluation results."""
    results_dir = os.path.join(_PROJECT_ROOT, "eval", "meta_harness", "results")

    # Load baseline
    baseline_path = os.path.join(results_dir, "baseline.json")
    if os.path.isfile(baseline_path):
        with open(baseline_path) as f:
            baseline = json.load(f)
        print(f"Baseline: {baseline['composite_score']:.4f} ({baseline['timestamp']})")
    else:
        print("No baseline found. Run: python -m eval.meta_harness baseline")
        return

    # Load evolution summary
    evo_path = os.path.join(results_dir, "evolution_summary.jsonl")
    if os.path.isfile(evo_path):
        print()
        print("Evolution history:")
        print(f"{'Iter':>5} {'Score':>8} {'Delta':>8} {'Status':>10}")
        print(f"{'─' * 5} {'─' * 8} {'─' * 8} {'─' * 10}")
        with open(evo_path) as f:
            for line in f:
                entry = json.loads(line)
                delta = entry.get("score", 0) - baseline["composite_score"]
                print(
                    f"{entry.get('iteration', '?'):>5} "
                    f"{entry.get('score', 0):>8.4f} "
                    f"{delta:>+8.4f} "
                    f"{entry.get('status', '?'):>10}"
                )
    else:
        print("\nNo evolution history yet. Run: python -m eval.meta_harness run --iterations N")


def cmd_run(args: argparse.Namespace) -> None:
    """Run the meta-harness optimization loop."""
    try:
        from eval.meta_harness.meta_loop import MetaHarnessRunner
    except ImportError:
        print("Meta loop not yet implemented. Run 'baseline' first to verify the inner loop.")
        sys.exit(1)

    runner = MetaHarnessRunner(
        iterations=args.iterations,
        search_repos=args.search_repos.split(",") if args.search_repos else None,
        bench_repos=args.bench_repos.split(",") if args.bench_repos else None,
        propose_mode=args.propose_mode,
    )
    asyncio.run(runner.run())


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="eval.meta_harness",
        description="Meta-harness optimization for code-intel search",
    )
    parser.add_argument("--search-repos", type=str, default=None,
                        help="Comma-separated repos for search quality (default: all)")
    parser.add_argument("--bench-repos", type=str, default=None,
                        help="Comma-separated repos for mcp bench (default: micro_slice)")
    parser.add_argument("--no-split", action="store_true",
                        help="Use all tasks (no train/eval split)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("baseline", help="Evaluate default config as baseline")

    eval_parser = subparsers.add_parser("evaluate", help="Evaluate a config file")
    eval_parser.add_argument("config_file", help="Path to harness_config.yaml")

    subparsers.add_parser("report", help="Show results summary")

    run_parser = subparsers.add_parser("run", help="Run optimization loop")
    run_parser.add_argument("--iterations", type=int, default=10,
                            help="Number of evolution iterations (default: 10)")
    run_parser.add_argument("--propose-mode", choices=["sweep", "llm"], default="sweep",
                            help="Proposal strategy: sweep (random) or llm (Claude)")
    run_parser.add_argument("--candidates", type=int, default=3,
                            help="Candidates per iteration (default: 3)")

    args = parser.parse_args()

    if args.command == "baseline":
        cmd_baseline(args)
    elif args.command == "evaluate":
        cmd_evaluate(args)
    elif args.command == "report":
        cmd_report(args)
    elif args.command == "run":
        cmd_run(args)


if __name__ == "__main__":
    main()
