"""CLI for code-intel-bench.

Usage:
    python -m eval.mcp_bench run --adapter attocode
    python -m eval.mcp_bench run --adapter attocode --categories orientation symbol_search
    python -m eval.mcp_bench run --adapter attocode --repos fastapi express --output results.json
    python -m eval.mcp_bench compare results_a.json results_b.json
    python -m eval.mcp_bench report results.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="code-intel-bench: The benchmark for code intelligence MCP servers",
    )
    sub = parser.add_subparsers(dest="command")

    # Run
    run_p = sub.add_parser("run", help="Run benchmark suite")
    run_p.add_argument("--adapter", default="attocode", choices=["attocode", "ripgrep", "ast_grep"])
    run_p.add_argument("--categories", nargs="*", default=[])
    run_p.add_argument("--repos", nargs="*", default=[])
    run_p.add_argument("--output", default="", help="Save results JSON to file")
    run_p.add_argument("--timeout", type=float, default=60.0)

    # Compare
    cmp_p = sub.add_parser("compare", help="Compare two result files")
    cmp_p.add_argument("file_a")
    cmp_p.add_argument("file_b")

    # Report
    rpt_p = sub.add_parser("report", help="Generate report from results file")
    rpt_p.add_argument("file")

    args = parser.parse_args()

    if args.command == "run":
        from eval.mcp_bench.mcp_runner import run_benchmark
        from eval.mcp_bench.schema import BenchConfig
        from eval.mcp_bench.report import format_report, results_to_json

        config = BenchConfig(
            adapter=args.adapter,
            categories_filter=args.categories,
            repos_filter=args.repos,
            timeout_per_task=args.timeout,
        )

        result = run_benchmark(config)
        print(format_report(result))

        if args.output:
            Path(args.output).write_text(results_to_json(result), encoding="utf-8")
            print(f"\nResults saved to {args.output}")

    elif args.command == "compare":
        from eval.mcp_bench.report import compare_results
        a = Path(args.file_a).read_text(encoding="utf-8")
        b = Path(args.file_b).read_text(encoding="utf-8")
        print(compare_results(a, b))

    elif args.command == "report":
        from eval.mcp_bench.schema import BenchSuiteResult, BenchConfig
        from eval.mcp_bench.report import format_report
        import json

        data = json.loads(Path(args.file).read_text(encoding="utf-8"))
        # Reconstruct minimal suite result from JSON
        from eval.mcp_bench.schema import TaskResult
        suite = BenchSuiteResult(
            config=BenchConfig(adapter=data.get("adapter", "")),
            total_tasks=data.get("total_tasks", 0),
            completed_tasks=data.get("completed_tasks", 0),
            mean_score=data.get("mean_score", 0),
            median_score=data.get("median_score", 0),
            mean_latency_ms=data.get("mean_latency_ms", 0),
            per_category=data.get("per_category", {}),
            task_results=[
                TaskResult(
                    task_id=t["task_id"],
                    category=t.get("category", ""),
                    repo=t.get("repo", ""),
                    score=t.get("score", 0),
                    error=t.get("error", ""),
                )
                for t in data.get("tasks", [])
            ],
        )
        print(format_report(suite))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
