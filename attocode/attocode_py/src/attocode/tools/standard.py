"""Standard tool registry creation."""

from __future__ import annotations

from typing import Any

from attocode.tools.bash import create_bash_tool
from attocode.tools.file_ops import create_file_tools
from attocode.tools.registry import ToolRegistry
from attocode.tools.search import create_search_tools


def create_standard_registry(
    working_dir: str | None = None,
    *,
    bash_timeout: float = 120.0,
    sandbox: Any = None,
    enable_spawn_agent: bool = False,
    provider_name: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> ToolRegistry:
    """Create a standard tool registry with all built-in tools."""
    registry = ToolRegistry()
    for tool in create_file_tools(working_dir):
        registry.register(tool)
    registry.register(create_bash_tool(working_dir, bash_timeout, sandbox=sandbox))
    for tool in create_search_tools(working_dir):
        registry.register(tool)

    if enable_spawn_agent:
        from attocode.tools.agent import create_spawn_agent_tool
        registry.register(create_spawn_agent_tool(
            working_dir, provider_name, api_key, model,
        ))

    return registry
