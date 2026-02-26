"""Codebase context tools: repo map, tree view, and overview."""

from __future__ import annotations

import os
from typing import Any

from attocode.tools.base import Tool, ToolSpec
from attocode.types.messages import DangerLevel

# detail_level -> max_tokens mapping (None = unlimited)
_DETAIL_LEVEL_TOKENS: dict[str, int | None] = {
    "summary": 4000,
    "standard": 12000,
    "full": None,
}

# Valid symbol type filters
_SYMBOL_TYPES = {"function", "class", "interface", "type", "variable", "enum"}


async def _get_repo_map(manager: Any, args: dict[str, Any]) -> str:
    """Generate a repository map with file structure and key symbols."""
    detail_level: str = args.get("detail_level", "full")
    max_tokens = _DETAIL_LEVEL_TOKENS.get(detail_level)

    repo_map = manager.get_repo_map(include_symbols=True, max_tokens=max_tokens)

    parts = [
        f"Files: {repo_map.total_files} | "
        f"Lines: {repo_map.total_lines} | "
        f"Languages: {', '.join(sorted(repo_map.languages.keys()))}",
        "",
        "```",
        repo_map.tree,
        "```",
    ]
    if repo_map.symbols:
        sym_cap = 10 if detail_level == "summary" else 25
        parts.append("")
        parts.append("## Key Symbols")
        for rel_path, syms in list(repo_map.symbols.items())[:sym_cap]:
            parts.append(f"- `{rel_path}`: {', '.join(syms)}")

    return "\n".join(parts)


async def _get_tree_view(manager: Any, args: dict[str, Any]) -> str:
    """Get a lightweight tree view of the repository."""
    max_depth = args.get("max_depth", 3)
    tree = manager.get_tree_view(max_depth=max_depth)
    return tree if tree else "(no files discovered)"


async def _execute_codebase_overview(manager: Any, args: dict[str, Any]) -> str:
    """Execute the codebase_overview tool.

    Three modes:
    - summary: File tree with counts and entry points (~200 tokens)
    - symbols (default): File tree + exported symbol names per file (~2-5K tokens)
    - full: Symbol details with params, return types, visibility (up to 10K tokens)
    """
    from attocode.integrations.utilities.token_estimate import estimate_tokens

    mode: str = args.get("mode", "symbols")
    directory: str = args.get("directory", "")
    symbol_type: str = args.get("symbol_type", "")
    max_tokens: int = args.get("max_tokens", 10000)
    force_refresh: bool = args.get("force_refresh", False)

    if mode not in ("summary", "symbols", "full"):
        return f"Error: mode must be 'summary', 'symbols', or 'full', got '{mode}'"
    if symbol_type and symbol_type not in _SYMBOL_TYPES:
        return (
            f"Error: symbol_type must be one of {sorted(_SYMBOL_TYPES)}, "
            f"got '{symbol_type}'"
        )

    # Optionally re-analyze for freshness after edits
    if force_refresh:
        try:
            manager.discover_files()
        except Exception:
            pass

    # Ensure files are discovered
    if not manager._files:
        manager.discover_files()

    # Filter files to directory subtree if specified
    files = manager._files
    if directory:
        # Normalize: strip trailing slash, normalize separators
        dir_prefix = directory.rstrip("/").rstrip(os.sep)
        files = [
            f for f in files
            if f.relative_path == dir_prefix
            or f.relative_path.startswith(dir_prefix + "/")
            or f.relative_path.startswith(dir_prefix + os.sep)
        ]
        if not files:
            return f"No files found under '{directory}'."

    # --- summary mode: lightweight tree + stats ---
    if mode == "summary":
        return _build_summary(manager, files, max_tokens)

    # --- symbols / full mode: need AST data ---
    from attocode.integrations.context.codebase_ast import parse_file

    # Collect per-file AST info
    file_asts: dict[str, Any] = {}
    for f in files:
        if f.language not in ("python", "javascript", "typescript"):
            continue
        cached = manager._ast_cache.get(f.relative_path)
        if cached is not None:
            file_asts[f.relative_path] = cached
        else:
            try:
                ast = parse_file(f.path)
                manager._ast_cache[f.relative_path] = ast
                file_asts[f.relative_path] = ast
            except Exception:
                pass

    if mode == "symbols":
        return _build_symbols_view(manager, files, file_asts, symbol_type, max_tokens)

    # mode == "full"
    return _build_full_view(manager, files, file_asts, symbol_type, max_tokens)


