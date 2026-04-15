"""MCP transport layer — stdio, SSE, and StreamableHTTP.

Extends the base MCPClient with two additional transport types:

1. StdioTransport — existing stdio-based communication (already in client.py)
2. SSETransport — Server-Sent Events transport (server pushes events over HTTP)
3. StreamableHTTPTransport — Anthropic's StreamableHTTP protocol with
   proper session management, polling, and path routing

Each transport implements the same interface so callers don't need to know
which transport is being used.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from .client import MCPCallResult, MCPTool

logger = logging.getLogger(__name__)


# =============================================================================
# Transport interface
# =============================================================================


class MCPTransport(ABC):
    """Abstract base for MCP transports."""

    @abstractmethod
    async def connect(self) -> None:
        """Initialize the transport and list available tools."""
        ...

    @abstractmethod
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPCallResult:
        """Call a tool by name."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the transport."""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        ...

    @property
    @abstractmethod
    def tools(self) -> list[MCPTool]:
        """Available tools from this transport."""
        ...

    @property
    @abstractmethod
    def transport_type(self) -> str:
        """Identifier: 'stdio', 'sse', 'http'."""
        ...


# =============================================================================
# SSE Transport
# =============================================================================


class SSETransport(MCPTransport):
    """Server-Sent Events transport for MCP.

    Uses httpx to POST tool calls to the server and receive results
    as SSE events.  Also receives server -> client notifications via
    a background SSE listener.

    The server URL is the base endpoint. Tool calls are POSTed to
    ``{base}/tools/call`` and notifications are received via
    ``{base}/events`` (SSE stream).
    """

    def __init__(
        self,
        base_url: str,
        server_name: str = "",
        headers: dict[str, str] | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._server_name = server_name
        self._headers = headers or {}
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._tools: list[MCPTool] = []
        self._event_task: asyncio.Task[None] | None = None
        self._event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._listeners: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def tools(self) -> list[MCPTool]:
        return list(self._tools)

    @property
    def transport_type(self) -> str:
        return "sse"

    async def connect(self) -> None:
        """Connect to the SSE MCP server and initialize."""
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers,
            timeout=httpx.Timeout(self._timeout),
        )

        # Initialize via JSON-RPC POST
        init_result = await self._rpc_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "attocode", "version": "0.1.0"},
        })

        if init_result is None:
            raise ConnectionError(f"SSE MCP server at {self._base_url} did not respond to initialize")

        # Send initialized notification
        await self._rpc_notify("notifications/initialized", {})

        # List tools
        tools_result = await self._rpc_request("tools/list", {})
        if tools_result and "tools" in tools_result:
            self._tools = [
                MCPTool(
                    name=t["name"],
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                    server_name=self._server_name,
                )
                for t in tools_result["tools"]
            ]

        # Start SSE event listener
        self._event_task = asyncio.create_task(self._sse_listener())

        self._connected = True
        logger.info("SSE MCP connected: %s (%d tools)", self._server_name, len(self._tools))

    async def _rpc_request(self, method: str, params: dict[str, Any]) -> Any:
        """Send a JSON-RPC request over HTTP POST."""
        if self._client is None:
            return None
        req_id = str(uuid.uuid4())
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }
        try:
            response = await self._client.post(
                "/",  # MCP SSE servers typically use root endpoint
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            if "error" in result:
                logger.warning("SSE MCP RPC error: %s", result["error"])
                return None
            return result.get("result")
        except httpx.HTTPError as exc:
            logger.warning("SSE MCP HTTP error: %s", exc)
            return None

    async def _rpc_notify(self, method: str, params: dict[str, Any]) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if self._client is None:
            return
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        try:
            await self._client.post("/", json=payload)
        except httpx.HTTPError as exc:
            logger.debug("SSE MCP notification error (non-fatal): %s", exc)

    async def _sse_listener(self) -> None:
        """Background task reading SSE events from the server."""
        if self._client is None:
            return
        try:
            async with self._client.stream("GET", "/events") as stream:
                async for line in stream.aiter_lines():
                    if not line.strip():
                        continue
                    if line.startswith("data: "):
                        data = line[6:]
                        try:
                            event = json.loads(data)
                            await self._handle_event(event)
                        except json.JSONDecodeError:
                            pass
        except httpx.HTTPError as exc:
            logger.warning("SSE listener disconnected: %s", exc)
        except asyncio.CancelledError:
            pass

    async def _handle_event(self, event: dict[str, Any]) -> None:
        """Route an incoming SSE event to the appropriate listener."""
        method = event.get("method", "")
        params = event.get("params", {})
        # Route to specific listeners
        if method in self._listeners:
            await self._listeners[method].put(params)
        # Also put in general queue
        await self._event_queue.put(event)

    def add_listener(self, method: str) -> asyncio.Queue[dict[str, Any]]:
        """Subscribe to a specific method's events. Returns the queue."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._listeners[method] = queue
        return queue

    def remove_listener(self, method: str) -> None:
        self._listeners.pop(method, None)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPCallResult:
        """Call a tool via HTTP POST."""
        if not self._connected:
            return MCPCallResult(success=False, error="Not connected")

        result = await self._rpc_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })

        if result is None:
            return MCPCallResult(success=False, error="No response from server")

        content = result.get("content", [])
        if content and isinstance(content, list):
            text_parts = [
                c.get("text", "")
                for c in content
                if c.get("type") == "text"
            ]
            return MCPCallResult(success=True, result="\n".join(text_parts))

        return MCPCallResult(success=True, result=str(result))

    async def disconnect(self) -> None:
        """Close the SSE connection."""
        if self._event_task:
            self._event_task.cancel()
            try:
                await self._event_task
            except asyncio.CancelledError:
                pass
            self._event_task = None

        if self._client:
            await self._client.aclose()
            self._client = None

        self._connected = False
        self._listeners.clear()


# =============================================================================
# StreamableHTTP Transport
# =============================================================================


@dataclass
class HTTPSession:
    """A single StreamableHTTP session with polling endpoint."""

    session_id: str
    poll_url: str
    send_url: str


class StreamableHTTPTransport(MCPTransport):
    """StreamableHTTP transport for MCP (Anthropic's HTTP streaming protocol).

    Uses a session-based approach:
    1. POST to /stream to initiate a session → get session_id + poll URL
    2. POST tool calls to /send/{session_id}
    3. Poll /receive/{session_id} for responses

    Supports both streaming (SSE) and polling modes.  Falls back to polling
    if the server doesn't advertise SSE support.

    Reference: https://modelcontextprotocol.io/specification/basic/streamable-http
    """

    def __init__(
        self,
        base_url: str,
        server_name: str = "",
        headers: dict[str, str] | None = None,
        timeout: float = 120.0,
        poll_interval: float = 0.5,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._server_name = server_name
        self._headers = headers or {}
        self._timeout = timeout
        self._poll_interval = poll_interval
        self._client: httpx.AsyncClient | None = None
        self._session: HTTPSession | None = None
        self._tools: list[MCPTool] = []
        self._connected = False
        self._receive_task: asyncio.Task[None] | None = None
        self._response_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._pending_requests: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._stream_mode = True  # Try SSE first, fall back to polling

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def tools(self) -> list[MCPTool]:
        return list(self._tools)

    @property
    def transport_type(self) -> str:
        return "http"

    async def connect(self) -> None:
        """Initialize an HTTP MCP session."""
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers,
            timeout=httpx.Timeout(self._timeout),
        )

        # Step 1: Send initial POST to establish session
        session_id = str(uuid.uuid4())
        payload = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "attocode", "version": "0.1.0"},
            },
            "id": session_id,
        }

        try:
            # Try the stream endpoint first
            response = await self._client.post(
                "/mcp/stream",
                json=payload,
            )
            response.raise_for_status()

            # Determine session URL from response headers
            # StreamableHTTP servers return a session ID in headers or body
            result = response.json()

            # Extract session from result
            session_info = result.get("session", {})
            if isinstance(session_info, dict):
                session_id = session_info.get("sessionId", session_id)
            elif isinstance(session_info, str):
                session_id = session_info

            self._session = HTTPSession(
                session_id=session_id,
                poll_url=f"/mcp/receive/{session_id}",
                send_url=f"/mcp/send/{session_id}",
            )

        except httpx.HTTPError:
            # Fallback: try non-stream endpoint
            try:
                response = await self._client.post("/mcp/", json=payload)
                response.raise_for_status()
                result = response.json()
                session_info = result.get("session", {})
                if isinstance(session_info, dict):
                    session_id = session_info.get("sessionId", session_id)
                elif isinstance(session_info, str):
                    session_id = session_info
                self._session = HTTPSession(
                    session_id=session_id,
                    poll_url=f"/mcp/{session_id}",
                    send_url=f"/mcp/{session_id}",
                )
                self._stream_mode = False
            except httpx.HTTPError as exc:
                raise ConnectionError(
                    f"StreamableHTTP MCP server at {self._base_url} unreachable: {exc}"
                ) from exc

        # Send initialized notification
        await self._send_notify("notifications/initialized", {})

        # List tools
        tools_result = await self._send_request("tools/list", {})
        if tools_result and "tools" in tools_result:
            self._tools = [
                MCPTool(
                    name=t["name"],
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                    server_name=self._server_name,
                )
                for t in tools_result["tools"]
            ]

        # Start receive loop
        self._receive_task = asyncio.create_task(self._receive_loop())

        self._connected = True
        logger.info(
            "StreamableHTTP MCP connected: %s (session=%s, stream=%s, tools=%d)",
            self._server_name, self._session.session_id, self._stream_mode, len(self._tools),
        )

    async def _send_request(self, method: str, params: dict[str, Any]) -> Any:
        """Send a request and wait for a response (via polling queue)."""
        if self._client is None or self._session is None:
            return None

        req_id = str(uuid.uuid4())
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": req_id,
        }

        future: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending_requests[req_id] = future

        try:
            await self._client.post(self._session.send_url, json=payload)
            # Wait for response in receive loop
            result = await asyncio.wait_for(future, timeout=self._timeout)
            if "error" in result:
                logger.warning("HTTP MCP error for %s: %s", method, result["error"])
                return None
            return result.get("result")
        except asyncio.TimeoutError:
            self._pending_requests.pop(req_id, None)
            return None
        except Exception as exc:
            self._pending_requests.pop(req_id, None)
            logger.warning("HTTP MCP request failed: %s", exc)
            return None

    async def _send_notify(self, method: str, params: dict[str, Any]) -> None:
        """Send a notification (no response expected)."""
        if self._client is None or self._session is None:
            return
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        try:
            await self._client.post(self._session.send_url, json=payload)
        except httpx.HTTPError as exc:
            logger.debug("HTTP MCP notification error (non-fatal): %s", exc)

    async def _receive_loop(self) -> None:
        """Background loop receiving server responses via polling or SSE."""
        if self._session is None or self._client is None:
            return

        if self._stream_mode:
            await self._receive_sse()
        else:
            await self._receive_poll()

    async def _receive_sse(self) -> None:
        """Receive responses via SSE stream."""
        if self._client is None or self._session is None:
            return
        try:
            async with self._client.stream("GET", self._session.poll_url) as stream:
                async for line in stream.aiter_lines():
                    if not line.strip():
                        continue
                    if line.startswith("data: "):
                        data = line[6:]
                        try:
                            msg = json.loads(data)
                            self._route_message(msg)
                        except json.JSONDecodeError:
                            pass
        except httpx.HTTPError as exc:
            logger.warning("HTTP SSE disconnected, falling back to polling: %s", exc)
            self._stream_mode = False
            await self._receive_poll()
        except asyncio.CancelledError:
            pass

    async def _receive_poll(self) -> None:
        """Receive responses via HTTP polling."""
        if self._client is None or self._session is None:
            return
        try:
            while True:
                try:
                    response = await self._client.get(self._session.poll_url)
                    if response.status_code == 204:
                        # No content yet
                        await asyncio.sleep(self._poll_interval)
                        continue
                    response.raise_for_status()
                    msg = response.json()
                    self._route_message(msg)
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 404:
                        # Session ended
                        break
                    raise
                await asyncio.sleep(self._poll_interval)
        except asyncio.CancelledError:
            pass
        except httpx.HTTPError as exc:
            logger.warning("HTTP polling error: %s", exc)

    def _route_message(self, msg: dict[str, Any]) -> None:
        """Route an incoming message to the matching pending request."""
        msg_id = msg.get("id")
        if msg_id and msg_id in self._pending_requests:
            future = self._pending_requests.pop(msg_id)
            if not future.done():
                future.set_result(msg)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPCallResult:
        """Call a tool via StreamableHTTP."""
        if not self._connected:
            return MCPCallResult(success=False, error="Not connected")

        result = await self._send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })

        if result is None:
            return MCPCallResult(success=False, error="Request timed out")

        content = result.get("content", [])
        if content and isinstance(content, list):
            text_parts = [
                c.get("text", "")
                for c in content
                if c.get("type") == "text"
            ]
            return MCPCallResult(success=True, result="\n".join(text_parts))

        return MCPCallResult(success=True, result=str(result))

    async def disconnect(self) -> None:
        """Close the HTTP session."""
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        # Cancel pending requests
        for future in self._pending_requests.values():
            if not future.done():
                future.cancel()
        self._pending_requests.clear()

        if self._client:
            await self._client.aclose()
            self._client = None

        self._session = None
        self._connected = False


# =============================================================================
# Transport factory
# =============================================================================


def create_transport(
    config: dict[str, Any],
    server_name: str = "",
) -> MCPTransport:
    """Factory: create the appropriate transport from a config dict.

    Config format:
        {"type": "stdio", "command": "...", "args": [...]}
        {"type": "sse", "url": "http://...", "headers": {...}}
        {"type": "http", "url": "http://...", "headers": {...}}
    """
    transport_type = config.get("type", "stdio").lower()

    if transport_type == "stdio":
        return _StdioWrapper(
            command=config["command"],
            args=config.get("args", []),
            env=config.get("env"),
            server_name=server_name,
        )

    if transport_type == "sse":
        return SSETransport(
            base_url=config["url"],
            server_name=server_name,
            headers=config.get("headers"),
            timeout=float(config.get("timeout", 60.0)),
        )

    if transport_type in ("http", "streamablehttp"):
        return StreamableHTTPTransport(
            base_url=config["url"],
            server_name=server_name,
            headers=config.get("headers"),
            timeout=float(config.get("timeout", 120.0)),
            poll_interval=float(config.get("poll_interval", 0.5)),
        )

    raise ValueError(f"Unknown MCP transport type: {transport_type}")


# =============================================================================
# Stdio wrapper (re-export from client.py)
# =============================================================================


class _StdioWrapper(MCPTransport):
    """Wraps the existing stdio MCPClient as an MCPTransport."""

    def __init__(
        self,
        command: str,
        args: list[str],
        env: dict[str, str] | None,
        server_name: str,
    ) -> None:
        from .client import MCPClient
        self._client = MCPClient(
            server_command=command,
            server_args=args,
            server_name=server_name,
            env=env,
        )

    @property
    def is_connected(self) -> bool:
        return self._client.is_connected

    @property
    def tools(self) -> list[MCPTool]:
        return self._client.tools

    @property
    def transport_type(self) -> str:
        return "stdio"

    async def connect(self) -> None:
        await self._client.connect()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPCallResult:
        return await self._client.call_tool(name, arguments)

    async def disconnect(self) -> None:
        await self._client.disconnect()
