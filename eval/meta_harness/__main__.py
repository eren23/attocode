"""CLI for meta-harness optimization.

Usage:
    python -m eval.meta_harness baseline              # Evaluate current defaults
    python -m eval.meta_harness run --iterations 10   # Run optimization loop
    python -m eval.meta_harness report                # Show results summary
    python -m eval.meta_harness evaluate config.yaml  # Evaluate a specific config

The optional ``--bench {search|rule|composite}`` flag selects which
inner-loop benchmark to optimize. ``search`` is the default and matches
historical behavior; ``rule`` drives the rule-bench harness (Step 5);
``composite`` runs both legs (Step 10).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from typing import Any

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))
    sys.path.insert(0, _PROJECT_ROOT)

from eval.meta_harness.paths import (
    baseline_path as _baseline_path,
)
from eval.meta_harness.paths import (
    ensure_results_dir,
)
from eval.meta_harness.paths import (
    evolution_path as _evolution_path,
)


def _select_bench(args: argparse.Namespace) -> dict[str, Any]:
    """Resolve a bench mode into the plumbing required by each subcommand.

    Returns a dict with keys: ``name``, ``spec`` (BenchSpec for the runner),
    ``evaluator`` (for one-shot baseline/evaluate), ``config_default``,
    ``config_loader`` (callable: path -> config), and ``artifact_prefix``.
    """
    bench = getattr(args, "bench", "search") or "search"

    if bench == "search":
        from eval.meta_harness.evaluator import CodeIntelBenchEvaluator
        from eval.meta_harness.harness_config import HarnessConfig
        from eval.meta_harness.meta_loop import make_search_bench_spec

        evaluator = CodeIntelBenchEvaluator(
            search_repos=args.search_repos.split(",") if args.search_repos else None,
            bench_repos=args.bench_repos.split(",") if args.bench_repos else None,
            split="" if args.no_split else "eval",
        )
        return {
            "name": "search",
            "spec": make_search_bench_spec(
                search_repos=args.search_repos.split(",") if args.search_repos else None,
                bench_repos=args.bench_repos.split(",") if args.bench_repos else None,
                split="" if args.no_split else "eval",
            ),
            "evaluator": evaluator,
            "config_default": HarnessConfig.default(),
            "config_loader": HarnessConfig.load_yaml,
            "config_filename": "harness_config.yaml",
            "artifact_prefix": "",
        }

    if bench == "rule":
        # Wired in Step 5. Stub out gracefully so --help / argparse still works.
        try:
            from eval.meta_harness.rule_bench.cli import build_rule_bench  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - exercised pre-Step-5
            raise SystemExit(
                f"--bench rule is not yet wired ({exc}). Land Steps 3-5 first."
            ) from exc
        return build_rule_bench(args)

    if bench == "composite":
        try:
            from eval.meta_harness.composite_evaluator import build_composite_bench  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - exercised pre-Step-10
            raise SystemExit(
                f"--bench composite is not yet wired ({exc}). Land Step 10 first."
            ) from exc
        return build_composite_bench(args)

    raise SystemExit(f"Unknown bench: {bench!r}")


def cmd_baseline(args: argparse.Namespace) -> None:
    """Evaluate current default config and save as baseline."""
    bench = _select_bench(args)

    print(f"Evaluating baseline ({bench['name']} bench)...")
    print()

    result = asyncio.run(bench["evaluator"].evaluate(_PROJECT_ROOT))

    if not result.success:
        print(f"Baseline evaluation failed: {result.error}")
        sys.exit(1)

    print(f"Composite score: {result.metric_value:.4f}")
    print()

    if result.metrics:
        print("Component scores:")
        for k, v in result.metrics.items():
            if v is not None:
                print(f"  {k}: {v:.4f}")
        print()

    if result.metadata:
        sq = result.metadata.get("search_quality", {})
        if sq and "per_repo" in sq:
            print("Search quality per repo:")
            for repo, metrics in sq["per_repo"].items():
                print(f"  {repo}: MRR={metrics['mrr']:.3f} NDCG={metrics['ndcg']:.3f} "
                      f"P@10={metrics['precision_at_10']:.3f} R@20={metrics['recall_at_20']:.3f}")
            print()

        mb = result.metadata.get("mcp_bench", {})
        if mb and "per_category" in mb:
            print("MCP bench per category:")
            for cat, metrics in mb["per_category"].items():
                print(f"  {cat}: score={metrics['mean_score']:.2f}/5.0 ({metrics['count']} tasks)")
            print()

        per_lang = result.metadata.get("per_language")
        if per_lang:
            print("Rule-bench per language:")
            for lang, score in per_lang.items():
                print(f"  {lang}: F1={score:.4f}")
            print()

    ensure_results_dir()
    baseline_path = _baseline_path(bench["artifact_prefix"])
    baseline_data = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "bench": bench["name"],
        "composite_score": result.metric_value,
        "metrics": result.metrics,
        "metadata": result.metadata,
        "config": bench["config_default"].to_dict(),
    }
    with open(baseline_path, "w") as f:
        json.dump(baseline_data, f, indent=2, default=str)
    print(f"Baseline saved to: {baseline_path}")


def cmd_evaluate(args: argparse.Namespace) -> None:
    """Evaluate a specific config file."""
    bench = _select_bench(args)

    config = bench["config_loader"](args.config_file)
    errors = config.validate()
    if errors:
        print("Config validation errors:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print(f"Evaluating config from: {args.config_file}")
    print(f"Config: {json.dumps(config.to_dict(), indent=2, default=str)}")
    print()

    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        config.save_yaml(os.path.join(tmpdir, bench["config_filename"]))
        result = asyncio.run(bench["evaluator"].evaluate(tmpdir))

    print(f"Composite score: {result.metric_value:.4f}")
    if result.metrics:
        for k, v in result.metrics.items():
            if v is not None:
                print(f"  {k}: {v:.4f}")


def cmd_report(args: argparse.Namespace) -> None:
    """Show summary of all evaluation results for the selected bench."""
    bench_name = getattr(args, "bench", "search") or "search"
    prefix = "" if bench_name == "search" else f"{bench_name}_"

    baseline_path = _baseline_path(prefix)
    if os.path.isfile(baseline_path):
        with open(baseline_path) as f:
            baseline = json.load(f)
        print(f"Baseline ({bench_name}): {baseline['composite_score']:.4f} ({baseline['timestamp']})")
    else:
        print(f"No baseline found for bench '{bench_name}'.")
        print(f"Run: python -m eval.meta_harness --bench {bench_name} baseline")
        return

    evo_path = _evolution_path(prefix)
    if os.path.isfile(evo_path):
        print()
        print("Evolution history:")
        print(f"{'Iter':>5} {'Score':>8} {'Delta':>8} {'Status':>10} {'Reason':<40}")
        print(f"{'─' * 5} {'─' * 8} {'─' * 8} {'─' * 10} {'─' * 40}")
        with open(evo_path) as f:
            for line in f:
                entry = json.loads(line)
                delta = entry.get("score", 0) - baseline["composite_score"]
                reason = entry.get("reject_reason") or ""
                print(
                    f"{entry.get('iteration', '?'):>5} "
                    f"{entry.get('score', 0):>8.4f} "
                    f"{delta:>+8.4f} "
                    f"{entry.get('status', '?'):>10} "
                    f"{reason[:40]:<40}"
                )
    else:
        print(f"\nNo evolution history yet. Run: python -m eval.meta_harness --bench {bench_name} run --iterations N")


def cmd_run(args: argparse.Namespace) -> None:
    """Run the meta-harness optimization loop."""
    from eval.meta_harness.meta_loop import MetaHarnessRunner

    bench = _select_bench(args)

    runner = MetaHarnessRunner(
        iterations=args.iterations,
        candidates_per_iteration=args.candidates,
        propose_mode=args.propose_mode,
        bench_spec=bench["spec"],
    )
    asyncio.run(runner.run())


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="eval.meta_harness",
        description="Meta-harness optimization for code-intel",
    )
    parser.add_argument("--bench", choices=["search", "rule", "composite"], default="search",
                        help="Which inner-loop benchmark to optimize (default: search)")
    parser.add_argument("--search-repos", type=str, default=None,
                        help="Comma-separated repos for search quality (default: all)")
    parser.add_argument("--bench-repos", type=str, default=None,
                        help="Comma-separated repos for mcp bench (default: micro_slice)")
    parser.add_argument("--no-split", action="store_true",
                        help="Use all tasks (no train/eval split)")

    # Rule-bench specific (ignored by other benches; used in Step 5)
    parser.add_argument("--packs", type=str, default=None,
                        help="Comma-separated rule packs to load (rule bench)")
    parser.add_argument("--corpus-dir", type=str, default=None,
                        help="Path to fixture corpus root (rule bench)")
    parser.add_argument("--include-community", action="store_true",
                        help="Include packs/community/* in rule-bench corpus")
    parser.add_argument("--include-attocode-fixtures", action="store_true",
                        help="Include eval/rule_harness/fixtures/attocode/* in rule-bench corpus")
    parser.add_argument("--include-legacy-corpus", action="store_true",
                        help="Include eval/rule_accuracy/corpus/* in rule-bench corpus")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("baseline", help="Evaluate default config as baseline")

    eval_parser = subparsers.add_parser("evaluate", help="Evaluate a config file")
    eval_parser.add_argument("config_file", help="Path to config YAML")

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
