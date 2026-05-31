"""Search quality evaluation using ground-truth relevance judgments.

Runs semantic search queries against CodeIntelService and computes
MRR, NDCG, Precision@k, Recall@k against verified relevant files.

Usage:
    python -m eval.search_quality                    # all repos with ground truth
    python -m eval.search_quality --repo attocode    # single repo
    python -m eval.search_quality --report report.md # save markdown report
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))
sys.path.insert(0, PROJECT_ROOT)

from attocode.code_intel.service import CodeIntelService

from eval.metrics import (
    compute_mrr,
    compute_ndcg,
    compute_precision_at_k,
    compute_recall_at_k,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GROUND_TRUTH_DIR = os.path.join(PROJECT_ROOT, "eval", "ground_truth")

REPO_CONFIGS: dict[str, str] = {
    "attocode": PROJECT_ROOT,
    "gh-cli": "/Users/eren/Documents/ai/benchmark-repos/gh-cli",
    "redis": "/Users/eren/Documents/ai/benchmark-repos/redis",
    "fastapi": "/Users/eren/Documents/ai/benchmark-repos/fastapi",
    "pandas": "/Users/eren/Documents/ai/benchmark-repos/pandas",
}

TOP_K_RESULTS = 20  # Number of search results to collect
PRECISION_K = 10
RECALL_K = 20
MRR_K = 10
NDCG_K = 10


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class QueryResult:
    """Evaluation result for a single query."""

    query: str
    relevant_files: list[str]
    retrieved_files: list[str]
    mrr: float
    ndcg: float
    precision_at_k: float
    recall_at_k: float
    search_time_ms: float


@dataclass(slots=True)
class RepoResult:
    """Aggregate evaluation result for a repo."""

    repo: str
    query_results: list[QueryResult] = field(default_factory=list)
    avg_mrr: float = 0.0
    avg_ndcg: float = 0.0
    avg_precision: float = 0.0
    avg_recall: float = 0.0
    total_queries: int = 0
    total_time_ms: float = 0.0
    # Provenance / correctness (stamped when --reindex is used)
    model_name: str = ""
    body_budget: str = ""
    embedded_chunks: int = 0
    index_ready: bool = False
    error: str = ""

    def to_dict(self) -> dict:
        """Machine-readable summary (used by --json and the sweep comparison)."""
        return {
            "repo": self.repo,
            "total_queries": self.total_queries,
            "avg_mrr": round(self.avg_mrr, 4),
            "avg_ndcg": round(self.avg_ndcg, 4),
            "avg_precision": round(self.avg_precision, 4),
            "avg_recall": round(self.avg_recall, 4),
            "total_time_ms": round(self.total_time_ms, 1),
            "model_name": self.model_name,
            "body_budget": self.body_budget,
            "embedded_chunks": self.embedded_chunks,
            "index_ready": self.index_ready,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Search output parsing
# ---------------------------------------------------------------------------

# Matches lines like:
#   1. [class] types/budget.py — BudgetEnforcementMode (score: 1.000)
#   2. [method] economics.py — get_graduated_enforcement (score: 0.830)
#   3. [function] src/server.c — initServer (score: 0.750)
_RESULT_LINE_RE = re.compile(
    r"^\s*\d+\.\s+\[.*?\]\s+(.+?)\s+—",
    re.MULTILINE,
)


def parse_search_results(output: str, max_results: int = TOP_K_RESULTS) -> list[str]:
    """Extract file paths from semantic search output.

    Returns up to *max_results* file paths in ranked order, deduplicated
    (keeping first occurrence).
    """
    seen: set[str] = set()
    paths: list[str] = []

    for match in _RESULT_LINE_RE.finditer(output):
        raw_path = match.group(1).strip()
        if raw_path and raw_path not in seen:
            seen.add(raw_path)
            paths.append(raw_path)
            if len(paths) >= max_results:
                break

    return paths


# ---------------------------------------------------------------------------
# Grep baseline
# ---------------------------------------------------------------------------


def run_grep_search(repo_path: str, query: str, top_k: int = 20) -> list[str]:
    """Run grep-based search as baseline comparison."""
    terms = query.lower().split()
    pattern = "|".join(terms[:5])
    try:
        result = subprocess.run(
            ["rg", "-l", "-i", pattern],
            cwd=repo_path, capture_output=True, text=True, timeout=10,
        )
        files = result.stdout.strip().splitlines()[:top_k]
        return files
    except Exception:
        return []


@dataclass(slots=True)
class GrepQueryResult:
    """Grep baseline result for a single query."""

    query: str
    retrieved_files: list[str]
    mrr: float
    ndcg: float
    precision_at_k: float
    recall_at_k: float
    search_time_ms: float


@dataclass(slots=True)
class GrepRepoResult:
    """Aggregate grep baseline result for a repo."""

    repo: str
    query_results: list[GrepQueryResult] = field(default_factory=list)
    avg_mrr: float = 0.0
    avg_ndcg: float = 0.0
    avg_precision: float = 0.0
    avg_recall: float = 0.0


def evaluate_grep_baseline(repo: str) -> GrepRepoResult:
    """Run grep baseline evaluation for a single repo."""
    repo_path = REPO_CONFIGS[repo]
    queries = load_ground_truth(repo)
    if not queries:
        return GrepRepoResult(repo=repo)

    result = GrepRepoResult(repo=repo)

    for entry in queries:
        query_text: str = entry["query"]
        relevant: list[str] = entry["relevant_files"]
        relevant_set = set(relevant)

        t0 = time.perf_counter()
        retrieved = run_grep_search(repo_path, query_text, top_k=TOP_K_RESULTS)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        mrr = compute_mrr(retrieved, relevant_set, k=MRR_K)
        ndcg = compute_ndcg(retrieved, relevant_set, k=NDCG_K)
        precision = compute_precision_at_k(retrieved, relevant_set, k=PRECISION_K)
        recall = compute_recall_at_k(retrieved, relevant_set, k=RECALL_K)

        gqr = GrepQueryResult(
            query=query_text,
            retrieved_files=retrieved,
            mrr=mrr,
            ndcg=ndcg,
            precision_at_k=precision,
            recall_at_k=recall,
            search_time_ms=elapsed_ms,
        )
        result.query_results.append(gqr)

    n = len(result.query_results)
    if n > 0:
        result.avg_mrr = sum(q.mrr for q in result.query_results) / n
        result.avg_ndcg = sum(q.ndcg for q in result.query_results) / n
        result.avg_precision = sum(q.precision_at_k for q in result.query_results) / n
        result.avg_recall = sum(q.recall_at_k for q in result.query_results) / n

    return result


# ---------------------------------------------------------------------------
# Ground-truth loading
# ---------------------------------------------------------------------------


def load_ground_truth(repo: str) -> list[dict] | None:
    """Load ground-truth queries for *repo* from YAML.

    Returns a list of dicts with 'query' and 'relevant_files' keys,
    or None if no ground-truth file exists.
    """
    yaml_path = os.path.join(GROUND_TRUTH_DIR, f"{repo}.yaml")
    if not os.path.isfile(yaml_path):
        return None

    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    return data.get("queries", [])


def discover_repos_with_ground_truth() -> list[str]:
    """Return repo names that have both a ground-truth YAML and a repo path."""
    repos: list[str] = []
    for yaml_file in sorted(Path(GROUND_TRUTH_DIR).glob("*.yaml")):
        repo_name = yaml_file.stem
        if repo_name in REPO_CONFIGS and os.path.isdir(REPO_CONFIGS[repo_name]):
            repos.append(repo_name)
    return repos


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def evaluate_repo(repo: str, reindex: bool = False) -> RepoResult:
    """Run search quality evaluation for a single repo.

    When ``reindex`` is True, force a full index rebuild (AST + embeddings)
    before scoring so the eval reflects the current chunking/embedder config
    rather than a stale or absent index. This is the synchronous build the
    query path does not perform on its own.
    """
    repo_path = REPO_CONFIGS[repo]
    queries = load_ground_truth(repo)
    if not queries:
        return RepoResult(repo=repo)

    result = RepoResult(repo=repo, total_queries=len(queries))
    result.body_budget = os.environ.get("ATTOCODE_BODY_TOKEN_BUDGET", "")

    svc = CodeIntelService(repo_path)
    if reindex:
        print(f"[{repo}] REINDEX_START force=True embeddings=True", file=sys.stderr)
        rstats = svc.reindex(force=True, embeddings=True)
        result.embedded_chunks = int(rstats.get("embedded_chunks", 0))
        print(f"[{repo}] REINDEX_DONE {rstats}", file=sys.stderr)

    # Provenance: which model actually served, and is the vector index live.
    try:
        mgr = svc._get_semantic_search()
        result.model_name = mgr.provider_name
        result.index_ready = bool(mgr.is_index_ready())
    except Exception as exc:  # noqa: BLE001
        result.model_name = f"unknown:{type(exc).__name__}"

    # Correctness guard: a --reindex run that embedded zero chunks would score
    # keyword-only (garbage for measuring vector changes). Fail loud, skip it.
    if reindex and result.embedded_chunks == 0:
        result.error = "no_embeddings_built"
        print(
            f"[{repo}] GUARD_FAIL: embeddings=True but 0 chunks embedded — "
            f"skipping (would measure keyword-only, not vectors)",
            file=sys.stderr,
        )
        return result

    for qi, entry in enumerate(queries, 1):
        query_text: str = entry["query"]
        relevant: list[str] = entry["relevant_files"]
        relevant_set = set(relevant)

        # Run semantic search
        t0 = time.perf_counter()
        raw_output = svc.semantic_search(query_text)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        print(
            f"[{repo}] QUERY {qi}/{len(queries)} {elapsed_ms:.0f}ms", file=sys.stderr,
        )

        retrieved = parse_search_results(raw_output, max_results=TOP_K_RESULTS)

        # Compute metrics
        mrr = compute_mrr(retrieved, relevant_set, k=MRR_K)
        ndcg = compute_ndcg(retrieved, relevant_set, k=NDCG_K)
        precision = compute_precision_at_k(retrieved, relevant_set, k=PRECISION_K)
        recall = compute_recall_at_k(retrieved, relevant_set, k=RECALL_K)

        qr = QueryResult(
            query=query_text,
            relevant_files=relevant,
            retrieved_files=retrieved,
            mrr=mrr,
            ndcg=ndcg,
            precision_at_k=precision,
            recall_at_k=recall,
            search_time_ms=elapsed_ms,
        )
        result.query_results.append(qr)
        result.total_time_ms += elapsed_ms

    # Aggregate
    n = len(result.query_results)
    if n > 0:
        result.avg_mrr = sum(q.mrr for q in result.query_results) / n
        result.avg_ndcg = sum(q.ndcg for q in result.query_results) / n
        result.avg_precision = sum(q.precision_at_k for q in result.query_results) / n
        result.avg_recall = sum(q.recall_at_k for q in result.query_results) / n

    print(
        f"[{repo}] REPO_DONE MRR={result.avg_mrr:.3f} NDCG={result.avg_ndcg:.3f} "
        f"model={result.model_name} budget={result.body_budget or '-'} "
        f"vec_ready={result.index_ready} chunks={result.embedded_chunks}",
        file=sys.stderr,
    )
    return result


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def format_text_report(results: list[RepoResult]) -> str:
    """Format results as a human-readable text report."""
    lines = [
        "=" * 70,
        "SEARCH QUALITY EVALUATION REPORT",
        "=" * 70,
        "",
    ]

    for repo_result in results:
        lines.append(f"Repository: {repo_result.repo}")
        lines.append(f"  Queries evaluated: {repo_result.total_queries}")
        lines.append(f"  Total search time: {repo_result.total_time_ms:.0f}ms")
        lines.append("")
        lines.append(f"  Aggregate Metrics:")
        lines.append(f"    MRR@{MRR_K}:          {repo_result.avg_mrr:.3f}")
        lines.append(f"    NDCG@{NDCG_K}:         {repo_result.avg_ndcg:.3f}")
        lines.append(f"    Precision@{PRECISION_K}:    {repo_result.avg_precision:.3f}")
        lines.append(f"    Recall@{RECALL_K}:       {repo_result.avg_recall:.3f}")
        lines.append("")

        # Per-query breakdown
        lines.append("  Per-Query Breakdown:")
        lines.append(
            f"    {'Query':<50} {'MRR':>6} {'NDCG':>6} {'P@10':>6} {'R@20':>6} {'ms':>8}"
        )
        lines.append(f"    {'-' * 50} {'-' * 6} {'-' * 6} {'-' * 6} {'-' * 6} {'-' * 8}")

        for qr in repo_result.query_results:
            q_short = qr.query[:48] + ".." if len(qr.query) > 50 else qr.query
            lines.append(
                f"    {q_short:<50} {qr.mrr:>6.3f} {qr.ndcg:>6.3f} "
                f"{qr.precision_at_k:>6.3f} {qr.recall_at_k:>6.3f} "
                f"{qr.search_time_ms:>8.0f}"
            )

        lines.append("")
        lines.append("-" * 70)
        lines.append("")

    # Summary table
    if len(results) > 1:
        lines.append("SUMMARY")
        lines.append(
            f"  {'Repo':<15} {'MRR':>6} {'NDCG':>6} {'P@10':>6} {'R@20':>6} {'Queries':>8} {'Time(ms)':>10}"
        )
        lines.append(
            f"  {'-' * 15} {'-' * 6} {'-' * 6} {'-' * 6} {'-' * 6} {'-' * 8} {'-' * 10}"
        )
        for rr in results:
            lines.append(
                f"  {rr.repo:<15} {rr.avg_mrr:>6.3f} {rr.avg_ndcg:>6.3f} "
                f"{rr.avg_precision:>6.3f} {rr.avg_recall:>6.3f} "
                f"{rr.total_queries:>8} {rr.total_time_ms:>10.0f}"
            )

        # Grand average
        total_queries = sum(rr.total_queries for rr in results)
        if total_queries > 0:
            grand_mrr = sum(rr.avg_mrr * rr.total_queries for rr in results) / total_queries
            grand_ndcg = sum(rr.avg_ndcg * rr.total_queries for rr in results) / total_queries
            grand_prec = sum(rr.avg_precision * rr.total_queries for rr in results) / total_queries
            grand_rec = sum(rr.avg_recall * rr.total_queries for rr in results) / total_queries
            total_time = sum(rr.total_time_ms for rr in results)

            lines.append(
                f"  {'-' * 15} {'-' * 6} {'-' * 6} {'-' * 6} {'-' * 6} {'-' * 8} {'-' * 10}"
            )
            lines.append(
                f"  {'OVERALL':<15} {grand_mrr:>6.3f} {grand_ndcg:>6.3f} "
                f"{grand_prec:>6.3f} {grand_rec:>6.3f} "
                f"{total_queries:>8} {total_time:>10.0f}"
            )

        lines.append("")

    lines.append("=" * 70)
    return "\n".join(lines)


def format_markdown_report(results: list[RepoResult]) -> str:
    """Format results as a Markdown report."""
    lines = [
        "# Search Quality Evaluation Report",
        "",
        f"_Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}_",
        "",
    ]
    # Provenance stamp: which model/budget produced these numbers, so a report
    # is never ambiguous about what was actually measured.
    _models = sorted({rr.model_name for rr in results if rr.model_name})
    _budgets = sorted({rr.body_budget for rr in results if rr.body_budget})
    if _models or _budgets:
        lines.append(
            f"_Model(s): {', '.join(_models) or 'n/a'}  |  "
            f"Body budget: {', '.join(_budgets) or 'n/a'}_"
        )
        lines.append("")
    _errored = [rr.repo for rr in results if rr.error]
    if _errored:
        lines.append(f"> ⚠️ Repos with errors (excluded/invalid): {', '.join(_errored)}")
        lines.append("")

    # Summary table
    lines.extend([
        "## Summary",
        "",
        "| Repo | Queries | MRR@10 | NDCG@10 | P@10 | R@20 | Time (ms) |",
        "|------|---------|--------|---------|------|------|-----------|",
    ])

    for rr in results:
        lines.append(
            f"| {rr.repo} | {rr.total_queries} | {rr.avg_mrr:.3f} | "
            f"{rr.avg_ndcg:.3f} | {rr.avg_precision:.3f} | "
            f"{rr.avg_recall:.3f} | {rr.total_time_ms:.0f} |"
        )

    # Grand average
    total_queries = sum(rr.total_queries for rr in results)
    if total_queries > 0 and len(results) > 1:
        grand_mrr = sum(rr.avg_mrr * rr.total_queries for rr in results) / total_queries
        grand_ndcg = sum(rr.avg_ndcg * rr.total_queries for rr in results) / total_queries
        grand_prec = sum(rr.avg_precision * rr.total_queries for rr in results) / total_queries
        grand_rec = sum(rr.avg_recall * rr.total_queries for rr in results) / total_queries
        total_time = sum(rr.total_time_ms for rr in results)

        lines.append(
            f"| **Overall** | {total_queries} | {grand_mrr:.3f} | "
            f"{grand_ndcg:.3f} | {grand_prec:.3f} | "
            f"{grand_rec:.3f} | {total_time:.0f} |"
        )

    lines.append("")

    # Per-repo details
    for rr in results:
        lines.extend([
            f"## {rr.repo}",
            "",
            f"| Query | MRR | NDCG | P@10 | R@20 | Time |",
            f"|-------|-----|------|------|------|------|",
        ])

        for qr in rr.query_results:
            q_escaped = qr.query.replace("|", "\\|")
            lines.append(
                f"| {q_escaped} | {qr.mrr:.3f} | {qr.ndcg:.3f} | "
                f"{qr.precision_at_k:.3f} | {qr.recall_at_k:.3f} | "
                f"{qr.search_time_ms:.0f}ms |"
            )

        lines.append("")

        # Show retrieved vs relevant for low-scoring queries
        low_scorers = [qr for qr in rr.query_results if qr.mrr < 0.5]
        if low_scorers:
            lines.append("<details>")
            lines.append(f"<summary>Low-MRR queries ({len(low_scorers)})</summary>")
            lines.append("")

            for qr in low_scorers:
                lines.append(f"**Query:** {qr.query}")
                lines.append("")
                lines.append("Expected:")
                for f in qr.relevant_files:
                    found = "found" if f in qr.retrieved_files else "missed"
                    lines.append(f"- `{f}` ({found})")
                lines.append("")
                lines.append("Retrieved (top 10):")
                for i, f in enumerate(qr.retrieved_files[:10], 1):
                    relevant_mark = "**relevant**" if f in set(qr.relevant_files) else ""
                    lines.append(f"- {i}. `{f}` {relevant_mark}")
                lines.append("")

            lines.append("</details>")
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Baseline comparison reports
# ---------------------------------------------------------------------------


def format_baseline_comparison(
    ci_results: list[RepoResult], grep_results: list[GrepRepoResult]
) -> str:
    """Format a side-by-side text comparison of code-intel vs grep baseline."""
    lines = [
        "=" * 70,
        "BASELINE COMPARISON: Code-Intel vs Grep",
        "=" * 70,
        "",
        f"  {'Repo':<15} {'CI MRR':>8} {'Grep MRR':>9} {'Delta':>7}  |  "
        f"{'CI NDCG':>8} {'Grep NDCG':>10} {'Delta':>7}",
        f"  {'-' * 15} {'-' * 8} {'-' * 9} {'-' * 7}  |  "
        f"{'-' * 8} {'-' * 10} {'-' * 7}",
    ]

    for ci, grep in zip(ci_results, grep_results):
        mrr_delta = ci.avg_mrr - grep.avg_mrr
        ndcg_delta = ci.avg_ndcg - grep.avg_ndcg
        lines.append(
            f"  {ci.repo:<15} {ci.avg_mrr:>8.3f} {grep.avg_mrr:>9.3f} {mrr_delta:>+7.3f}  |  "
            f"{ci.avg_ndcg:>8.3f} {grep.avg_ndcg:>10.3f} {ndcg_delta:>+7.3f}"
        )

    # Grand averages
    total_ci_queries = sum(rr.total_queries for rr in ci_results)
    if total_ci_queries > 0 and len(ci_results) > 1:
        grand_ci_mrr = sum(rr.avg_mrr * rr.total_queries for rr in ci_results) / total_ci_queries
        grand_ci_ndcg = sum(rr.avg_ndcg * rr.total_queries for rr in ci_results) / total_ci_queries

        n_grep = sum(len(gr.query_results) for gr in grep_results)
        if n_grep > 0:
            grand_grep_mrr = sum(
                gr.avg_mrr * len(gr.query_results) for gr in grep_results
            ) / n_grep
            grand_grep_ndcg = sum(
                gr.avg_ndcg * len(gr.query_results) for gr in grep_results
            ) / n_grep
        else:
            grand_grep_mrr = grand_grep_ndcg = 0.0

        mrr_delta = grand_ci_mrr - grand_grep_mrr
        ndcg_delta = grand_ci_ndcg - grand_grep_ndcg

        lines.append(
            f"  {'-' * 15} {'-' * 8} {'-' * 9} {'-' * 7}  |  "
            f"{'-' * 8} {'-' * 10} {'-' * 7}"
        )
        lines.append(
            f"  {'OVERALL':<15} {grand_ci_mrr:>8.3f} {grand_grep_mrr:>9.3f} {mrr_delta:>+7.3f}  |  "
            f"{grand_ci_ndcg:>8.3f} {grand_grep_ndcg:>10.3f} {ndcg_delta:>+7.3f}"
        )

    lines.extend(["", "=" * 70])
    return "\n".join(lines)


def format_baseline_comparison_markdown(
    ci_results: list[RepoResult], grep_results: list[GrepRepoResult]
) -> str:
    """Format a Markdown side-by-side comparison of code-intel vs grep baseline."""
    lines = [
        "## Baseline Comparison: Code-Intel vs Grep",
        "",
        "| Repo | CI MRR | Grep MRR | MRR Delta | CI NDCG | Grep NDCG | NDCG Delta |",
        "|------|--------|----------|-----------|---------|-----------|------------|",
    ]

    for ci, grep in zip(ci_results, grep_results):
        mrr_delta = ci.avg_mrr - grep.avg_mrr
        ndcg_delta = ci.avg_ndcg - grep.avg_ndcg
        lines.append(
            f"| {ci.repo} | {ci.avg_mrr:.3f} | {grep.avg_mrr:.3f} | {mrr_delta:+.3f} | "
            f"{ci.avg_ndcg:.3f} | {grep.avg_ndcg:.3f} | {ndcg_delta:+.3f} |"
        )

    total_ci_queries = sum(rr.total_queries for rr in ci_results)
    if total_ci_queries > 0 and len(ci_results) > 1:
        grand_ci_mrr = sum(rr.avg_mrr * rr.total_queries for rr in ci_results) / total_ci_queries
        grand_ci_ndcg = sum(rr.avg_ndcg * rr.total_queries for rr in ci_results) / total_ci_queries

        n_grep = sum(len(gr.query_results) for gr in grep_results)
        if n_grep > 0:
            grand_grep_mrr = sum(
                gr.avg_mrr * len(gr.query_results) for gr in grep_results
            ) / n_grep
            grand_grep_ndcg = sum(
                gr.avg_ndcg * len(gr.query_results) for gr in grep_results
            ) / n_grep
        else:
            grand_grep_mrr = grand_grep_ndcg = 0.0

        mrr_delta = grand_ci_mrr - grand_grep_mrr
        ndcg_delta = grand_ci_ndcg - grand_grep_ndcg
        lines.append(
            f"| **Overall** | {grand_ci_mrr:.3f} | {grand_grep_mrr:.3f} | {mrr_delta:+.3f} | "
            f"{grand_ci_ndcg:.3f} | {grand_grep_ndcg:.3f} | {ndcg_delta:+.3f} |"
        )

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def format_sweep_comparison(runs: list[dict]) -> str:
    """Render a budget-vs-metrics comparison table from sweep run summaries.

    Each entry in ``runs`` is a dict with keys ``label`` (e.g. the body budget)
    and ``overall`` (a dict with ``avg_mrr``/``avg_ndcg``/``total_queries``).
    Pure function — no I/O — so it is unit-testable and reused by the driver.
    """
    lines = [
        "# Sweep Comparison",
        "",
        "| Config | Queries | MRR@10 | NDCG@10 |",
        "|--------|---------|--------|---------|",
    ]
    best_mrr = max((r["overall"].get("avg_mrr", 0.0) for r in runs), default=0.0)
    for r in runs:
        ov = r["overall"]
        mrr = ov.get("avg_mrr", 0.0)
        star = " ⭐" if runs and mrr == best_mrr and mrr > 0 else ""
        lines.append(
            f"| {r['label']} | {ov.get('total_queries', 0)} | "
            f"{mrr:.3f}{star} | {ov.get('avg_ndcg', 0.0):.3f} |"
        )
    return "\n".join(lines)


def _overall_from_results(results: list[RepoResult]) -> dict:
    """Query-weighted overall metrics across repos (skips errored repos)."""
    ok = [rr for rr in results if not rr.error and rr.total_queries > 0]
    tq = sum(rr.total_queries for rr in ok)
    if tq == 0:
        return {"avg_mrr": 0.0, "avg_ndcg": 0.0, "total_queries": 0}
    return {
        "avg_mrr": sum(rr.avg_mrr * rr.total_queries for rr in ok) / tq,
        "avg_ndcg": sum(rr.avg_ndcg * rr.total_queries for rr in ok) / tq,
        "total_queries": tq,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate search quality against ground-truth relevance judgments"
    )
    parser.add_argument(
        "--repo",
        type=str,
        default=None,
        help="Evaluate a single repo (default: all repos with ground truth)",
    )
    parser.add_argument(
        "--report",
        type=str,
        default=None,
        help="Save Markdown report to this path",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-query retrieved files",
    )
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="Also run grep-based baseline and show side-by-side comparison",
    )
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="Force a full reindex (AST + embeddings) of each repo before "
        "scoring. Required to measure index changes (chunking/embedder); "
        "respects ATTOCODE_EMBEDDING_MODEL and ATTOCODE_BODY_TOKEN_BUDGET. "
        "Default off preserves prior behavior (scores the existing index).",
    )
    parser.add_argument(
        "--json",
        type=str,
        default=None,
        help="Write machine-readable per-repo results (incl. provenance) to "
        "this JSON path. Diffable and salvageable if a run partially completes.",
    )
    args = parser.parse_args()

    # Determine repos to evaluate
    if args.repo:
        if args.repo not in REPO_CONFIGS:
            print(f"Error: unknown repo '{args.repo}'. Available: {', '.join(REPO_CONFIGS)}")
            sys.exit(1)
        if not os.path.isdir(REPO_CONFIGS[args.repo]):
            print(f"Error: repo path not found: {REPO_CONFIGS[args.repo]}")
            sys.exit(1)
        repos = [args.repo]
    else:
        repos = discover_repos_with_ground_truth()
        if not repos:
            print("No repos with ground-truth data found.")
            sys.exit(1)

    print(f"Evaluating search quality for: {', '.join(repos)}")
    print()

    # Run evaluations
    all_results: list[RepoResult] = []
    all_grep_results: list[GrepRepoResult] = []
    for repo in repos:
        print(f"  Evaluating {repo}...")
        try:
            result = evaluate_repo(repo, reindex=args.reindex)
        except Exception as exc:  # noqa: BLE001 — one repo failing must not kill the sweep
            import traceback
            traceback.print_exc()
            print(f"    ERROR evaluating {repo}: {type(exc).__name__}: {exc}")
            err = RepoResult(repo=repo)
            err.error = f"{type(exc).__name__}: {exc}"
            all_results.append(err)
            continue

        if result.total_queries == 0:
            print(f"    No ground-truth queries found, skipping.")
            continue

        if result.error:
            print(f"    SKIPPED ({result.error}).")
            all_results.append(result)
            continue

        all_results.append(result)
        print(
            f"    {result.total_queries} queries | "
            f"MRR={result.avg_mrr:.3f} NDCG={result.avg_ndcg:.3f} "
            f"P@{PRECISION_K}={result.avg_precision:.3f} R@{RECALL_K}={result.avg_recall:.3f} "
            f"| {result.total_time_ms:.0f}ms"
        )

        # Run grep baseline if requested
        if args.baseline:
            grep_result = evaluate_grep_baseline(repo)
            all_grep_results.append(grep_result)
            mrr_delta = result.avg_mrr - grep_result.avg_mrr
            ndcg_delta = result.avg_ndcg - grep_result.avg_ndcg
            print(
                f"    Code-Intel MRR={result.avg_mrr:.3f} vs Grep MRR={grep_result.avg_mrr:.3f} "
                f"(delta={mrr_delta:+.3f})"
            )
            print(
                f"    Code-Intel NDCG={result.avg_ndcg:.3f} vs Grep NDCG={grep_result.avg_ndcg:.3f} "
                f"(delta={ndcg_delta:+.3f})"
            )

        if args.verbose:
            for i, qr in enumerate(result.query_results):
                print(f"      Q: {qr.query}")
                print(f"        Retrieved: {qr.retrieved_files[:5]}")
                print(f"        Relevant:  {qr.relevant_files}")
                print(
                    f"        MRR={qr.mrr:.3f} NDCG={qr.ndcg:.3f} "
                    f"P@{PRECISION_K}={qr.precision_at_k:.3f} R@{RECALL_K}={qr.recall_at_k:.3f}"
                )
                if args.baseline and i < len(all_grep_results[-1].query_results):
                    gqr = all_grep_results[-1].query_results[i]
                    print(
                        f"        Grep: MRR={gqr.mrr:.3f} NDCG={gqr.ndcg:.3f} "
                        f"P@{PRECISION_K}={gqr.precision_at_k:.3f} R@{RECALL_K}={gqr.recall_at_k:.3f}"
                    )
                    print(f"        Grep Retrieved: {gqr.retrieved_files[:5]}")

    if not all_results:
        print("\nNo results to report.")
        sys.exit(1)

    # Print text report
    print()
    print(format_text_report(all_results))

    # Print baseline comparison report if requested
    if args.baseline and all_grep_results:
        print()
        print(format_baseline_comparison(all_results, all_grep_results))

    # Save markdown report if requested
    if args.report:
        md_report = format_markdown_report(all_results)
        if args.baseline and all_grep_results:
            md_report += "\n\n" + format_baseline_comparison_markdown(all_results, all_grep_results)
        with open(args.report, "w") as f:
            f.write(md_report)
        print(f"\nMarkdown report saved to: {args.report}")

    # Save machine-readable results if requested
    if args.json:
        import json
        payload = {
            "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "body_budget": os.environ.get("ATTOCODE_BODY_TOKEN_BUDGET", ""),
            "embedding_model_env": os.environ.get("ATTOCODE_EMBEDDING_MODEL", ""),
            "overall": _overall_from_results(all_results),
            "repos": [rr.to_dict() for rr in all_results],
        }
        with open(args.json, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"JSON results saved to: {args.json}")


if __name__ == "__main__":
    main()
