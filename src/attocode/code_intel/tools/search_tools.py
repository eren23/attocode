"""Search and security tools for the code-intel MCP server.

Tools: semantic_search, semantic_search_status, security_scan, fast_search.
"""

from __future__ import annotations

import threading

from attocode.code_intel.server import (
    _get_ast_service,
    _get_context_mgr,
    _get_project_dir,
    mcp,
)

# ---------------------------------------------------------------------------
# Lazy singletons
# ---------------------------------------------------------------------------

_semantic_search = None
_semantic_search_lock = threading.Lock()

_trigram_index = None
_trigram_index_lock = threading.Lock()


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


def _get_trigram_index():
    """Lazily initialize the trigram index (thread-safe).

    Loads an existing index from disk if available. Returns None
    if no index has been built yet.
    """
    global _trigram_index
    if _trigram_index is None:
        with _trigram_index_lock:
            if _trigram_index is None:
                import os
                project_dir = _get_project_dir()
                index_dir = os.path.join(project_dir, ".attocode", "index")
                if os.path.isdir(index_dir):
                    try:
                        from attocode.integrations.context.trigram_index import TrigramIndex
                        idx = TrigramIndex(index_dir=index_dir)
                        if idx.load():
                            _trigram_index = idx
                    except Exception:
                        pass
    return _trigram_index


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
    discovered_files = 0
    ast_indexed_files = 0
    degradation_reasons: list[str] = []

    try:
        ctx = _get_context_mgr()
        discovered = getattr(ctx, "_files", None)
        if isinstance(discovered, list):
            discovered_files = len(discovered)
        if discovered_files == 0:
            discovered_files = len(ctx.discover_files())
    except Exception as exc:
        degradation_reasons.append(f"context_error:{type(exc).__name__}")

    try:
        ast_svc = _get_ast_service()
        stats = ast_svc._store.stats() if hasattr(ast_svc, "_store") else {}
        ast_indexed_files = int(
            stats.get("files", 0)
            or stats.get("files_indexed", 0)
            or len(getattr(ast_svc, "_ast_cache", {}))
        )
    except Exception as exc:
        degradation_reasons.append(f"ast_error:{type(exc).__name__}")

    if discovered_files == 0:
        degradation_reasons.append("no_files_discovered")
    if ast_indexed_files == 0:
        degradation_reasons.append("no_files_indexed")

    lines = [
        "Semantic search status:",
        f"  Provider: {mgr.provider_name}",
        f"  Available: {mgr.is_available}",
        f"  Status: {progress.status}",
        f"  Coverage: {progress.coverage:.0%} ({progress.indexed_files}/{progress.total_files} files)",
        f"  Failed: {progress.failed_files}",
        f"  Vector search active: {mgr.is_index_ready()}",
        f"  Discovery count: {discovered_files}",
        f"  AST indexed files: {ast_indexed_files}",
        f"  Health: {'degraded' if degradation_reasons else 'healthy'}",
    ]
    if degradation_reasons:
        lines.append(f"  Degradation reason: {', '.join(degradation_reasons)}")
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


@mcp.tool()
def fast_search(
    pattern: str,
    path: str = "",
    max_results: int = 50,
    case_insensitive: bool = False,
) -> str:
    """Fast regex search using trigram index pre-filtering.

    Uses a trigram inverted index to identify candidate files before
    running the full regex, typically 10-100x faster than brute-force grep
    on large codebases. Falls back to standard grep when:
      - No trigram index has been built (run ``reindex`` first)
      - The pattern yields no extractable trigrams (e.g., ``.*``)

    Args:
        pattern: Regex pattern to search for (e.g. "def process_.*event").
        path: Subdirectory to search (relative to project root, empty for all).
        max_results: Maximum number of matching lines to return (default 50).
        case_insensitive: Whether to match case-insensitively.
    """
    import os
    import re
    from pathlib import Path

    project_dir = _get_project_dir()
    root = Path(project_dir)
    if path:
        root = root / path
    root = root.resolve()

    if not root.exists():
        return f"Error: Path not found: {root}"

    flags = re.IGNORECASE if case_insensitive else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        return f"Error: Invalid regex pattern: {e}"

    # Try trigram pre-filtering
    trigram_idx = _get_trigram_index()
    candidates: list[str] | None = None
    index_status = "no index"

    if trigram_idx is not None and trigram_idx.is_ready():
        candidates = trigram_idx.query(pattern, case_insensitive=case_insensitive)
        if candidates is not None:
            index_status = f"trigram filter: {len(candidates)} candidates"
        else:
            index_status = "no trigrams extractable, full scan"
    else:
        # Try to build the index on first use
        try:
            from attocode.integrations.context.trigram_index import TrigramIndex
            index_dir = os.path.join(project_dir, ".attocode", "index")
            idx = TrigramIndex(index_dir=index_dir)
            stats = idx.build(project_dir)
            global _trigram_index
            _trigram_index = idx
            candidates = idx.query(pattern, case_insensitive=case_insensitive)
            index_status = (
                f"built index ({stats['files_indexed']} files, "
                f"{stats['build_time_ms']}ms), "
                f"{len(candidates) if candidates is not None else 'N/A'} candidates"
            )
        except Exception:
            index_status = "index build failed, full scan"

    # Determine files to search
    if candidates is not None:
        files = sorted(root / c for c in candidates)
    else:
        files = sorted(root.rglob("*"))

    matches: list[str] = []
    for file in files:
        if not file.is_file() or file.name.startswith("."):
            continue
        try:
            content = file.read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(content.splitlines(), 1):
            if regex.search(line):
                try:
                    rel = file.relative_to(Path(project_dir))
                except ValueError:
                    rel = file.name
                matches.append(f"{rel}:{i}: {line.strip()}")
                if len(matches) >= max_results:
                    break
        if len(matches) >= max_results:
            break

    if not matches:
        return f"No matches found ({index_status})"

    result = "\n".join(matches)
    if len(matches) >= max_results:
        result += f"\n... (limited to {max_results} results)"
    result += f"\n({index_status})"
    return result
