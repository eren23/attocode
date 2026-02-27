"""MCP (Model Context Protocol) client.

Implements a stdio-based JSON-RPC client for communicating
with MCP servers that provide additional tools.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any


def _expand_env(env: dict[str, str] | None) -> dict[str, str] | None:
    """Expand ``${VAR}`` references and merge with the current environment.

    When *env* is provided, we start from ``os.environ`` (so the child
    process inherits PATH, HOME, etc.) and overlay the user-supplied
    values after expanding any ``${VAR_NAME}`` patterns against
    ``os.environ``.
    """
    if not env:
        return None
    base = os.environ.copy()
    for key, val in env.items():
        expanded = re.sub(
            r"\$\{(\w+)\}",
            lambda m: os.environ.get(m.group(1), ""),
            val,
        )
        base[key] = expanded
    return base


@dataclass
class MCPTool:
    """A tool provided by an MCP server."""

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    server_name: str = ""


@dataclass
class MCPCallResult:
    """Result of calling an MCP tool."""

    success: bool
    result: Any = None
    error: str | None = None


class MCPClient:
    """Stdio-based JSON-RPC MCP client.

    Launches an MCP server process, communicates via stdin/stdout
    using JSON-RPC 2.0 protocol.
    """

    def __init__(
        self,
        server_command: str,
        server_args: list[str] | None = None,
        server_name: str = "",
        env: dict[str, str] | None = None,
    ) -> None:
        self._command = server_command
        self._args = server_args or []
        self._server_name = server_name
        self._env = env
        self._process: asyncio.subprocess.Process | None = None
        self._tools: list[MCPTool] = []
        self._initialized = False
        self._request_id = 0

    async def connect(self) -> None:
        """Start the MCP server process and initialize."""
        self._process = await asyncio.create_subprocess_exec(
            self._command,
            *self._args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_expand_env(self._env),
        )

        # Send initialize request
        result = await self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "attocode", "version": "0.1.0"},
        })

        if result is not None:
            self._initialized = True

            # Send initialized notification
            await self._notify("notifications/initialized", {})

            # List tools
            await self._refresh_tools()

    async def disconnect(self) -> None:
        """Disconnect and terminate the server process."""
        if self._process:
            try:
                if self._process.stdin:
                    self._process.stdin.close()
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                self._process.kill()
            finally:
                self._process = None
                self._initialized = False

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPCallResult:
        """Call an MCP tool."""
        if not self._initialized:
            return MCPCallResult(success=False, error="Not connected")

        try:
            result = await self._request("tools/call", {
                "name": name,
                "arguments": arguments,
            })
            if result is None:
                return MCPCallResult(success=False, error="No response")

            # MCP tool results have a 'content' array
            content = result.get("content", [])
            if content and isinstance(content, list):
                text_parts = [
                    c.get("text", "")
                    for c in content
                    if c.get("type") == "text"
                ]
                return MCPCallResult(success=True, result="\n".join(text_parts))

            return MCPCallResult(success=True, result=str(result))
        except Exception as e:
            return MCPCallResult(success=False, error=str(e))

    @property
    def tools(self) -> list[MCPTool]:
        """Get available tools."""
        return list(self._tools)

    @property
    def is_connected(self) -> bool:
        return self._initialized

    @property
    def server_name(self) -> str:
        return self._server_name

    async def _refresh_tools(self) -> None:
        """Refresh the tool list from the server."""
        result = await self._request("tools/list", {})
        if result and "tools" in result:
            self._tools = [
                MCPTool(
                    name=t["name"],
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                    server_name=self._server_name,
                )
                for t in result["tools"]
            ]

    async def _request(self, method: str, params: dict[str, Any]) -> Any:
        """Send a JSON-RPC request and wait for response."""
        if not self._process or not self._process.stdin or not self._process.stdout:
            return None

        self._request_id += 1
        msg = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }

        data = json.dumps(msg) + "\n"
        self._process.stdin.write(data.encode())
        await self._process.stdin.drain()

        # Read response
        try:
            line = await asyncio.wait_for(
                self._process.stdout.readline(), timeout=30.0
            )
            if not line:
                return None
            response = json.loads(line.decode())
            if "error" in response:
                return None
            return response.get("result")
        except (asyncio.TimeoutError, json.JSONDecodeError):
            return None

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self._process or not self._process.stdin:
            return

        msg = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }

        data = json.dumps(msg) + "\n"
        self._process.stdin.write(data.encode())
        await self._process.stdin.drain()
