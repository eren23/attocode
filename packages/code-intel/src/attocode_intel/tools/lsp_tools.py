"""LSP tools for the code-intel MCP server.

Tools: lsp_definition, lsp_references, lsp_hover, lsp_diagnostics,
lsp_enrich.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from attocode_intel._shared import (
    _get_project_dir,
    _get_remote_service,
    _get_service,
    mcp,
)

if TYPE_CHECKING:
    from attocode_intel._internal.integrations.lsp.client import LSPManager

# ---------------------------------------------------------------------------
# Lazy LSP manager singleton
# ---------------------------------------------------------------------------

_lsp_manager: LSPManager | None = None


def _get_lsp_manager() -> LSPManager:
    """Lazily initialize the LSP manager for MCP server use."""
    from attocode_intel.request_context import current_request
    if (request := current_request.get()) is not None:
        return request.service._get_lsp_manager()
    global _lsp_manager
    if _lsp_manager is None:
        from attocode_intel._internal.integrations.lsp.client import LSPConfig, LSPManager

        project_dir = _get_project_dir()
        config = LSPConfig(
            enabled=True,
            root_uri=f"file://{project_dir}",
        )
        _lsp_manager = LSPManager(config=config)
    return _lsp_manager


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def lsp_definition(file: str, line: int, col: int = 0) -> str:
    """Get the type-resolved definition location of a symbol.

    More accurate than regex cross-references -- uses the language server
    for true type-resolved go-to-definition.

    Args:
        file: File path (relative to project root or absolute).
        line: Line number (0-indexed).
        col: Column number (0-indexed, default 0).
    """
    return await _get_service().lsp_definition(file=file, line=line, col=col)


@mcp.tool()
async def lsp_references(
    file: str, line: int, col: int = 0, include_declaration: bool = True,
) -> str:
    """Find all references to a symbol at position with type awareness.

    Args:
        file: File path (relative to project root or absolute).
        line: Line number (0-indexed).
        col: Column number (0-indexed, default 0).
        include_declaration: Whether to include the declaration itself.
    """
    return await _get_service().lsp_references(
        file=file,
        line=line,
        col=col,
        include_declaration=include_declaration,
    )


@mcp.tool()
async def lsp_hover(file: str, line: int, col: int = 0) -> str:
    """Get type signature and documentation for a symbol at position.

    Args:
        file: File path (relative to project root or absolute).
        line: Line number (0-indexed).
        col: Column number (0-indexed, default 0).
    """
    return await _get_service().lsp_hover(file=file, line=line, col=col)


@mcp.tool()
def lsp_diagnostics(file: str) -> str:
    """Get errors and warnings from the language server for a file.

    Args:
        file: File path to check for diagnostics.
    """
    return _get_service().lsp_diagnostics(file=file)


@mcp.tool()
async def lsp_enrich(files: list[str]) -> str:
    """Enrich the cross-reference index with type-precise LSP data.

    For each file, queries the language server for definitions and
    references of exported symbols, then feeds the results into the
    cross-reference index with ``source="lsp"``.  LSP-sourced entries
    rank higher in symbol search.

    Use this when you need precise cross-references for critical files
    before performing deep analysis (impact analysis, refactoring, etc.).

    Falls back gracefully if no language server is available.

    Args:
        files: List of file paths to enrich (relative or absolute).
    """
    remote = _get_remote_service()
    if remote is not None:
        return await remote.lsp_enrich(files)

    from attocode_intel.precision import PrecisionSession
    from attocode_intel.request_context import current_request

    service = _get_service()
    request = current_request.get()
    session = (request.stores.setdefault("precision", PrecisionSession(service))
               if request else PrecisionSession(service))
    ast_svc = service._get_ast_service()
    outcomes = []
    for file in files:
        rel_path = os.path.relpath(file, service.project_dir) if os.path.isabs(file) else file
        for symbol in ast_svc.get_file_symbols(rel_path):
            outcome = await session.enrich(symbol.qualified_name, rel_path)
            outcomes.extend(outcome.get("queries", [{"status": outcome["status"]}]))
    verified = sum(item["status"] == "verified" for item in outcomes)
    lines = ["LSP enrichment complete.", f"  Files processed: {len(files)}",
             f"  Symbols enriched: {verified}",
             f"  Unverified queries: {len(outcomes) - verified}",
             "Missing relationships do not prove absence; syntax candidates remain available."]
    return "\n".join(lines)


@mcp.tool()
async def lsp_completions(
    file: str, line: int, col: int = 0, limit: int = 20,
) -> str:
    """Get completion suggestions at a cursor position.

    Shows available types, methods, and properties with type info
    and documentation. Useful when you want to see what APIs are
    available at a given position.

    Args:
        file: File path (relative to project root or absolute).
        line: Line number (0-indexed).
        col: Column number (0-indexed, default 0).
        limit: Maximum completions to return (default 20, max 100).
    """
    return await _get_service().lsp_completions(
        file=file, line=line, col=col, limit=limit,
    )


@mcp.tool()
async def lsp_workspace_symbol(query: str, limit: int = 30) -> str:
    """Search for symbols by name across the entire workspace.

    Uses the LSP's indexed workspace/symbol request — faster and more
    accurate than grep for finding definitions.  Returns classes,
    functions, methods, constants, and other symbols whose names
    contain the query string.

    Args:
        query: Symbol name to search for (partial match, case-insensitive).
        limit: Maximum results to return (default 30, max 100).
    """
    return await _get_service().lsp_workspace_symbol(query=query, limit=limit)


@mcp.tool()
async def lsp_incoming_calls(file: str, line: int, col: int = 0) -> str:
    """Find what calls the symbol at the given position.

    Shows the full list of callers with their file locations.
    Use this when you need to understand all the places that
    invoke a function, method, or class.

    Args:
        file: File path (relative to project root or absolute).
        line: Line number (0-indexed).
        col: Column number (0-indexed, default 0).
    """
    return await _get_service().lsp_incoming_calls(file=file, line=line, col=col)


@mcp.tool()
async def lsp_outgoing_calls(file: str, line: int, col: int = 0) -> str:
    """Find what the symbol at the given position calls.

    Shows the full list of callees with their file locations.
    Use this when you need to understand what a function does
    by tracing its dependencies.

    Args:
        file: File path (relative to project root or absolute).
        line: Line number (0-indexed).
        col: Column number (0-indexed, default 0).
    """
    return await _get_service().lsp_outgoing_calls(file=file, line=line, col=col)
