"""Retrieval quality of four arms on the search ground truth.

Arms: our semantic search; the same with a Jev rerank of its top candidate files;
jevgrep (``jg``), which asks Jev about every directory, file and chunk; and ranked grep.
Eval only; nothing here is product code.

    uv run python -m eval.jev_retrieval --repos fastapi express --limit 2 --json out.json --report out.md
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from eval.metrics import (  # noqa: E402
    compute_mrr,
    compute_ndcg,
    compute_precision_at_k,
    compute_recall_at_k,
)
from eval.search_quality import GROUND_TRUTH_DIR, REPO_CONFIGS, run_grep_search  # noqa: E402

REPOS = {**REPO_CONFIGS, "express": "/Users/eren/Documents/ai/benchmark-repos/express"}
JG = os.path.expanduser("~/attocode-studies/tools/node_modules/.bin/jg")
CANDIDATES, KEEP, CHUNKS = 40, 20, 80
JG_LINE = re.compile(r'^- "(.+)" — ')
QUESTION = ("Does this file provide implementation, caller, or test evidence that a developer "
            "would need to investigate the query?")
CRITERIA = {
    "true": "The file holds code or tests that the query is about, or code that calls or configures it.",
    "false": "The file only shares words with the query, or it is about a different behavior.",
}
ARMS = ("semantic", "semantic+jev", "jevgrep", "grep")


def queries(repo: str) -> list[dict]:
    """Hand-written and git-derived queries for one repo."""
    rows = []
    for name in (f"{repo}.yaml", f"{repo}_git.yaml"):
        path = Path(GROUND_TRUTH_DIR) / name
        if path.is_file():
            for q in yaml.safe_load(path.read_text()).get("queries") or []:
                rows.append({"query": q["query"], "relevant": set(q["relevant_files"]), "source": name})
    return rows


def relative(path: str, root: str) -> str:
    return os.path.relpath(path, root) if os.path.isabs(path) else path.removeprefix("./")


def semantic_candidates(svc, query: str, root: str) -> list[tuple[str, str]]:
    """Unique files in rank order, each with the text of its best chunk."""
    seen: dict[str, str] = {}
    for row in svc.semantic_search_data(query, top_k=CHUNKS)["results"]:
        seen.setdefault(relative(row["file_path"], root), row.get("snippet") or "")
    return list(seen.items())[:CANDIDATES]


def jev_rerank(query: str, candidates: list[tuple[str, str]], root: str, ask=None) -> tuple[list[str], int, int]:
    """Order candidates by Jev's p(relevant); keep the original rank on ties and failures."""
    if ask is None:
        from attocode_intel.confidence.jev import _decide, _load_env, backend
        from attocode_intel.confidence.redact import redact
        _load_env()
        chosen = backend()
        questions = {"p": {"type": "noul", "instructions": QUESTION, "criteria": CRITERIA}}

        def ask(rank: int, path: str, text: str) -> float | None:
            if not text:
                try:
                    text = (Path(root) / path).read_text(errors="replace")
                except OSError:
                    text = ""
            state = {"query": query, "file": redact(path), "code": redact(text)[:3000]}
            try:
                row = _decide("attocode_search_rerank", state, questions,
                              "yes" if rank < KEEP else "no", chosen)
                value = ((row.get("answers") or {}).get("p") or {}).get("noul")
            except Exception:
                return None
            ok = isinstance(value, int | float) and not isinstance(value, bool)
            return float(value) if ok and math.isfinite(value) and 0 <= value <= 1 else None

    with ThreadPoolExecutor(max_workers=16) as pool:
        probs = list(pool.map(lambda item: ask(item[0], *item[1]), enumerate(candidates)))
    failed = sum(p is None for p in probs)
    # A failed answer counts as 0.5, so the file stays near its semantic rank.
    order = sorted(range(len(candidates)), key=lambda i: (-(0.5 if probs[i] is None else probs[i]), i))
    return [candidates[i][0] for i in order][:KEEP], len(candidates), failed


def parse_jg(stdout: str) -> list[str]:
    return [m.group(1) for line in stdout.splitlines() if (m := JG_LINE.match(line))]


def run_jevgrep(query: str, root: str) -> tuple[list[str], dict]:
    proc = subprocess.run([JG, query, root], capture_output=True, text=True, timeout=1800)
    return [relative(p, root) for p in parse_jg(proc.stdout)], {"exit_code": proc.returncode, "stderr_tail": proc.stderr[-400:]}


