"""Base adapter protocol for code intelligence tools.

Each adapter maps generic benchmark task categories to tool-specific
MCP tool names and arguments.
"""

from __future__ import annotations

from typing import Protocol

from eval.mcp_bench.schema import BenchTask


class ToolAdapter(Protocol):
    """Protocol for mapping benchmark tasks to MCP tool calls."""

    name: str
    server_command: list[str]

    def map_task_to_tool_calls(
        self, task: BenchTask, repo_dir: str,
    ) -> list[tuple[str, dict]]:
        """Map a benchmark task to (tool_name, arguments) pairs.

        Args:
            task: The benchmark task to execute.
            repo_dir: Absolute path to the repository.

        Returns:
            List of (tool_name, tool_arguments) tuples.
        """
        ...
