"""Audit where source-labeled files land in broad-query lexical candidate pools.

This is a diagnostic, not a relevance benchmark: labels identify known relevant
files but do not exhaust every plausible answer. External repositories are
copied so their working trees and index caches are not changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

import yaml
from attocode_intel._internal.integrations.context.semantic_search import SemanticSearchManager

from eval.ranking_pair import REPO_PATHS, _copy_external
from eval.source_view_trial import source_view_candidates


def score_pool(files: list[str], gold: list[str]) -> dict:
    """Keep first-occurrence file ranks, matching small-page navigation."""
    distinct = list(dict.fromkeys(files))
    labeled = set(gold)
    ranks = {path: rank for rank, path in enumerate(distinct, 1) if path in labeled}
    return {
        "first_labeled_rank": min(ranks.values(), default=None),
        "labeled_ranks": ranks,
        "labeled_at_5": any(rank <= 5 for rank in ranks.values()),
        "labeled_at_8": any(rank <= 8 for rank in ranks.values()),
        "labeled_at_24": bool(ranks),
        "top_5": distinct[:5],
        "next_3": distinct[5:8],
        "candidate_files": distinct[:24],
    }


def score_source_view(query: str, pool: list, gold: list[str], intent: str = "") -> dict:
    """Compare the same five-slot page with an opt-in path-only source view."""
    baseline = [hit.file_path for hit in pool[:5]]
    started = time.perf_counter()
    selected = source_view_candidates(query, pool, 5)
    view_ms = (time.perf_counter() - started) * 1000
    source_files = [hit.file_path for hit in selected]
    labels = set(gold)
    return {
        "intent": intent or "source",
        "source_view": source_files,
        "source_view_labeled_at_5": bool(labels.intersection(source_files)),
        "source_view_labeled_count_5": len(labels.intersection(source_files)),
        "baseline_labeled_count_5": len(labels.intersection(baseline)),
        "source_view_unchanged": source_files == baseline,
        "source_view_ms": round(view_ms, 3),
    }


def summarize(reports: list[dict]) -> dict:
    cases = [case for repo in reports for case in repo["queries"]]
    times = sorted(case["search_ms"] for case in cases)
    source_cases = [case for case in cases if case["intent"] == "source"]
    test_cases = [case for case in cases if case["intent"] == "tests"]
    return {
        "queries": len(cases),
        "labeled_at_5": sum(case["labeled_at_5"] for case in cases),
        "labeled_at_8": sum(case["labeled_at_8"] for case in cases),
        "labeled_at_24": sum(case["labeled_at_24"] for case in cases),
        "missed_at_5_but_in_24": sum(
            not case["labeled_at_5"] and case["labeled_at_24"] for case in cases
        ),
        "missing_from_24": sum(not case["labeled_at_24"] for case in cases),
        "median_search_ms": round(statistics.median(times), 2) if times else None,
        "p95_search_ms": round(times[int(0.95 * (len(times) - 1))], 2) if times else None,
        "source_intent_queries": len(source_cases),
        "source_intent_baseline_labeled_at_5": sum(case["labeled_at_5"] for case in source_cases),
        "source_intent_view_labeled_at_5": sum(
            case["source_view_labeled_at_5"] for case in source_cases
        ),
        "source_intent_gains": sum(
            case["source_view_labeled_at_5"] and not case["labeled_at_5"]
            for case in source_cases
        ),
        "source_intent_losses": sum(
            case["labeled_at_5"] and not case["source_view_labeled_at_5"]
            for case in source_cases
        ),
        "test_intent_controls": len(test_cases),
        "test_intent_unchanged": sum(case["source_view_unchanged"] for case in test_cases),
    }


def evaluate(case_pack: Path, repos: list[str], timeout: float) -> dict:
    pack = yaml.safe_load(case_pack.read_text(encoding="utf-8"))["repos"]
    reports = []
    with tempfile.TemporaryDirectory(prefix="attocode-broad-candidate-audit-") as temp:
        for repo in repos:
            source = Path(REPO_PATHS[repo]).resolve()
            if not source.is_dir():
                raise FileNotFoundError(source)
            root = source if repo == "attocode" else Path(temp) / repo
            if repo != "attocode":
                _copy_external(source, root)
            cases = pack[repo]
            for case in cases:
                missing = [p for p in case["relevant_files"] if not (root / p).is_file()]
                if missing:
                    raise ValueError(f"{repo}: missing labeled files: {missing}")
            manager = SemanticSearchManager(str(root))
            try:
                # Cold-start work is explicitly excluded from per-query search latency.
                manager.search_candidates(cases[0]["query"], top_k=24)
                if not manager.wait_for_body_index(timeout=timeout):
                    raise TimeoutError(f"{repo}: source index did not become ready")
                index = manager.candidate_diagnostics()
                if index["status"] != "ready":
                    raise RuntimeError(f"{repo}: incomplete index: {index}")
                rows = []
                for case in cases:
                    started = time.perf_counter()
                    pool = manager.search_candidates(case["query"], top_k=24)
                    search_ms = (time.perf_counter() - started) * 1000
                    if manager.candidate_diagnostics()["status"] != "ready":
                        raise RuntimeError(f"{repo}: index changed during {case['query']!r}")
                    rows.append({
                        "query": case["query"],
                        "gold": case["relevant_files"],
                        "search_ms": round(search_ms, 2),
                        **score_pool([hit.file_path for hit in pool], case["relevant_files"]),
                        **score_source_view(
                            case["query"], pool, case["relevant_files"], case.get("intent", ""),
                        ),
                    })
                revision = subprocess.run(
                    ["git", "rev-parse", "HEAD"], cwd=source,
                    capture_output=True, text=True, check=False, timeout=3,
                )
                reports.append({
                    "repo": repo,
                    "source_revision": revision.stdout.strip() if revision.returncode == 0
                    else "unknown",
                    "index": index,
                    "queries": rows,
                })
            finally:
                manager.close()
    return {
        "case_pack": str(case_pack),
        "case_pack_sha256": hashlib.sha256(case_pack.read_bytes()).hexdigest(),
        "summary": summarize(reports),
        "repos": reports,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--case-pack", type=Path, required=True)
    parser.add_argument("--repos", nargs="+", choices=tuple(REPO_PATHS), required=True)
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(args.case_pack, args.repos, args.timeout)
    print(json.dumps(result["summary"]), flush=True)
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
