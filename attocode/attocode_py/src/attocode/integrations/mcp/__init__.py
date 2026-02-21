"""MCP (Model Context Protocol) integration.

Provides MCP client, config loading, tool search, and validation.
"""

from attocode.integrations.mcp.client import MCPCallResult, MCPClient, MCPTool
from attocode.integrations.mcp.client_manager import (
    ConnectionState,
    MCPClientManager,
    ServerEntry,
)
from attocode.integrations.mcp.config import MCPServerConfig, load_mcp_configs
from attocode.integrations.mcp.tool_search import (
    MCPToolMatch,
    MCPToolSearchIndex,
    create_mcp_tool_search_tool,
)
from attocode.integrations.mcp.tool_validator import MCPToolValidator
from attocode.integrations.mcp.custom_tools import (
    MCPCustomToolConfig,
    MCPCustomTools,
)
from attocode.integrations.mcp.meta_tools import (
    MCPContextStats,
    MCPMetaTools,
    MCPServerStats,
)

__all__ = [
    # client
    "MCPCallResult",
    "MCPClient",
    "MCPTool",
    # client_manager
    "ConnectionState",
    "MCPClientManager",
    "ServerEntry",
    # config
    "MCPServerConfig",
    "load_mcp_configs",
    # tool_search
    "MCPToolMatch",
    "MCPToolSearchIndex",
    "create_mcp_tool_search_tool",
    # tool_validator
    "MCPToolValidator",
    # custom_tools
    "MCPCustomToolConfig",
    "MCPCustomTools",
    # meta_tools
    "MCPContextStats",
    "MCPMetaTools",
    "MCPServerStats",
]
