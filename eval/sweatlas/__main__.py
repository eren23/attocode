"""SWE-Atlas Codebase QnA evaluation adapter.

Loads the SWE-Atlas QnA dataset (124 deep codebase understanding tasks)
and evaluates CodeIntelService-augmented answers vs baseline.

Dataset: HuggingFace ScaleAI/SWE-Atlas-QnA
- 124 tasks from 11 production repos (Go, Python, C, TypeScript)
- Categories: architecture (35%), root-cause (30%), onboarding (23%), security (9%)
- Rubric-based scoring (avg 12.3 criteria per task, LLM judge binary met/unmet)
- Metric: Task Resolve Rate (% tasks where ALL rubric items pass)

Usage:
    python -m eval.sweatlas list                              # list tasks & categories
    python -m eval.sweatlas run --limit 10                    # run first 10 tasks
    python -m eval.sweatlas run --category "Architecture & system design"
    python -m eval.sweatlas run --baseline                    # without code-intel
    python -m eval.sweatlas run --compare                     # both modes, show delta
    python -m eval.sweatlas report                            # report from latest results
    python -m eval.sweatlas report --compare ci.jsonl bl.jsonl  # compare two runs
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

DATASET_ID = "ScaleAI/SWE-Atlas-QnA"
CACHE_DIR = Path.home() / ".cache" / "attocode" / "sweatlas"
DEFAULT_OUTPUT = Path("eval/sweatlas/results.jsonl")


# ---------------------------------------------------------------------------
# Dataset loading (unchanged — works with HuggingFace or local cache)
# ---------------------------------------------------------------------------

def load_dataset(limit: int | None = None, category: str = "") -> list[dict]:
    """Load SWE-Atlas QnA dataset.

    Tries local cache first, falls back to HuggingFace.
    """
    cache_file = CACHE_DIR / "dataset.jsonl"

    # Try loading from cache first
    if cache_file.exists():
        tasks = []
        for line in cache_file.read_text().splitlines():
            if line.strip():
                task = json.loads(line)
                if category and task.get("category", "").lower() != category.lower():
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
        print("Install datasets: pip install datasets")
        print(f"Or place dataset at: {cache_file}")
        return []


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_list(args: argparse.Namespace) -> None:
    """List available tasks with category/repo/language breakdown."""
    tasks = load_dataset()
    if not tasks:
        print("No tasks loaded. See usage instructions above.")
        return

    categories: dict[str, int] = {}
    repos: dict[str, int] = {}
    languages: dict[str, int] = {}
    for t in tasks:
        cat = t.get("category", "unknown")
        repo_url = t.get("repository_url", "unknown")
        repo = repo_url.split("/")[-1] if "/" in repo_url else repo_url
        lang = t.get("language", "unknown")
        categories[cat] = categories.get(cat, 0) + 1
        repos[repo] = repos.get(repo, 0) + 1
        languages[lang] = languages.get(lang, 0) + 1

    print(f"SWE-Atlas QnA: {len(tasks)} tasks\n")
    print("Categories:")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count} ({100*count/len(tasks):.0f}%)")
    print("\nRepositories:")
    for repo, count in sorted(repos.items(), key=lambda x: -x[1]):
        print(f"  {repo}: {count}")
    print("\nLanguages:")
    for lang, count in sorted(languages.items(), key=lambda x: -x[1]):
        print(f"  {lang}: {count}")


def cmd_run(args: argparse.Namespace) -> None:
    """Run evaluation on tasks."""
    tasks = load_dataset(limit=args.limit, category=args.category)
    if not tasks:
        return

    compare = getattr(args, "compare", False)
    modes = ["with_code_intel", "baseline"] if compare else ["baseline" if args.baseline else "with_code_intel"]

    print(f"Loaded {len(tasks)} tasks")
    print(f"Mode(s): {', '.join(modes)}")
    print()

    from eval.sweatlas.repo_manager import ensure_repo

    # Step 1: Clone/cache repos
    repo_dirs: dict[str, str] = {}
    unique_repos = {
        (t.get("repository_url", ""), t.get("repository_base_commit", ""))
        for t in tasks
    }
    print(f"Ensuring {len(unique_repos)} repos are cloned...")
    for repo_url, commit in unique_repos:
        if not repo_url:
            continue
        try:
            repo_dir = ensure_repo(repo_url, commit)
            repo_dirs[repo_url] = str(repo_dir)
            repo_name = repo_url.split("/")[-1] if "/" in repo_url else repo_url
            repo_dirs[repo_name] = str(repo_dir)
            print(f"  {repo_url} -> {repo_dir}")
        except Exception as e:
            print(f"  FAILED: {repo_url}: {e}")
    print()

    from eval.sweatlas.runner import TaskResult, run_tasks

    all_results: dict[str, list[TaskResult]] = {}

    for mode in modes:
        baseline = mode == "baseline"
        print(f"--- Running mode: {mode} ---\n")
        start = time.monotonic()

        results = asyncio.run(
            run_tasks(
                tasks,
                repo_dirs,
                baseline=baseline,
                answer_model=args.answer_model,
                judge_model=args.judge_model,
            )
        )

        elapsed = time.monotonic() - start
        all_results[mode] = results

        # Summary
        valid = [r for r in results if not r.error]
        avg_score = sum(r.score for r in valid) / len(valid) if valid else 0
        resolved = sum(1 for r in valid if r.resolved)
        print(f"\n{mode} summary ({len(valid)}/{len(results)} successful):")
        print(f"  Avg rubric score: {avg_score:.3f}")
        print(f"  Task resolve rate: {resolved}/{len(valid)} ({100*resolved/len(valid):.1f}%)" if valid else "  No valid results")
        print(f"  Total time: {elapsed:.1f}s\n")

    # Write results
    for mode, results in all_results.items():
        suffix = f"_{mode}" if len(modes) > 1 else ""
        output = Path(args.output) if args.output else DEFAULT_OUTPUT.with_name(f"results{suffix}{DEFAULT_OUTPUT.suffix}")
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w") as f:
            for r in results:
                f.write(json.dumps(r.to_dict()) + "\n")
        print(f"Results written to {output}")

    # Print comparison if both modes ran
    if compare and "with_code_intel" in all_results and "baseline" in all_results:
        _print_comparison(all_results["with_code_intel"], all_results["baseline"])


def cmd_report(args: argparse.Namespace) -> None:
    """Generate markdown report from results."""
    from eval.sweatlas.scorer import TaskScore, format_report

    compare_files = getattr(args, "compare_files", None)

    if compare_files and len(compare_files) == 2:
        scores_a = _load_scores(compare_files[0])
        scores_b = _load_scores(compare_files[1])
        report = format_report(scores_a, mode="with_code_intel", compare_scores=scores_b)
    else:
        results_path = Path(args.input) if args.input else DEFAULT_OUTPUT
        if not results_path.exists():
            print(f"No results found at {results_path}. Run evaluation first.")
            return
        scores = _load_scores(str(results_path))
        report = format_report(scores)

    output = Path(args.output) if args.output else Path("eval/sweatlas/report.md")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report)
    print(report)
    print(f"\nReport written to {output}")


def _load_scores(path: str) -> list:
    """Load TaskScore-compatible objects from results JSONL."""
    from eval.sweatlas.scorer import TaskScore

    scores = []
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        scores.append(
            TaskScore(
                task_id=data.get("task_id", ""),
                category=data.get("category", ""),
                repo=data.get("repo", ""),
                rubric_total=data.get("rubric_total", 0),
                rubric_met=data.get("rubric_met", 0),
            )
        )
    return scores


def _print_comparison(ci_results: list, bl_results: list) -> None:
    """Print a side-by-side comparison of two runs."""
    print("\n=== Comparison: Code-Intel vs Baseline ===\n")

    # Build lookup by task_id
    bl_by_id = {r.task_id: r for r in bl_results}

    categories: dict[str, dict[str, list[float]]] = {}
    for r in ci_results:
        cat = r.category
        if cat not in categories:
            categories[cat] = {"ci": [], "bl": []}
        categories[cat]["ci"].append(r.score)
        bl_r = bl_by_id.get(r.task_id)
        if bl_r:
            categories[cat]["bl"].append(bl_r.score)

    print(f"{'Category':<35} {'CI Score':>10} {'BL Score':>10} {'Delta':>8}")
    print("-" * 65)
    total_ci, total_bl, n_ci, n_bl = 0.0, 0.0, 0, 0
    for cat, scores in sorted(categories.items()):
        ci_avg = sum(scores["ci"]) / len(scores["ci"]) if scores["ci"] else 0
        bl_avg = sum(scores["bl"]) / len(scores["bl"]) if scores["bl"] else 0
        delta = ci_avg - bl_avg
        print(f"{cat:<35} {ci_avg:>10.3f} {bl_avg:>10.3f} {delta:>+8.3f}")
        total_ci += sum(scores["ci"])
        total_bl += sum(scores["bl"])
        n_ci += len(scores["ci"])
        n_bl += len(scores["bl"])

    if n_ci > 0 and n_bl > 0:
        ci_overall = total_ci / n_ci
        bl_overall = total_bl / n_bl
        print("-" * 65)
        print(f"{'Overall':<35} {ci_overall:>10.3f} {bl_overall:>10.3f} {ci_overall - bl_overall:>+8.3f}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="SWE-Atlas QnA evaluation — code understanding benchmark"
    )
    sub = parser.add_subparsers(dest="command")

    # list
    sub.add_parser("list", help="List available tasks, categories, and repos")

    # run
    run_p = sub.add_parser("run", help="Run evaluation")
    run_p.add_argument("--limit", type=int, default=None, help="Max tasks to run")
    run_p.add_argument("--category", default="", help="Filter by category name")
    run_p.add_argument("--baseline", action="store_true", help="Run without code-intel (LLM only)")
    run_p.add_argument("--compare", action="store_true", help="Run both modes and show delta")
    run_p.add_argument("--output", default="", help="Output JSONL path")
    run_p.add_argument(
        "--answer-model", default="",
        help="LLM model for answer generation (default: claude-sonnet-4-6)",
    )
    run_p.add_argument(
        "--judge-model", default="",
        help="LLM model for rubric scoring (default: claude-haiku-4-5-20251001)",
    )

    # report
    report_p = sub.add_parser("report", help="Generate markdown report from results")
    report_p.add_argument("--input", default="", help="Input results JSONL path")
    report_p.add_argument("--output", default="", help="Output markdown path")
    report_p.add_argument("--compare", dest="compare_files", nargs=2, metavar="FILE",
                          help="Compare two result files: CI_RESULTS BL_RESULTS")

    args = parser.parse_args()
    if args.command == "list":
        cmd_list(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "report":
        cmd_report(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
