"""LSP tools for the code-intel MCP server.

Tools: lsp_definition, lsp_references, lsp_hover, lsp_diagnostics.
"""

from __future__ import annotations

import contextlib
import os

from attocode.code_intel.server import (
    _get_project_dir,
    mcp,
)

# ---------------------------------------------------------------------------
# Lazy LSP manager singleton
# ---------------------------------------------------------------------------

_lsp_manager = None


def _get_lsp_manager():
    """Lazily initialize the LSP manager for MCP server use."""
    global _lsp_manager
    if _lsp_manager is None:
        from attocode.integrations.lsp.client import LSPConfig, LSPManager

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
    lsp = _get_lsp_manager()
    project_dir = _get_project_dir()

    if not os.path.isabs(file):
        file = os.path.join(project_dir, file)

    try:
        loc = await lsp.get_definition(file, line, col)
    except Exception as e:
        return f"LSP not available: {e}"

    if loc is None:
        return f"No definition found at {file}:{line}:{col}"

    uri = loc.uri
    if uri.startswith("file://"):
        uri = uri[7:]
    with contextlib.suppress(ValueError):
        uri = os.path.relpath(uri, project_dir)
    return f"Definition: {uri}:{loc.range.start.line + 1}:{loc.range.start.character + 1}"


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
    lsp = _get_lsp_manager()
    project_dir = _get_project_dir()

    if not os.path.isabs(file):
        file = os.path.join(project_dir, file)

    try:
        locs = await lsp.get_references(file, line, col, include_declaration=include_declaration)
    except Exception as e:
        return f"LSP not available: {e}"

    if not locs:
        return f"No references found at {file}:{line}:{col}"

    lines = [f"References ({len(locs)}):"]
    for loc in locs[:50]:
        uri = loc.uri
        if uri.startswith("file://"):
            uri = uri[7:]
        with contextlib.suppress(ValueError):
            uri = os.path.relpath(uri, project_dir)
        lines.append(f"  {uri}:{loc.range.start.line + 1}:{loc.range.start.character + 1}")
    if len(locs) > 50:
        lines.append(f"  ... and {len(locs) - 50} more")
    return "\n".join(lines)


@mcp.tool()
async def lsp_hover(file: str, line: int, col: int = 0) -> str:
    """Get type signature and documentation for a symbol at position.

    Args:
        file: File path (relative to project root or absolute).
        line: Line number (0-indexed).
        col: Column number (0-indexed, default 0).
    """
    lsp = _get_lsp_manager()
    project_dir = _get_project_dir()

    if not os.path.isabs(file):
        file = os.path.join(project_dir, file)

    try:
        info = await lsp.get_hover(file, line, col)
    except Exception as e:
        return f"LSP not available: {e}"

    if info is None:
        return f"No hover information at {file}:{line}:{col}"
    return f"Hover at {file}:{line}:{col}:\n{info}"


@mcp.tool()
def lsp_diagnostics(file: str) -> str:
    """Get errors and warnings from the language server for a file.

    Args:
        file: File path to check for diagnostics.
    """
    lsp = _get_lsp_manager()
    project_dir = _get_project_dir()

    if not os.path.isabs(file):
        file = os.path.join(project_dir, file)

    try:
        diags = lsp.get_diagnostics(file)
    except Exception as e:
        return f"LSP not available: {e}"

    if not diags:
        return f"No diagnostics for {file}"

    lines = [f"Diagnostics ({len(diags)}):"]
    for d in diags[:30]:
        source = f" [{d.source}]" if d.source else ""
        code = f" ({d.code})" if d.code else ""
        lines.append(
            f"  [{d.severity}]{source}{code} "
            f"L{d.range.start.line + 1}:{d.range.start.character + 1}: "
            f"{d.message}"
        )
    if len(diags) > 30:
        lines.append(f"  ... and {len(diags) - 30} more")
    return "\n".join(lines)
