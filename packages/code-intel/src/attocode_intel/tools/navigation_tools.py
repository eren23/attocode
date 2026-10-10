"""Navigation tools for the code-intel MCP server.

Tools: repo_map, symbols, search_symbols, explore_codebase,
project_summary, bootstrap.
"""

from __future__ import annotations

from attocode_intel._shared import (
    _get_ast_service,
    _get_service,
    mcp,
)
from attocode_intel.tools.pin_tools import pin_stamped


@mcp.tool()
@pin_stamped
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
@pin_stamped
def symbols(path: str) -> str:
    """List the functions, classes and methods that a file defines."""
    return _get_service().symbols(path)


@mcp.tool()
@pin_stamped
def search_symbols(name: str, limit: int = 30, kind: str = "", task_hint: str = "") -> str:
    """Find symbol definitions by name, best match first: exact, prefix, substring, case-insensitive and camelCase or snake_case parts.

    Args:
        name: A name or part of one, for example "parse_file" or "Router".
        kind: Optional filter: function, class, method, variable, constant, interface or type.
        task_hint: Optional task text that orders equal matches.
    """
    service = _get_service()
    if task_hint and hasattr(service, "_task_file_scores"):
        return service.search_symbols(name, limit=limit, kind=kind,
                                      task_hint=task_hint)
    return service.search_symbols(name, limit=limit, kind=kind)


@mcp.tool()
def inspect_symbol(symbol_name: str, file_path: str | None = None, line: int | None = None,
                   source_start_line: int | None = None, task_hint: str | None = None) -> str:
    """Get a symbol in one call: definition, source excerpt, references, imports and candidate tests.

    A name is enough. For an ambiguous name, the result lists choices: give the repository-relative file_path
    and the definition start line to select one. Add task_hint to order the excerpts and tests for your task.
    For a long definition, follow next_source or set source_start_line. Keep each context_ranges group with
    its excerpt. Missing relationships do not prove absence.
    """
    import json

    from attocode_intel.symbol_inspection import inspect_symbol_data

    return json.dumps(inspect_symbol_data(_get_service(), symbol_name, file_path, line, source_start_line, task_hint))


@mcp.tool()
def explore_codebase(
    path: str = "",
    max_items: int = 30,
    importance_threshold: float = 0.3,
    task_hint: str = "",
) -> str:
    """List one directory level: subdirectories with file counts and languages, and files with importance and top symbols.

    Args:
        path: Directory relative to the project root ("" for the root).
        importance_threshold: Minimum file importance, 0.0 to 1.0.
        task_hint: Optional task text that orders the files.
    """
    service = _get_service()
    kwargs = {"path": path, "max_items": max_items,
              "importance_threshold": importance_threshold}
    if task_hint and hasattr(service, "_task_file_scores"):
        kwargs["task_hint"] = task_hint
    return service.explore_codebase(**kwargs)


@mcp.tool()
def project_summary(max_tokens: int = 4000) -> str:
    """Summarize the project: purpose, size, entry points, architecture, layout, dependency layers, tech stack, tests and build."""
    return _get_service().project_summary(max_tokens=max_tokens)


@mcp.tool()
def bootstrap(
    task_hint: str = "",
    max_tokens: int = 8000,
    indexing_depth: str = "auto",
) -> str:
    """Find where a behavior is implemented in an unfamiliar repository.

    With task_hint, the result has the code that matches the task, a project summary, a map and the conventions.

    Args:
        task_hint: What you want to find or change.
        indexing_depth: "auto" (default), "eager", "lazy" or "minimal".
    """
    return _get_service().bootstrap(
        task_hint=task_hint,
        max_tokens=max_tokens,
        indexing_depth=indexing_depth,
    )


@mcp.tool()
def hydration_status() -> str:
    """Report the index progress: tier, phase, parse and reference coverage, and embedding status."""
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
    excluded = status.get("excluded_checkout_roots", [])
    if excluded or status.get("excluded_checkout_roots_truncated"):
        lines.append("Git checkouts excluded by this workspace's ignore rules:")
        lines.extend(f"  {path}" for path in excluded)
        if status.get("excluded_checkout_roots_truncated"):
            lines.append("  Scan incomplete; other ignored Git checkouts may exist.")
        lines.append("Select a checkout with workspace=<path to checkout> to index its files.")
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
    task_hint: str = "",
) -> str:
    """Show the files around the given files: what they import and what imports them, with their top symbols.

    Args:
        files: Center file paths.
        depth: Number of hops, 1 or 2 (default 1).
        task_hint: Optional task text that orders the files.
    """
    service = _get_service()
    kwargs = {"files": files, "depth": depth, "max_tokens": max_tokens,
              "include_symbols": include_symbols}
    if task_hint and hasattr(service, "_task_file_scores"):
        kwargs["task_hint"] = task_hint
    return service.relevant_context(**kwargs)


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
