---
sidebar_position: 7
title: MCP Integration
---

# MCP Integration

Attocode connects to external tool servers via the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/). MCP servers expose tools that the agent can discover, load, and call at runtime, extending its capabilities beyond built-in tools.

## Architecture

The MCP integration consists of several modules in `src/integrations/mcp/`:

| Module | Purpose |
|--------|---------|
| `mcp-client.ts` | Core client that manages server connections and tool calls |
| `mcp-tool-search.ts` | Meta-tool for runtime tool discovery |
| `mcp-tool-validator.ts` | Quality validation for tool descriptions |
| `mcp-custom-tools.ts` | Custom tool definitions layered on top of MCP |

## Configuration

MCP servers are configured in `.mcp.json` at the project root:

```json
{
  "servers": {
    "playwright": {
      "command": "npx",
      "args": ["@anthropic/mcp-playwright"],
      "env": {},
      "cwd": "."
    },
    "filesystem": {
      "command": "npx",
      "args": ["@anthropic/mcp-filesystem", "/path/to/allowed/dir"]
    }
  }
}
```

Each server entry specifies:

| Field | Type | Description |
|-------|------|-------------|
| `command` | string | Command to spawn the server process |
| `args` | string[] | Command-line arguments |
| `env` | Record | Environment variables for the process |
| `cwd` | string | Working directory |

### Hierarchical Config

Multiple config files can be loaded in priority order (later overrides earlier):

```typescript
mcpClient.loadFromHierarchicalConfigs([
  '/path/to/global.mcp.json',    // User-level defaults
  './.mcp.json',                  // Project-level overrides
]);
```

Servers with the same name in later configs replace earlier definitions. Servers from all configs are merged together.

## Connection Lifecycle

1. **Load config** -- Parse `.mcp.json` and register server definitions
2. **Auto-connect** -- By default, all servers connect on startup (configurable via `autoConnect: false`)
3. **Spawn process** -- Each server is spawned as a child process communicating via stdio
4. **Initialize** -- JSON-RPC `initialize` handshake
5. **Discover tools** -- `tools/list` call retrieves available tools
6. **Ready** -- Tools are registered in the agent's tool registry

Connection states: `disconnected` -> `connecting` -> `connected` (or `error`).

## Lazy Loading

For projects with many MCP tools, loading all tool schemas into the context window is expensive. Attocode supports lazy loading to reduce token usage:

```typescript
const mcpClient = new MCPClient({
  lazyLoading: true,
  summaryDescriptionLimit: 100,
  maxToolsPerSearch: 5,
  alwaysLoadTools: ['mcp_playwright_browser_snapshot'],
});
```

With lazy loading enabled:

- **Summaries in context** -- Each tool is represented as a lightweight `MCPToolSummary` (~50 tokens) instead of the full schema (~200-500 tokens)
- **On-demand loading** -- Full tool definitions are loaded when the agent searches for or calls a specific tool
- **Token savings** -- Up to 83% reduction in MCP context cost (e.g., 50 tools: ~15,000 tokens full vs. ~2,500 tokens as summaries)

The `alwaysLoadTools` option bypasses lazy loading for tools that are called frequently.

## Tool Search

The `mcp_tool_search` meta-tool lets the agent discover and load MCP tools at runtime:

```
mcp_tool_search({ query: "browser click" })
mcp_tool_search({ query: "browser_(click|hover)", regex: true })
mcp_tool_search({ query: "screenshot", limit: 3 })
```

Search matches against tool names and descriptions. Found tools are automatically loaded into the tool registry so they become available for the next tool call. The `mcp_tool_list` companion tool lists all tools from a specific server.

## Tool Validation

The `MCPToolValidator` scores tool descriptions for quality to help ensure LLMs can use them correctly. Quality checks include:

| Check | Impact on Score |
|-------|----------------|
| Description exists and has minimum length | -40 if missing |
| Input schema has property descriptions | -20 if missing |
| Required parameters are marked | -10 if missing |
| Description contains usage patterns/examples | Optional bonus |
| Naming follows conventions (snake_case, prefixed) | -5 if violated |

Tools are scored 0-100, with a default passing threshold of 40. Use `/mcp tools` to see validation results.

## Context Statistics

The `/mcp stats` command shows token cost estimates for MCP tools, including summary tokens, fully loaded definition tokens, and counts for each category. This helps you understand how much of your context window MCP tools consume and whether lazy loading would help.

## Commands

| Command | Description |
|---------|-------------|
| `/mcp` | List all servers with connection status and tool counts |
| `/mcp connect <name>` | Connect to a specific server |
| `/mcp disconnect <name>` | Disconnect from a server |
| `/mcp tools` | List all available MCP tools across all servers |
| `/mcp search <query>` | Search tools and lazy-load matches |
| `/mcp stats` | Show context usage statistics |

## Events

The MCP client emits events for monitoring:

| Event | Trigger |
|-------|---------|
| `server.connecting` | Connection attempt started |
| `server.connected` | Successfully connected, includes tool count |
| `server.disconnected` | Server disconnected |
| `server.error` | Connection or communication error |
| `tool.call` | Tool invocation started |
| `tool.result` | Tool call completed (success or failure) |
| `tool.dynamicLoad` | Tool schema loaded on demand |
| `tool.search` | Search query executed, includes result count |

## Error Handling

MCP tool calls use retry logic with exponential backoff (configured via `MCP_RETRY_CONFIG`). Recoverable errors (timeouts, transient failures) are retried automatically. Non-recoverable errors are reported to the agent and optionally logged to the Dead Letter Queue for later inspection. Environment variables in server configs support `${VAR_NAME}` expansion at load time.

## Plan Mode Integration

MCP tools that perform write operations are intercepted in plan mode. The system uses regex pattern matching on tool names to detect writes -- tools matching patterns like `mcp_*_create_*`, `mcp_*_update_*`, `mcp_*_delete_*` are queued, while read-only MCP tools pass through immediately.

## Source Files

| File | Purpose |
|------|---------|
| `src/integrations/mcp/mcp-client.ts` | MCPClient class, server management, tool calls |
| `src/integrations/mcp/mcp-tool-search.ts` | createMCPToolSearchTool, createMCPToolListTool |
| `src/integrations/mcp/mcp-tool-validator.ts` | Tool description quality scoring |
| `src/integrations/mcp/mcp-custom-tools.ts` | Custom tool definitions |
