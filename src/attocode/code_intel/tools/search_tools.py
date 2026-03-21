"""Search and security tools for the code-intel MCP server.

Tools: semantic_search, security_scan, relevant_context helpers.
"""

from __future__ import annotations

import threading

from attocode.code_intel.server import (
    _get_project_dir,
    mcp,
)

# ---------------------------------------------------------------------------
# Lazy singletons
# ---------------------------------------------------------------------------

_semantic_search = None
_semantic_search_lock = threading.Lock()


def _get_semantic_search():
    """Lazily initialize the semantic search manager (thread-safe)."""
    global _semantic_search
    if _semantic_search is None:
        with _semantic_search_lock:
            if _semantic_search is None:
                from attocode.integrations.context.semantic_search import SemanticSearchManager
                project_dir = _get_project_dir()
                _semantic_search = SemanticSearchManager(root_dir=project_dir)
    return _semantic_search


_security_scanner = None


def _get_security_scanner():
    """Lazily initialize the security scanner."""
    global _security_scanner
    if _security_scanner is None:
        from attocode.integrations.security.scanner import SecurityScanner
        project_dir = _get_project_dir()
        _security_scanner = SecurityScanner(root_dir=project_dir)
    return _security_scanner


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def semantic_search(
    query: str,
    top_k: int = 10,
    file_filter: str = "",
    branch: str = "",
) -> str:
    """Search the codebase using natural language queries.

    Finds relevant files, functions, and classes by meaning -- not just
    keyword matching. Uses embeddings when available (sentence-transformers
    or OpenAI), falls back to keyword matching otherwise.

    Args:
        query: Natural language search query (e.g. "authentication middleware").
        top_k: Number of results to return (default 10).
        file_filter: Optional glob pattern to filter files (e.g. "*.py").
        branch: Optional branch name for scoping results (service mode).
            In local mode, results are automatically scoped to files
            present in the working directory.
    """
    mgr = _get_semantic_search()
    results = mgr.search(query, top_k=top_k, file_filter=file_filter)
    return mgr.format_results(results)


@mcp.tool()
def semantic_search_status() -> str:
    """Get the status of the semantic search index.

    Returns: provider name, coverage percentage, files indexed/total,
    indexing status, and whether vector search is active.
    """
    mgr = _get_semantic_search()
    progress = mgr.get_index_progress()
    lines = [
        "Semantic search status:",
        f"  Provider: {mgr.provider_name}",
        f"  Available: {mgr.is_available}",
        f"  Status: {progress.status}",
        f"  Coverage: {progress.coverage:.0%} ({progress.indexed_files}/{progress.total_files} files)",
        f"  Failed: {progress.failed_files}",
        f"  Vector search active: {mgr.is_index_ready()}",
    ]
    if progress.elapsed_seconds > 0:
        lines.append(f"  Elapsed: {progress.elapsed_seconds:.1f}s")
    return "\n".join(lines)


@mcp.tool()
def security_scan(
    mode: str = "full",
    path: str = "",
) -> str:
    """Scan the codebase for security issues.

    Detects hardcoded secrets, code anti-patterns, and dependency
    pinning issues. All scanning is local (no external API calls).
    Returns a compliance score (0-100) and categorized findings.

    Args:
        mode: Scan mode -- 'quick' (secrets), 'full' (all), 'secrets', 'patterns', 'dependencies'.
        path: Subdirectory to scan (relative to project root, empty for all).
    """
    scanner = _get_security_scanner()
    report = scanner.scan(mode=mode, path=path)
    return scanner.format_report(report)
