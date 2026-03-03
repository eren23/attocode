"""LSP agent tools — expose language server capabilities to the agent.

Wraps the LSPManager to provide type-resolved definitions, references,
hover info, and diagnostics as on-demand agent tools.
"""

from __future__ import annotations

import os
from typing import Any

from attocode.tools.base import Tool, ToolSpec
from attocode.types.messages import DangerLevel


async def _execute_lsp_definition(lsp_manager: Any, args: dict[str, Any]) -> str:
    """Get type-resolved definition of a symbol."""
    file_path: str = args["file"]
    line: int = args["line"]
    col: int = args.get("col", 0)

    try:
        loc = await lsp_manager.get_definition(file_path, line, col)
    except Exception as e:
        return f"LSP error: {e}"

    if loc is None:
        return f"No definition found at {file_path}:{line}:{col}"

    uri = loc.uri
    if uri.startswith("file://"):
        uri = uri[7:]
    return (
        f"Definition: {uri}:{loc.range.start.line + 1}:{loc.range.start.character + 1}"
    )


async def _execute_lsp_references(lsp_manager: Any, args: dict[str, Any]) -> str:
    """Get all references to a symbol at position."""
    file_path: str = args["file"]
    line: int = args["line"]
    col: int = args.get("col", 0)
    include_declaration: bool = args.get("include_declaration", True)

    try:
        locs = await lsp_manager.get_references(
            file_path, line, col, include_declaration=include_declaration,
        )
    except Exception as e:
        return f"LSP error: {e}"

    if not locs:
        return f"No references found at {file_path}:{line}:{col}"

    lines = [f"References ({len(locs)}):"]
    for loc in locs[:50]:
        uri = loc.uri
        if uri.startswith("file://"):
            uri = uri[7:]
        lines.append(
            f"  {uri}:{loc.range.start.line + 1}:{loc.range.start.character + 1}"
        )
    if len(locs) > 50:
        lines.append(f"  ... and {len(locs) - 50} more")
    return "\n".join(lines)


async def _execute_lsp_hover(lsp_manager: Any, args: dict[str, Any]) -> str:
    """Get type signature and docs for a symbol at position."""
    file_path: str = args["file"]
    line: int = args["line"]
    col: int = args.get("col", 0)

    try:
        info = await lsp_manager.get_hover(file_path, line, col)
    except Exception as e:
        return f"LSP error: {e}"

    if info is None:
        return f"No hover information at {file_path}:{line}:{col}"

    return f"Hover info at {file_path}:{line}:{col}:\n{info}"


async def _execute_lsp_diagnostics(lsp_manager: Any, args: dict[str, Any]) -> str:
    """Get errors/warnings from the language server."""
    file_path: str = args.get("file", "")

    try:
        diags = lsp_manager.get_diagnostics(file_path)
    except Exception as e:
        return f"LSP error: {e}"

    if not diags:
        return f"No diagnostics for {file_path}" if file_path else "No diagnostics"

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


def create_lsp_tools(lsp_manager: Any) -> list[Tool]:
    """Create LSP agent tools bound to an LSPManager.

    Args:
        lsp_manager: Initialized LSPManager instance.

    Returns:
        List of Tool objects for LSP queries.
    """

    async def _def(args: dict[str, Any]) -> Any:
        return await _execute_lsp_definition(lsp_manager, args)

    async def _refs(args: dict[str, Any]) -> Any:
        return await _execute_lsp_references(lsp_manager, args)

    async def _hover(args: dict[str, Any]) -> Any:
        return await _execute_lsp_hover(lsp_manager, args)

    async def _diags(args: dict[str, Any]) -> Any:
        return await _execute_lsp_diagnostics(lsp_manager, args)

    _position_params = {
        "file": {
            "type": "string",
            "description": "File path (absolute or relative to project root).",
        },
        "line": {
            "type": "integer",
            "description": "Line number (0-indexed).",
        },
        "col": {
            "type": "integer",
            "default": 0,
            "description": "Column number (0-indexed, default 0).",
        },
    }

    return [
        Tool(
            spec=ToolSpec(
                name="lsp_definition",
                description=(
                    "Get the type-resolved definition location of a symbol. "
                    "More accurate than regex cross-references. Requires a "
                    "running language server for the file's language."
                ),
                parameters={
                    "type": "object",
                    "properties": _position_params,
                    "required": ["file", "line"],
                },
                danger_level=DangerLevel.SAFE,
            ),
            execute=_def,
            tags=["lsp", "navigation"],
        ),
        Tool(
            spec=ToolSpec(
                name="lsp_references",
                description=(
                    "Find all references to a symbol with type awareness. "
                    "More accurate than regex grep for finding usages."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        **_position_params,
                        "include_declaration": {
                            "type": "boolean",
                            "default": True,
                            "description": "Include the declaration in results.",
                        },
                    },
                    "required": ["file", "line"],
                },
                danger_level=DangerLevel.SAFE,
            ),
            execute=_refs,
            tags=["lsp", "navigation"],
        ),
        Tool(
            spec=ToolSpec(
                name="lsp_hover",
                description=(
                    "Get type signature and documentation for a symbol. "
                    "Useful when you need to understand a function's signature "
                    "or a variable's type without reading the full file."
                ),
                parameters={
                    "type": "object",
                    "properties": _position_params,
                    "required": ["file", "line"],
                },
                danger_level=DangerLevel.SAFE,
            ),
            execute=_hover,
            tags=["lsp", "info"],
        ),
        Tool(
            spec=ToolSpec(
                name="lsp_diagnostics",
                description=(
                    "Get errors and warnings from the language server for a file. "
                    "Useful after edits to check for type errors or syntax issues."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "file": {
                            "type": "string",
                            "description": (
                                "File path to get diagnostics for. "
                                "Required for targeted diagnostics."
                            ),
                        },
                    },
                    "required": ["file"],
                },
                danger_level=DangerLevel.SAFE,
            ),
            execute=_diags,
            tags=["lsp", "diagnostics"],
        ),
    ]
