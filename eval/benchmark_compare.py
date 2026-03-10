"""CLI for comparing any two benchmark runs from the database or JSON files.

Usage:
    python -m eval.benchmark_compare --run-a run-001 --run-b run-002
    python -m eval.benchmark_compare --file-a baseline.json --file-b current.json
    python -m eval.benchmark_compare --db benchmarks.db --latest-vs run-001
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from eval.benchmark_db import BenchmarkDB
from eval.quality_scorers import compute_repo_quality


def load_from_json(path: str) -> dict[str, dict[str, float]]:
    """Load benchmark data from a JSON file."""
    with open(path) as f:
        data = json.load(f)
    return _normalize_benchmark_json(data)


def _normalize_benchmark_json(data: Any) -> dict[str, dict[str, float]]:
    """Normalize benchmark JSON from either legacy or current formats."""
    if not isinstance(data, dict):
        return {}

    repos = data.get("repos") if isinstance(data.get("repos"), dict) else data
    if not isinstance(repos, dict):
        return {}

    normalized: dict[str, dict[str, float]] = {}
    for repo_name, repo_data in repos.items():
        if not isinstance(repo_name, str) or not isinstance(repo_data, dict):
            continue

        # Current format: metrics already flattened under each repo.
        if "bootstrap_time_ms" in repo_data:
            normalized[repo_name] = {
                "bootstrap_time_ms": float(repo_data.get("bootstrap_time_ms", 0) or 0),
                "symbol_count": float(repo_data.get("symbol_count", 0) or 0),
                "quality_score": float(repo_data.get("quality_score", 0) or 0),
                "total_time_ms": float(repo_data.get("total_time_ms", 0) or 0),
            }
            continue

        # Legacy format: task-level benchmark payload.
        if "error" in repo_data:
            continue

        total_ms = sum(
            task.get("time_ms", 0)
            for task in repo_data.values()
            if isinstance(task, dict) and "time_ms" in task
        )
        normalized[repo_name] = {
            "bootstrap_time_ms": float(repo_data.get("bootstrap", {}).get("time_ms", 0) or 0),
            "symbol_count": float(repo_data.get("symbol_discovery", {}).get("output_len", 0) or 0),
            "quality_score": float(compute_repo_quality(repo_data)),
            "total_time_ms": float(total_ms),
        }

    return normalized


def load_from_db(db_path: str, run_id: str) -> dict[str, dict[str, float]]:
    """Load benchmark data from the SQLite database."""
    db = BenchmarkDB(db_path)
    db.connect()
    run = db.get_run(run_id)
    db.close()
    if not run:
        return {}
    return {
        e.repo: {
            "bootstrap_time_ms": e.bootstrap_time_ms,
            "symbol_count": e.symbol_count,
            "quality_score": e.quality_score,
            "total_time_ms": e.total_time_ms,
        }
        for e in run.entries
    }


def compare_repos(
    data_a: dict[str, dict[str, float]],
    data_b: dict[str, dict[str, float]],
    label_a: str = "A",
    label_b: str = "B",
) -> str:
    """Compare two sets of benchmark results."""
    all_repos = sorted(set(data_a.keys()) | set(data_b.keys()))
    metrics = ["bootstrap_time_ms", "symbol_count", "quality_score", "total_time_ms"]

    lines = [
        "=" * 80,
        f"BENCHMARK COMPARISON: {label_a} vs {label_b}",
        "=" * 80,
        "",
    ]

    for repo in all_repos:
        a = data_a.get(repo, {})
        b = data_b.get(repo, {})
        if not a and not b:
            continue

        lines.append(f"### {repo}")
        lines.append(f"{'Metric':<25} {label_a:>12} {label_b:>12} {'Delta':>10} {'Pct':>8}")
        lines.append("-" * 70)

        for metric in metrics:
            val_a = a.get(metric, 0)
            val_b = b.get(metric, 0)
            delta = val_b - val_a
            pct = (delta / val_a * 100) if val_a != 0 else 0

            # Format based on metric type
            if "time" in metric:
                lines.append(f"{metric:<25} {val_a:>11.0f} {val_b:>11.0f} {delta:>+10.0f} {pct:>+7.1f}%")
            elif "score" in metric:
                lines.append(f"{metric:<25} {val_a:>11.1f} {val_b:>11.1f} {delta:>+10.1f} {pct:>+7.1f}%")
            else:
                lines.append(f"{metric:<25} {val_a:>11.0f} {val_b:>11.0f} {delta:>+10.0f} {pct:>+7.1f}%")

        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Compare benchmark runs")
    parser.add_argument("--file-a", help="First JSON results file")
    parser.add_argument("--file-b", help="Second JSON results file")
    parser.add_argument("--db", help="SQLite database path")
    parser.add_argument("--run-a", help="First run ID (from DB)")
    parser.add_argument("--run-b", help="Second run ID (from DB)")
    parser.add_argument("--latest-vs", help="Compare latest run against this run ID")

    args = parser.parse_args()

    if args.file_a and args.file_b:
        data_a = load_from_json(args.file_a)
        data_b = load_from_json(args.file_b)
        label_a = os.path.basename(args.file_a)
        label_b = os.path.basename(args.file_b)
    elif args.db and args.run_a and args.run_b:
        data_a = load_from_db(args.db, args.run_a)
        data_b = load_from_db(args.db, args.run_b)
        label_a = args.run_a
        label_b = args.run_b
    elif args.db and args.latest_vs:
        db = BenchmarkDB(args.db)
        db.connect()
        latest = db.get_latest_run()
        db.close()
        if not latest:
            print("No runs found in database")
            sys.exit(1)
        data_a = load_from_db(args.db, args.latest_vs)
        data_b = load_from_db(args.db, latest.run_id)
        label_a = args.latest_vs
        label_b = f"{latest.run_id} (latest)"
    else:
        parser.error("Specify --file-a/--file-b OR --db with --run-a/--run-b OR --db with --latest-vs")

    if not data_a:
        print(f"No data for {label_a if args.file_a else args.run_a}")
        sys.exit(1)
    if not data_b:
        print(f"No data for {label_b if args.file_b else args.run_b}")
        sys.exit(1)

    print(compare_repos(data_a, data_b, label_a, label_b))


if __name__ == "__main__":
    main()
