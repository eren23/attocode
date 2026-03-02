"""MCP server exposing Attocode's code intelligence capabilities.

Provides 8 tools for deep codebase understanding:
- repo_map: Token-budgeted file tree with symbols
- symbols: List symbols in a file
- search_symbols: Fuzzy symbol search across codebase
- dependencies: File import/importer relationships
- impact_analysis: Transitive impact of file changes (BFS)
- cross_references: Symbol definitions + usage sites
- file_analysis: Detailed single-file analysis
- dependency_graph: Dependency graph from a starting file

Usage::

    attocode-code-intel --project /path/to/repo
"""

from __future__ import annotations

import logging
import os
import sys

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print(
        "Error: 'mcp' package not installed. "
        "Reinstall with: uv tool install --force --reinstall --from . attocode",
        file=sys.stderr,
    )
    sys.exit(1)

logger = logging.getLogger(__name__)

mcp = FastMCP("attocode-code-intel")

# Lazily initialized singletons
_ast_service = None
_context_mgr = None
_code_analyzer = None


def _get_project_dir() -> str:
    """Get the project directory from env var or raise."""
    project_dir = os.environ.get("ATTOCODE_PROJECT_DIR", "")
    if not project_dir:
        raise RuntimeError(
            "ATTOCODE_PROJECT_DIR not set. "
            "Pass --project <path> or set the environment variable."
        )
    return os.path.abspath(project_dir)


def _get_ast_service():
    """Lazily initialize and return the ASTService singleton."""
    global _ast_service
    if _ast_service is None:
        from attocode.integrations.context.ast_service import ASTService

        project_dir = _get_project_dir()
        _ast_service = ASTService.get_instance(project_dir)
        if not _ast_service.initialized:
            logger.info("Initializing ASTService for %s...", project_dir)
            _ast_service.initialize()
            logger.info(
                "ASTService ready: %d files indexed",
                len(_ast_service._ast_cache),
            )
    return _ast_service


def _get_context_mgr():
    """Lazily initialize and return the CodebaseContextManager."""
    global _context_mgr
    if _context_mgr is None:
        from attocode.integrations.context.codebase_context import CodebaseContextManager

        project_dir = _get_project_dir()
        _context_mgr = CodebaseContextManager(root_dir=project_dir)
        _context_mgr.discover_files()
    return _context_mgr


def _get_code_analyzer():
    """Lazily initialize and return the CodeAnalyzer."""
    global _code_analyzer
    if _code_analyzer is None:
        from attocode.integrations.context.code_analyzer import CodeAnalyzer

        _code_analyzer = CodeAnalyzer()
    return _code_analyzer


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


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
    ctx = _get_context_mgr()
    repo = ctx.get_repo_map(include_symbols=include_symbols, max_tokens=max_tokens)

    lines = [repo.tree]
    lines.append("")
    lines.append(
        f"({repo.total_files} files, {repo.total_lines:,} lines, "
        f"{len(repo.languages)} languages)"
    )
    return "\n".join(lines)


@mcp.tool()
def symbols(path: str) -> str:
    """List all symbols (functions, classes, methods) defined in a file.

    Args:
        path: File path (relative to project root or absolute).
    """
    svc = _get_ast_service()
    locs = svc.get_file_symbols(path)

    if not locs:
        return f"No symbols found in {path}"

    lines = [f"Symbols in {path}:"]
    for loc in sorted(locs, key=lambda s: s.start_line):
        lines.append(f"  {loc.kind} {loc.qualified_name}  (L{loc.start_line}-{loc.end_line})")
    return "\n".join(lines)


@mcp.tool()
def search_symbols(name: str) -> str:
    """Search for symbol definitions across the entire codebase.

    Finds functions, classes, and methods matching the given name
    (exact or suffix match).

    Args:
        name: Symbol name to search for (e.g. "parse_file", "AgentBuilder").
    """
    svc = _get_ast_service()
    locs = svc.find_symbol(name)

    if not locs:
        return f"No definitions found for '{name}'"

    lines = [f"Definitions of '{name}':"]
    for loc in locs:
        lines.append(
            f"  {loc.kind} {loc.qualified_name}  "
            f"in {loc.file_path}:{loc.start_line}-{loc.end_line}"
        )
    return "\n".join(lines)


@mcp.tool()
def dependencies(path: str) -> str:
    """Get import/dependency relationships for a file.

    Shows both what the file imports from (dependencies) and what files
    import it (dependents/importers).

    Args:
        path: File path (relative to project root or absolute).
    """
    svc = _get_ast_service()
    deps = svc.get_dependencies(path)
    dependents = svc.get_dependents(path)

    lines = [f"Dependencies for {path}:"]

    lines.append(f"\n  Imports from ({len(deps)} files):")
    if deps:
        for d in sorted(deps):
            lines.append(f"    {d}")
    else:
        lines.append("    (none)")

    lines.append(f"\n  Imported by ({len(dependents)} files):")
    if dependents:
        for d in sorted(dependents):
            lines.append(f"    {d}")
    else:
        lines.append("    (none)")

    return "\n".join(lines)