def score(ranked: list[str], relevant: set[str]) -> dict[str, float]:
    return {"mrr@10": compute_mrr(ranked, relevant, 10), "ndcg@10": compute_ndcg(ranked, relevant, 10),
            "p@10": compute_precision_at_k(ranked, relevant, 10), "r@20": compute_recall_at_k(ranked, relevant, 20)}


def evaluate(repo: str, arms: tuple[str, ...], limit: int | None, reindex: bool) -> list[dict]:
    from attocode_intel.service import CodeIntelService
    root = REPOS[repo]
    svc = CodeIntelService(root)
    if reindex:
        svc.reindex(force=True, embeddings=True)
    rows = []
    for q in queries(repo)[:limit]:
        row = {"repo": repo, "query": q["query"], "source": q["source"], "relevant": sorted(q["relevant"]), "arms": {}}
        start = time.monotonic()
        candidates = semantic_candidates(svc, q["query"], root)
        base = time.monotonic() - start
        if "semantic" in arms:
            ranked = [path for path, _ in candidates][:KEEP]
            row["arms"]["semantic"] = {"ranked": ranked, "seconds": base, "jev_calls": 0, **score(ranked, q["relevant"])}
        if "semantic+jev" in arms:
            start = time.monotonic()
            ranked, calls, failed = jev_rerank(q["query"], candidates, root)
            row["arms"]["semantic+jev"] = {"ranked": ranked, "seconds": base + time.monotonic() - start,
                                           "jev_calls": calls, "jev_failed": failed, **score(ranked, q["relevant"])}
        if "jevgrep" in arms:
            start = time.monotonic()
            ranked, info = run_jevgrep(q["query"], root)
            row["arms"]["jevgrep"] = {"ranked": ranked, "seconds": time.monotonic() - start,
                                      "jev_calls": None, **info, **score(ranked, q["relevant"])}
        if "grep" in arms:
            start = time.monotonic()
            ranked = [relative(p, root) for p in run_grep_search(root, q["query"], top_k=KEEP)]
            row["arms"]["grep"] = {"ranked": ranked, "seconds": time.monotonic() - start, "jev_calls": 0,
                                   **score(ranked, q["relevant"])}
        rows.append(row)
        print(json.dumps({"repo": repo, "query": q["query"][:60],
                          **{a: round(v["mrr@10"], 3) for a, v in row["arms"].items()}}), flush=True)
    return rows


def report(rows: list[dict]) -> str:
    lines = ["| Scope | Arm | Queries | MRR@10 | NDCG@10 | P@10 | R@20 | Median s | Jev calls/query | Wins/losses vs semantic (MRR@10) |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for scope in [*sorted({r["repo"] for r in rows}), "pooled"]:
        subset = [r for r in rows if scope in ("pooled", r["repo"])]
        for arm in ARMS:
            got = [r["arms"][arm] for r in subset if arm in r["arms"]]
            if not got:
                continue
            mean = {k: statistics.mean(g[k] for g in got) for k in ("mrr@10", "ndcg@10", "p@10", "r@20")}
            calls = [g["jev_calls"] for g in got if g["jev_calls"] is not None]
            pairs = [(r["arms"][arm]["mrr@10"], r["arms"]["semantic"]["mrr@10"]) for r in subset
                     if arm in r["arms"] and "semantic" in r["arms"]]
            wl = "-" if arm == "semantic" or not pairs else f"{sum(a > b for a, b in pairs)}/{sum(a < b for a, b in pairs)}"
            per_query = f"{statistics.mean(calls):.0f}" if calls else "not reported"
            lines.append(f"| {scope} | {arm} | {len(got)} | {mean['mrr@10']:.3f} | {mean['ndcg@10']:.3f} | "
                         f"{mean['p@10']:.3f} | {mean['r@20']:.3f} | {statistics.median(g['seconds'] for g in got):.1f} | "
                         f"{per_query} | {wl} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repos", nargs="+", default=["fastapi", "express"])
    parser.add_argument("--arms", nargs="+", choices=ARMS, default=list(ARMS))
    parser.add_argument("--limit", type=int, help="Queries per repo, for a dry run")
    parser.add_argument("--reindex", action="store_true", help="Rebuild the AST and embedding index first")
    parser.add_argument("--json", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    rows = [row for repo in args.repos for row in evaluate(repo, tuple(args.arms), args.limit, args.reindex)]
    table = report(rows)
    print(table)
    if args.json:
        args.json.write_text(json.dumps(rows, indent=2, default=sorted))
    if args.report:
        args.report.write_text(table)


if __name__ == "__main__":
    main()
