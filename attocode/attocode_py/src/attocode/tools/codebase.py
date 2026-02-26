"""Codebase context tools: repo map and tree view."""

from __future__ import annotations

from typing import Any

from attocode.tools.base import Tool, ToolSpec
from attocode.types.messages import DangerLevel

# detail_level -> max_tokens mapping (None = unlimited)
_DETAIL_LEVEL_TOKENS: dict[str, int | None] = {
    "summary": 4000,
    "standard": 12000,
    "full": None,
}


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
