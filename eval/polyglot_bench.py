"""Aider Polyglot Benchmark comparison.

Evaluates attoswarm against the Aider Polyglot benchmark:
225 Exercism problems across 6 languages. Starts with a Python/Go/JS subset.

Usage:
    python -m eval.polyglot_bench run --languages python go javascript --limit 30
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

logger = logging.getLogger(__name__)

# Published Aider Polyglot leaderboard (top entries)
AIDER_LEADERBOARD = [
    {"model": "o1-preview", "pass_rate": 0.929, "edit_format": "diff"},
    {"model": "claude-3.5-sonnet", "pass_rate": 0.893, "edit_format": "diff"},
    {"model": "gpt-4o", "pass_rate": 0.867, "edit_format": "diff"},
    {"model": "deepseek-v2.5", "pass_rate": 0.818, "edit_format": "diff"},
    {"model": "claude-3-opus", "pass_rate": 0.724, "edit_format": "diff"},
]


@dataclass(slots=True)
class ExercismProblem:
    """A single Exercism problem for benchmarking."""
    slug: str
    language: str
    track_dir: str
    test_cmd: list[str]
    solution_files: list[str]
    description: str = ""


@dataclass(slots=True)
class ProblemResult:
    """Result of attempting a single Exercism problem."""
    slug: str
    language: str
    passed: bool = False
    test_output: str = ""
    wall_time_seconds: float = 0.0
    tokens_used: int = 0
    cost_usd: float = 0.0
    error: str = ""


# Language-specific test commands
LANGUAGE_TEST_CMDS = {
    "python": ["python", "-m", "pytest", "-x", "-q"],
    "go": ["go", "test", "-v", "./..."],
    "javascript": ["npm", "test"],
    "rust": ["cargo", "test"],
    "java": ["gradle", "test"],
    "ruby": ["ruby", "-Ilib", "-Itest"],
}


def discover_exercism_problems(
    exercism_dir: str,
    languages: list[str],
    limit: int | None = None,
) -> list[ExercismProblem]:
    """Discover Exercism problems from local exercism workspace.

    Expected structure:
        exercism_dir/
            python/
                hello-world/
                    hello_world.py
                    hello_world_test.py
                    .meta/
                        config.json
    """
    problems: list[ExercismProblem] = []
    exercism_path = Path(exercism_dir)

    for lang in languages:
        lang_dir = exercism_path / lang
        if not lang_dir.is_dir():
            continue

        test_cmd = LANGUAGE_TEST_CMDS.get(lang, ["echo", "no test command"])

        for problem_dir in sorted(lang_dir.iterdir()):
            if not problem_dir.is_dir():
                continue
            if problem_dir.name.startswith("."):
                continue

            # Find solution files (non-test files)
            solution_files = []
            for f in problem_dir.iterdir():
                if f.is_file() and not f.name.startswith("."):
                    if "test" not in f.name.lower() and f.suffix in (".py", ".go", ".js", ".rs", ".java", ".rb"):
                        solution_files.append(f.name)

            # Load description
            desc = ""
            desc_path = problem_dir / ".docs" / "instructions.md"
            if desc_path.exists():
                desc = desc_path.read_text()[:3000]

            problems.append(ExercismProblem(
                slug=problem_dir.name,
                language=lang,
                track_dir=str(problem_dir),
                test_cmd=test_cmd,
                solution_files=solution_files,
                description=desc,
            ))

            if limit and len(problems) >= limit:
                return problems

    return problems


async def solve_problem(
    problem: ExercismProblem,
    model: str = "claude-sonnet-4-20250514",
    timeout: float = 300.0,
) -> ProblemResult:
    """Attempt to solve an Exercism problem using attocode."""
    result = ProblemResult(slug=problem.slug, language=problem.language)

    prompt = (
        f"Solve this Exercism {problem.language} exercise: {problem.slug}\n\n"
        f"Instructions:\n{problem.description}\n\n"
        f"Files to implement: {', '.join(problem.solution_files)}\n"
        f"The test file already exists. Implement the solution to make all tests pass.\n"
        f"Do not modify test files.\n"
    )

    cmd = ["attocode", "--non-interactive", "--model", model, prompt]
    # Strip known secret env vars to prevent leakage into untrusted repos
    _SECRET_PREFIXES = ("CLAUDECODE", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AWS_", "GITHUB_TOKEN")
    env = {k: v for k, v in os.environ.items() if not any(k.startswith(p) for p in _SECRET_PREFIXES)}

    t0 = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=problem.track_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        await asyncio.wait_for(proc.communicate(), timeout=timeout)
        result.wall_time_seconds = time.monotonic() - t0

        # Run tests
        test_proc = subprocess.run(
            problem.test_cmd,
            cwd=problem.track_dir,
            capture_output=True,
            text=True,
            timeout=60,
        )
        result.passed = test_proc.returncode == 0
        result.test_output = (test_proc.stdout + test_proc.stderr)[:2000]

    except asyncio.TimeoutError:
        result.wall_time_seconds = time.monotonic() - t0
        result.error = f"Timed out after {timeout}s"
    except Exception as e:
        result.wall_time_seconds = time.monotonic() - t0
        result.error = str(e)

    return result


async def run_benchmark(
    problems: list[ExercismProblem],
    model: str = "claude-sonnet-4-20250514",
    concurrency: int = 1,
    timeout: float = 300.0,
) -> list[ProblemResult]:
    """Run benchmark on all problems."""
    semaphore = asyncio.Semaphore(concurrency)

    async def run_one(problem: ExercismProblem) -> ProblemResult:
        async with semaphore:
            logger.info("Solving: %s/%s", problem.language, problem.slug)
            result = await solve_problem(problem, model, timeout)
            logger.info(
                "%s/%s: %s (%.1fs)",
                problem.language, problem.slug,
                "PASS" if result.passed else "FAIL",
                result.wall_time_seconds,
            )
            return result

    tasks = [run_one(p) for p in problems]
    return list(await asyncio.gather(*tasks))


def format_results(results: list[ProblemResult], model_label: str = "Attoswarm") -> str:
    """Format results as a leaderboard comparison."""
    by_lang: dict[str, list[ProblemResult]] = {}
    for r in results:
        by_lang.setdefault(r.language, []).append(r)

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    pass_rate = passed / total if total > 0 else 0

    lines = [
        "# Aider Polyglot Benchmark Results",
        "",
        "## Per-Language",
        "",
        "| Language | Total | Passed | Pass Rate |",
        "|----------|-------|--------|-----------|",
    ]

    for lang in sorted(by_lang.keys()):
        lang_results = by_lang[lang]
        lang_passed = sum(1 for r in lang_results if r.passed)
        lang_total = len(lang_results)
        lang_rate = lang_passed / lang_total if lang_total > 0 else 0
        lines.append(f"| {lang} | {lang_total} | {lang_passed} | {lang_rate:.1%} |")

    lines.extend([
        f"| **Total** | **{total}** | **{passed}** | **{pass_rate:.1%}** |",
        "",
        "## Leaderboard Comparison",
        "",
        "| Rank | Agent | Pass Rate |",
        "|------|-------|-----------|",
    ])

    all_entries = [(model_label, pass_rate)] + [
        (f"{e['model']} (Aider)", e["pass_rate"]) for e in AIDER_LEADERBOARD
    ]
    all_entries.sort(key=lambda x: -x[1])

    for i, (name, rate) in enumerate(all_entries, 1):
        display_name = f"**{name}**" if name == model_label else name
        lines.append(f"| {i} | {display_name} | {rate:.1%} |")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Aider Polyglot Benchmark")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--exercism-dir", default=os.path.expanduser("~/exercism"))
    run_parser.add_argument("--languages", nargs="+", default=["python", "go", "javascript"])
    run_parser.add_argument("--limit", type=int)
    run_parser.add_argument("--model", default="claude-sonnet-4-20250514")
    run_parser.add_argument("--concurrency", type=int, default=1)
    run_parser.add_argument("--timeout", type=float, default=300.0)
    run_parser.add_argument("--output", default="polyglot_results.json")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    if args.command == "run":
        problems = discover_exercism_problems(args.exercism_dir, args.languages, args.limit)
        if not problems:
            print(f"No problems found in {args.exercism_dir}")
            sys.exit(1)

        print(f"Found {len(problems)} problems")
        results = asyncio.run(run_benchmark(problems, args.model, args.concurrency, args.timeout))

        results_data = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "model": args.model,
            "results": [
                {"slug": r.slug, "language": r.language, "passed": r.passed,
                 "wall_time_seconds": r.wall_time_seconds, "error": r.error}
                for r in results
            ],
        }
        with open(args.output, "w") as f:
            json.dump(results_data, f, indent=2)
        print(f"\nResults saved to: {args.output}")
        print(format_results(results))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
