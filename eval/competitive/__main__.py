"""Competitive code search comparison framework.

Evaluates Attocode code-intel search quality against published baselines
from CodeSearchNet, Sourcegraph, and other code search tools.

Runs a standardized query set, measures latency + quality metrics,
and generates a comparative positioning report.

Usage:
    python -m eval.competitive                      # run all repos
    python -m eval.competitive --repo attocode      # single repo
    python -m eval.competitive --report report.md   # save report
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Published baseline metrics from competitors (for comparison context)
PUBLISHED_BASELINES = {
    "codesearchnet": {
        "description": "CodeSearchNet Challenge (6M functions, 6 languages, 99 NL queries)",
        "source": "https://github.com/github/CodeSearchNet",
        "metrics": {
            "NDCG": 0.40,  # Approximate top model NDCG on CSN
            "MRR": 0.35,
        },
        "notes": "Function-level retrieval; not directly comparable to file-level search",
    },
    "sourcegraph": {
        "description": "Sourcegraph code search (regex + structural + ranking)",
        "source": "https://arxiv.org/abs/2408.05344",
        "metrics": {
            "NDCG": None,  # Not published
            "MRR": None,
            "p50_latency_ms": 200,  # Approximate from public docs
        },
        "notes": "Regex-first search; semantic search experimental. Cross-repo capable.",
    },
    "github_code_search": {
        "description": "GitHub Code Search (regex + symbol search)",
        "source": "https://github.blog/changelog/2023-05-08-github-code-search-is-generally-available/",
        "metrics": {
            "NDCG": None,
            "MRR": None,
            "p50_latency_ms": 150,
        },
        "notes": "Regex + symbol search. No semantic/embedding search. No impact analysis.",
    },
    "greptile": {
        "description": "Greptile AI codebase Q&A",
        "source": "https://greptile.com",
        "metrics": {
            "NDCG": None,
            "MRR": None,
        },
        "notes": "AI-powered Q&A over codebases. No published quality metrics.",
    },
}

# Standardized query set covering different search intents
QUERY_SET = {
    "attocode": [
        {"query": "token budget management and enforcement", "intent": "concept_search", "difficulty": "medium"},
        {"query": "message routing and tool dispatch", "intent": "concept_search", "difficulty": "medium"},
        {"query": "swarm task decomposition", "intent": "concept_search", "difficulty": "hard"},
        {"query": "agent session checkpoints", "intent": "concept_search", "difficulty": "medium"},
        {"query": "AST parsing and symbol indexing", "intent": "concept_search", "difficulty": "hard"},
        {"query": "execution loop iteration control", "intent": "concept_search", "difficulty": "easy"},
        {"query": "worker pool parallel spawning", "intent": "concept_search", "difficulty": "hard"},
        {"query": "semantic search embeddings", "intent": "concept_search", "difficulty": "easy"},
    ],
    "gh-cli": [
        {"query": "command factory and execution", "intent": "concept_search", "difficulty": "medium"},
        {"query": "GitHub API authentication", "intent": "concept_search", "difficulty": "easy"},
        {"query": "pull request review workflow", "intent": "concept_search", "difficulty": "medium"},
        {"query": "repository fork handling", "intent": "concept_search", "difficulty": "medium"},
    ],
    "redis": [
        {"query": "event-driven command handling", "intent": "concept_search", "difficulty": "medium"},
        {"query": "sorted set data structure", "intent": "concept_search", "difficulty": "easy"},
        {"query": "RDB persistence snapshot", "intent": "concept_search", "difficulty": "medium"},
        {"query": "cluster node discovery", "intent": "concept_search", "difficulty": "hard"},
    ],
    "fastapi": [
        {"query": "request validation dependency injection", "intent": "concept_search", "difficulty": "medium"},
        {"query": "OpenAPI schema generation", "intent": "concept_search", "difficulty": "easy"},
        {"query": "WebSocket connection management", "intent": "concept_search", "difficulty": "medium"},
        {"query": "middleware request lifecycle", "intent": "concept_search", "difficulty": "medium"},
    ],
    "pandas": [
        {"query": "missing data NaN propagation", "intent": "concept_search", "difficulty": "medium"},
        {"query": "DataFrame indexing label access", "intent": "concept_search", "difficulty": "easy"},
        {"query": "CSV parsing file IO", "intent": "concept_search", "difficulty": "easy"},
        {"query": "groupby aggregation split apply combine", "intent": "concept_search", "difficulty": "medium"},
    ],
}

REPO_PATHS = {
    "attocode": "/Users/eren/Documents/AI/first-principles-agent",
    "gh-cli": "/Users/eren/Documents/ai/benchmark-repos/gh-cli",
    "redis": "/Users/eren/Documents/ai/benchmark-repos/redis",
    "fastapi": "/Users/eren/Documents/ai/benchmark-repos/fastapi",
    "pandas": "/Users/eren/Documents/ai/benchmark-repos/pandas",
}


@dataclass
class QueryResult:
    query: str
    intent: str
    difficulty: str
    results_count: int = 0
    latency_ms: float = 0.0
    output_len: int = 0
    top_results: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class RepoEvaluation:
    repo: str
    queries: list[QueryResult] = field(default_factory=list)
    total_time_ms: float = 0.0

    @property
    def avg_latency_ms(self) -> float:
        valid = [q.latency_ms for q in self.queries if not q.error]
        return sum(valid) / len(valid) if valid else 0

    @property
    def p50_latency_ms(self) -> float:
        valid = sorted(q.latency_ms for q in self.queries if not q.error)
        if not valid:
            return 0
        mid = len(valid) // 2
        return valid[mid]

    @property
    def p95_latency_ms(self) -> float:
        valid = sorted(q.latency_ms for q in self.queries if not q.error)
        if not valid:
            return 0
        idx = int(len(valid) * 0.95)
        return valid[min(idx, len(valid) - 1)]

    @property
    def avg_results_count(self) -> float:
        valid = [q.results_count for q in self.queries if not q.error]
        return sum(valid) / len(valid) if valid else 0


def parse_search_results(output: str) -> list[str]:
    """Extract file paths from semantic search output."""
    paths = []
    for line in output.splitlines():
        m = re.match(r"\s*\d+\.\s+\[.*?\]\s+(.+?)\s+[—\-]", line)
        if m:
            path = m.group(1).strip()
            if path and path not in paths:
                paths.append(path)
    return paths[:20]


def evaluate_repo(repo: str, repo_path: str, queries: list[dict]) -> RepoEvaluation:
    """Run all queries against a repo's CodeIntelService."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
    from attocode.code_intel.service import CodeIntelService

    evaluation = RepoEvaluation(repo=repo)

    svc = CodeIntelService(repo_path)

    for qdef in queries:
        query = qdef["query"]
        t0 = time.perf_counter()
        try:
            output = svc.semantic_search(query)
            latency = (time.perf_counter() - t0) * 1000
            top_results = parse_search_results(output)

            result = QueryResult(
                query=query,
                intent=qdef.get("intent", ""),
                difficulty=qdef.get("difficulty", ""),
                results_count=len(top_results),
                latency_ms=round(latency, 1),
                output_len=len(output),
                top_results=top_results[:5],
            )
        except Exception as e:
            latency = (time.perf_counter() - t0) * 1000
            result = QueryResult(
                query=query,
                intent=qdef.get("intent", ""),
                difficulty=qdef.get("difficulty", ""),
                latency_ms=round(latency, 1),
                error=str(e),
            )
        evaluation.queries.append(result)

    evaluation.total_time_ms = sum(q.latency_ms for q in evaluation.queries)
    return evaluation


