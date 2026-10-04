"""Paired, model-free lexical ranking comparison on source-labeled queries.

The baseline is the search_candidates order before the broad-query reranker.
Both arms use the same warmed lexical index, candidate pool, and query order.
External repositories are copied into a temporary workspace so their caches and
working trees are never changed.

Usage:
    PYTHONPATH=packages/code-intel/src .venv/bin/python -m eval.ranking_pair \
        --repos attocode fastapi --json /private/tmp/ranking-pair.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import yaml
from attocode_intel._internal.integrations.context import semantic_search
from attocode_intel._internal.integrations.context.semantic_search import SemanticSearchManager
from attocode_intel.focused_evidence import terms
from attocode_intel.query_ranking import query_concepts

from eval.metrics import compute_mrr, compute_ndcg, compute_recall_at_k
from eval.search_quality import GROUND_TRUTH_DIR, REPO_CONFIGS

_BENCHMARK_ROOT = Path(REPO_CONFIGS["fastapi"]).parent
REPO_PATHS = {
    **REPO_CONFIGS,
    **{name: str(_BENCHMARK_ROOT / name) for name in (
        "express", "requests", "vapor", "phoenix", "ripgrep",
        "faker", "starship", "spdlog", "protobuf", "prisma",
    )},
}


def _prior_order(_query, candidates, top_k, _file_filter=""):
    return candidates[:top_k]


def _unique_files(results, limit=20):
    return list(dict.fromkeys(row.file_path for row in results))[:limit]


def _score(files, gold):
    relevant = set(gold)
    return {
        "mrr5": compute_mrr(files, relevant, 5),
        "ndcg5": compute_ndcg(files, relevant, 5),
        "recall5": compute_recall_at_k(files, relevant, 5),
        "mrr10": compute_mrr(files, relevant, 10),
        "ndcg10": compute_ndcg(files, relevant, 10),
        "recall20": compute_recall_at_k(files, relevant, 20),
        "unique_returned": len(files),
    }


def _short_query(query: str) -> str:
    """Derive a two-concept proxy without reading relevance labels or results."""
    concepts = set(query_concepts(query))
    words = re.findall(r"[A-Za-z][A-Za-z0-9]*", re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", query))
    selected = []
    for word in words:
        for term in terms(word):
            if term in concepts and term not in selected:
                selected.append(term)
        if len(selected) >= 2:
            break
    return " ".join(selected[:2])


def _copy_external(source: Path, destination: Path) -> None:
    shutil.copytree(
        source, destination, symlinks=True,
        ignore=shutil.ignore_patterns(
            ".git", ".attocode", ".venv", "node_modules", "__pycache__",
            ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
        ),
    )


def evaluate_repo(repo: str, *, scratch: Path, timeout: float,
                  short_variant: bool = False, cases: list[dict] | None = None,
                  top_k: int = 80, treatment: str = "experimental") -> dict:
    source = Path(REPO_PATHS[repo]).resolve()
    if not source.is_dir():
        raise FileNotFoundError(source)
    root = source
    if repo != "attocode":
        root = scratch / repo
        _copy_external(source, root)

    if cases is None:
        manifest = Path(GROUND_TRUTH_DIR) / f"{repo}.yaml"
        queries = yaml.safe_load(manifest.read_text())["queries"]
    else:
        queries = cases
    for case in queries:
        missing = [path for path in case["relevant_files"] if not (root / path).is_file()]
        if missing:
            raise ValueError(f"Missing labeled files in {repo}: {missing}")

    manager = SemanticSearchManager(str(root))
    # Avoid an unrelated dependency/frecency boost changing the candidate pool
    # between arms. It is disabled equally, not just for the treatment.
    manager.scoring_config.importance_weight = 0
    manager.scoring_config.frecency_weight = 0
    manager.search_candidates(queries[0]["query"], top_k=top_k)
    if not manager.wait_for_body_index(timeout=timeout):
        raise TimeoutError(f"{repo}: source-body index did not become ready")
    index = manager.candidate_diagnostics()
    if index.get("status") != "ready":
        raise RuntimeError(f"{repo}: incomplete lexical index: {index}")

    rows = []
    for case in queries:
        original, gold = case["query"], case["relevant_files"]
        query = _short_query(original) if short_variant else original
        for _attempt in range(3):
            arms = {}
            for arm in ("prior", "current"):
                started = time.perf_counter()
                if arm == "prior":
                    with patch.dict(os.environ, {"ATTOCODE_INTEL_BROAD_RERANK": "1"}), \
                         patch.object(semantic_search, "rerank_broad_candidates", _prior_order):
                        found = manager.search_candidates(query, top_k=top_k)
                else:
                    flag = "1" if treatment == "experimental" else "0"
                    with patch.dict(os.environ, {"ATTOCODE_INTEL_BROAD_RERANK": flag}):
                        found = manager.search_candidates(query, top_k=top_k)
                elapsed = (time.perf_counter() - started) * 1000
                if manager.candidate_diagnostics().get("status") != "ready":
                    break  # Discard both arms; incomplete retrieval is not a zero-hit score.
                files = _unique_files(found)
                arms[arm] = {**_score(files, gold), "files": files, "ms": round(elapsed, 1)}
            if len(arms) == 2:
                break
            if not manager.wait_for_body_index(timeout=timeout):
                raise TimeoutError(f"{repo}: index did not recover during {query!r}")
        else:
            raise RuntimeError(f"{repo}: index repeatedly invalidated during {query!r}")
        rows.append({"query": query, "original_query": original, "gold": gold, "arms": arms})

    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=source, capture_output=True,
        text=True, check=False, timeout=3,
    )
    manager.close()
    return {
        "repo": repo,
        "source": str(source),
        "source_revision": revision.stdout.strip() if revision.returncode == 0 else "unknown",
        "index": index,
        "queries": rows,
    }


def summary(repos: list[dict]) -> dict:
    pairs = [case for repo in repos for case in repo["queries"]]
    result = {"count": len(pairs), "metrics": {}}
    for metric in ("mrr5", "ndcg5", "recall5", "mrr10", "ndcg10", "recall20",
                   "unique_returned"):
        before = [row["arms"]["prior"][metric] for row in pairs]
        after = [row["arms"]["current"][metric] for row in pairs]
        deltas = [b - a for a, b in zip(before, after, strict=True)]
        result["metrics"][metric] = {
            "prior": round(statistics.mean(before), 4),
            "current": round(statistics.mean(after), 4),
            "delta": round(statistics.mean(deltas), 4),
            "wins": sum(delta > 1e-9 for delta in deltas),
            "losses": sum(delta < -1e-9 for delta in deltas),
            "ties": sum(abs(delta) <= 1e-9 for delta in deltas),
        }
    for arm in ("prior", "current"):
        result[f"median_{arm}_ms"] = round(statistics.median(
            row["arms"][arm]["ms"] for row in pairs
        ), 1)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repos", nargs="+", choices=tuple(REPO_PATHS), required=True)
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument("--short-variant", action="store_true",
                        help="Use the first two query concepts as a systematic broad-query proxy")
    parser.add_argument("--case-pack", type=Path,
                        help="YAML with repos: {name: [{query, relevant_files}]} judgments")
    parser.add_argument("--top-k", type=int, default=80,
                        help="Chunk result count, 5 for a typical navigation page")
    parser.add_argument("--treatment", choices=("experimental", "default"),
                        default="experimental")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    case_pack = None
    if args.case_pack:
        case_pack = yaml.safe_load(args.case_pack.read_text())["repos"]
        for repo in args.repos:
            if not case_pack.get(repo):
                raise ValueError(f"No judgments for {repo} in {args.case_pack}")
    with tempfile.TemporaryDirectory(prefix="attocode-ranking-pair-") as temp:
        reports = []
        for repo in args.repos:
            result = evaluate_repo(repo, scratch=Path(temp), timeout=args.timeout,
                                   short_variant=args.short_variant,
                                   cases=case_pack[repo] if case_pack else None,
                                   top_k=args.top_k, treatment=args.treatment)
            reports.append(result)
            print(json.dumps({"repo": repo, "summary": summary([result])}), flush=True)
    output = {"comparison": "pre-broad-query-order vs current",
              "treatment": args.treatment, "top_k_chunks": args.top_k,
              "variant": "first_two_concepts" if args.short_variant else "original",
              "case_pack_sha256": hashlib.sha256(args.case_pack.read_bytes()).hexdigest()
              if args.case_pack else None,
              "repos": reports,
              "summary": summary(reports)}
    print(json.dumps({"pooled": output["summary"]}), flush=True)
    if args.json:
        args.json.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
