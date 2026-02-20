"""MCP tool search index.

Provides keyword-based search over all available MCP tools so
the agent can discover tools by natural-language queries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from attocode.integrations.mcp.client import MCPTool
from attocode.tools.base import Tool, ToolSpec
from attocode.types.messages import DangerLevel


@dataclass(slots=True)
class MCPToolMatch:
    """A single search result from the tool search index."""

    tool_name: str
    server_name: str
    description: str
    relevance_score: int  # 0-100


# Regex to split on non-alphanumeric boundaries (underscores, hyphens, spaces, etc.)
_SPLIT_RE = re.compile(r"[^a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    """Lowercase and split text into keyword tokens."""
    return {t for t in _SPLIT_RE.split(text.lower()) if len(t) >= 2}


class MCPToolSearchIndex:
    """Keyword-based search index over MCP tools.

    Each tool is indexed by tokens extracted from its name and
    description.  The :meth:`search` method ranks tools by how many
    query tokens match and where (name matches weighted higher).
    """

    def __init__(self) -> None:
        self._tools: list[MCPTool] = []
        # Pre-computed token sets for each tool (parallel to _tools)
        self._name_tokens: list[set[str]] = []
        self._desc_tokens: list[set[str]] = []

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    def add_tool(self, tool: MCPTool) -> None:
        """Add a single tool to the index."""
        self._tools.append(tool)
        self._name_tokens.append(_tokenize(tool.name))
        self._desc_tokens.append(_tokenize(tool.description))

    def add_tools(self, tools: list[MCPTool]) -> None:
        """Bulk-add tools to the index."""
        for t in tools:
            self.add_tool(t)

    def clear(self) -> None:
        """Remove all tools from the index."""
        self._tools.clear()
        self._name_tokens.clear()
        self._desc_tokens.clear()

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str, limit: int = 5) -> list[MCPToolMatch]:
        """Search for tools matching *query*.

        Scoring:
        - Each query token that matches a **name** token: +30 points
        - Each query token that matches a **description** token: +15 points
        - Substring match in name: +20 points per token
        - Substring match in description: +10 points per token
        - Score is clamped to 0-100.

        Returns up to *limit* results sorted by relevance descending.
        """
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        scored: list[tuple[int, MCPTool]] = []
        for i, tool in enumerate(self._tools):
            name_toks = self._name_tokens[i]
            desc_toks = self._desc_tokens[i]
            score = 0

            tool_name_lower = tool.name.lower()
            tool_desc_lower = tool.description.lower()

            for qt in query_tokens:
                # Exact token matches
                if qt in name_toks:
                    score += 30
                if qt in desc_toks:
                    score += 15

                # Substring matches (for partial / compound words)
                if qt in tool_name_lower:
                    score += 20
                if qt in tool_desc_lower:
                    score += 10

            if score > 0:
                scored.append((min(score, 100), tool))

        scored.sort(key=lambda x: x[0], reverse=True)

        return [
            MCPToolMatch(
                tool_name=tool.name,
                server_name=tool.server_name,
                description=tool.description,
                relevance_score=score,
            )
            for score, tool in scored[:limit]
        ]


# ------------------------------------------------------------------
# Agent-callable tool factory
# ------------------------------------------------------------------


def create_mcp_tool_search_tool(search_index: MCPToolSearchIndex) -> Tool:
    """Create a Tool that the agent can invoke to search MCP tools.

    The tool accepts ``{"query": "...", "limit": N}`` and returns a
    JSON-formatted list of matches.
    """
    import json as _json

    async def _execute(args: dict[str, Any]) -> Any:
        query = args.get("query", "")
        limit = args.get("limit", 5)
        matches = search_index.search(query, limit=limit)
        return _json.dumps(
            [
                {
                    "tool_name": m.tool_name,
                    "server_name": m.server_name,
                    "description": m.description,
                    "relevance_score": m.relevance_score,
                }
                for m in matches
            ],
            indent=2,
        )

    spec = ToolSpec(
        name="mcp_tool_search",
        description=(
            "Search for MCP tools by keyword. Returns matching tools "
            "with relevance scores."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query to match against tool names and descriptions.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default 5).",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
        danger_level=DangerLevel.SAFE,
    )

    return Tool(spec=spec, execute=_execute, tags=["mcp", "search"])