def _build_summary(manager: Any, files: list[Any], max_tokens: int) -> str:
    """Build summary mode output: file tree with counts and entry points."""
    from attocode.integrations.utilities.token_estimate import estimate_tokens

    # Compute stats
    languages: dict[str, int] = {}
    total_lines = 0
    entry_points: list[str] = []
    for f in files:
        if f.language:
            languages[f.language] = languages.get(f.language, 0) + 1
        total_lines += f.line_count
        name = os.path.basename(f.relative_path).lower()
        if name in ("main.py", "main.ts", "app.py", "app.ts", "cli.py", "cli.ts",
                     "index.ts", "index.js", "__main__.py"):
            entry_points.append(f.relative_path)

    parts = [
        "# Codebase Overview (summary)",
        "",
        f"**{len(files)} files** | **{total_lines:,} lines** | "
        f"Languages: {', '.join(f'{lang} ({cnt})' for lang, cnt in sorted(languages.items(), key=lambda x: -x[1]))}",
    ]

    if entry_points:
        parts.append("")
        parts.append("## Entry Points")
        for ep in entry_points:
            parts.append(f"- `{ep}`")

    # Compact directory tree (depth 2)
    parts.append("")
    parts.append("## Directory Structure")
    tree = manager.get_tree_view(max_depth=2)
    parts.append(f"```\n{tree}\n```")

    result = "\n".join(parts)
    # Truncate if over budget
    if estimate_tokens(result) > max_tokens:
        lines = result.split("\n")
        while lines and estimate_tokens("\n".join(lines)) > max_tokens:
            lines.pop()
        lines.append("... (truncated)")
        result = "\n".join(lines)

    return result


def _build_symbols_view(
    manager: Any,
    files: list[Any],
    file_asts: dict[str, Any],
    symbol_type: str,
    max_tokens: int,
) -> str:
    """Build symbols mode: file tree + exported symbol names per file."""
    from attocode.integrations.utilities.token_estimate import estimate_tokens

    parts = [
        "# Codebase Overview (symbols)",
        "",
    ]

    # Stats line
    languages: dict[str, int] = {}
    total_lines = 0
    for f in files:
        if f.language:
            languages[f.language] = languages.get(f.language, 0) + 1
        total_lines += f.line_count

    parts.append(
        f"**{len(files)} files** | **{total_lines:,} lines** | "
        f"Languages: {', '.join(sorted(languages.keys()))}"
    )
    parts.append("")

    # Files with their symbols
    parts.append("## Files & Symbols")
    token_count = estimate_tokens("\n".join(parts))

    for f in files:
        ast = file_asts.get(f.relative_path)
        if ast is None:
            # Non-parseable file: just show name
            entry = f"- `{f.relative_path}` ({f.line_count}L, {f.language or 'unknown'})"
        else:
            symbols = _filter_symbols(ast, symbol_type, names_only=True)
            sym_str = ", ".join(symbols[:8])
            suffix = f"  [{sym_str}]" if sym_str else ""
            entry = f"- `{f.relative_path}` ({f.line_count}L){suffix}"

        entry_tokens = estimate_tokens(entry)
        if token_count + entry_tokens > max_tokens:
            remaining = len(files) - len([
                p for p in parts if p.startswith("- `")
            ])
            parts.append(f"... +{remaining} more files (token limit reached)")
            break

        parts.append(entry)
        token_count += entry_tokens

    return "\n".join(parts)


