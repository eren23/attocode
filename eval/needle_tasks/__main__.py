"""Needle-in-the-haystack deep code understanding evaluation.

Tests code-intel capabilities that no existing benchmark covers:
call chain tracing, dead code finding, impact assessment,
architecture quizzes, and cross-file symbol resolution.

Usage:
    python -m eval.needle_tasks                     # run all tasks
    python -m eval.needle_tasks --type impact_assessment  # filter by type
    python -m eval.needle_tasks --id arch_highest_fanin   # single task
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import yaml


def load_tasks(
    task_file: str = "",
    task_type: str = "",
    task_id: str = "",
) -> tuple[dict, list[dict]]:
    """Load task definitions from YAML."""
    if not task_file:
        task_file = str(Path(__file__).parent / "tasks.yaml")

    with open(task_file) as f:
        data = yaml.safe_load(f)

    tasks = data.get("tasks", [])
    if task_type:
        tasks = [t for t in tasks if t.get("type") == task_type]
    if task_id:
        tasks = [t for t in tasks if t.get("id") == task_id]

    return data, tasks


def run_trace_call_chain(svc: Any, task: dict) -> dict:
    """Run a call chain tracing task."""
    target_file = task["target_file"]
    target_function = task["target_function"]
    max_depth = task.get("max_depth", 3)

    # Use dependency_graph and cross_references
    dep_output = svc.dependency_graph(target_file, depth=max_depth)
    xref_output = svc.cross_references(target_function)
    impact_output = svc.impact_analysis([target_file])

    gt = task.get("ground_truth", {})
    direct_callers = gt.get("direct_callers", [])

    # Check if ground truth callers appear in output
    found_callers = []
    for caller in direct_callers:
        if caller in dep_output or caller in xref_output or caller in impact_output:
            found_callers.append(caller)

    recall = len(found_callers) / len(direct_callers) if direct_callers else 1.0

    return {
        "found_callers": found_callers,
        "expected_callers": direct_callers,
        "recall": round(recall, 3),
        "passed": recall >= 0.5,
        "dep_output_len": len(dep_output),
        "xref_output_len": len(xref_output),
    }


def run_find_dead_code(svc: Any, task: dict) -> dict:
    """Run a dead code detection task."""
    scope = task.get("scope", "")
    try:
        dead_data = svc.dead_code_data(scope=scope, level="symbol", top_n=30)
        items = dead_data.get("items", [])
        stats = dead_data.get("stats", {})
        return {
            "dead_count": len(items),
            "stats": stats,
            "passed": len(items) > 0,
            "sample_items": [str(i) for i in items[:5]],
        }
    except Exception as e:
        return {"error": str(e), "passed": False}


def run_impact_assessment(svc: Any, task: dict) -> dict:
    """Run an impact assessment task."""
    target_file = task["target_file"]
    target_symbol = task.get("target_symbol", "")

    impact_output = svc.impact_analysis([target_file])
    dep_output = svc.dependency_graph(target_file, depth=2)
    xref_output = svc.cross_references(target_symbol) if target_symbol else ""

    gt = task.get("ground_truth", {})
    min_affected = gt.get("min_affected_files", 0)
    must_include = gt.get("must_include", [])

    # Count affected files in output
    combined = impact_output + "\n" + dep_output + "\n" + xref_output
    # Simple heuristic: count unique .py/.ts/.go file paths
    file_refs = set(re.findall(r'[\w/.-]+\.\w{1,4}', combined))
    affected_count = len(file_refs)

    found_required = [f for f in must_include if any(f in line for line in combined.splitlines())]

    passed = affected_count >= min_affected and len(found_required) >= len(must_include) * 0.5

    return {
        "affected_files": affected_count,
        "min_required": min_affected,
        "found_required": found_required,
        "expected_required": must_include,
        "passed": passed,
    }


def run_architecture_quiz(svc: Any, task: dict) -> dict:
    """Run an architecture quiz task."""
    question = task["question"]
    answer_type = task.get("answer_type", "text")
    gt = task.get("ground_truth", {})

    # Use bootstrap, community_detection, hotspots
    bootstrap_out = svc.bootstrap(task_hint=question, max_tokens=6000)
    hotspots_out = svc.hotspots(top_n=10)

    combined = bootstrap_out + "\n" + hotspots_out

    if answer_type == "file_path":
        expected = gt.get("expected_answer", "")
        acceptable = gt.get("acceptable_answers", [expected])
        found = any(a in combined for a in acceptable)
        return {"passed": found, "expected": acceptable, "output_len": len(combined)}

    elif answer_type == "integer":
        expected = gt.get("expected_answer", 0)
        tolerance = gt.get("tolerance", 0)
        # Try to find the number in output
        try:
            comm_out = svc.community_detection()
            numbers = re.findall(r'(\d+)\s*communit', comm_out, re.I)
            if numbers:
                detected = int(numbers[0])
                passed = abs(detected - expected) <= tolerance
                return {"passed": passed, "detected": detected, "expected": expected}
        except Exception:
            pass
        return {"passed": False, "expected": expected}

    elif answer_type == "file_list":
        must_include = gt.get("must_include_any", [])
        found = [f for f in must_include if f in combined]
        passed = len(found) >= 1
        return {"passed": passed, "found": found, "expected_any": must_include}

    return {"passed": False, "error": f"Unknown answer_type: {answer_type}"}


def run_cross_file_symbol(svc: Any, task: dict) -> dict:
    """Run a cross-file symbol resolution task."""
    symbol = task["symbol"]
    gt = task.get("ground_truth", {})

    sym_output = svc.search_symbols(symbol)
    xref_output = svc.cross_references(symbol)

    combined = sym_output + "\n" + xref_output

    # Check definitions
    def_files = gt.get("definition_files", [])
    found_defs = [f for f in def_files if f in combined]

    # Count usage files
    min_usages = gt.get("min_usage_files", 0)
    file_refs = set(re.findall(r'([\w/.-]+\.(?:py|ts|js|go|rs|ex))', combined))
    usage_count = len(file_refs)

    passed = len(found_defs) == len(def_files) and usage_count >= min_usages

    return {
        "found_definitions": found_defs,
        "expected_definitions": def_files,
        "usage_file_count": usage_count,
        "min_usage_required": min_usages,
        "passed": passed,
    }


def run_trace_call_chain_grep(task: dict, repo_path: str) -> dict:
    """Grep baseline for call chain tracing."""
    import subprocess
    target_function = task["target_function"]

    try:
        result = subprocess.run(
            ["rg", "-l", target_function], cwd=repo_path,
            capture_output=True, text=True, timeout=10,
        )
        files = result.stdout.strip().splitlines()
    except Exception:
        files = []

    gt = task.get("ground_truth", {})
    direct_callers = gt.get("direct_callers", [])
    found = [c for c in direct_callers if any(c in f for f in files)]
    recall = len(found) / len(direct_callers) if direct_callers else 1.0

    return {
        "found_callers": found,
        "expected_callers": direct_callers,
        "recall": round(recall, 3),
        "passed": recall >= 0.5,
        "grep_files_found": len(files),
    }


def run_find_dead_code_grep(task: dict, repo_path: str) -> dict:
    """Grep baseline for dead code detection."""
    import subprocess
    import re as _re

    scope = task.get("scope", "")
    scope_path = os.path.join(repo_path, scope) if scope else repo_path

    # Find function/class definitions in scope
    try:
        result = subprocess.run(
            ["rg", "-n", r"(def|class|function|fn)\s+(\w+)", scope_path],
            capture_output=True, text=True, timeout=10,
        )
        definitions = result.stdout.strip().splitlines()
    except Exception:
        definitions = []

    dead_count = 0
    for line in definitions[:20]:
        m = _re.search(r"(def|class|function|fn)\s+(\w+)", line)
        if m:
            name = m.group(2)
            if name.startswith("_"):
                continue
            try:
                ref_result = subprocess.run(
                    ["rg", "-c", name, repo_path],
                    capture_output=True, text=True, timeout=5,
                )
                total = sum(int(x) for x in ref_result.stdout.splitlines() if x.strip().isdigit())
                if total <= 1:
                    dead_count += 1
            except Exception:
                pass

    return {"dead_count": dead_count, "passed": dead_count > 0}


def run_impact_assessment_grep(task: dict, repo_path: str) -> dict:
    """Grep baseline for impact assessment."""
    import subprocess

    target_file = task["target_file"]
    target_symbol = task.get("target_symbol", "")
    gt = task.get("ground_truth", {})

    # Find files that reference the target
    search_term = target_symbol or os.path.basename(target_file).rsplit(".", 1)[0]
    try:
        result = subprocess.run(
            ["rg", "-l", search_term, repo_path],
            capture_output=True, text=True, timeout=10,
        )
        files = result.stdout.strip().splitlines()
    except Exception:
        files = []

    min_affected = gt.get("min_affected_files", 0)
    must_include = gt.get("must_include", [])
    found_required = [f for f in must_include if any(f in ref for ref in files)]
    passed = len(files) >= min_affected and len(found_required) >= len(must_include) * 0.5

    return {
        "affected_files": len(files),
        "min_required": min_affected,
        "found_required": found_required,
        "expected_required": must_include,
        "passed": passed,
    }


def run_architecture_quiz_grep(task: dict, repo_path: str) -> dict:
    """Grep baseline for architecture quiz."""
    import subprocess

    answer_type = task.get("answer_type", "text")
    gt = task.get("ground_truth", {})

    if answer_type == "file_path":
        # Can't determine fan-in via grep alone — guess based on file size
        return {"passed": False, "reason": "grep cannot compute fan-in metrics"}

    elif answer_type == "integer":
        # Can't detect communities via grep
        return {"passed": False, "reason": "grep cannot detect architectural communities"}

    elif answer_type == "file_list":
        # List largest files as a proxy for "critical"
        try:
            result = subprocess.run(
                ["rg", "--files"], cwd=repo_path,
                capture_output=True, text=True, timeout=10,
            )
            files = result.stdout.strip().splitlines()
        except Exception:
            files = []

        must_include = gt.get("must_include_any", [])
        found = [f for f in must_include if f in "\n".join(files)]
        return {"passed": len(found) >= 1, "found": found, "expected_any": must_include}

    return {"passed": False}


def run_cross_file_symbol_grep(task: dict, repo_path: str) -> dict:
    """Grep baseline for cross-file symbol resolution."""
    import subprocess
    import re as _re

    symbol = task["symbol"]
    gt = task.get("ground_truth", {})

    # Find definitions
    try:
        defs_result = subprocess.run(
            ["rg", "-l", f"(class|def|struct|interface|type)\\s+{symbol}"],
            cwd=repo_path, capture_output=True, text=True, timeout=10,
        )
        def_files = defs_result.stdout.strip().splitlines()
    except Exception:
        def_files = []

    # Find all references
    try:
        refs_result = subprocess.run(
            ["rg", "-l", symbol], cwd=repo_path,
            capture_output=True, text=True, timeout=10,
        )
        ref_files = refs_result.stdout.strip().splitlines()
    except Exception:
        ref_files = []

    expected_defs = gt.get("definition_files", [])
    found_defs = [f for f in expected_defs if any(f in d for d in def_files)]
    min_usages = gt.get("min_usage_files", 0)

    passed = len(found_defs) == len(expected_defs) and len(ref_files) >= min_usages

    return {
        "found_definitions": found_defs,
        "expected_definitions": expected_defs,
        "usage_file_count": len(ref_files),
        "min_usage_required": min_usages,
        "passed": passed,
    }


GREP_TASK_RUNNERS = {
    "trace_call_chain": run_trace_call_chain_grep,
    "find_dead_code": run_find_dead_code_grep,
    "impact_assessment": run_impact_assessment_grep,
    "architecture_quiz": run_architecture_quiz_grep,
    "cross_file_symbol_resolution": run_cross_file_symbol_grep,
}


TASK_RUNNERS = {
    "trace_call_chain": run_trace_call_chain,
    "find_dead_code": run_find_dead_code,
    "impact_assessment": run_impact_assessment,
    "architecture_quiz": run_architecture_quiz,
    "cross_file_symbol_resolution": run_cross_file_symbol,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Needle-in-haystack code understanding evaluation")
    parser.add_argument("--tasks", default="", help="Path to tasks YAML")
    parser.add_argument("--type", default="", help="Filter by task type")
    parser.add_argument("--id", default="", help="Run single task by ID")
    parser.add_argument("--output", default="eval/needle_tasks/results.json", help="Output path")
    parser.add_argument("--mode", choices=["both", "code-intel", "grep"], default="code-intel",
                        help="Run mode: code-intel (default), grep baseline, or both for comparison")
    args = parser.parse_args()

    data, tasks = load_tasks(args.tasks, args.type, args.id)
    if not tasks:
        print("No tasks found.")
        return

    repo_path = data.get("repo_path", ".")
    print(f"Repo: {data.get('repo', 'unknown')} ({repo_path})")
    print(f"Tasks: {len(tasks)}")
    print()

    results: list[dict] = []
    passed_count = 0

    # Run code-intel tasks
    if args.mode in ("code-intel", "both"):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
        from attocode.code_intel.service import CodeIntelService

        svc = CodeIntelService(repo_path)

        for i, task in enumerate(tasks):
            task_id = task["id"]
            task_type = task["type"]
            runner = TASK_RUNNERS.get(task_type)

            if not runner:
                print(f"  [{i+1}/{len(tasks)}] {task_id} ({task_type}) — SKIP: unknown type")
                continue

            print(f"  [{i+1}/{len(tasks)}] {task_id} ({task_type})...", end=" ", flush=True)

            t0 = time.perf_counter()
            try:
                result = runner(svc, task)
            except Exception as e:
                result = {"error": str(e), "passed": False}
            elapsed = time.perf_counter() - t0

            result["task_id"] = task_id
            result["task_type"] = task_type
            result["mode"] = "code-intel"
            result["time_s"] = round(elapsed, 2)
            results.append(result)

            status = "PASS" if result.get("passed") else "FAIL"
            if result.get("passed"):
                passed_count += 1
            print(f"{status} ({elapsed:.1f}s)")

        # Summary
        print(f"\nCode-Intel: {passed_count}/{len(results)} passed")

        # Per-type breakdown
        type_stats: dict[str, list[bool]] = {}
        for r in results:
            type_stats.setdefault(r["task_type"], []).append(r.get("passed", False))

        for typ, passes in sorted(type_stats.items()):
            p = sum(passes)
            print(f"  {typ}: {p}/{len(passes)}")

    # Run grep baseline
    grep_results: list[dict] = []
    grep_passed = 0

    if args.mode in ("both", "grep"):
        for i, task in enumerate(tasks):
            task_type = task["type"]
            grep_runner = GREP_TASK_RUNNERS.get(task_type)
            if not grep_runner:
                continue

            print(f"  [grep {i+1}/{len(tasks)}] {task['id']} ({task_type})...", end=" ", flush=True)
            t0 = time.perf_counter()
            try:
                result = grep_runner(task, repo_path)
            except Exception as e:
                result = {"error": str(e), "passed": False}
            elapsed = time.perf_counter() - t0
            result["task_id"] = task["id"]
            result["task_type"] = task_type
            result["mode"] = "grep"
            result["time_s"] = round(elapsed, 2)
            grep_results.append(result)

            if result.get("passed"):
                grep_passed += 1
            status = "PASS" if result.get("passed") else "FAIL"
            print(f"{status} ({elapsed:.1f}s)")

        print(f"\nGrep baseline: {grep_passed}/{len(grep_results)} passed")

    # Comparison table
    if args.mode == "both":
        print(f"\n## Comparison: Code-Intel vs Grep")
        print(f"| Task Type | Code-Intel | Grep | Winner |")
        print(f"|-----------|-----------|------|--------|")

        ci_by_type: dict[str, list[bool]] = {}
        for r in results:
            ci_by_type.setdefault(r["task_type"], []).append(r.get("passed", False))
        grep_by_type: dict[str, list[bool]] = {}
        for r in grep_results:
            grep_by_type.setdefault(r["task_type"], []).append(r.get("passed", False))

        for typ in sorted(set(list(ci_by_type.keys()) + list(grep_by_type.keys()))):
            ci_pass = sum(ci_by_type.get(typ, []))
            ci_total = len(ci_by_type.get(typ, []))
            g_pass = sum(grep_by_type.get(typ, []))
            g_total = len(grep_by_type.get(typ, []))
            winner = "Code-Intel" if ci_pass > g_pass else "Grep" if g_pass > ci_pass else "Tie"
            print(f"| {typ} | {ci_pass}/{ci_total} | {g_pass}/{g_total} | {winner} |")

    # Save
    all_results = results + grep_results
    total_passed = passed_count + grep_passed
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump({
            "repo": data.get("repo"),
            "mode": args.mode,
            "total": len(all_results),
            "passed": total_passed,
            "results": all_results,
        }, f, indent=2)
    print(f"\nSaved to {output_path}")


if __name__ == "__main__":
    main()
