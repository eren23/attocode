"""ripgrep baseline adapter — text search only.

Provides a baseline comparison by mapping tasks to ripgrep (rg) searches.
Only supports semantic_search and symbol_search; other categories produce
empty tool calls (score 0).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from eval.mcp_bench.schema import BenchTask


@dataclass
class RipgrepAdapter:
    """Maps benchmark tasks to ripgrep CLI invocations via a thin MCP wrapper."""

    name: str = "ripgrep"
    server_command: list[str] = field(
        default_factory=lambda: ["rg", "--json"],
    )

    def map_task_to_tool_calls(
        self, task: BenchTask, repo_dir: str,
    ) -> list[tuple[str, dict]]:
        category = task.category

        if category == "symbol_search":
            pattern = task.target_symbol or task.query
            return [("rg_search", {"pattern": pattern, "path": repo_dir})]

        elif category == "semantic_search":
            query = task.search_query or task.query
            # Split query into keywords and search for the most specific one
            keywords = query.split()
            pattern = max(keywords, key=len) if keywords else query
            return [("rg_search", {"pattern": pattern, "path": repo_dir})]

        elif category == "orientation":
            # Search for README, main entry files
            return [("rg_search", {"pattern": "^# ", "path": repo_dir, "glob": "README*"})]

        # No coverage for: dependency, impact, architecture, security, dead_code
        return []
