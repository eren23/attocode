"""LSP agent tools — expose language server capabilities to the agent.

Wraps the LSPManager to provide type-resolved definitions, references,
hover info, and diagnostics as on-demand agent tools.
"""

from __future__ import annotations

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


async def _execute_lsp_call_hierarchy(lsp_manager: Any, args: dict[str, Any]) -> str:
    """Get call hierarchy for a symbol at position.

    Two-step: first prepareCallHierarchy, then fetch calls.
    Shows both incoming (who calls this) and outgoing (what this calls).
    """
    file_path: str = args["file"]
    line: int = args["line"]
    col: int = args.get("col", 0)
    direction: str = args.get("direction", "both")  # incoming, outgoing, or both

    try:
        uri = lsp_manager._to_uri(file_path)  # type: ignore[attr-defined]

        # Step 1: prepare
        prepared = await lsp_manager._get_client_for_file(file_path)
        if not prepared:
            return "No LSP server available for this file"

        # Call prepare on the client
        client = prepared
        raw_items = await client.prepare_call_hierarchy(uri, line, col)
        if not raw_items:
            return f"No callable symbol found at {file_path}:{line}:{col}"

        item = raw_items[0]
        symbol_name = item.get("name", "?")
        symbol_uri = item.get("uri", uri)

        parts = [f"Call hierarchy for '{symbol_name}' at {file_path}:{line}:{col}", ""]

        # Step 2: fetch incoming and/or outgoing
        if direction in ("incoming", "both"):
            incoming = await client.incoming_calls(item)
            if incoming:
                parts.append(f"Called by ({len(incoming)} locations):")
                for call in incoming[:20]:
                    from_loc = call.get("from", {})
                    from_uri = from_loc.get("uri", symbol_uri)
                    if from_uri.startswith("file://"):
                        from_uri = from_uri[7:]
                    from_range = from_loc.get("range", {})
                    from_start = from_range.get("start", {})
                    line_num = from_start.get("line", 0) + 1
                    from_name = from_loc.get("name", "?")
                    parts.append(f"  ← {from_name} at {from_uri}:{line_num}")
                if len(incoming) > 20:
                    parts.append(f"  ... and {len(incoming) - 20} more")
            else:
                parts.append("Called by: (none)")

        if direction in ("outgoing", "both"):
            outgoing = await client.outgoing_calls(item)
            if outgoing:
                parts.append(f"Calls ({len(outgoing)} locations):")
                for call in outgoing[:20]:
                    to_loc = call.get("to", {})
                    to_uri = to_loc.get("uri", symbol_uri)
                    if to_uri.startswith("file://"):
                        to_uri = to_uri[7:]
                    to_range = to_loc.get("range", {})
                    to_start = to_range.get("start", {})
                    line_num = to_start.get("line", 0) + 1
                    to_name = to_loc.get("name", "?")
                    parts.append(f"  → {to_name} at {to_uri}:{line_num}")
                if len(outgoing) > 20:
                    parts.append(f"  ... and {len(outgoing) - 20} more")
            else:
                parts.append("Calls: (none)")

        return "\n".join(parts)

    except Exception as e:
        return f"Call hierarchy error: {e}"


def create_call_hierarchy_tools(lsp_manager: Any) -> list[Tool]:
    """Create call hierarchy tools bound to an LSPManager."""

    async def _call_hierarchy(args: dict[str, Any]) -> Any:
        return await _execute_lsp_call_hierarchy(lsp_manager, args)

    return [
        Tool(
            spec=ToolSpec(
                name="lsp_call_hierarchy",
                description=(
                    "Explore the call hierarchy for a symbol: what calls it "
                    "(incoming) and what it calls (outgoing). Requires a language "
                    "server with callHierarchy support (TypeScript, Python, Rust, Go)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
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
                        "direction": {
                            "type": "string",
                            "enum": ["incoming", "outgoing", "both"],
                            "default": "both",
                            "description": "Which direction of the call graph to show.",
                        },
                    },
                    "required": ["file", "line"],
                },
                danger_level=DangerLevel.SAFE,
            ),
            execute=_call_hierarchy,
            tags=["lsp", "navigation", "call-hierarchy"],
        ),
    ]


# =============================================================================
# Completions
# =============================================================================


