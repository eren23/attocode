"""Semantic search agent tool."""

from __future__ import annotations

from typing import Any

from attocode.tools.base import Tool, ToolSpec
from attocode.types.messages import DangerLevel


async def _execute_semantic_search(manager: Any, args: dict[str, Any]) -> str:
    """Execute a semantic search query."""
    query: str = args.get("query", "")
    if not query:
        return "Error: 'query' parameter is required."

    top_k: int = args.get("top_k", 10)
    file_filter: str = args.get("file_filter", "")

    results = manager.search(query, top_k=top_k, file_filter=file_filter)
    return manager.format_results(results)


def create_semantic_search_tool(manager: Any) -> Tool:
    """Create the semantic_search tool bound to a SemanticSearchManager.

    Args:
        manager: SemanticSearchManager instance.

    Returns:
        A Tool for semantic code search.
    """

    async def _execute(args: dict[str, Any]) -> Any:
        return await _execute_semantic_search(manager, args)

    return Tool(
        spec=ToolSpec(
            name="semantic_search",
            description=(
                "Search the codebase using natural language queries. "
                "Finds relevant files, functions, and classes by meaning — "
                "not just keyword matching. Requires an embedding provider "
                "(sentence-transformers or OpenAI). Falls back to keyword "
                "matching if no provider is available."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Natural language search query, e.g. "
                            "'authentication middleware' or 'database connection pooling'."
                        ),
                    },
                    "top_k": {
                        "type": "integer",
                        "default": 10,
                        "description": "Number of results to return (default 10).",
                    },
                    "file_filter": {
                        "type": "string",
                        "default": "",
                        "description": (
                            "Optional glob pattern to filter files, e.g. '*.py' or 'src/**/*.ts'."
                        ),
                    },
                },
                "required": ["query"],
            },
            danger_level=DangerLevel.SAFE,
        ),
        execute=_execute,
        tags=["search", "semantic"],
    )
