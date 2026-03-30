"""Navigation tools for the code-intel MCP server.

Tools: repo_map, symbols, search_symbols, explore_codebase,
project_summary, bootstrap.
"""

from __future__ import annotations

from attocode.code_intel._shared import (
    _get_ast_service,
    _get_service,
    mcp,
)


@mcp.tool()
def repo_map(
    include_symbols: bool = True,
    max_tokens: int = 6000,
) -> str:
    """Get a token-budgeted repository map showing file structure and key symbols.

    Returns a tree view of the project with the most important files annotated
    with their top-level symbols (functions, classes). Files are tiered by
    importance: high-importance files show symbols, medium show names only,
    low-importance files are collapsed.

    Args:
        include_symbols: Whether to annotate files with top-level symbols.
        max_tokens: Token budget for the output (default 6000).
    """
    return _get_service().repo_map(include_symbols=include_symbols, max_tokens=max_tokens)


@mcp.tool()
def symbols(path: str) -> str:
    """List all symbols (functions, classes, methods) defined in a file.

    Args:
        path: File path (relative to project root or absolute).
    """
    return _get_service().symbols(path)


@mcp.tool()
def search_symbols(name: str, limit: int = 30, kind: str = "") -> str:
    """Search for symbol definitions across the entire codebase.

    Multi-strategy search: exact match, prefix, substring, case-insensitive,
    and camelCase/snake_case token matching.  Results ranked by match quality
    and symbol importance.

    Args:
        name: Symbol name or pattern (e.g. "parse_file", "Router", "exitCode").
        limit: Maximum results to return (default 30).
        kind: Filter by symbol kind: "function", "class", "method", "variable",
            "constant", "interface", "type". Empty = all kinds.
    """
    return _get_service().search_symbols(name, limit=limit, kind=kind)


@mcp.tool()
def explore_codebase(
    path: str = "",
    max_items: int = 30,
    importance_threshold: float = 0.3,
) -> str:
    """Explore the codebase one directory level at a time.

    Returns directories with file counts and languages, and files with
    importance scores and top symbols. Use for drill-down navigation
    on large codebases instead of the full repo map.

    Args:
        path: Relative directory path ("" for root, e.g. "src/attocode/integrations").
        max_items: Maximum items (dirs + files) to return (default 30).
        importance_threshold: Minimum file importance to show (0.0-1.0, default 0.3).
    """
    return _get_service().explore_codebase(
        path=path,
        max_items=max_items,
        importance_threshold=importance_threshold,
    )


@mcp.tool()
def project_summary(max_tokens: int = 4000) -> str:
    """Get a high-level project summary suitable for bootstrapping understanding.

    Produces a structured overview including project identity, stats,
    entry points, core architecture, directory layout, dependency layers,
    tech stack, test structure, and build system. Ideal as a first tool
    call when approaching an unknown codebase.

    Args:
        max_tokens: Token budget for the output (default 4000).
    """
    return _get_service().project_summary(max_tokens=max_tokens)


@mcp.tool()
def bootstrap(
    task_hint: str = "",
    max_tokens: int = 8000,
    indexing_depth: str = "auto",
) -> str:
    """All-in-one codebase orientation -- the best first tool call.

    Detects codebase size and returns an optimized bundle:
    - Project summary (identity, stats, entry points, architecture)
    - Repository map OR hierarchical exploration (size-dependent)
    - Coding conventions (25-file sample)
    - Relevant search results (if task_hint provided)
    - Navigation guidance tailored to codebase size

    Replaces 2-4 sequential calls (project_summary + repo_map + conventions
    + semantic_search) with a single call. Inspired by Stripe's pre-hydration
    pattern.

    Args:
        task_hint: Optional description of what you're trying to do.
            When provided, includes semantic search results for relevant code.
        max_tokens: Token budget for the entire output (default 8000).
        indexing_depth: Indexing strategy. "auto" picks based on repo size.
            "eager" forces full sync indexing. "lazy" does minimal skeleton.
            "minimal" skips parsing entirely.
    """
    return _get_service().bootstrap(
        task_hint=task_hint,
        max_tokens=max_tokens,
        indexing_depth=indexing_depth,
    )


@mcp.tool()
def hydration_status() -> str:
    """Check progressive indexing status.

    Returns the current hydration tier, phase, parse coverage,
    reference coverage, and embedding status. Use this to decide
    whether to wait for full indexing or proceed with partial results.
    """
    svc = _get_service()
    status = svc.hydration_status()
    lines = [
        f"Tier: {status.get('tier', 'unknown')}",
        f"Phase: {status.get('phase', 'unknown')}",
        f"Parse coverage: {status.get('parse_coverage', 0):.0%} "
        f"({status.get('parsed_files', 0)}/{status.get('total_files', 0)} files)",
        f"Reference coverage: {status.get('reference_coverage', 0):.0%}",
        f"Embedding coverage: {status.get('embedding_coverage', 0):.0%}",
        f"Elapsed: {status.get('elapsed_ms', 0):.0f}ms",
    ]
    return "\n".join(lines)


@mcp.tool()
def conventions(sample_size: int = 50, path: str = "") -> str:
    """Detect coding conventions and style patterns in the project.

    Analyzes function naming, type hints, docstrings, async usage,
    import style, popular decorators, class patterns, and module
    organization across a sample of the most important files.

    When ``path`` is set, only samples files within that directory subtree
    and appends a comparison to project-wide conventions. This follows
    Stripe's "scoped rules" pattern -- different directories may follow
    different conventions.

    Args:
        sample_size: Number of files to sample (default 50).
        path: Optional directory path to scope the analysis to (e.g. "src/core").
            When empty, analyzes the entire project.
    """
    return _get_service().conventions(sample_size=sample_size, path=path)


@mcp.tool()
def relevant_context(
    files: list[str],
    depth: int = 1,
    max_tokens: int = 4000,
    include_symbols: bool = True,
) -> str:
    """Get a subgraph capsule -- a file and its neighbors with symbols.

    BFS from center file(s) in both directions (imports and importers) up to
    `depth` hops. For each file shows: language, line count, importance,
    relationship to center, and top symbols. Replaces N+1 sequential calls
    (dependency_graph + symbols on each neighbor).

    Args:
        files: Center file paths (relative to project root or absolute).
        depth: How many hops to traverse (default 1, max 2).
        max_tokens: Token budget for the output (default 4000).
        include_symbols: Whether to include symbol lists (default True).
    """
    return _get_service().relevant_context(
        files=files,
        depth=depth,
        max_tokens=max_tokens,
        include_symbols=include_symbols,
    )


@mcp.tool()
def reindex(force: bool = False) -> str:
    """Trigger a re-index of the codebase symbol database.

    By default performs an incremental update — only re-parses files whose
    mtime has changed since the last scan.  Pass ``force=True`` to rebuild
    the entire index from scratch.

    Args:
        force: If True, discard the cached index and re-parse every file.
    """
    svc = _get_ast_service()
    if force:
        svc.force_reindex()
    else:
        svc.initialize(force=False)

    stats = svc._store.stats() if hasattr(svc, "_store") else {}
    mode = "full rebuild" if force else "incremental"
    return (
        f"Reindex complete ({mode}).\n"
        f"  Files: {stats.get('files', '?')}\n"
        f"  Symbols: {stats.get('symbols', '?')}\n"
        f"  References: {stats.get('references', '?')}\n"
        f"  Dependencies: {stats.get('dependencies', '?')}"
    )