async def _execute_lsp_completions(lsp_manager: Any, args: dict[str, Any]) -> str:
    """Get completion suggestions at a cursor position.

    Shows what the language server would suggest at that position,
    including type info and documentation. Useful for understanding
    available APIs or auto-completing a partially-typed expression.
    """
    file_path: str = args["file"]
    line: int = args["line"]
    col: int = args.get("col", 0)
    limit: int = args.get("limit", 20)

    try:
        items = await lsp_manager.get_completions(file_path, line, col)
    except Exception as e:
        return f"LSP completions error: {e}"

    if not items:
        return f"No completions at {file_path}:{line}:{col}"

    lines = [f"Completions at {file_path}:{line}:{col} ({len(items)} available, showing top {limit}):"]
    for item in items[:limit]:
        detail = f" — {item.detail}" if item.detail else ""
        docs = f"\n    {item.documentation[:100]}" if item.documentation else ""
        lines.append(f"  [{item.kind}] {item.label}{detail}{docs}")
    if len(items) > limit:
        lines.append(f"  ... and {len(items) - limit} more")
    return "\n".join(lines)


# =============================================================================
# Incoming / outgoing calls (separate tools)
# =============================================================================


async def _execute_lsp_incoming_calls(lsp_manager: Any, args: dict[str, Any]) -> str:
    """Find what calls the symbol at the given position.

    Step 1: prepare the symbol. Step 2: fetch incoming calls.
    Returns a list of callers with their file locations.
    """
    file_path: str = args["file"]
    line: int = args["line"]
    col: int = args.get("col", 0)

    try:
        client = lsp_manager._get_client_for_file(file_path)
        if not client:
            return "No LSP server available for this file"
        uri = lsp_manager._to_uri(file_path)

        prepared = await client.prepare_call_hierarchy(uri, line, col)
        if not prepared:
            return f"No callable symbol found at {file_path}:{line}:{col}"

        incoming = await client.incoming_calls(prepared[0])
    except Exception as e:
        return f"Incoming calls error: {e}"

    if not incoming:
        return f"No callers found for {prepared[0].get('name', '?')} at {file_path}:{line}:{col}"

    lines = [f"Called by ({len(incoming)} locations):"]
    for call in incoming[:30]:
        from_loc = call.get("from", {})
        from_uri = from_loc.get("uri", "")
        if from_uri.startswith("file://"):
            from_uri = from_uri[7:]
        from_range = from_loc.get("range", {})
        from_start = from_range.get("start", {})
        line_num = from_start.get("line", 0) + 1
        col_num = from_start.get("character", 0) + 1
        from_name = from_loc.get("name", "?")
        container = from_loc.get("containerName", "")
        if container:
            from_name = f"{container}.{from_name}"
        lines.append(f"  ← {from_name} at {from_uri}:{line_num}:{col_num}")
    if len(incoming) > 30:
        lines.append(f"  ... and {len(incoming) - 30} more")
    return "\n".join(lines)


async def _execute_lsp_outgoing_calls(lsp_manager: Any, args: dict[str, Any]) -> str:
    """Find what the symbol at the given position calls.

    Step 1: prepare the symbol. Step 2: fetch outgoing calls.
    Returns a list of callees with their file locations.
    """
    file_path: str = args["file"]
    line: int = args["line"]
    col: int = args.get("col", 0)

    try:
        client = lsp_manager._get_client_for_file(file_path)
        if not client:
            return "No LSP server available for this file"
        uri = lsp_manager._to_uri(file_path)

        prepared = await client.prepare_call_hierarchy(uri, line, col)
        if not prepared:
            return f"No callable symbol found at {file_path}:{line}:{col}"

        outgoing = await client.outgoing_calls(prepared[0])
    except Exception as e:
        return f"Outgoing calls error: {e}"

    if not outgoing:
        return f"{prepared[0].get('name', '?')} calls nothing at {file_path}:{line}:{col}"

    lines = [f"Calls ({len(outgoing)} locations):"]
    for call in outgoing[:30]:
        to_loc = call.get("to", {})
        to_uri = to_loc.get("uri", "")
        if to_uri.startswith("file://"):
            to_uri = to_uri[7:]
        to_range = to_loc.get("range", {})
        to_start = to_range.get("start", {})
        line_num = to_start.get("line", 0) + 1
        col_num = to_start.get("character", 0) + 1
        to_name = to_loc.get("name", "?")
        container = to_loc.get("containerName", "")
        if container:
            to_name = f"{container}.{to_name}"
        lines.append(f"  → {to_name} at {to_uri}:{line_num}:{col_num}")
    if len(outgoing) > 30:
        lines.append(f"  ... and {len(outgoing) - 30} more")
    return "\n".join(lines)


# =============================================================================
# Workspace symbol search
# =============================================================================


