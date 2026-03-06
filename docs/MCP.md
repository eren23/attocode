# MCP Integration

## Overview

Attocode supports the [Model Context Protocol](https://modelcontextprotocol.io/) for connecting external tools. Located in `src/attocode/integrations/mcp/`.

## Configuration

### Project-level (`.attocode/mcp.json`)

```json
{
  "servers": [
    {
      "name": "context7",
      "command": "npx",
      "args": ["-y", "@upstash/context7-mcp@latest"],
      "enabled": true
    },
    {
      "name": "custom-tools",
      "command": "python",
      "args": ["my_mcp_server.py"],
      "env": {"API_KEY": "..."},
      "lazy_load": true
    }
  ]
}
```

### User-level (`~/.attocode/mcp.json`)

Same format. Project-level configs override user-level.

## Architecture

| Module | Purpose |
|--------|---------|
| `config.py` | Load MCP configs from hierarchy |
| `client.py` | `MCPClient` - manages server connections |
| `tool_search.py` | Search across MCP tool namespaces |
| `tool_validator.py` | Validate MCP tool responses |

## Usage

MCP servers are auto-connected at agent startup when configs are present. Their tools are registered in the tool registry with a namespace prefix.

```bash
# List connected MCP servers
/mcp
```

## Lazy Loading

Set `lazy_load: true` to defer server startup until a tool from that server is first needed. Useful for expensive servers.

## Custom MCP Servers

Create a `.attocode/mcp.json` in your project with server configs. The server must implement the MCP protocol (stdio transport).
