"""Eval runner — CLI entry point for running evaluations.

Usage:
    # Run on SWE-bench Lite (first 10 instances)
    python -m eval.runner --dataset swe-bench-lite --limit 10

    # Compare two runs
    python -m eval.runner --compare run-A run-B

    # List past runs
    python -m eval.runner --history
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

from eval.harness import BenchInstance, EvalHarness, ResultsDB
from eval.metrics import compare_runs, compute_metrics, format_comparison, format_report

logger = logging.getLogger(__name__)


# =============================================================================
# Dataset Loaders
# =============================================================================


def load_swe_bench_instances(
    dataset_path: str,
    *,
    limit: int | None = None,
    split: str = "test",
) -> list[BenchInstance]:
    """Load SWE-bench instances from a JSONL file.

    Expected format per line:
    {
        "instance_id": "django__django-16379",
        "repo": "django/django",
        "base_commit": "abc123",
        "problem_statement": "...",
        "patch": "...",
        "test_patch": "...",
        "hints_text": "..."
    }
    """
    path = Path(dataset_path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    instances: list[BenchInstance] = []
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            instances.append(BenchInstance(
                instance_id=data["instance_id"],
                repo=data.get("repo", ""),
                base_commit=data.get("base_commit", ""),
                problem_statement=data.get("problem_statement", ""),
                patch_gold=data.get("patch", ""),
                test_patch=data.get("test_patch", ""),
                hints=data.get("hints_text", ""),
                metadata={
                    "split": split,
                    "version": data.get("version", ""),
                },
            ))

            if limit and len(instances) >= limit:
                break

    return instances


# =============================================================================
# Agent Factory
# =============================================================================


class AttocodeAgentFactory:
    """Factory that creates Attocode agent instances for evaluation."""

    def __init__(
        self,
        model: str = "",
        provider: str = "anthropic",
        max_iterations: int = 50,
    ) -> None:
        self.model = model
        self.provider = provider
        self.max_iterations = max_iterations

    async def create_and_run(
        self,
        working_dir: str,
        problem_statement: str,
        *,
        model: str | None = None,
        max_iterations: int = 50,
        timeout: float = 600.0,
    ) -> dict[str, Any]:
        """Create and run an Attocode agent on the problem."""
        from attocode.agent.builder import AgentBuilder

        agent = (
            AgentBuilder()
            .with_provider(self.provider)
            .with_model(model or self.model)
            .with_working_dir(working_dir)
            .with_max_iterations(max_iterations)
            .with_sandbox(enabled=True, mode="auto")
            .with_economics(enabled=True)
            .with_compaction(enabled=True)
            .build()
        )

        try:
            result = await asyncio.wait_for(
                agent.run(problem_statement),
                timeout=timeout,
            )

            return {
                "success": result.success,
                "output": result.response,
                "tokens_used": result.metrics.total_tokens if result.metrics else 0,
                "cost": result.metrics.total_cost if result.metrics else 0.0,
                "iterations": result.metrics.iterations if result.metrics else 0,
                "tool_calls": result.metrics.tool_calls if result.metrics else 0,
                "model": model or self.model,
            }
        except asyncio.TimeoutError:
            raise
        except Exception as exc:
            return {
                "success": False,
                "output": str(exc),
                "tokens_used": 0,
                "cost": 0.0,
                "iterations": 0,
                "tool_calls": 0,
                "model": model or self.model,
            }
        finally:
            try:
                await agent.cleanup()
            except Exception:
                pass


# =============================================================================
# CLI
# =============================================================================


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Attocode Evaluation Harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run evaluation")
    run_parser.add_argument(
        "--dataset", required=True,
        help="Path to dataset JSONL file",
    )
    run_parser.add_argument(
        "--model", default="claude-sonnet-4-20250514",
        help="Model to use",
    )
    run_parser.add_argument(
        "--provider", default="anthropic",
        help="LLM provider",
    )
    run_parser.add_argument(
        "--limit", type=int, default=None,
        help="Max instances to run",
    )
    run_parser.add_argument(
        "--concurrency", type=int, default=1,
        help="Parallel instances",
    )
    run_parser.add_argument(
        "--max-iterations", type=int, default=50,
        help="Max agent iterations per instance",
    )
    run_parser.add_argument(
        "--timeout", type=float, default=600.0,
        help="Timeout per instance in seconds",
    )
    run_parser.add_argument(
        "--run-id", default="",
        help="Custom run ID",
    )
    run_parser.add_argument(
        "--db", default="eval_results.db",
        help="Results database path",
    )

    # Compare command
    compare_parser = subparsers.add_parser("compare", help="Compare two runs")
    compare_parser.add_argument("run_a", help="First run ID")
    compare_parser.add_argument("run_b", help="Second run ID")
    compare_parser.add_argument(
        "--db", default="eval_results.db",
        help="Results database path",
    )

    # History command
    history_parser = subparsers.add_parser("history", help="Show run history")
    history_parser.add_argument(
        "--db", default="eval_results.db",
        help="Results database path",
    )
    history_parser.add_argument(
        "--limit", type=int, default=20,
        help="Max runs to show",
    )

    return parser


async def cmd_run(args: argparse.Namespace) -> None:
    """Execute the 'run' command."""
    instances = load_swe_bench_instances(
        args.dataset,
        limit=args.limit,
    )
    print(f"Loaded {len(instances)} instances")

    factory = AttocodeAgentFactory(
        model=args.model,
        provider=args.provider,
        max_iterations=args.max_iterations,
    )

    harness = EvalHarness(
        agent_factory=factory,
        results_db=args.db,
        model=args.model,
        max_iterations=args.max_iterations,
        timeout=args.timeout,
    )

    run_id = args.run_id or f"eval-{int(time.time())}"
    print(f"Starting eval run: {run_id}")

    results = await harness.run_suite(
        instances,
        run_id=run_id,
        concurrency=args.concurrency,
        config={
            "model": args.model,
            "provider": args.provider,
            "max_iterations": args.max_iterations,
            "timeout": args.timeout,
            "concurrency": args.concurrency,
            "dataset": args.dataset,
            "limit": args.limit,
        },
    )

    # Print report
    metrics = compute_metrics(results)
    print(format_report(metrics))

    harness.close()


def cmd_compare(args: argparse.Namespace) -> None:
    """Execute the 'compare' command."""
    from eval.harness import RunResult, InstanceStatus

    db = ResultsDB(args.db)
    db.connect()

    results_a_raw = db.get_run_results(args.run_a)
    results_b_raw = db.get_run_results(args.run_b)

    if not results_a_raw:
        print(f"No results found for run: {args.run_a}")
        return
    if not results_b_raw:
        print(f"No results found for run: {args.run_b}")
        return

    def _to_run_result(row: dict[str, Any]) -> RunResult:
        return RunResult(
            instance_id=row["instance_id"],
            status=InstanceStatus(row["status"]),
            tokens_used=row.get("tokens_used", 0),
            cost_usd=row.get("cost_usd", 0.0),
            wall_time_seconds=row.get("wall_time_seconds", 0.0),
            tests_passed=bool(row.get("tests_passed", 0)),
            error=row.get("error", ""),
            model=row.get("model", ""),
        )

    results_a = [_to_run_result(r) for r in results_a_raw]
    results_b = [_to_run_result(r) for r in results_b_raw]

    comp = compare_runs(results_a, results_b, args.run_a, args.run_b)
    print(format_comparison(comp))

    db.close()


def cmd_history(args: argparse.Namespace) -> None:
    """Execute the 'history' command."""
    db = ResultsDB(args.db)
    db.connect()

    runs = db.get_run_history(args.limit)
    if not runs:
        print("No evaluation runs found.")
        return

    print(f"{'Run ID':<25} {'Date':<20} {'Model':<30} {'Pass Rate':>10} {'Tokens':>10} {'Cost':>8}")
    print("-" * 110)
    for run in runs:
        print(
            f"{run['run_id']:<25} "
            f"{run['timestamp']:<20} "
            f"{run['model']:<30} "
            f"{run['pass_rate']:>9.1%} "
            f"{run['total_tokens']:>10,} "
            f"${run['total_cost']:>7.2f}"
        )

    db.close()


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.command == "run":
        asyncio.run(cmd_run(args))
    elif args.command == "compare":
        cmd_compare(args)
    elif args.command == "history":
        cmd_history(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
