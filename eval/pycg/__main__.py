"""PyCG call graph evaluation adapter.

Evaluates CodeIntelService dependency tracing accuracy against
PyCG's verified Python call graph ground truth.

PyCG provides 112 micro-benchmark modules across 16 categories with
manually verified callgraph.json files. Precision >98%, recall ~70%.

Source: https://github.com/vitsalis/PyCG
Benchmark: https://github.com/vitsalis/pycg-evaluation

Usage:
    python -m eval.pycg setup          # clone PyCG benchmark repo
    python -m eval.pycg run            # run evaluation
    python -m eval.pycg run --limit 20 # run on first 20 modules
    python -m eval.pycg report         # generate comparison report
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

PYCG_REPO = "https://github.com/vitsalis/PyCG.git"
PYCG_EVAL_REPO = "https://github.com/vitsalis/pycg-evaluation.git"
CACHE_DIR = Path.home() / ".cache" / "attocode" / "pycg"
MICRO_BENCH_DIR = CACHE_DIR / "pycg-evaluation" / "micro-benchmark"


def cmd_setup(args: argparse.Namespace) -> None:
    """Clone PyCG benchmark repositories."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    eval_dir = CACHE_DIR / "pycg-evaluation"
    if eval_dir.exists():
        print(f"PyCG evaluation repo already at {eval_dir}")
    else:
        print(f"Cloning PyCG evaluation repo...")
        subprocess.run(
            ["git", "clone", "--depth", "1", PYCG_EVAL_REPO, str(eval_dir)],
            check=True,
        )
        print(f"Cloned to {eval_dir}")

    # Count available benchmarks
    if MICRO_BENCH_DIR.exists():
        categories = [d for d in MICRO_BENCH_DIR.iterdir() if d.is_dir()]
        total = sum(
            1 for cat in categories
            for mod in cat.iterdir()
            if mod.is_dir() and (mod / "callgraph.json").exists()
        )
        print(f"Found {total} micro-benchmarks across {len(categories)} categories")


def discover_benchmarks(limit: int | None = None) -> list[dict]:
    """Discover available micro-benchmark modules with ground truth."""
    if not MICRO_BENCH_DIR.exists():
        print(f"PyCG benchmarks not found. Run: python -m eval.pycg setup")
        return []

    benchmarks = []
    for category_dir in sorted(MICRO_BENCH_DIR.iterdir()):
        if not category_dir.is_dir():
            continue
        category = category_dir.name
        for module_dir in sorted(category_dir.iterdir()):
            if not module_dir.is_dir():
                continue
            callgraph_file = module_dir / "callgraph.json"
            if not callgraph_file.exists():
                continue

            # Load ground truth
            with open(callgraph_file) as f:
                callgraph = json.load(f)

            # Find Python source files
            py_files = list(module_dir.glob("*.py"))

            benchmarks.append({
                "category": category,
                "module": module_dir.name,
                "path": str(module_dir),
                "callgraph": callgraph,
                "py_files": [str(f) for f in py_files],
                "edge_count": sum(len(targets) for targets in callgraph.values()),
            })

            if limit and len(benchmarks) >= limit:
                return benchmarks

    return benchmarks


def _bare(name: str) -> str:
    """Last segment of a dotted qualified name."""
    return name.rsplit(".", 1)[-1] if name else name


def evaluate_module(benchmark: dict) -> dict:
    """Evaluate attocode's call-graph against a PyCG benchmark module.

    Compares bare caller→callee pairs (last segment of the dotted name)
    so external module prefixes don't penalize us when our extractor
    only knows the function name. Ground truth and prediction share a
    matching keyspace before precision/recall is computed.
    """
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
        from attocode.code_intel.service import CodeIntelService
    except ImportError:
        return {"error": "Cannot import CodeIntelService", **benchmark}

    module_path = benchmark["path"]
    ground_truth = benchmark["callgraph"]

    # Ground-truth edges as bare (caller, callee) pairs.
    gt_edges_set: set[tuple[str, str]] = set()
    for caller, callees in ground_truth.items():
        for callee in callees:
            gt_edges_set.add((_bare(caller), _bare(callee)))

    if not gt_edges_set:
        return {
            "category": benchmark["category"],
            "module": benchmark["module"],
            "gt_edges": 0, "our_edges": 0, "true_positives": 0,
            "precision": 0.0, "recall": 0.0, "f1": 0.0,
        }

    try:
        svc = CodeIntelService(module_path)
        # Force a reindex so ASTService picks up references for the corpus.
        svc.reindex()

        # Pull the call-edge map straight from the in-memory CrossRefIndex —
        # avoids parsing the human-readable `call_graph` output.
        ast_svc = svc._get_ast_service()
        index = ast_svc._index
        our_edges_set: set[tuple[str, str]] = set()
        for caller, callees in index.call_edges.items():
            cb = _bare(caller)
            for callee in callees:
                our_edges_set.add((cb, _bare(callee)))

        true_positives = gt_edges_set & our_edges_set
        precision = len(true_positives) / len(our_edges_set) if our_edges_set else 0.0
        recall = len(true_positives) / len(gt_edges_set) if gt_edges_set else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0 else 0.0
        )

        return {
            "category": benchmark["category"],
            "module": benchmark["module"],
            "gt_edges": len(gt_edges_set),
            "our_edges": len(our_edges_set),
            "true_positives": len(true_positives),
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
        }
    except Exception as e:
        return {
            "category": benchmark["category"],
            "module": benchmark["module"],
            "error": str(e),
        }


