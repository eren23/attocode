"""Qualitative task comparison: real agent-style queries, BEFORE vs AFTER.

Runs 5 realistic queries across 3 repos with both configs, prints
side-by-side top-10 results for human judgment.

Usage:
    python -m eval.meta_harness.qualitative_tasks
"""

from __future__ import annotations

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))
    sys.path.insert(0, _PROJECT_ROOT)

from attocode.code_intel.service import CodeIntelService

from eval.meta_harness.harness_config import HarnessConfig
from eval.meta_harness.paths import BASELINE_ORIGINAL_CONFIG, BEST_CONFIG_REFERENCE
from eval.search_quality import parse_search_results


# Real agent-style tasks: mix of concept, symbol, task, structural queries
TASKS = [
    # Concept query — what a Python agent might ask attocode
    {
        "repo": "attocode",
        "path": "/Users/eren/Documents/AI/first-principles-agent",
        "query": "how does the agent handle context overflow and auto compaction",
        "type": "concept",
        "expected_dir": "context/ or agent/ files involving compaction",
    },
    # Symbol query — looking for a specific concept
    {
        "repo": "attocode",
        "path": "/Users/eren/Documents/AI/first-principles-agent",
        "query": "budget pool allocation and enforcement",
        "type": "concept",
        "expected_dir": "budget/ module",
    },
    # Task query — how-to
    {
        "repo": "fastapi",
        "path": "/Users/eren/Documents/ai/benchmark-repos/fastapi",
        "query": "how to add custom middleware to a FastAPI app",
        "type": "task",
        "expected_dir": "middleware and application setup",
    },
    # Domain-terminology query that was Redis's strength
    {
        "repo": "redis",
        "path": "/Users/eren/Documents/ai/benchmark-repos/redis",
        "query": "how does redis handle memory eviction under pressure",
        "type": "domain",
        "expected_dir": "evict.c, memory management",
    },
    # Structural/architectural query
    {
        "repo": "attocode",
        "path": "/Users/eren/Documents/AI/first-principles-agent",
        "query": "MCP server tool registration and dispatch",
        "type": "structural",
        "expected_dir": "MCP integration files",
    },
]


def run_query(config: HarnessConfig, query: str, path: str, top_k: int = 10) -> list[tuple[str, str, float]]:
    """Run a query and return top-k (file, name, score) tuples."""
    svc = CodeIntelService(path)
    config.apply_to_service(svc)
    output = svc.semantic_search(query, top_k=top_k)
    # Parse output with score
    results: list[tuple[str, str, float]] = []
    lines = output.split("\n")
    for line in lines:
        line = line.strip()
        if not line or not line[0].isdigit():
            continue
        # Format: "1. [chunk_type] file/path.py — symbol_name (score: 0.750)"
        try:
            # Skip "1. " prefix
            _, rest = line.split(". ", 1)
            # Extract chunk type
            if "[" in rest and "]" in rest:
                type_start = rest.index("[") + 1
                type_end = rest.index("]")
                chunk_type = rest[type_start:type_end]
                rest = rest[type_end + 1:].strip()
            else:
                chunk_type = ""
            # Extract file and symbol
            if " — " in rest:
                file_part, rest = rest.split(" — ", 1)
            else:
                file_part = rest
                rest = ""
            # Extract score
            score = 0.0
            if "(score:" in rest:
                score_start = rest.rindex("(score:") + len("(score:")
                score_end = rest.rindex(")")
                try:
                    score = float(rest[score_start:score_end].strip())
                except ValueError:
                    pass
                rest = rest[:rest.rindex("(score:")].strip()
            symbol = rest.strip()
            results.append((file_part.strip(), f"{chunk_type}:{symbol}" if symbol else chunk_type, score))
        except Exception:
            continue
    return results[:top_k]


def main() -> None:
    before_cfg = HarnessConfig.load_yaml(BASELINE_ORIGINAL_CONFIG)
    after_cfg = HarnessConfig.load_yaml(BEST_CONFIG_REFERENCE)

    print("=" * 100)
    print("QUALITATIVE TASK COMPARISON: BEFORE vs AFTER")
    print("=" * 100)
    print()

    for i, task in enumerate(TASKS, 1):
        print(f"\n━━━ TASK {i}/{len(TASKS)}: [{task['type']}] {task['repo']} ━━━")
        print(f"Query: {task['query']}")
        print(f"Expected: {task['expected_dir']}")
        print()

        if not os.path.isdir(task["path"]):
            print(f"  SKIP: path not found ({task['path']})")
            continue

        # BEFORE (force kw-only to match original state)
        before_svc = CodeIntelService(task["path"])
        before_cfg.apply_to_service(before_svc)
        mgr = before_svc._get_semantic_search()
        mgr.nl_mode = "none"
        before_output = before_svc.semantic_search(task["query"], top_k=10)
        before_results = parse_search_results(before_output, max_results=10)

        # AFTER (default: vectors + adaptive fusion)
        after_svc = CodeIntelService(task["path"])
        after_cfg.apply_to_service(after_svc)
        after_output = after_svc.semantic_search(task["query"], top_k=10)
        after_results = parse_search_results(after_output, max_results=10)

        # Print side by side
        print(f"{'#':>2}  {'BEFORE (original defaults, no vectors)':<50} {'AFTER (optimized + adaptive fusion)':<50}")
        print(f"{'-' * 2}  {'-' * 50} {'-' * 50}")
        for rank in range(10):
            b = before_results[rank] if rank < len(before_results) else "(empty)"
            a = after_results[rank] if rank < len(after_results) else "(empty)"
            match = "✓" if b == a else " "
            # Truncate for display
            b_disp = b[:48] if len(b) > 48 else b
            a_disp = a[:48] if len(a) > 48 else a
            print(f"{rank+1:>2}{match} {b_disp:<50} {a_disp:<50}")

        # Compute overlap
        before_set = set(before_results[:5])
        after_set = set(after_results[:5])
        overlap = len(before_set & after_set)
        print()
        print(f"Top-5 overlap: {overlap}/5  |  Top-5 differs: {5 - overlap}/5")

    print()
    print("=" * 100)
    print("Legend: ✓ = same result, blank = different")
    print("Higher score at top = more confident.")
    print("=" * 100)


if __name__ == "__main__":
    main()
