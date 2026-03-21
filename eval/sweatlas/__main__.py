"""SWE-Atlas Codebase QnA evaluation adapter.

Loads the SWE-Atlas QnA dataset (124 deep codebase understanding tasks)
and evaluates CodeIntelService-augmented answers vs baseline.

Dataset: HuggingFace ScaleAI/SWE-Atlas-QnA
- 124 tasks from 11 production repos
- Categories: architecture (35%), root-cause (30%), onboarding (23%), security (9%)
- Rubric-based scoring (avg 12.3 criteria per task)

Usage:
    python -m eval.sweatlas list                    # list available tasks
    python -m eval.sweatlas run --limit 10          # run first 10 tasks
    python -m eval.sweatlas run --category architecture  # filter by category
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DATASET_ID = "ScaleAI/SWE-Atlas-QnA"
CACHE_DIR = Path.home() / ".cache" / "attocode" / "sweatlas"


def load_dataset(limit: int | None = None, category: str = "") -> list[dict]:
    """Load SWE-Atlas QnA dataset.

    Tries HuggingFace first, falls back to local cache.
    """
    cache_file = CACHE_DIR / "dataset.jsonl"

    # Try loading from cache first
    if cache_file.exists():
        tasks = []
        for line in cache_file.read_text().splitlines():
            if line.strip():
                task = json.loads(line)
                if category and task.get("category", "") != category:
                    continue
                tasks.append(task)
                if limit and len(tasks) >= limit:
                    break
        if tasks:
            return tasks

    # Try HuggingFace
    try:
        from datasets import load_dataset as hf_load
        ds = hf_load(DATASET_ID, split="test")
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(cache_file, "w") as f:
            for row in ds:
                f.write(json.dumps(dict(row)) + "\n")
        return load_dataset(limit=limit, category=category)
    except Exception as e:
        print(f"Could not load dataset: {e}")
        print(f"Install datasets: pip install datasets")
        print(f"Or place dataset at: {cache_file}")
        return []


def cmd_list(args: argparse.Namespace) -> None:
    """List available tasks."""
    tasks = load_dataset()
    if not tasks:
        print("No tasks loaded. See usage instructions above.")
        return

    categories: dict[str, int] = {}
    repos: dict[str, int] = {}
    for t in tasks:
        cat = t.get("category", "unknown")
        repo = t.get("repo", "unknown")
        categories[cat] = categories.get(cat, 0) + 1
        repos[repo] = repos.get(repo, 0) + 1

    print(f"SWE-Atlas QnA: {len(tasks)} tasks")
    print(f"\nCategories:")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count}")
    print(f"\nRepos:")
    for repo, count in sorted(repos.items(), key=lambda x: -x[1]):
        print(f"  {repo}: {count}")


def cmd_run(args: argparse.Namespace) -> None:
    """Run evaluation on tasks."""
    tasks = load_dataset(limit=args.limit, category=args.category)
    if not tasks:
        return

    print(f"Loaded {len(tasks)} tasks")
    print(f"Mode: {'with_code_intel' if not args.baseline else 'baseline (no code-intel)'}")
    print()

    results = []
    for i, task in enumerate(tasks):
        task_id = task.get("instance_id", task.get("id", f"task_{i}"))
        repo = task.get("repo", "unknown")
        category = task.get("category", "unknown")
        question = task.get("question", task.get("problem_statement", ""))

        print(f"  [{i+1}/{len(tasks)}] {task_id} ({repo}/{category})")
        print(f"    Q: {question[:100]}...")

        # Placeholder: actual execution would use CodeIntelService + LLM
        results.append({
            "task_id": task_id,
            "repo": repo,
            "category": category,
            "question": question[:200],
            "status": "prepared",
        })

    # Write results
    output = Path(args.output) if args.output else Path("eval/sweatlas/results.jsonl")
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    print(f"\n{len(results)} task results written to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="SWE-Atlas QnA evaluation")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="List available tasks")

    run_p = sub.add_parser("run", help="Run evaluation")
    run_p.add_argument("--limit", type=int, default=None, help="Max tasks to run")
    run_p.add_argument("--category", default="", help="Filter by category")
    run_p.add_argument("--baseline", action="store_true", help="Run without code-intel")
    run_p.add_argument("--output", default="", help="Output JSONL path")

    args = parser.parse_args()
    if args.command == "list":
        cmd_list(args)
    elif args.command == "run":
        cmd_run(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
