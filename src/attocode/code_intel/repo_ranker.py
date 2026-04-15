"""Graph-ranked repo map using PageRank.

Ranks files and symbols by their connectivity in the
dependency graph, weighted by task relevance. Produces
a token-budgeted summary of the most important code.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RankedEntry:
    """A ranked file or symbol in the repo map."""
    path: str
    score: float
    symbols: list[str] = field(default_factory=list)
    line_count: int = 0
    category: str = ""  # "core", "util", "test", etc.


@dataclass(slots=True)
class RepoMapResult:
    """Result of repo map ranking."""
    entries: list[RankedEntry]
    total_files: int
    token_budget: int
    tokens_used: int
    truncated: bool = False


def pagerank(
    adjacency: dict[str, list[str]],
    *,
    damping: float = 0.85,
    iterations: int = 30,
    tolerance: float = 1e-6,
) -> dict[str, float]:
    """Compute PageRank scores for nodes in a directed graph.

    Args:
        adjacency: Maps each node to its outgoing edges (dependencies).
        damping: Damping factor (probability of following a link).
        iterations: Maximum iterations.
        tolerance: Convergence threshold.

    Returns:
        Dict mapping node -> PageRank score.
    """
    nodes = set(adjacency.keys())
    for targets in adjacency.values():
        nodes.update(targets)

    if not nodes:
        return {}

    n = len(nodes)
    node_list = sorted(nodes)
    node_idx = {node: i for i, node in enumerate(node_list)}

    # Build reverse adjacency (who points to me?)
    in_links: dict[int, list[int]] = {i: [] for i in range(n)}
    out_degree: dict[int, int] = {i: 0 for i in range(n)}

    for source, targets in adjacency.items():
        src_idx = node_idx[source]
        valid_targets = [t for t in targets if t in node_idx]
        out_degree[src_idx] = len(valid_targets)
        for target in valid_targets:
            in_links[node_idx[target]].append(src_idx)

    # Initialize uniform
    scores = [1.0 / n] * n
    base = (1.0 - damping) / n

    # Identify dangling nodes (no outgoing edges)
    dangling = [i for i in range(n) if out_degree[i] == 0]

    for _ in range(iterations):
        # Redistribute dangling node rank uniformly
        dangling_sum = sum(scores[i] for i in dangling)
        new_scores = [0.0] * n
        for i in range(n):
            rank_sum = sum(
                scores[j] / out_degree[j]
                for j in in_links[i]
                if out_degree[j] > 0
            )
            new_scores[i] = base + damping * (rank_sum + dangling_sum / n)

        # Check convergence
        diff = sum(abs(new_scores[i] - scores[i]) for i in range(n))
        scores = new_scores
        if diff < tolerance:
            break

    return {node_list[i]: scores[i] for i in range(n)}


def _task_relevance(path: str, task_keywords: list[str]) -> float:
    """Compute task relevance score for a file path."""
    if not task_keywords:
        return 1.0
    path_lower = path.lower()
    matches = sum(1 for kw in task_keywords if kw.lower() in path_lower)
    if matches == 0:
        return 0.1
    return min(1.0, 0.3 + 0.7 * (matches / len(task_keywords)))


def _estimate_entry_tokens(entry: RankedEntry) -> int:
    """Estimate tokens for a ranked entry in the output."""
    # path + symbols list
    tokens = len(entry.path.split("/")) + 2
    tokens += sum(len(s.split()) + 1 for s in entry.symbols)
    return max(tokens, 3)


def _categorize_path(path: str) -> str:
    """Categorize a file path."""
    parts = path.lower().split("/")
    if any(p in ("test", "tests", "spec", "specs") for p in parts):
        return "test"
    if any(p in ("util", "utils", "helpers", "lib") for p in parts):
        return "util"
    if any(p in ("core", "engine", "kernel") for p in parts):
        return "core"
    if any(p in ("api", "routes", "handlers", "views") for p in parts):
        return "api"
    if any(p in ("config", "settings", "conf") for p in parts):
        return "config"
    return "module"


def rank_repo_files(
    adjacency: dict[str, list[str]],
    *,
    task_context: str = "",
    token_budget: int = 1024,
    symbols_by_file: dict[str, list[str]] | None = None,
    line_counts: dict[str, int] | None = None,
    exclude_tests: bool = True,
) -> RepoMapResult:
    """Rank repository files by graph importance and task relevance.

    Combines PageRank connectivity score with task-context keyword
    relevance to produce a token-budgeted list of the most important
    files and their key symbols.

    Args:
        adjacency: File dependency graph (file -> [imported files]).
        task_context: Description of the current task for relevance scoring.
        token_budget: Maximum tokens for the output.
        symbols_by_file: Optional mapping of file -> symbol names.
        line_counts: Optional mapping of file -> line count.
        exclude_tests: Whether to exclude test files from ranking.

    Returns:
        RepoMapResult with ranked entries within token budget.
    """
    symbols_by_file = symbols_by_file or {}
    line_counts = line_counts or {}

    # Compute PageRank
    pr_scores = pagerank(adjacency)

    # Extract task keywords
    task_keywords = [w for w in task_context.split() if len(w) > 2] if task_context else []

    # Score each file
    scored: list[tuple[str, float]] = []
    for path, pr_score in pr_scores.items():
        if exclude_tests and _categorize_path(path) == "test":
            continue
        relevance = _task_relevance(path, task_keywords)
        combined = pr_score * relevance
        scored.append((path, combined))

    # Sort by combined score descending
    scored.sort(key=lambda x: x[1], reverse=True)

    # Build entries within token budget
    entries: list[RankedEntry] = []
    tokens_used = 0
    truncated = False

    for path, score in scored:
        entry = RankedEntry(
            path=path,
            score=score,
            symbols=symbols_by_file.get(path, [])[:10],  # Cap symbols per file
            line_count=line_counts.get(path, 0),
            category=_categorize_path(path),
        )
        entry_tokens = _estimate_entry_tokens(entry)
        if tokens_used + entry_tokens > token_budget:
            truncated = True
            break
        entries.append(entry)
        tokens_used += entry_tokens

    return RepoMapResult(
        entries=entries,
        total_files=len(pr_scores),
        token_budget=token_budget,
        tokens_used=tokens_used,
        truncated=truncated,
    )


def format_repo_map(result: RepoMapResult) -> str:
    """Format a RepoMapResult as a human-readable string."""
    if not result.entries:
        return "No files ranked."

    lines = [f"Repo map ({len(result.entries)}/{result.total_files} files, ~{result.tokens_used} tokens):"]
    lines.append("")

    for entry in result.entries:
        score_pct = entry.score * 100
        prefix = f"  [{entry.category:>6}] {entry.path}"
        if entry.symbols:
            syms = ", ".join(entry.symbols[:5])
            if len(entry.symbols) > 5:
                syms += f" (+{len(entry.symbols) - 5})"
            prefix += f"  ({syms})"
        lines.append(f"{prefix}  [{score_pct:.1f}%]")

    if result.truncated:
        lines.append(f"\n  ... {result.total_files - len(result.entries)} more files omitted (token budget)")

    return "\n".join(lines)