async def _execute_workspace_symbol(lsp_manager: Any, args: dict[str, Any]) -> str:
    """Search for symbols by name across the entire workspace.

    Uses the LSP's indexed workspace/symbol request — faster and more
    accurate than grep for finding definitions by name.
    Returns classes, functions, methods, constants, and other symbols
    whose names contain the query string.
    """
    query: str = args["query"]
    limit: int = args.get("limit", 30)

    try:
        symbols = await lsp_manager.search_symbols(query, max_results=limit)
    except Exception as e:
        return f"Workspace symbol search error: {e}"

    if not symbols:
        return f"No symbols matching '{query}'"

    lines = [f"Symbols matching '{query}' ({len(symbols)}):"]
    for sym in symbols:
        uri = sym.uri
        if uri.startswith("file://"):
            uri = uri[7:]
        line = sym.range.start.line + 1
        detail = f" — {sym.detail}" if sym.detail else ""
        container = f" ({sym.container_name})" if sym.container_name else ""
        lines.append(f"  [{sym.kind}] {sym.name}{detail}{container} at {uri}:{line}")
    return "\n".join(lines)


# =============================================================================
# All tools assembled
# =============================================================================


def create_all_lsp_tools(lsp_manager: Any) -> list[Tool]:
    """Create all LSP tools: definitions, references, hover, diagnostics,
    completions, call hierarchy (incoming/outgoing/both), and workspace symbol.

    Combines create_lsp_tools and create_call_hierarchy_tools plus the
    new completions, incoming/outgoing, and workspace_symbol tools.
    """

    async def _completions(args: dict[str, Any]) -> Any:
        return await _execute_lsp_completions(lsp_manager, args)

    async def _incoming(args: dict[str, Any]) -> Any:
        return await _execute_lsp_incoming_calls(lsp_manager, args)

    async def _outgoing(args: dict[str, Any]) -> Any:
        return await _execute_lsp_outgoing_calls(lsp_manager, args)

    async def _workspace_symbol(args: dict[str, Any]) -> Any:
        return await _execute_workspace_symbol(lsp_manager, args)

    position_params = {
        "file": {"type": "string", "description": "File path (absolute or relative to project root)."},
        "line": {"type": "integer", "description": "Line number (0-indexed)."},
        "col": {"type": "integer", "default": 0, "description": "Column number (0-indexed, default 0)."},
    }

    all_tools: list[Tool] = []

    # ---- Completions ----
    all_tools.append(Tool(
        spec=ToolSpec(
            name="lsp_completions",
            description=(
                "Get completion suggestions at a cursor position. "
                "Shows available types, methods, and properties with type info "
                "and documentation. Useful when you want to see what APIs are "
                "available or complete a partially-typed expression."
            ),
            parameters={
                "type": "object",
                "properties": {
                    **position_params,
                    "limit": {
                        "type": "integer",
                        "default": 20,
                        "description": "Maximum completions to return (default 20).",
                    },
                },
                "required": ["file", "line"],
            },
            danger_level=DangerLevel.SAFE,
        ),
        execute=_completions,
        tags=["lsp", "completions"],
    ))

    # ---- Incoming calls ----
    all_tools.append(Tool(
        spec=ToolSpec(
            name="lsp_incoming_calls",
            description=(
                "Find what calls the symbol at the given position. "
                "Shows the full list of callers with their file locations. "
                "Use this when you need to understand all the places that "
                "invoke a function, method, or class."
            ),
            parameters={
                "type": "object",
                "properties": position_params,
                "required": ["file", "line"],
            },
            danger_level=DangerLevel.SAFE,
        ),
        execute=_incoming,
        tags=["lsp", "navigation", "call-hierarchy"],
    ))

    # ---- Outgoing calls ----
    all_tools.append(Tool(
        spec=ToolSpec(
            name="lsp_outgoing_calls",
            description=(
                "Find what the symbol at the given position calls. "
                "Shows the full list of callees with their file locations. "
                "Use this when you need to understand what a function does "
                "by tracing its dependencies."
            ),
            parameters={
                "type": "object",
                "properties": position_params,
                "required": ["file", "line"],
            },
            danger_level=DangerLevel.SAFE,
        ),
        execute=_outgoing,
        tags=["lsp", "navigation", "call-hierarchy"],
    ))

    # ---- Workspace symbol search ----
    all_tools.append(Tool(
        spec=ToolSpec(
            name="workspace_symbol",
            description=(
                "Search for symbols (functions, classes, methods, constants) "
                "by name across the entire workspace using the LSP index. "
                "Much faster and more accurate than grep for finding definitions. "
                "Returns symbol name, kind, container, and location."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Symbol name to search for (partial match, case-insensitive).",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 30,
                        "description": "Maximum results to return (default 30).",
                    },
                },
                "required": ["query"],
            },
            danger_level=DangerLevel.SAFE,
        ),
        execute=_workspace_symbol,
        tags=["lsp", "navigation", "search"],
    ))

    return all_tools