@mcp.tool()
def impact_analysis(changed_files: list[str]) -> str:
    """Analyze the transitive impact of changing one or more files.

    Uses BFS on the reverse dependency graph to find all files that
    could be affected by changes to the given files. This is useful
    for understanding the blast radius of a code change.

    Args:
        changed_files: List of file paths that were changed.
    """
    svc = _get_ast_service()
    impacted = svc.get_impact(changed_files)

    if not impacted:
        return f"No other files are impacted by changes to {', '.join(changed_files)}"

    lines = [f"Impact analysis for {', '.join(changed_files)}:"]
    lines.append(f"\n  {len(impacted)} files affected:")
    for f in sorted(impacted):
        lines.append(f"    {f}")
    return "\n".join(lines)


@mcp.tool()
def cross_references(symbol_name: str) -> str:
    """Find where a symbol is defined and all places it is referenced.

    Shows both the definition locations and all call sites, imports,
    and attribute accesses for the given symbol.

    Args:
        symbol_name: Name of the symbol to look up.
    """
    svc = _get_ast_service()
    definitions = svc.find_symbol(symbol_name)
    references = svc.get_callers(symbol_name)

    lines = [f"Cross-references for '{symbol_name}':"]

    lines.append(f"\n  Definitions ({len(definitions)}):")
    if definitions:
        for loc in definitions:
            lines.append(
                f"    {loc.kind} {loc.qualified_name}  "
                f"in {loc.file_path}:{loc.start_line}"
            )
    else:
        lines.append("    (none found)")

    lines.append(f"\n  References ({len(references)}):")
    if references:
        for ref in references[:50]:  # Cap at 50 to avoid huge output
            lines.append(f"    [{ref.ref_kind}] {ref.file_path}:{ref.line}")
        if len(references) > 50:
            lines.append(f"    ... and {len(references) - 50} more")
    else:
        lines.append("    (none found)")

    return "\n".join(lines)


@mcp.tool()
def file_analysis(path: str) -> str:
    """Get detailed analysis of a single file including code chunks, imports, and exports.

    Extracts structured information about functions, classes, methods,
    imports, and exports using AST parsing (tree-sitter or regex fallback).

    Args:
        path: File path (relative to project root or absolute).
    """
    analyzer = _get_code_analyzer()
    project_dir = _get_project_dir()

    # Resolve to absolute path if relative
    if not os.path.isabs(path):
        path = os.path.join(project_dir, path)

    result = analyzer.analyze_file(path)

    lines = [f"Analysis of {result.path}:"]
    lines.append(f"  Language: {result.language}")
    lines.append(f"  Lines: {result.line_count}")

    if result.imports:
        lines.append(f"\n  Imports ({len(result.imports)}):")
        for imp in result.imports:
            lines.append(f"    {imp}")

    if result.exports:
        lines.append(f"\n  Exports ({len(result.exports)}):")
        for exp in result.exports:
            lines.append(f"    {exp}")

    if result.chunks:
        lines.append(f"\n  Code chunks ({len(result.chunks)}):")
        for chunk in result.chunks:
            sig = f" — {chunk.signature}" if chunk.signature else ""
            parent = f" (in {chunk.parent})" if chunk.parent else ""
            lines.append(
                f"    {chunk.kind} {chunk.name}{parent}{sig}  "
                f"L{chunk.start_line}-{chunk.end_line}"
            )

    return "\n".join(lines)


@mcp.tool()
def dependency_graph(start_file: str, depth: int = 2) -> str:
    """Get the dependency graph starting from a file.

    Shows the import tree radiating outward from the given file,
    including both forward dependencies (what it imports) and
    reverse dependencies (what imports it).

    Args:
        start_file: File path to start from.
        depth: How many hops to traverse (default 2).
    """
    svc = _get_ast_service()
    rel = svc._to_rel(start_file)

    lines = [f"Dependency graph for {rel} (depth={depth}):"]

    # Forward BFS
    lines.append("\n  Imports (forward):")
    visited_fwd: set[str] = set()
    queue_fwd: list[tuple[str, int]] = [(rel, 0)]
    while queue_fwd:
        current, d = queue_fwd.pop(0)
        if current in visited_fwd or d > depth:
            continue
        visited_fwd.add(current)
        indent = "    " + "  " * d
        if d > 0:
            lines.append(f"{indent}{current}")
        deps = svc.get_dependencies(current)
        for dep in sorted(deps):
            if dep not in visited_fwd:
                queue_fwd.append((dep, d + 1))

    if len(visited_fwd) <= 1:
        lines.append("    (none)")

    # Reverse BFS
    lines.append("\n  Imported by (reverse):")
    visited_rev: set[str] = set()
    queue_rev: list[tuple[str, int]] = [(rel, 0)]
    while queue_rev:
        current, d = queue_rev.pop(0)
        if current in visited_rev or d > depth:
            continue
        visited_rev.add(current)
        indent = "    " + "  " * d
        if d > 0:
            lines.append(f"{indent}{current}")
        dependents = svc.get_dependents(current)
        for dep in sorted(dependents):
            if dep not in visited_rev:
                queue_rev.append((dep, d + 1))

    if len(visited_rev) <= 1:
        lines.append("    (none)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for the MCP server."""
    # Parse --project from sys.argv
    project_dir = "."
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--project" and i + 1 < len(args):
            project_dir = args[i + 1]
            break
        if arg.startswith("--project="):
            project_dir = arg.split("=", 1)[1]
            break

    os.environ["ATTOCODE_PROJECT_DIR"] = os.path.abspath(project_dir)

    logger.info("Starting attocode-code-intel for %s", project_dir)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