def _build_full_view(
    manager: Any,
    files: list[Any],
    file_asts: dict[str, Any],
    symbol_type: str,
    max_tokens: int,
) -> str:
    """Build full mode: symbol details with params, return types, visibility."""
    from attocode.integrations.utilities.token_estimate import estimate_tokens

    parts = [
        "# Codebase Overview (full)",
        "",
    ]

    languages: dict[str, int] = {}
    total_lines = 0
    for f in files:
        if f.language:
            languages[f.language] = languages.get(f.language, 0) + 1
        total_lines += f.line_count

    parts.append(
        f"**{len(files)} files** | **{total_lines:,} lines** | "
        f"Languages: {', '.join(sorted(languages.keys()))}"
    )
    parts.append("")

    token_count = estimate_tokens("\n".join(parts))
    files_shown = 0

    for f in files:
        ast = file_asts.get(f.relative_path)
        if ast is None:
            continue

        symbols = _filter_symbols(ast, symbol_type, names_only=False)
        if not symbols:
            continue

        file_block_parts = [f"### `{f.relative_path}` ({f.line_count}L)"]
        for sym in symbols:
            file_block_parts.append(sym)

        file_block = "\n".join(file_block_parts) + "\n"
        block_tokens = estimate_tokens(file_block)

        if token_count + block_tokens > max_tokens:
            parts.append(f"... (token limit reached, {len(files) - files_shown} files omitted)")
            break

        parts.append(file_block)
        token_count += block_tokens
        files_shown += 1

    return "\n".join(parts)


def _filter_symbols(
    ast: Any,
    symbol_type: str,
    *,
    names_only: bool = True,
) -> list[str]:
    """Extract symbols from a FileAST, optionally filtered by type.

    Args:
        ast: FileAST instance.
        symbol_type: Filter to this kind ("function", "class", etc.), or "" for all.
        names_only: If True, return just names. If False, return detailed signatures.
    """
    results: list[str] = []

    include_functions = not symbol_type or symbol_type == "function"
    include_classes = not symbol_type or symbol_type == "class"
    include_variables = not symbol_type or symbol_type == "variable"
    # interface/type/enum apply to TS-like ASTs; we treat them as classes
    include_interface = not symbol_type or symbol_type in ("interface", "type", "enum")

    if include_functions:
        for func in ast.functions:
            if names_only:
                results.append(func.name)
            else:
                params_str = ", ".join(func.params[:6])
                if len(func.params) > 6:
                    params_str += ", ..."
                ret = f" -> {func.return_type}" if func.return_type else ""
                prefix = "async " if func.is_async else ""
                vis = f"[{func.visibility}] " if func.visibility != "public" else ""
                results.append(f"- {vis}{prefix}def **{func.name}**({params_str}){ret}")

    if include_classes:
        for cls in ast.classes:
            if names_only:
                results.append(cls.name)
            else:
                bases = f"({', '.join(cls.bases)})" if cls.bases else ""
                method_names = [m.name for m in cls.methods[:6]]
                methods_str = ", ".join(method_names)
                if len(cls.methods) > 6:
                    methods_str += f", ... +{len(cls.methods) - 6} more"
                results.append(
                    f"- class **{cls.name}**{bases}  "
                    f"methods: [{methods_str}]"
                )

    if include_variables and hasattr(ast, "top_level_vars"):
        for var in ast.top_level_vars:
            if names_only:
                results.append(var)
            else:
                results.append(f"- var **{var}**")

    # For interface/type/enum: these would show up as classes in the AST
    # with specific decorators or naming patterns. The class filter above
    # already captures them if present.

    return results


