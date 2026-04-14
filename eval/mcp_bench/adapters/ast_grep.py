"""ast-grep adapter — structural search baseline.

Covers symbol_search and some orientation tasks via ast-grep patterns.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from eval.mcp_bench.schema import BenchTask


@dataclass
class AstGrepAdapter:
    """Maps benchmark tasks to ast-grep MCP server tools."""

    name: str = "ast-grep"
    server_command: list[str] = field(
        default_factory=lambda: ["ast-grep", "lsp"],
    )

    def map_task_to_tool_calls(
        self, task: BenchTask, repo_dir: str,
    ) -> list[tuple[str, dict]]:
        category = task.category

        if category == "symbol_search":
            symbol = task.target_symbol or task.query
            return [("sg_search", {"pattern": symbol, "path": repo_dir})]

        elif category == "semantic_search":
            query = task.search_query or task.query
            return [("sg_search", {"pattern": query, "path": repo_dir})]

        # Limited coverage — ast-grep is structural, not semantic
        return []
