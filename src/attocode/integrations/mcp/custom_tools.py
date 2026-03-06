"""MCP custom tools registration.

Allows registering custom tools that are exposed via MCP protocol,
enabling external tools to be seamlessly integrated into the agent's
tool registry alongside built-in tools.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from attocode.tools.base import Tool, ToolSpec
from attocode.types.messages import DangerLevel


@dataclass(slots=True)
class MCPCustomToolConfig:
    """Configuration for a custom MCP tool."""

    name: str
    description: str
    parameters: dict[str, Any]
    server_name: str = ""
    danger_level: DangerLevel = DangerLevel.SAFE
    tags: list[str] = field(default_factory=list)
    timeout: float = 30.0


class MCPCustomTools:
    """Registry for custom MCP tools.

    Manages custom tool definitions that bridge between MCP servers
    and the agent's internal tool system. Handles:
    - Tool registration from MCP server discovery
    - Conversion between MCP and internal tool formats
    - Tool lifecycle management (enable/disable)
    - Parameter validation and coercion
    """

    def __init__(self) -> None:
        self._tools: dict[str, MCPCustomToolConfig] = {}
        self._handlers: dict[str, Callable[[dict[str, Any]], Awaitable[Any]]] = {}
        self._enabled: set[str] = set()

    def register(
        self,
        config: MCPCustomToolConfig,
        handler: Callable[[dict[str, Any]], Awaitable[Any]],
    ) -> None:
        """Register a custom MCP tool."""
        self._tools[config.name] = config
        self._handlers[config.name] = handler
        self._enabled.add(config.name)

    def unregister(self, name: str) -> bool:
        """Unregister a tool. Returns True if it existed."""
        if name in self._tools:
            del self._tools[name]
            self._handlers.pop(name, None)
            self._enabled.discard(name)
            return True
        return False

    def enable(self, name: str) -> bool:
        """Enable a registered tool."""
        if name in self._tools:
            self._enabled.add(name)
            return True
        return False

    def disable(self, name: str) -> bool:
        """Disable a tool without unregistering."""
        if name in self._enabled:
            self._enabled.discard(name)
            return True
        return False

    def get_tool(self, name: str) -> Tool | None:
        """Get a tool as an internal Tool object."""
        config = self._tools.get(name)
        handler = self._handlers.get(name)
        if config is None or handler is None:
            return None
        if name not in self._enabled:
            return None

        return Tool(
            spec=ToolSpec(
                name=config.name,
                description=config.description,
                parameters=config.parameters,
                danger_level=config.danger_level,
            ),
            execute=handler,
            tags=config.tags,
        )

    def get_all_tools(self) -> list[Tool]:
        """Get all enabled tools as internal Tool objects."""
        tools = []
        for name in self._enabled:
            tool = self.get_tool(name)
            if tool is not None:
                tools.append(tool)
        return tools

    def list_tools(self) -> list[MCPCustomToolConfig]:
        """List all registered tool configs."""
        return list(self._tools.values())

    def list_enabled(self) -> list[str]:
        """List names of enabled tools."""
        return sorted(self._enabled)

    @property
    def count(self) -> int:
        return len(self._tools)

    @property
    def enabled_count(self) -> int:
        return len(self._enabled)

    def clear(self) -> None:
        """Clear all tools."""
        self._tools.clear()
        self._handlers.clear()
        self._enabled.clear()