def cmd_run(args: argparse.Namespace) -> None:
    """Run call graph evaluation."""
    benchmarks = discover_benchmarks(limit=args.limit)
    if not benchmarks:
        return

    print(f"Evaluating {len(benchmarks)} PyCG micro-benchmarks...")
    print()

    results = []
    for i, bench in enumerate(benchmarks):
        print(f"  [{i+1}/{len(benchmarks)}] {bench['category']}/{bench['module']} ({bench['edge_count']} edges)...", end=" ", flush=True)
        result = evaluate_module(bench)
        results.append(result)

        if "error" in result:
            print(f"ERROR: {result['error'][:60]}")
        else:
            print(f"P={result['precision']:.2f} R={result['recall']:.2f} F1={result['f1']:.2f}")

    # Summary
    valid = [r for r in results if "error" not in r]
    if valid:
        avg_p = sum(r["precision"] for r in valid) / len(valid)
        avg_r = sum(r["recall"] for r in valid) / len(valid)
        avg_f1 = sum(r["f1"] for r in valid) / len(valid)
        print(f"\nSummary ({len(valid)}/{len(results)} evaluated):")
        print(f"  Avg Precision: {avg_p:.3f}")
        print(f"  Avg Recall:    {avg_r:.3f}")
        print(f"  Avg F1:        {avg_f1:.3f}")

    # Save results
    output = Path(args.output) if args.output else Path("eval/pycg/results.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        json.dump({"benchmarks": results, "summary": {
            "total": len(results),
            "evaluated": len(valid),
            "avg_precision": round(avg_p, 3) if valid else 0,
            "avg_recall": round(avg_r, 3) if valid else 0,
            "avg_f1": round(avg_f1, 3) if valid else 0,
        }}, f, indent=2)
    print(f"\nResults saved to {output}")


def cmd_report(args: argparse.Namespace) -> None:
    """Generate comparison report from saved results."""
    results_path = Path("eval/pycg/results.json")
    if not results_path.exists():
        print("No results found. Run: python -m eval.pycg run")
        return

    with open(results_path) as f:
        data = json.load(f)

    summary = data["summary"]
    benchmarks = data["benchmarks"]

    print("# PyCG Call Graph Evaluation Report")
    print()
    print(f"**Modules evaluated**: {summary['evaluated']}/{summary['total']}")
    print(f"**Avg Precision**: {summary['avg_precision']:.3f}")
    print(f"**Avg Recall**: {summary['avg_recall']:.3f}")
    print(f"**Avg F1**: {summary['avg_f1']:.3f}")
    print()

    # Per-category breakdown
    categories: dict[str, list] = {}
    for b in benchmarks:
        if "error" not in b:
            categories.setdefault(b["category"], []).append(b)

    print("| Category | Modules | Avg Precision | Avg Recall | Avg F1 |")
    print("|----------|---------|---------------|------------|--------|")
    for cat, mods in sorted(categories.items()):
        p = sum(m["precision"] for m in mods) / len(mods)
        r = sum(m["recall"] for m in mods) / len(mods)
        f = sum(m["f1"] for m in mods) / len(mods)
        print(f"| {cat} | {len(mods)} | {p:.3f} | {r:.3f} | {f:.3f} |")


def main() -> None:
    parser = argparse.ArgumentParser(description="PyCG call graph evaluation")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("setup", help="Clone PyCG benchmark repos")

    run_p = sub.add_parser("run", help="Run evaluation")
    run_p.add_argument("--limit", type=int, default=None, help="Max modules to evaluate")
    run_p.add_argument("--output", default="", help="Output JSON path")

    sub.add_parser("report", help="Generate report from results")

    args = parser.parse_args()
    if args.command == "setup":
        cmd_setup(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "report":
        cmd_report(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
