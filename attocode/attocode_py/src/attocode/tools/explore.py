"""Explore codebase tool — hierarchical drill-down navigation."""

from __future__ import annotations

from typing import Any

from attocode.tools.base import Tool, ToolSpec
from attocode.types.messages import DangerLevel


async def _execute_explore(explorer: Any, args: dict[str, Any]) -> str:
    """Execute the explore_codebase tool."""
    path: str = args.get("path", "")
    max_items: int = args.get("max_items", 30)
    importance_threshold: float = args.get("importance_threshold", 0.3)

    result = explorer.explore(
        path,
        max_items=max_items,
        importance_threshold=importance_threshold,
    )
    return explorer.format_result(result)


def create_explore_tool(explorer: Any) -> Tool:
    """Create the explore_codebase tool bound to a HierarchicalExplorer.

    Args:
        explorer: HierarchicalExplorer instance.

    Returns:
        A Tool for hierarchical codebase exploration.
    """

    async def _execute(args: dict[str, Any]) -> Any:
        return await _execute_explore(explorer, args)

    return Tool(
        spec=ToolSpec(
            name="explore_codebase",
            description=(
                "Explore the codebase one directory level at a time. "
                "Returns directories with file counts and languages, and "
                "individual files with importance scores and top symbols. "
                "Use this for drill-down navigation on large codebases "
                "instead of the full repo map. Call with no path for the "
                "root view, then drill into directories of interest."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "default": "",
                        "description": (
                            "Relative directory path to explore. "
                            "Empty string for root. "
                            "Example: 'src/attocode/integrations'"
                        ),
                    },
                    "max_items": {
                        "type": "integer",
                        "default": 30,
                        "description": "Maximum items (dirs + files) to return.",
                    },
                    "importance_threshold": {
                        "type": "number",
                        "default": 0.3,
                        "description": (
                            "Minimum importance score for files to be shown (0.0-1.0)."
                        ),
                    },
                },
            },
            danger_level=DangerLevel.SAFE,
        ),
        execute=_execute,
        tags=["codebase", "exploration"],
    )
