"""MCP server connection and tool registration.

Extracted from agent.py to keep the main agent module focused
on orchestration.  All functions take the agent instance as the
first parameter so the public API of ProductionAgent stays unchanged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from attocode.agent.agent import ProductionAgent

logger = logging.getLogger(__name__)


async def connect_mcp_servers(agent: ProductionAgent) -> list[Any]:
    """Connect to MCP servers and register their tools.

    Uses MCPClientManager for lifecycle management.  Eager servers
    are connected immediately and their tools registered in the
    registry.  Lazy servers are deferred -- a tool_resolver callback
    on the registry will connect them on first use.
    """
    from attocode.integrations.mcp.client_manager import MCPClientManager
    from attocode.integrations.mcp.config import MCPServerConfig
    from attocode.integrations.mcp.meta_tools import MCPMetaTools
    from attocode.tools.base import Tool, ToolSpec
    from attocode.types.messages import DangerLevel

    if not hasattr(agent, "_mcp_meta_tools") or agent._mcp_meta_tools is None:
        agent._mcp_meta_tools = MCPMetaTools()  # type: ignore[attr-defined]
    manager = MCPClientManager(meta_tools=agent._mcp_meta_tools)  # type: ignore[attr-defined]

    # Convert dicts to MCPServerConfig and register
    configs: list[MCPServerConfig] = []
    for mcp_cfg in agent._mcp_server_configs:
        cfg = MCPServerConfig(
            name=mcp_cfg.get("name", ""),
            command=mcp_cfg.get("command", ""),
            args=mcp_cfg.get("args", []),
            env=mcp_cfg.get("env", {}),
            enabled=mcp_cfg.get("enabled", True),
            lazy_load=mcp_cfg.get("lazy_load", False),
        )
        configs.append(cfg)

    manager.register_all(configs)
    await manager.connect_eager()

    # Store manager so /mcp commands can use it
    agent._mcp_client_manager = manager

    # Helper: build a namespaced tool name
    def _tool_name(server_name: str, raw_name: str) -> str:
        return f"mcp__{server_name}__{raw_name}" if server_name else raw_name

    # Helper: wrap an MCP tool as a registry Tool
    def _make_tool(server_name: str, mcp_tool: Any) -> Tool:
        def _make_call(mgr: MCPClientManager, name: str):
            async def _run(args: dict) -> Any:
                r = await mgr.call_tool(name, args)
                return r.result if r.success else f"Error: {r.error}"
            return _run

        return Tool(
            spec=ToolSpec(
                name=_tool_name(server_name, mcp_tool.name),
                description=mcp_tool.description,
                parameters=mcp_tool.input_schema,
                danger_level=DangerLevel.MODERATE,
            ),
            execute=_make_call(manager, mcp_tool.name),
            tags=["mcp", server_name],
        )

    # Register tools from eagerly-connected servers
    for mcp_tool in manager.get_all_tools():
        # Find which server owns this tool
        for sname in manager.server_names:
            srv_tools = manager.get_tools_for_server(sname)
            if any(t.name == mcp_tool.name for t in srv_tools):
                agent._registry.register(_make_tool(sname, mcp_tool))
                break

    # Set up lazy resolver for tools on pending (lazy) servers
    has_lazy = any(c.lazy_load and c.enabled for c in configs)
    if has_lazy:
        async def _resolve_tool(tool_name: str) -> Tool | None:
            """Lazy resolver: connect pending servers to find the requested tool."""
            # Strip mcp__ prefix to get raw tool name
            raw_name = tool_name
            if tool_name.startswith("mcp__"):
                parts = tool_name.split("__", 2)
                if len(parts) == 3:
                    raw_name = parts[2]

            # call_tool triggers lazy connect for pending servers
            await manager.call_tool(raw_name, {})

            # If lazy connect succeeded, find the tool definition
            for sname in manager.server_names:
                for mt in manager.get_tools_for_server(sname):
                    if mt.name == raw_name:
                        return _make_tool(sname, mt)
            return None

        agent._registry.set_tool_resolver(_resolve_tool)

    return []  # No longer returning raw clients
