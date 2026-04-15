"""MCP client manager with lazy loading support.

Wraps multiple MCPClient instances and manages their lifecycle,
including on-demand (lazy) connection for servers that don't need
to be available immediately at startup.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from attocode.integrations.mcp.client import MCPCallResult, MCPClient, MCPTool
from attocode.integrations.mcp.transports import MCPTransport

if TYPE_CHECKING:
    from attocode.integrations.mcp.config import MCPServerConfig
    from attocode.integrations.mcp.meta_tools import MCPMetaTools


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
    client: _TransportAsClient | None = None
    state: ConnectionState = ConnectionState.PENDING
    error: str | None = None


class _TransportAsClient:
    """Wraps an MCPTransport as an MCPClient-compatible object.

    The MCPClientManager and MCPClient expect a `.tools` property and
    `.is_connected` attribute.  This wrapper adapts any MCPTransport to
    that interface so the existing client_manager code works unchanged.
    """

    def __init__(self, transport: MCPTransport, server_name: str) -> None:
        self._transport = transport
        self._server_name = server_name
        self._tools: list[MCPTool] = transport.tools

    @property
    def tools(self) -> list[MCPTool]:
        return self._transport.tools

    @property
    def is_connected(self) -> bool:
        return self._transport.is_connected

    @property
    def server_name(self) -> str:
        return self._server_name

    async def disconnect(self) -> None:
        await self._transport.disconnect()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPCallResult:
        return await self._transport.call_tool(name, arguments)


class MCPClientManager:
    """Manages multiple MCP server connections with lazy loading.

    On startup, only servers with ``lazy_load=False`` are connected
    eagerly.  Lazy servers store their config and connect on first
    tool request via :meth:`ensure_connected`.
    """

    def __init__(self, meta_tools: MCPMetaTools | None = None) -> None:
        self._servers: dict[str, ServerEntry] = {}
        self._meta_tools: MCPMetaTools | None = meta_tools

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
                        return await self._call_and_record(
                            entry.config.name, entry.client, tool_name, arguments,
                        )

        # Tool not found in connected servers -- try lazy connect
        for entry in self._servers.values():
            if entry.state == ConnectionState.PENDING and entry.config.enabled:
                success = await self._connect(entry)
                if success and entry.client is not None:
                    for tool in entry.client.tools:
                        if tool.name == tool_name:
                            return await self._call_and_record(
                                entry.config.name, entry.client, tool_name, arguments,
                            )

        return MCPCallResult(success=False, error=f"Tool not found: {tool_name}")

    async def _call_and_record(
        self,
        server_name: str,
        client: MCPClient,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> MCPCallResult:
        """Call a tool and record statistics in MCPMetaTools if available."""
        start = time.monotonic()
        result = await client.call_tool(tool_name, arguments)
        elapsed_ms = (time.monotonic() - start) * 1000
        if self._meta_tools is not None:
            self._meta_tools.record_call(server_name, tool_name, elapsed_ms, result.success)
        return result

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_tool_summaries(self) -> list[dict[str, str]]:
        """Return lightweight {name, description, server} for all tools on connected servers.

        Lazy (pending) servers are skipped — they'll be connected on first
        tool call via :meth:`call_tool`.  This keeps startup cheap.
        """
        summaries: list[dict[str, str]] = []
        for name, entry in self._servers.items():
            if entry.client is None or entry.state != ConnectionState.CONNECTED:
                continue
            for tool in entry.client.tools:
                summaries.append({
                    "name": tool.name,
                    "description": tool.description,
                    "server": name,
                })
        return summaries

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
        """Low-level connect helper using transport factory. Returns True on success."""
        from .transports import create_transport

        entry.state = ConnectionState.CONNECTING

        try:
            transport_config = entry.config.get_transport_config()
            transport = create_transport(
                transport_config,
                server_name=entry.config.name,
            )
            await transport.connect()
            # Wrap the transport as an MCPClient-compatible object
            entry.client = _TransportAsClient(transport, entry.config.name)
            entry.state = ConnectionState.CONNECTED
            return True
        except Exception as exc:  # noqa: BLE001
            entry.state = ConnectionState.FAILED
            entry.error = str(exc)
            return False
