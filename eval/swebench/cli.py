"""CLI for SWE-bench evaluation: run, grade, compare, efficiency, leaderboard.

Usage:
    python -m eval.swebench run --limit 10 --model claude-sonnet-4-20250514
    python -m eval.swebench grade --run-id eval-1234
    python -m eval.swebench compare eval-1234 eval-5678
    python -m eval.swebench efficiency --run-id eval-1234
    python -m eval.swebench leaderboard --run-id eval-1234
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from eval.harness import BenchInstance, EvalHarness, ResultsDB, RunResult, InstanceStatus
from eval.metrics import compute_metrics, format_report
from eval.swebench.adapter import AttoswarmSWEBenchFactory
from eval.swebench.config import SWEBenchEvalConfig
from eval.swebench.dataset import load_from_jsonl, load_from_huggingface
from eval.swebench.efficiency import extract_efficiency, extract_efficiency_batch, format_efficiency_report
from eval.swebench.grader import grade_local, grade_official
from eval.swebench.report import (
    generate_leaderboard,
    generate_comparison_report,
    generate_per_repo_breakdown,
)

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eval.swebench",
        description="SWE-bench Lite Evaluation for Attoswarm",
    )
    subparsers = parser.add_subparsers(dest="command")

    # --- run ---
    run_parser = subparsers.add_parser("run", help="Run SWE-bench evaluation")
    run_parser.add_argument("--dataset", help="Path to JSONL dataset file")
    run_parser.add_argument("--huggingface", action="store_true", help="Load from HuggingFace")
    run_parser.add_argument("--limit", type=int, help="Max instances to run")
    run_parser.add_argument("--instance-ids", nargs="+", help="Specific instance IDs")
    run_parser.add_argument("--model", default="claude-sonnet-4-20250514")
    run_parser.add_argument("--provider", default="anthropic")
    run_parser.add_argument("--max-tokens", type=int, default=2_000_000)
    run_parser.add_argument("--max-cost", type=float, default=5.0)
    run_parser.add_argument("--timeout", type=int, default=1200)
    run_parser.add_argument("--concurrency", type=int, default=1)
    run_parser.add_argument("--run-id", default="")
    run_parser.add_argument("--db", default="eval_swebench.db")
    run_parser.add_argument("--debug", action="store_true")

    # --- grade ---
    grade_parser = subparsers.add_parser("grade", help="Grade completed run")
    grade_parser.add_argument("--run-id", required=True)
    grade_parser.add_argument("--db", default="eval_swebench.db")
    grade_parser.add_argument("--official", action="store_true", help="Use official SWE-bench harness")

    # --- compare ---
    cmp_parser = subparsers.add_parser("compare", help="Compare two runs")
    cmp_parser.add_argument("run_a", help="First run ID")
    cmp_parser.add_argument("run_b", help="Second run ID")
    cmp_parser.add_argument("--db", default="eval_swebench.db")

    # --- efficiency ---
    eff_parser = subparsers.add_parser("efficiency", help="Analyze swarm efficiency")
    eff_parser.add_argument("--run-id", required=True)
    eff_parser.add_argument("--db", default="eval_swebench.db")
    eff_parser.add_argument("--run-dir", help="Override run directory path")

    # --- leaderboard ---
    lb_parser = subparsers.add_parser("leaderboard", help="Show leaderboard")
    lb_parser.add_argument("--run-id", required=True)
    lb_parser.add_argument("--db", default="eval_swebench.db")
    lb_parser.add_argument("--label", default="Attoswarm")

    return parser


async def cmd_run(args: argparse.Namespace) -> None:
    """Run SWE-bench evaluation."""
    # Load instances
    if args.dataset:
        instances = load_from_jsonl(
            args.dataset,
            limit=args.limit,
            instance_ids=args.instance_ids,
        )
    elif args.huggingface:
        instances = load_from_huggingface(
            limit=args.limit,
            instance_ids=args.instance_ids,
        )
    else:
        print("Specify --dataset or --huggingface")
        sys.exit(1)

    print(f"Loaded {len(instances)} SWE-bench instances")

    # Build config
    config = SWEBenchEvalConfig(
        model=args.model,
        provider=args.provider,
        max_tokens=args.max_tokens,
        max_cost_usd=args.max_cost,
        max_runtime_seconds=args.timeout,
        debug=args.debug,
    )

    factory = AttoswarmSWEBenchFactory(config=config)

    harness = EvalHarness(
        agent_factory=factory,
        results_db=args.db,
        model=args.model,
        timeout=args.timeout,
    )

    run_id = args.run_id or f"swebench-{int(time.time())}"
    print(f"Starting run: {run_id}")

    try:
        results = await harness.run_suite(
            instances,
            run_id=run_id,
            concurrency=args.concurrency,
            config=vars(config),
        )

        # Report
        metrics = compute_metrics(results)
        print(format_report(metrics))

        # Per-repo breakdown
        print(generate_per_repo_breakdown(results))
    finally:
        harness.close()

    print(f"\nRun ID: {run_id}")


def cmd_grade(args: argparse.Namespace) -> None:
    """Grade a completed SWE-bench run."""
    db = ResultsDB(args.db)
    db.connect()
    results_raw = db.get_run_results(args.run_id)
    db.close()

    if not results_raw:
        print(f"No results for run: {args.run_id}")
        return

    # Load instances from dataset to get test patches
    # We need the original instance data for grading
    print(f"Grading {len(results_raw)} instances from run: {args.run_id}")

    passed = 0
    failed = 0
    errors = 0

    for row in results_raw:
        instance_id = row["instance_id"]
        patch = row.get("patch_generated", "")
        metadata = row.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        if not metadata:
            print(f"  SKIP {instance_id}: missing stored instance metadata (rerun with updated harness)")
            errors += 1
            continue

        instance_dir = str(metadata.get("working_dir", ""))
        instance = BenchInstance(
            instance_id=instance_id,
            repo=str(metadata.get("repo", "")),
            base_commit=str(metadata.get("base_commit", "")),
            problem_statement=str(metadata.get("problem_statement", "")),
            test_patch=str(metadata.get("test_patch", "")),
            patch_gold=str(metadata.get("patch_gold", "")),
            hints=str(metadata.get("hints", "")),
            metadata=metadata.get("instance_metadata", {}) if isinstance(metadata.get("instance_metadata"), dict) else {},
        )

        if args.official:
            result = grade_official(instance, patch)
        else:
            if not instance_dir or not os.path.isdir(instance_dir):
                print(f"  SKIP {instance_id}: working dir not found")
                errors += 1
                continue
            result = grade_local(instance, instance_dir, patch)

        status = "PASS" if result.passed else "FAIL"
        print(f"  [{status}] {instance_id}: {result.fail_to_pass_passed}/{result.fail_to_pass_total} tests")

        if result.passed:
            passed += 1
        else:
            failed += 1

    total = passed + failed + errors
    print(f"\nGrade Summary: {passed}/{total} passed ({passed/total:.0%})" if total > 0 else "\nNo instances graded")


def cmd_compare(args: argparse.Namespace) -> None:
    """Compare two SWE-bench runs."""
    db = ResultsDB(args.db)
    db.connect()

    results_a_raw = db.get_run_results(args.run_a)
    results_b_raw = db.get_run_results(args.run_b)
    db.close()

    if not results_a_raw:
        print(f"No results for run: {args.run_a}")
        return
    if not results_b_raw:
        print(f"No results for run: {args.run_b}")
        return

    def _to_result(row: dict) -> RunResult:
        return RunResult(
            instance_id=row["instance_id"],
            status=InstanceStatus(row["status"]),
            tokens_used=row.get("tokens_used", 0),
            cost_usd=row.get("cost_usd", 0.0),
            wall_time_seconds=row.get("wall_time_seconds", 0.0),
            tests_passed=bool(row.get("tests_passed", 0)),
            model=row.get("model", ""),
        )

    results_a = [_to_result(r) for r in results_a_raw]
    results_b = [_to_result(r) for r in results_b_raw]

    print(generate_comparison_report(results_a, results_b, args.run_a, args.run_b))


def cmd_efficiency(args: argparse.Namespace) -> None:
    """Analyze swarm efficiency for a run."""
    run_dirs: list[str] = []
    if args.run_dir:
        if os.path.isdir(args.run_dir):
            run_dirs = [args.run_dir]
    else:
        # Try to resolve run dirs from persisted eval metadata.
        db = ResultsDB(args.db)
        db.connect()
        rows = db.get_run_results(args.run_id)
        db.close()
        for row in rows:
            meta = row.get("metadata", {})
            if not isinstance(meta, dict):
                continue
            working_dir = str(meta.get("working_dir", ""))
            if not working_dir:
                continue
            candidate = os.path.join(working_dir, ".swarm-run")
            if os.path.isdir(candidate):
                run_dirs.append(candidate)

        # Fallback to historical defaults.
        if not run_dirs:
            candidates = [
                os.path.join(".agent", args.run_id),
                os.path.join("/tmp", f"attocode-eval-{args.run_id}"),
            ]
            for c in candidates:
                if os.path.isdir(c):
                    run_dirs.append(c)

    # Deduplicate while preserving order.
    deduped: list[str] = []
    for d in run_dirs:
        if d not in deduped:
            deduped.append(d)

    if not deduped:
        print(f"Run directory not found for: {args.run_id}")
        print("Use --run-dir to specify the path")
        sys.exit(1)

    if len(deduped) == 1:
        metrics = extract_efficiency(deduped[0])
        print(format_efficiency_report([metrics]))
        return

    print(format_efficiency_report(extract_efficiency_batch(deduped)))


def cmd_leaderboard(args: argparse.Namespace) -> None:
    """Show leaderboard with our results."""
    db = ResultsDB(args.db)
    db.connect()
    results_raw = db.get_run_results(args.run_id)
    db.close()

    if not results_raw:
        print(f"No results for run: {args.run_id}")
        return

    results = [
        RunResult(
            instance_id=r["instance_id"],
            status=InstanceStatus(r["status"]),
            tokens_used=r.get("tokens_used", 0),
            cost_usd=r.get("cost_usd", 0.0),
            wall_time_seconds=r.get("wall_time_seconds", 0.0),
            tests_passed=bool(r.get("tests_passed", 0)),
            model=r.get("model", ""),
        )
        for r in results_raw
    ]

    print(generate_leaderboard(results, run_label=args.label))


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "debug", False) else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.command == "run":
        asyncio.run(cmd_run(args))
    elif args.command == "grade":
        cmd_grade(args)
    elif args.command == "compare":
        cmd_compare(args)
    elif args.command == "efficiency":
        cmd_efficiency(args)
    elif args.command == "leaderboard":
        cmd_leaderboard(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
