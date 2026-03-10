#!/usr/bin/env python3
"""Migration script: import existing benchmark JSON results into SQLite DB.

Reads existing benchmark_results.json files and imports them into the
benchmark_db SQLite store for time-series regression analysis.

Usage:
    python eval/import_benchmark_history.py
    python eval/import_benchmark_history.py --db benchmarks.db
    python eval/import_benchmark_history.py --json scripts/benchmark_results.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from eval.benchmark_db import BenchmarkDB, BenchmarkEntry, BenchmarkRun, get_git_info
from eval.quality_scorers import compute_repo_quality


def import_benchmark_json(
    json_path: str,
    db: BenchmarkDB,
    run_id: str = "",
) -> int:
    """Import a benchmark_results.json into the DB.

    Returns number of entries imported.
    """
    with open(json_path) as f:
        data = json.load(f)
    repos = _extract_repo_map(data)

    git = get_git_info(PROJECT_ROOT)
    if not run_id:
        # Generate from file modification time
        mtime = os.path.getmtime(json_path)
        run_id = f"import-{int(mtime)}"

    run = BenchmarkRun(
        run_id=run_id,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(json_path))),
        git_sha=git["sha"],
        branch=git["branch"],
        metadata={"source": json_path},
    )

    for repo_name, repo_data in repos.items():
        if not isinstance(repo_name, str) or not isinstance(repo_data, dict):
            continue
        if "error" in repo_data:
            continue

        if "bootstrap_time_ms" in repo_data:
            bootstrap_ms = float(repo_data.get("bootstrap_time_ms", 0) or 0)
            symbol_count = int(repo_data.get("symbol_count", 0) or 0)
            quality = float(repo_data.get("quality_score", 0) or 0)
            total_ms = float(repo_data.get("total_time_ms", 0) or 0)
        else:
            # Legacy task payload.
            bootstrap_ms = float(repo_data.get("bootstrap", {}).get("time_ms", 0) or 0)
            symbol_count = int(repo_data.get("symbol_discovery", {}).get("output_len", 0) or 0)
            quality = float(compute_repo_quality(repo_data))
            total_ms = float(sum(
                task.get("time_ms", 0)
                for task in repo_data.values()
                if isinstance(task, dict) and "time_ms" in task
            ))

        run.entries.append(BenchmarkEntry(
            repo=repo_name,
            bootstrap_time_ms=bootstrap_ms,
            symbol_count=symbol_count,
            quality_score=quality,
            total_time_ms=total_ms,
        ))

    db.save_run(run)
    return len(run.entries)


def _extract_repo_map(data: object) -> dict[str, object]:
    """Get repository mapping from either legacy or current benchmark JSON."""
    if not isinstance(data, dict):
        return {}
    repos = data.get("repos")
    if isinstance(repos, dict):
        return repos
    return data


def main():
    parser = argparse.ArgumentParser(description="Import benchmark history into SQLite")
    parser.add_argument(
        "--json",
        nargs="*",
        default=[os.path.join(PROJECT_ROOT, "scripts", "benchmark_results.json")],
        help="JSON files to import",
    )
    parser.add_argument("--db", default=os.path.join(PROJECT_ROOT, "eval", "benchmarks.db"))
    parser.add_argument("--run-id", default="", help="Custom run ID (auto-generated if empty)")

    args = parser.parse_args()

    db = BenchmarkDB(args.db)
    db.connect()

    total = 0
    for json_path in args.json:
        if not os.path.exists(json_path):
            print(f"  SKIP: {json_path} not found")
            continue
        n = import_benchmark_json(json_path, db, args.run_id)
        print(f"  Imported {n} entries from {json_path}")
        total += n

    db.close()
    print(f"\nTotal: {total} entries imported to {args.db}")


if __name__ == "__main__":
    main()
