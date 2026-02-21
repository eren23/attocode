"""MCP meta tools for context stats and tool listing.

Provides tools that give the agent visibility into its own MCP
connections, available tools, and resource usage statistics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from attocode.integrations.mcp.client import MCPTool


@dataclass(slots=True)
class MCPServerStats:
    """Statistics for a connected MCP server."""

    server_name: str
    tool_count: int
    connected: bool
    uptime_seconds: float = 0.0
    total_calls: int = 0
    failed_calls: int = 0
    avg_latency_ms: float = 0.0


@dataclass(slots=True)
class MCPContextStats:
    """Overall MCP context statistics."""

    total_servers: int = 0
    connected_servers: int = 0
    total_tools: int = 0
    total_calls: int = 0
    servers: list[MCPServerStats] = field(default_factory=list)


class MCPMetaTools:
    """Provides meta-level tools for MCP introspection.

    Gives the agent ability to:
    - List all connected MCP servers and their status
    - Query available tools across all servers
    - Get usage statistics for MCP tool calls
    - Search for tools by capability description
    """

    def __init__(self) -> None:
        self._call_counts: dict[str, int] = {}
        self._failure_counts: dict[str, int] = {}
        self._latencies: dict[str, list[float]] = {}

    def record_call(self, server_name: str, tool_name: str, latency_ms: float, success: bool) -> None:
        """Record an MCP tool call for statistics."""
        key = f"{server_name}:{tool_name}"
        self._call_counts[key] = self._call_counts.get(key, 0) + 1
        if not success:
            self._failure_counts[key] = self._failure_counts.get(key, 0) + 1
        if key not in self._latencies:
            self._latencies[key] = []
        self._latencies[key].append(latency_ms)
        # Keep only last 100 latency samples
        if len(self._latencies[key]) > 100:
            self._latencies[key] = self._latencies[key][-100:]

    def get_context_stats(
        self,
        servers: dict[str, Any] | None = None,
        tools: list[MCPTool] | None = None,
    ) -> MCPContextStats:
        """Get overall MCP context statistics."""
        server_stats: list[MCPServerStats] = []
        total_tools = 0
        connected = 0

        if servers:
            for name, info in servers.items():
                is_connected = bool(info.get("connected", False)) if isinstance(info, dict) else False
                tool_count = int(info.get("tool_count", 0)) if isinstance(info, dict) else 0
                total_tools += tool_count
                if is_connected:
                    connected += 1

                # Aggregate call stats for this server
                server_calls = sum(
                    v for k, v in self._call_counts.items()
                    if k.startswith(f"{name}:")
                )
                server_failures = sum(
                    v for k, v in self._failure_counts.items()
                    if k.startswith(f"{name}:")
                )
                server_latencies = [
                    lat for k, lats in self._latencies.items()
                    if k.startswith(f"{name}:")
                    for lat in lats
                ]
                avg_lat = sum(server_latencies) / len(server_latencies) if server_latencies else 0.0

                server_stats.append(MCPServerStats(
                    server_name=name,
                    tool_count=tool_count,
                    connected=is_connected,
                    total_calls=server_calls,
                    failed_calls=server_failures,
                    avg_latency_ms=avg_lat,
                ))

        if tools:
            total_tools = max(total_tools, len(tools))

        return MCPContextStats(
            total_servers=len(servers) if servers else 0,
            connected_servers=connected,
            total_tools=total_tools,
            total_calls=sum(self._call_counts.values()),
            servers=server_stats,
        )

    def format_tool_list(self, tools: list[MCPTool]) -> str:
        """Format tool list for display."""
        if not tools:
            return "No MCP tools available."

        lines = [f"## MCP Tools ({len(tools)} available)\n"]
        by_server: dict[str, list[MCPTool]] = {}
        for tool in tools:
            server = getattr(tool, "server_name", "unknown")
            by_server.setdefault(server, []).append(tool)

        for server, server_tools in sorted(by_server.items()):
            lines.append(f"### {server}")
            for tool in server_tools:
                desc = tool.description[:80] if tool.description else "No description"
                lines.append(f"- **{tool.name}**: {desc}")
            lines.append("")

        return "\n".join(lines)

    def search_tools(self, query: str, tools: list[MCPTool]) -> list[MCPTool]:
        """Search tools by name or description."""
        query_lower = query.lower()
        return [
            t for t in tools
            if query_lower in t.name.lower()
            or query_lower in (t.description or "").lower()
        ]

    def clear(self) -> None:
        """Clear all statistics."""
        self._call_counts.clear()
        self._failure_counts.clear()
        self._latencies.clear()
