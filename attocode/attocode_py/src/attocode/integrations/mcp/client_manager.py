"""MCP client manager with lazy loading support.

Wraps multiple MCPClient instances and manages their lifecycle,
including on-demand (lazy) connection for servers that don't need
to be available immediately at startup.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from attocode.integrations.mcp.client import MCPCallResult, MCPClient, MCPTool
from attocode.integrations.mcp.config import MCPServerConfig


class ConnectionState(StrEnum):
    """Connection lifecycle state for an MCP server."""

    PENDING = "pending"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    FAILED = "failed"
    DISCONNECTED = "disconnected"


@dataclass(slots=True)
class ServerEntry:
    """Internal bookkeeping for a managed MCP server."""

    config: MCPServerConfig
    client: MCPClient | None = None
    state: ConnectionState = ConnectionState.PENDING
    error: str | None = None


class MCPClientManager:
    """Manages multiple MCP server connections with lazy loading.

    On startup, only servers with ``lazy_load=False`` are connected
    eagerly.  Lazy servers store their config and connect on first
    tool request via :meth:`ensure_connected`.
    """

    def __init__(self) -> None:
        self._servers: dict[str, ServerEntry] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, config: MCPServerConfig) -> None:
        """Register a server configuration.

        Does not connect -- call :meth:`connect_eager` afterwards.
        """
        self._servers[config.name] = ServerEntry(config=config)

    def register_all(self, configs: list[MCPServerConfig]) -> None:
        """Register multiple server configurations at once."""
        for cfg in configs:
            self.register(cfg)

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect_eager(self) -> list[str]:
        """Connect all non-lazy, enabled servers.

        Returns the names of servers that were successfully connected.
        """
        connected: list[str] = []
        for name, entry in self._servers.items():
            if not entry.config.enabled:
                entry.state = ConnectionState.DISCONNECTED
                continue
            if entry.config.lazy_load:
                # Stay in PENDING -- will be connected on demand
                continue
            success = await self._connect(entry)
            if success:
                connected.append(name)
        return connected

    async def ensure_connected(self, server_name: str) -> bool:
        """Ensure the named server is connected.

        If the server is lazy and hasn't been connected yet, this
        triggers the connection.  Returns True on success.
        """
        entry = self._servers.get(server_name)
        if entry is None:
            return False

        if entry.state == ConnectionState.CONNECTED:
            return True

        if not entry.config.enabled:
            return False

        return await self._connect(entry)

    async def disconnect_all(self) -> None:
        """Disconnect all connected servers."""
        for entry in self._servers.values():
            if entry.client is not None and entry.state == ConnectionState.CONNECTED:
                await entry.client.disconnect()
                entry.state = ConnectionState.DISCONNECTED
                entry.client = None

    async def disconnect(self, server_name: str) -> None:
        """Disconnect a single server by name."""
        entry = self._servers.get(server_name)
        if entry is None:
            return
        if entry.client is not None and entry.state == ConnectionState.CONNECTED:
            await entry.client.disconnect()
            entry.state = ConnectionState.DISCONNECTED
            entry.client = None

    # ------------------------------------------------------------------
    # Tool access
    # ------------------------------------------------------------------

    def get_all_tools(self) -> list[MCPTool]:
        """Return tools from all currently-connected servers."""
        tools: list[MCPTool] = []
        for entry in self._servers.values():
            if entry.client is not None and entry.state == ConnectionState.CONNECTED:
                tools.extend(entry.client.tools)
        return tools

    def get_tools_for_server(self, server_name: str) -> list[MCPTool]:
        """Return tools from a specific connected server."""
        entry = self._servers.get(server_name)
        if entry is None or entry.client is None:
            return []
        return entry.client.tools

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> MCPCallResult:
        """Call a tool by name, connecting its server lazily if needed.

        Searches all servers for a matching tool.  If the owning server
        is lazy and not yet connected, :meth:`ensure_connected` is
        called first.
        """
        # First check already-connected servers
        for entry in self._servers.values():
            if entry.client is not None and entry.state == ConnectionState.CONNECTED:
                for tool in entry.client.tools:
                    if tool.name == tool_name:
                        return await entry.client.call_tool(tool_name, arguments)

        # Tool not found in connected servers -- try lazy connect
        for entry in self._servers.values():
            if entry.state == ConnectionState.PENDING and entry.config.enabled:
                success = await self._connect(entry)
                if success and entry.client is not None:
                    for tool in entry.client.tools:
                        if tool.name == tool_name:
                            return await entry.client.call_tool(
                                tool_name, arguments
                            )

        return MCPCallResult(success=False, error=f"Tool not found: {tool_name}")

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_state(self, server_name: str) -> ConnectionState | None:
        """Return the connection state for a server, or None if unknown."""
        entry = self._servers.get(server_name)
        return entry.state if entry else None

    @property
    def server_names(self) -> list[str]:
        """Names of all registered servers."""
        return list(self._servers)

    @property
    def connected_count(self) -> int:
        """Number of currently-connected servers."""
        return sum(
            1
            for e in self._servers.values()
            if e.state == ConnectionState.CONNECTED
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _connect(self, entry: ServerEntry) -> bool:
        """Low-level connect helper.  Returns True on success."""
        entry.state = ConnectionState.CONNECTING
        client = MCPClient(
            server_command=entry.config.command,
            server_args=entry.config.args,
            server_name=entry.config.name,
            env=entry.config.env or None,
        )
        try:
            await client.connect()
            entry.client = client
            entry.state = ConnectionState.CONNECTED
            return True
        except Exception as exc:  # noqa: BLE001
            entry.state = ConnectionState.FAILED
            entry.error = str(exc)
            return False