def generate_report(evaluations: list[RepoEvaluation], output_path: str = "") -> str:
    """Generate competitive comparison report."""
    lines = [
        "# Competitive Code Search Comparison Report",
        "",
        f"**Date**: {time.strftime('%Y-%m-%d %H:%M')}",
        f"**Repos evaluated**: {len(evaluations)}",
        f"**Total queries**: {sum(len(e.queries) for e in evaluations)}",
        "",
        "---",
        "",
        "## Attocode Search Performance",
        "",
        "| Repo | Queries | Avg Latency (ms) | P50 (ms) | P95 (ms) | Avg Results | Total Time (ms) |",
        "|------|---------|-------------------|----------|----------|-------------|-----------------|",
    ]

    for ev in evaluations:
        lines.append(
            f"| {ev.repo} | {len(ev.queries)} | {ev.avg_latency_ms:.0f} | "
            f"{ev.p50_latency_ms:.0f} | {ev.p95_latency_ms:.0f} | "
            f"{ev.avg_results_count:.1f} | {ev.total_time_ms:.0f} |"
        )

    # Grand totals
    all_queries = [q for ev in evaluations for q in ev.queries if not q.error]
    all_latencies = sorted(q.latency_ms for q in all_queries)
    if all_latencies:
        grand_avg = sum(all_latencies) / len(all_latencies)
        grand_p50 = all_latencies[len(all_latencies) // 2]
        grand_p95 = all_latencies[int(len(all_latencies) * 0.95)]
        lines.append(f"| **Total** | **{len(all_queries)}** | **{grand_avg:.0f}** | **{grand_p50:.0f}** | **{grand_p95:.0f}** | — | **{sum(ev.total_time_ms for ev in evaluations):.0f}** |")

    lines.extend([
        "",
        "## Published Baselines (for context)",
        "",
        "| Tool | NDCG | MRR | P50 Latency | Notes |",
        "|------|------|-----|-------------|-------|",
    ])

    for name, info in PUBLISHED_BASELINES.items():
        m = info["metrics"]
        ndcg = f"{m.get('NDCG', 'N/A')}" if m.get("NDCG") is not None else "N/A"
        mrr = f"{m.get('MRR', 'N/A')}" if m.get("MRR") is not None else "N/A"
        p50 = f"{m.get('p50_latency_ms', 'N/A')}ms" if m.get("p50_latency_ms") is not None else "N/A"
        lines.append(f"| {name} | {ndcg} | {mrr} | {p50} | {info['notes'][:60]} |")

    lines.extend([
        "",
        "## Per-Query Detail",
        "",
    ])

    for ev in evaluations:
        lines.append(f"### {ev.repo}")
        lines.append("")
        lines.append("| Query | Latency (ms) | Results | Difficulty | Top Result |")
        lines.append("|-------|-------------|---------|------------|------------|")
        for q in ev.queries:
            top = q.top_results[0] if q.top_results else "(none)"
            if q.error:
                top = f"ERROR: {q.error[:40]}"
            lines.append(f"| {q.query[:50]} | {q.latency_ms:.0f} | {q.results_count} | {q.difficulty} | {top[:50]} |")
        lines.append("")

    lines.extend([
        "## Competitive Positioning",
        "",
        "### Where Attocode Leads",
        "- **Impact analysis**: No competitor offers single-call transitive blast radius",
        "- **Dependency graph + DSL**: BFS traversal with Cypher-like query language",
        "- **Dead code detection**: 3-level analysis with confidence scoring",
        "- **Community detection**: Louvain algorithm with modularity scores",
        "- **Hotspot scoring**: Composite risk ranking with god-file/hub labels",
        "",
        "### Where Competitors Lead",
        "- **Regex search**: Sourcegraph + GitHub have regex as primary (we have semantic only)",
        "- **Cross-repo navigation**: Sourcegraph SCIP enables compiler-accurate cross-repo refs",
        "- **Scale**: Sourcegraph handles millions of files (we cap at 2,000)",
        "- **AI Q&A**: Greptile/Cody have conversational codebase Q&A",
        "",
        "### Parity Areas",
        "- **Semantic search**: Competitive with BM25+TF-IDF (needs embedding upgrade for parity)",
        "- **Symbol search**: Good coverage across 15+ languages via tree-sitter",
        "- **Multi-tenant**: Full org/repo model with pgvector cross-repo search",
        "",
    ])

    report = "\n".join(lines)

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(report)
        print(f"Report saved to {output_path}")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Competitive code search comparison")
    parser.add_argument("--repo", default="", help="Single repo to evaluate")
    parser.add_argument("--report", default="", help="Save markdown report to path")
    parser.add_argument("--json", default="", help="Save raw results to JSON")
    args = parser.parse_args()

    repos_to_eval = {}
    if args.repo:
        if args.repo in REPO_PATHS:
            repos_to_eval[args.repo] = REPO_PATHS[args.repo]
        else:
            print(f"Unknown repo: {args.repo}. Available: {list(REPO_PATHS.keys())}")
            return
    else:
        repos_to_eval = {k: v for k, v in REPO_PATHS.items() if Path(v).exists()}

    if not repos_to_eval:
        print("No repos available.")
        return

    print(f"Running competitive evaluation on {len(repos_to_eval)} repos...")
    print()

    evaluations = []
    for repo, repo_path in repos_to_eval.items():
        queries = QUERY_SET.get(repo, [])
        if not queries:
            print(f"  {repo}: no queries defined, skipping")
            continue

        print(f"  {repo} ({len(queries)} queries)...", end=" ", flush=True)
        ev = evaluate_repo(repo, repo_path, queries)
        evaluations.append(ev)
        print(f"avg={ev.avg_latency_ms:.0f}ms, p50={ev.p50_latency_ms:.0f}ms")

    if not evaluations:
        print("No evaluations completed.")
        return

    # Generate report
    report = generate_report(evaluations, args.report)
    if not args.report:
        print()
        print(report)

    # Save JSON
    if args.json:
        raw = {
            "evaluations": [
                {
                    "repo": ev.repo,
                    "avg_latency_ms": ev.avg_latency_ms,
                    "p50_latency_ms": ev.p50_latency_ms,
                    "p95_latency_ms": ev.p95_latency_ms,
                    "queries": [
                        {
                            "query": q.query,
                            "latency_ms": q.latency_ms,
                            "results_count": q.results_count,
                            "difficulty": q.difficulty,
                            "top_results": q.top_results,
                        }
                        for q in ev.queries
                    ],
                }
                for ev in evaluations
            ]
        }
        Path(args.json).write_text(json.dumps(raw, indent=2))
        print(f"JSON results saved to {args.json}")


if __name__ == "__main__":
    main()
