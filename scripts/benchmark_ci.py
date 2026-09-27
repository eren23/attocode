#!/usr/bin/env python3
"""CI-optimized benchmark runner for regression detection.

Runs benchmarks on a subset of repos (3 by default), takes 3-run medians
for timing stability, and compares against a committed baseline to detect
regressions.

Usage:
    python scripts/benchmark_ci.py
    python scripts/benchmark_ci.py --repos attocode gh-cli redis
    python scripts/benchmark_ci.py --update-baseline
    python scripts/benchmark_ci.py --compare-with eval/benchmark_baseline.json
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from attocode.code_intel.service import CodeIntelService

# Add eval to path
sys.path.insert(0, PROJECT_ROOT)
from eval.quality_scorers import TASK_SCORERS, compute_repo_quality
from eval.benchmark_db import BenchmarkDB, BenchmarkRun, BenchmarkEntry, get_git_info

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_REPOS = ["attocode", "gh-cli", "redis"]
NUM_RUNS = 3  # Median of N runs for timing stability

REGRESSION_THRESHOLDS = {
    "bootstrap_time_ms": 0.15,  # 15% — relaxed for timing
    "symbol_count": 0.10,       # 10%
    "quality_score": 0.10,      # 10%
}

BASELINE_PATH = os.path.join(PROJECT_ROOT, "eval", "benchmark_baseline.json")

REPO_CONFIGS = {
    "attocode": {
        "path": PROJECT_ROOT,
        "symbol": "CodebaseContextManager",
        "dep_file": "src/attocode/core/loop.py",
        "nav_file": "src/attocode/core/loop.py",
        "nav_function": "check_iteration_budget",
        "search_query": "token budget management and enforcement",
    },
    "gh-cli": {
        "path": "/Users/eren/Documents/ai/benchmark-repos/gh-cli",
        "symbol": "exitCode",
        "dep_file": "internal/ghcmd/cmd.go",
        "nav_file": "internal/gh/gh.go",
        "nav_function": "Config",
        "search_query": "CLI command factory and command execution",
    },
    "redis": {
        "path": "/Users/eren/Documents/ai/benchmark-repos/redis",
        "symbol": "redisServer",
        "dep_file": "src/server.h",
        "nav_file": "src/server.c",
        "nav_function": "initServer",
        "search_query": "event-driven server architecture and command handling",
    },
    "fastapi": {
        "path": "/Users/eren/Documents/ai/benchmark-repos/fastapi",
        "symbol": "FastAPI",
        "dep_file": "fastapi/applications.py",
        "nav_file": "fastapi/applications.py",
        "nav_function": "FastAPI",
        "search_query": "request validation and dependency injection",
    },
    "pandas": {
        "path": "/Users/eren/Documents/ai/benchmark-repos/pandas",
        "symbol": "DataFrame",
        "dep_file": "pandas/core/frame.py",
        "nav_file": "pandas/core/frame.py",
        "nav_function": "DataFrame",
        "search_query": "missing data handling and NaN propagation",
    },
    "okhttp": {
        "path": "/Users/eren/Documents/ai/benchmark-repos/okhttp",
        "symbol": "OkHttpClient",
        "dep_file": "okhttp/src/commonJvmAndroid/kotlin/okhttp3/OkHttpClient.kt",
        "nav_file": "okhttp/src/commonJvmAndroid/kotlin/okhttp3/OkHttpClient.kt",
        "nav_function": "OkHttpClient",
        "search_query": "connection pooling and HTTP/2 multiplexing",
    },
    "swiftformat": {
        "path": "/Users/eren/Documents/ai/benchmark-repos/SwiftFormat",
        "symbol": "FormatRule",
        "dep_file": "Sources/FormatRule.swift",
        "nav_file": "Sources/FormatRule.swift",
        "nav_function": "FormatRule",
        "search_query": "token parsing and indentation rules",
    },
    "phoenix": {
        "path": "/Users/eren/Documents/ai/benchmark-repos/phoenix",
        "symbol": "Router",
        "dep_file": "lib/phoenix/router.ex",
        "nav_file": "lib/phoenix/router.ex",
        "nav_function": "Router",
        "search_query": "plug pipeline and request lifecycle",
    },
    "spdlog": {
        "path": "/Users/eren/Documents/ai/benchmark-repos/spdlog",
        "symbol": "logger",
        "dep_file": "include/spdlog/spdlog.h",
        "nav_file": "include/spdlog/spdlog.h",
        "nav_function": "logger",
        "search_query": "sink architecture and log pattern formatting",
    },
    "faker": {
        "path": "/Users/eren/Documents/ai/benchmark-repos/faker",
        "symbol": "Faker",
        "dep_file": "lib/faker.rb",
        "nav_file": "lib/faker.rb",
        "nav_function": "Faker",
        "search_query": "locale handling and random data generation",
    },
    "zls": {
        "path": "/Users/eren/Documents/ai/benchmark-repos/zls",
        "symbol": "Server",
        "dep_file": "src/Server.zig",
        "nav_file": "src/Server.zig",
        "nav_function": "Server",
        "search_query": "LSP protocol handling and document synchronization",
    },
    "laravel": {
        "path": "/Users/eren/Documents/ai/benchmark-repos/framework",
        "symbol": "Application",
        "dep_file": "src/Illuminate/Foundation/Application.php",
        "nav_file": "src/Illuminate/Foundation/Application.php",
        "nav_function": "Application",
        "search_query": "service container and dependency injection bindings",
    },
}


@dataclass
class RepoMetrics:
    repo: str
    bootstrap_time_ms: float
    symbol_count: int
    quality_score: float
    total_time_ms: float = 0.0


@dataclass
class RegressionResult:
    metric: str
    repo: str
    baseline_value: float
    current_value: float
    delta_pct: float
    threshold_pct: float
    is_regression: bool




def run_single_benchmark(repo_name: str, cfg: dict) -> dict:
    """Run all 10 benchmark tasks on a repo, return raw results."""
    svc = CodeIntelService(cfg["path"])
    results = {}

    t0 = time.perf_counter()
    output = svc.bootstrap(task_hint="understand architecture", max_tokens=8000)
    bootstrap_ms = (time.perf_counter() - t0) * 1000
    results["bootstrap"] = {
        "time_ms": bootstrap_ms,
        "output_len": len(output),
        "output_preview": output[:1500],
    }

    # Symbol discovery
    t0 = time.perf_counter()
    sym_out = svc.search_symbols(cfg["symbol"])
    xref_out = svc.cross_references(cfg["symbol"])
    ms = (time.perf_counter() - t0) * 1000
    combined = sym_out + "\n\n" + xref_out
    results["symbol_discovery"] = {
        "time_ms": ms, "output_len": len(combined),
        "output_preview": combined[:1500], "calls": 2,
    }

    # Dependency tracing
    t0 = time.perf_counter()
    dep_out = svc.dependency_graph(cfg["dep_file"], depth=2)
    imp_out = svc.impact_analysis([cfg["dep_file"]])
    ms = (time.perf_counter() - t0) * 1000
    combined = dep_out + "\n\n" + imp_out
    results["dependency_tracing"] = {
        "time_ms": ms, "output_len": len(combined),
        "output_preview": combined[:1500], "calls": 2,
    }

    # Architecture
    t0 = time.perf_counter()
    comm_out = svc.community_detection()
    hot_out = svc.hotspots(top_n=15)
    ms = (time.perf_counter() - t0) * 1000
    combined = comm_out + "\n\n" + hot_out
    results["architecture"] = {
        "time_ms": ms, "output_len": len(combined),
        "output_preview": combined[:1500], "calls": 2,
    }

    # Code navigation
    t0 = time.perf_counter()
    nav_out = svc.symbols(cfg["nav_file"])
    ref_out = svc.cross_references(cfg["nav_function"])
    ms = (time.perf_counter() - t0) * 1000
    combined = nav_out + "\n\n" + ref_out
    results["code_navigation"] = {
        "time_ms": ms, "output_len": len(combined),
        "output_preview": combined[:1500], "calls": 2,
    }

    # Semantic search
    t0 = time.perf_counter()
    search_out = svc.semantic_search(cfg["search_query"])
    ms = (time.perf_counter() - t0) * 1000
    results["semantic_search"] = {
        "time_ms": ms, "output_len": len(search_out),
        "output_preview": search_out[:1500], "calls": 1,
    }

    # Dead code analysis
    t0 = time.perf_counter()
    try:
        dead_data = svc.dead_code_data(level="symbol", top_n=30)
        dead_out = json.dumps(dead_data, default=str)
    except (AttributeError, Exception) as e:
        dead_out = f"Error: {e}"
    ms = (time.perf_counter() - t0) * 1000
    results["dead_code"] = {
        "time_ms": ms, "output_len": len(dead_out),
        "output_preview": dead_out[:1500],
    }

    # Distill
    t0 = time.perf_counter()
    try:
        distill_data = svc.distill_data(files=[cfg["dep_file"]], level="signatures", max_tokens=4000)
        distill_out = json.dumps(distill_data, default=str)
    except (AttributeError, Exception) as e:
        distill_out = f"Error: {e}"
    ms = (time.perf_counter() - t0) * 1000
    results["distill"] = {
        "time_ms": ms, "output_len": len(distill_out),
        "output_preview": distill_out[:1500],
    }

    # Graph DSL query
    t0 = time.perf_counter()
    try:
        dsl_query = cfg.get("graph_dsl_query", f'MATCH "{cfg["dep_file"]}" -[IMPORTS*1..3]-> t RETURN t')
        dsl_out = svc.graph_dsl(dsl_query)
    except (AttributeError, Exception) as e:
        dsl_out = f"Error: {e}"
    ms = (time.perf_counter() - t0) * 1000
    results["graph_dsl"] = {
        "time_ms": ms, "output_len": len(dsl_out),
        "output_preview": dsl_out[:1500],
    }

    # Code evolution
    t0 = time.perf_counter()
    try:
        evo_data = svc.code_evolution_data(path=cfg["dep_file"], max_results=10)
        evo_out = json.dumps(evo_data, default=str)
    except (AttributeError, Exception) as e:
        evo_out = f"Error: {e}"
    ms = (time.perf_counter() - t0) * 1000
    results["code_evolution"] = {
        "time_ms": ms, "output_len": len(evo_out),
        "output_preview": evo_out[:1500],
    }

    return results


def run_grep_baseline(repo_name: str, cfg: dict) -> dict:
    """Run grep-only baseline for the same 10 tasks (no CodeIntelService)."""
    import subprocess

    results = {}
    path = cfg["path"]

    def rg(args: list[str]) -> str:
        try:
            r = subprocess.run(
                ["rg", *args], cwd=path,
                capture_output=True, text=True, timeout=30,
            )
            return r.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return ""

    # Bootstrap — file listing + line count
    t0 = time.perf_counter()
    files = rg(["--files"])
    file_count = len(files.strip().splitlines()) if files.strip() else 0
    readme = ""
    for name in ["README.md", "README.rst", "README.txt", "README"]:
        try:
            readme = open(os.path.join(path, name)).read()[:2000]
            break
        except FileNotFoundError:
            continue
    output = f"Files: {file_count}\n{readme}"
    ms = (time.perf_counter() - t0) * 1000
    results["bootstrap"] = {"time_ms": ms, "output_len": len(output), "output_preview": output[:1500]}

    # Symbol discovery — regex for definitions + reference count
    t0 = time.perf_counter()
    sym = cfg["symbol"]
    defs = rg(["-n", f"(class|def|function|fn|struct|func|fun|type|interface|protocol|object|trait)\\s+{sym}"])
    refs = rg(["-c", sym])
    combined = f"Definitions:\n{defs}\nReferences:\n{refs}"
    ms = (time.perf_counter() - t0) * 1000
    results["symbol_discovery"] = {"time_ms": ms, "output_len": len(combined), "output_preview": combined[:1500], "calls": 2}

    # Dependency tracing — import grep
    t0 = time.perf_counter()
    dep_base = os.path.basename(cfg["dep_file"]).rsplit(".", 1)[0]
    forward = rg(["-n", r"^(import|from|use|require|#include|using)\s", cfg["dep_file"]])
    reverse = rg(["-l", dep_base])
    combined = f"Imports (forward):\n{forward}\nImported by:\n{reverse}"
    ms = (time.perf_counter() - t0) * 1000
    results["dependency_tracing"] = {"time_ms": ms, "output_len": len(combined), "output_preview": combined[:1500], "calls": 2}

    # Architecture — directory listing (no community detection)
    t0 = time.perf_counter()
    dirs = rg(["--files"])
    dir_set = set()
    for line in (dirs or "").splitlines():
        parts = line.strip().split("/")
        if len(parts) > 1:
            dir_set.add(parts[0])
    output = f"Top directories: {sorted(dir_set)[:20]}\nTotal files: {file_count}"
    ms = (time.perf_counter() - t0) * 1000
    results["architecture"] = {"time_ms": ms, "output_len": len(output), "output_preview": output[:1500], "calls": 1}

    # Code navigation — symbols in file + function refs
    t0 = time.perf_counter()
    nav_syms = rg(["-n", r"(class|def|function|fn|struct|func)\s+\w+", cfg["nav_file"]])
    func_refs = rg(["-n", cfg["nav_function"]])
    combined = f"Symbols in {cfg['nav_file']}:\n{nav_syms}\nReferences to {cfg['nav_function']}:\n{func_refs}"
    ms = (time.perf_counter() - t0) * 1000
    results["code_navigation"] = {"time_ms": ms, "output_len": len(combined), "output_preview": combined[:1500], "calls": 2}

    # Semantic search — keyword OR matching
    t0 = time.perf_counter()
    terms = cfg["search_query"].split()
    pattern = "|".join(terms[:5])
    search_out = rg(["-l", "-i", pattern])
    file_list = search_out.strip().splitlines()[:20] if search_out else []
    output = "\n".join(f"{i+1}. {f}" for i, f in enumerate(file_list))
    ms = (time.perf_counter() - t0) * 1000
    results["semantic_search"] = {"time_ms": ms, "output_len": len(output), "output_preview": output[:1500], "calls": 1}

    # Dead code — check if symbol has references
    t0 = time.perf_counter()
    # Pick a few symbols from nav_file and check if they're referenced elsewhere
    nav_content = rg(["-n", r"(def|function|fn|func|class)\s+(\w+)", cfg["nav_file"]])
    syms_found = []
    for line in (nav_content or "").splitlines()[:10]:
        import re as _re
        m = _re.search(r"(def|function|fn|func|class)\s+(\w+)", line)
        if m:
            name = m.group(2)
            count = rg(["-c", name])
            total = sum(int(x) for x in (count or "").splitlines() if x.strip().isdigit())
            if total <= 1:
                syms_found.append(f"Possibly dead: {name} ({total} references)")
    output = "\n".join(syms_found) if syms_found else "No dead symbols detected via grep"
    ms = (time.perf_counter() - t0) * 1000
    results["dead_code"] = {"time_ms": ms, "output_len": len(output), "output_preview": output[:1500]}

    # Distill — extract function signatures via regex
    t0 = time.perf_counter()
    sigs = rg(["-n", r"^\s*(def |function |fn |func |class |struct |interface |type )\w+", cfg["dep_file"]])
    output = f"Signatures from {cfg['dep_file']}:\n{sigs or '(none)'}"
    ms = (time.perf_counter() - t0) * 1000
    results["distill"] = {"time_ms": ms, "output_len": len(output), "output_preview": output[:1500]}

    # Graph DSL — not possible with grep
    t0 = time.perf_counter()
    output = "N/A — graph DSL queries require dependency graph (not available with grep)"
    ms = (time.perf_counter() - t0) * 1000
    results["graph_dsl"] = {"time_ms": ms, "output_len": len(output), "output_preview": output[:1500]}

    # Code evolution — git log
    t0 = time.perf_counter()
    try:
        r = subprocess.run(
            ["git", "log", "--oneline", "-10", "--", cfg["dep_file"]],
            cwd=path, capture_output=True, text=True, timeout=10,
        )
        output = r.stdout or "(no git history)"
    except Exception:
        output = "(git not available)"
    ms = (time.perf_counter() - t0) * 1000
    results["code_evolution"] = {"time_ms": ms, "output_len": len(output), "output_preview": output[:1500]}

    return results


def benchmark_repo_with_median(repo_name: str, cfg: dict, num_runs: int = NUM_RUNS) -> RepoMetrics:
    """Run benchmark N times and take median for timing stability."""
    print(f"\n  Benchmarking {repo_name} ({num_runs} runs)...")

    bootstrap_times = []
    quality_scores = []
    symbol_counts = []
    total_times = []

    for run_idx in range(num_runs):
        print(f"    Run {run_idx + 1}/{num_runs}...", end=" ", flush=True)
        results = run_single_benchmark(repo_name, cfg)

        bootstrap_ms = results["bootstrap"]["time_ms"]
        bootstrap_times.append(bootstrap_ms)

        # Quality score
        quality = compute_repo_quality(results)
        quality_scores.append(quality)

        # Symbol count: use output_len as a reliable proxy (not regex on truncated preview)
        sym_output_len = results.get("symbol_discovery", {}).get("output_len", 0)
        symbol_counts.append(sym_output_len)

        # Total time
        total_ms = sum(t.get("time_ms", 0) for t in results.values())
        total_times.append(total_ms)

        print(f"bootstrap={bootstrap_ms:.0f}ms, quality={quality:.1f}")

    return RepoMetrics(
        repo=repo_name,
        bootstrap_time_ms=statistics.median(bootstrap_times),
        symbol_count=round(statistics.median(symbol_counts)),
        quality_score=round(statistics.median(quality_scores), 1),
        total_time_ms=statistics.median(total_times),
    )


def load_baseline(path: str) -> dict | None:
    """Load baseline from JSON file."""
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def check_regressions(
    current: list[RepoMetrics],
    baseline: dict,
) -> list[RegressionResult]:
    """Check current metrics against baseline for regressions."""
    regressions = []

    for metrics in current:
        base_repo = baseline.get("repos", {}).get(metrics.repo)
        if not base_repo:
            continue

        checks = [
            ("bootstrap_time_ms", metrics.bootstrap_time_ms, base_repo.get("bootstrap_time_ms", 0), True),
            ("symbol_count", metrics.symbol_count, base_repo.get("symbol_count", 0), False),
            ("quality_score", metrics.quality_score, base_repo.get("quality_score", 0), False),
        ]

        for metric_name, current_val, baseline_val, higher_is_worse in checks:
            if baseline_val == 0:
                continue

            if higher_is_worse:
                delta_pct = (current_val - baseline_val) / baseline_val
            else:
                delta_pct = (baseline_val - current_val) / baseline_val

            threshold = REGRESSION_THRESHOLDS[metric_name]
            is_regression = delta_pct > threshold

            regressions.append(RegressionResult(
                metric=metric_name,
                repo=metrics.repo,
                baseline_value=baseline_val,
                current_value=current_val,
                delta_pct=delta_pct,
                threshold_pct=threshold,
                is_regression=is_regression,
            ))

    return regressions


def format_pr_comment(
    metrics: list[RepoMetrics],
    regressions: list[RegressionResult],
    baseline: dict | None,
) -> str:
    """Format benchmark results as a GitHub PR comment."""
    has_failure = any(r.is_regression for r in regressions)
    status = "FAIL" if has_failure else "PASS"

    lines = [
        f"## Benchmark Results: {status}",
        "",
        "| Repo | Bootstrap (ms) | Symbols | Quality | Status |",
        "|------|---------------|---------|---------|--------|",
    ]

    for m in metrics:
        # Find regressions for this repo
        repo_regs = [r for r in regressions if r.repo == m.repo]
        repo_status = "FAIL" if any(r.is_regression for r in repo_regs) else "pass"

        # Format with delta from baseline
        boot_str = f"{m.bootstrap_time_ms:.0f}"
        sym_str = str(m.symbol_count)
        qual_str = f"{m.quality_score:.1f}/5"

        if baseline and m.repo in baseline.get("repos", {}):
            base = baseline["repos"][m.repo]
            boot_delta = ((m.bootstrap_time_ms - base.get("bootstrap_time_ms", 0)) /
                         base.get("bootstrap_time_ms", 1)) * 100
            sym_delta = ((m.symbol_count - base.get("symbol_count", 0)) /
                        max(base.get("symbol_count", 1), 1)) * 100
            qual_delta = m.quality_score - base.get("quality_score", 0)

            boot_str += f" ({boot_delta:+.1f}%)"
            sym_str += f" ({sym_delta:+.0f}%)"
            qual_str += f" ({qual_delta:+.1f})"

        lines.append(f"| {m.repo} | {boot_str} | {sym_str} | {qual_str} | {repo_status} |")

    if has_failure:
        lines.extend(["", "### Regressions Detected", ""])
        for r in regressions:
            if r.is_regression:
                lines.append(
                    f"- **{r.repo}/{r.metric}**: {r.baseline_value:.1f} -> "
                    f"{r.current_value:.1f} ({r.delta_pct:+.1%}, threshold: {r.threshold_pct:.0%})"
                )

    return "\n".join(lines)


def save_baseline(metrics: list[RepoMetrics], path: str) -> None:
    """Save current metrics as the new baseline."""
    git = get_git_info(PROJECT_ROOT)
    baseline = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "git_sha": git["sha"],
        "branch": git["branch"],
        "repos": {},
    }
    for m in metrics:
        baseline["repos"][m.repo] = {
            "bootstrap_time_ms": m.bootstrap_time_ms,
            "symbol_count": m.symbol_count,
            "quality_score": m.quality_score,
            "total_time_ms": m.total_time_ms,
        }
    with open(path, "w") as f:
        json.dump(baseline, f, indent=2)
    print(f"\nBaseline saved to: {path}")


def main():
    parser = argparse.ArgumentParser(description="CI benchmark runner with regression detection")
    parser.add_argument("--repos", nargs="+", default=DEFAULT_REPOS, help="Repos to benchmark")
    parser.add_argument("--num-runs", type=int, default=NUM_RUNS, help="Number of runs for median")
    parser.add_argument("--baseline", default=BASELINE_PATH, help="Baseline JSON path")
    parser.add_argument("--update-baseline", action="store_true", help="Update baseline with current results")
    parser.add_argument("--output-json", help="Output JSON results path")
    parser.add_argument("--output-comment", help="Output PR comment markdown path")
    parser.add_argument("--fail-on-regression", action=argparse.BooleanOptionalAction, default=True, help="Exit 1 on regression")
    parser.add_argument("--mode", choices=["both", "code-intel", "grep"], default="both",
                        help="Run mode: both (default), code-intel only, or grep only")

    args = parser.parse_args()

    print("=" * 60)
    print("  CI Benchmark Runner")
    print("=" * 60)

    git = get_git_info(PROJECT_ROOT)
    print(f"  Git: {git['sha']} ({git['branch']})")

    # Validate repos
    repos = []
    for repo_name in args.repos:
        cfg = REPO_CONFIGS.get(repo_name)
        if not cfg:
            print(f"  SKIP {repo_name}: no config")
            continue
        if not os.path.isdir(cfg["path"]):
            print(f"  SKIP {repo_name}: {cfg['path']} not found")
            continue
        repos.append(repo_name)

    if not repos:
        print("\nNo repos available.")
        sys.exit(1)

    # Run code-intel benchmarks
    ci_metrics: list[RepoMetrics] = []
    if args.mode in ("both", "code-intel"):
        print("\n=== Code-Intel Mode ===")
        for repo_name in repos:
            cfg = REPO_CONFIGS[repo_name]
            metrics = benchmark_repo_with_median(repo_name, cfg, args.num_runs)
            ci_metrics.append(metrics)

    # Run grep baseline
    grep_results: dict[str, dict] = {}
    if args.mode in ("both", "grep"):
        print("\n=== Grep Baseline Mode ===")
        for repo_name in repos:
            cfg = REPO_CONFIGS[repo_name]
            print(f"\n  Grep baseline: {repo_name}...", end=" ", flush=True)
            grep_results[repo_name] = run_grep_baseline(repo_name, cfg)
            grep_quality = compute_repo_quality(grep_results[repo_name])
            print(f"quality={grep_quality:.1f}")

    # Comparison table
    if args.mode == "both" and ci_metrics and grep_results:
        print("\n## Code-Intel vs Grep Comparison\n")
        print("| Repo | CI Quality | Grep Quality | Delta | Winner |")
        print("|------|-----------|-------------|-------|--------|")

        total_ci, total_grep, count = 0, 0, 0
        for m in ci_metrics:
            if m.repo in grep_results:
                gq = compute_repo_quality(grep_results[m.repo])
                delta = m.quality_score - gq
                winner = "Code-Intel" if delta > 0 else "Grep" if delta < 0 else "Tie"
                print(f"| {m.repo} | {m.quality_score:.1f}/5 | {gq:.1f}/5 | {delta:+.1f} | {winner} |")
                total_ci += m.quality_score
                total_grep += gq
                count += 1

        if count:
            avg_delta = (total_ci - total_grep) / count
            print(f"| **Average** | **{total_ci/count:.1f}** | **{total_grep/count:.1f}** | **{avg_delta:+.1f}** | {'Code-Intel' if avg_delta > 0 else 'Grep'} |")

    # Use ci_metrics for regression detection and output (backward compatible)
    metrics = ci_metrics

    if not metrics and args.mode == "grep":
        # grep-only mode: no regression detection needed
        print("\nGrep-only mode complete.")
        return

    if not metrics:
        print("\nNo repos benchmarked.")
        sys.exit(1)

    # Load baseline and check regressions
    baseline = load_baseline(args.baseline)
    regressions = check_regressions(metrics, baseline) if baseline else []

    # Print PR comment
    comment = format_pr_comment(metrics, regressions, baseline)
    print(f"\n{comment}")

    # Save outputs
    if args.output_comment:
        with open(args.output_comment, "w") as f:
            f.write(comment)
        print(f"\nPR comment saved to: {args.output_comment}")

    if args.output_json:
        result_data = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "git": git,
            "repos": {m.repo: {
                "bootstrap_time_ms": m.bootstrap_time_ms,
                "symbol_count": m.symbol_count,
                "quality_score": m.quality_score,
                "total_time_ms": m.total_time_ms,
            } for m in metrics},
            "regressions": [{
                "metric": r.metric, "repo": r.repo,
                "baseline": r.baseline_value, "current": r.current_value,
                "delta_pct": r.delta_pct, "is_regression": r.is_regression,
            } for r in regressions],
        }
        if grep_results:
            result_data["grep_baseline"] = {
                repo: {"quality_score": compute_repo_quality(res)}
                for repo, res in grep_results.items()
            }
        with open(args.output_json, "w") as f:
            json.dump(result_data, f, indent=2)
        print(f"JSON results saved to: {args.output_json}")

    # Persist results to SQLite DB for time-series analysis
    db_path = os.path.join(PROJECT_ROOT, "eval", "benchmarks.db")
    run_id = f"ci-{git['sha']}-{int(time.time())}"
    db = BenchmarkDB(db_path)
    db.connect()
    db.save_run(BenchmarkRun(
        run_id=run_id,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
        git_sha=git["sha"],
        branch=git["branch"],
        entries=[
            BenchmarkEntry(
                repo=m.repo,
                bootstrap_time_ms=m.bootstrap_time_ms,
                symbol_count=m.symbol_count,
                quality_score=m.quality_score,
                total_time_ms=m.total_time_ms,
            )
            for m in metrics
        ],
    ))
    db.close()
    print(f"Results persisted to DB: {run_id}")

    # Update baseline if requested
    if args.update_baseline:
        save_baseline(metrics, args.baseline)

    # Exit with failure if regressions detected
    if args.fail_on_regression and any(r.is_regression for r in regressions):
        print("\nFAIL: Regressions detected!")
        sys.exit(1)

    print("\nPASS: No regressions detected.")


if __name__ == "__main__":
    main()