def create_codebase_overview_tool(manager: Any) -> Tool:
    """Create the codebase_overview tool bound to a CodebaseContextManager.

    This tool provides a unified entry point for codebase exploration using
    pre-analyzed AST data. It avoids the need for expensive glob + read_file
    spam when the agent needs broad understanding of the codebase.

    Args:
        manager: CodebaseContextManager instance.

    Returns:
        A Tool for the LLM to query the codebase structure.
    """

    async def _execute(args: dict[str, Any]) -> Any:
        return await _execute_codebase_overview(manager, args)

    return Tool(
        spec=ToolSpec(
            name="codebase_overview",
            description=(
                "Get an overview of the codebase using pre-analyzed AST data. "
                "Use this BEFORE glob/read_file for broad exploration questions "
                "like 'what services exist?' or 'show me all classes in src/'. "
                "A summary repo map is already in your context from startup; "
                "use this tool for filtered, refreshed, or more detailed views.\n"
                "\n"
                "Modes:\n"
                "- 'summary': File tree with counts and entry points (~200 tokens)\n"
                "- 'symbols' (default): File tree + exported symbol names per file (~2-5K tokens)\n"
                "- 'full': Symbol details with params, return types, visibility (up to 10K tokens)"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["summary", "symbols", "full"],
                        "default": "symbols",
                        "description": (
                            "Level of detail. 'summary' for quick stats, "
                            "'symbols' for file list with symbol names, "
                            "'full' for complete signatures."
                        ),
                    },
                    "directory": {
                        "type": "string",
                        "description": (
                            "Filter to a subtree (e.g. 'src/integrations/context'). "
                            "Omit for the entire repository."
                        ),
                    },
                    "symbol_type": {
                        "type": "string",
                        "enum": ["function", "class", "interface", "type", "variable", "enum"],
                        "description": (
                            "Filter symbols by kind. Omit to show all symbol types."
                        ),
                    },
                    "max_tokens": {
                        "type": "integer",
                        "default": 10000,
                        "description": "Cap output size in estimated tokens (default: 10000).",
                    },
                    "force_refresh": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "Re-run file discovery before returning. "
                            "Use after making edits to get fresh data."
                        ),
                    },
                },
            },
            danger_level=DangerLevel.SAFE,
        ),
        execute=_execute,
        tags=["codebase", "context", "overview"],
    )


def create_codebase_tools(manager: Any) -> list[Tool]:
    """Create codebase context tools bound to the given manager.

    Args:
        manager: CodebaseContextManager instance.

    Returns:
        List of Tool objects for repo map and tree view.
    """

    async def _repo_map(args: dict[str, Any]) -> Any:
        return await _get_repo_map(manager, args)

    async def _tree_view(args: dict[str, Any]) -> Any:
        return await _get_tree_view(manager, args)

    return [
        Tool(
            spec=ToolSpec(
                name="get_repo_map",
                description=(
                    "Get a repository map showing file structure, languages, "
                    "line counts, and key symbols (classes, functions). Use this to "
                    "understand the codebase layout before making changes. "
                    "A summary-level map is already injected at startup; use "
                    "detail_level='standard' or 'full' for more detail on demand."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "detail_level": {
                            "type": "string",
                            "enum": ["summary", "standard", "full"],
                            "default": "full",
                            "description": (
                                "Level of detail: 'summary' (~4K tokens), "
                                "'standard' (~12K tokens), 'full' (no limit)."
                            ),
                        },
                    },
                },
                danger_level=DangerLevel.SAFE,
            ),
            execute=_repo_map,
            tags=["codebase", "context"],
        ),
        Tool(
            spec=ToolSpec(
                name="get_tree_view",
                description=(
                    "Get a lightweight directory tree view of the repository. "
                    "Faster than get_repo_map but without symbol information."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "max_depth": {
                            "type": "integer",
                            "default": 3,
                            "description": "Maximum directory depth to display.",
                        },
                    },
                },
                danger_level=DangerLevel.SAFE,
            ),
            execute=_tree_view,
            tags=["codebase", "context"],
        ),
    ]
