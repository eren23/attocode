# Lesson 7: MCP Integration

## What You'll Learn

The Model Context Protocol (MCP) is an open protocol for extending AI capabilities:
- **Tools**: Let AI call external functions
- **Resources**: Provide context to the AI
- **Prompts**: Reusable prompt templates

In this lesson, we'll:
1. Understand MCP basics
2. Connect to an MCP server
3. Use MCP tools in our agent
4. Create a simple MCP server

## Key Concepts

### Why MCP?

Without MCP, every agent needs custom tool implementations:
```typescript
// ❌ Hard-coded tools
const tools = [
  readFileTool,
  writeFileTool,
  searchCodeTool,  // Custom implementation
  jiraIntegration, // Another custom implementation
  slackTool,       // Yet another...
];
```

With MCP, tools come from standardized servers:
```typescript
// ✅ Dynamic tools from MCP servers
const mcpClient = new MCPClient();
await mcpClient.connect('stdio://code-search-server');
await mcpClient.connect('sse://jira-server:8080');

const tools = await mcpClient.listTools(); // All tools from all servers
```

### MCP Architecture

```
┌─────────────┐     ┌───────────────┐     ┌─────────────────┐
│   Agent     │────▶│  MCP Client   │────▶│   MCP Server    │
│             │◀────│               │◀────│   (tools +      │
│             │     │               │     │    resources)   │
└─────────────┘     └───────────────┘     └─────────────────┘
```

### Transport Types

MCP supports multiple transports:
- **stdio**: Server runs as subprocess, communicates via stdin/stdout
- **SSE**: Server sends events over HTTP
- **WebSocket**: Bidirectional communication

## Files in This Lesson

- `types.ts` - MCP type definitions
- `mcp-client.ts` - Client for connecting to MCP servers
- `mcp-tools.ts` - Converting MCP tools to agent tools
- `example-server/` - Simple MCP server example
- `main.ts` - Demonstration

## Running This Lesson

```bash
# Run the demo
npm run lesson:7

# Run the example server standalone
npx tsx 07-mcp-integration/example-server/server.ts
```

## MCP Message Types

### List Tools
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/list"
}
```

### Call Tool
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "search_codebase",
    "arguments": { "query": "authentication" }
  }
}
```

### List Resources
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "resources/list"
}
```

## Building an MCP Server

```typescript
const server = new MCPServer({
  name: 'my-tools',
  version: '1.0.0',
});

server.addTool({
  name: 'hello',
  description: 'Say hello',
  inputSchema: { type: 'object', properties: { name: { type: 'string' } } },
  handler: async ({ name }) => ({ content: `Hello, ${name}!` }),
});

server.listen();
```

## Advanced: Lazy Tool Loading

When connecting to multiple MCP servers, the combined tool schemas can consume significant context window tokens. The production agent implements **lazy loading** to reduce this overhead by ~83%.

### The Problem

```
Without lazy loading:
┌────────────────────────────────────────────────────────────────────┐
│  50 MCP tools with full schemas: ~15,000 tokens                     │
│  Every request includes all tool definitions                        │
│  Context quickly fills up with rarely-used tool schemas             │
└────────────────────────────────────────────────────────────────────┘

With lazy loading:
┌────────────────────────────────────────────────────────────────────┐
│  50 MCP tools as summaries: ~2,500 tokens                           │
│  Full schemas loaded on-demand via meta-tools                       │
│  83% reduction in MCP tool context                                  │
└────────────────────────────────────────────────────────────────────┘
```

### Tool Summaries

Instead of loading full schemas, store minimal summaries:

```typescript
interface MCPToolSummary {
  name: string;           // e.g., "browser_click"
  serverName: string;     // e.g., "playwright"
  description: string;    // Brief description
  originalName: string;   // Original tool name
}

// Example: Convert full tool to summary
function toSummary(tool: MCPTool, serverName: string): MCPToolSummary {
  return {
    name: `${serverName}_${tool.name}`,
    serverName,
    description: tool.description.slice(0, 100), // Truncate for brevity
    originalName: tool.name,
  };
}
```

### Meta-Tools for Discovery

Create meta-tools that let the agent discover and load tools on demand:

```typescript
// mcp_tool_search - Search for and load tools
const searchTool = {
  name: 'mcp_tool_search',
  description: `Search for MCP tools by name or description.
Found tools are automatically loaded and become available for use.

Examples:
- "browser click" - find click-related browser tools
- "screenshot" - find screenshot tools`,
  parameters: {
    type: 'object',
    properties: {
      query: { type: 'string', description: 'Search keywords' },
      limit: { type: 'number', description: 'Max results (default: 5)' },
    },
    required: ['query'],
  },
  execute: async ({ query, limit = 5 }) => {
    // Search tool summaries
    const matches = mcpClient.searchTools(query, { limit });

    // Auto-load matched tools (fetch full schemas)
    const loadedTools = mcpClient.loadTools(matches.map(m => m.name));

    return {
      tools: matches,
      message: `Found and loaded ${matches.length} tools matching "${query}".`,
    };
  },
};

// mcp_tool_list - List all available tools
const listTool = {
  name: 'mcp_tool_list',
  description: 'List all available MCP tools with brief descriptions.',
  execute: async ({ server }) => {
    const summaries = mcpClient.getAllToolSummaries();
    return { tools: summaries, count: summaries.length };
  },
};

// mcp_context_stats - Monitor token usage
const statsTool = {
  name: 'mcp_context_stats',
  description: 'Show MCP tool context usage statistics.',
  execute: async () => {
    const stats = mcpClient.getContextStats();
    return {
      stats,
      savings: `${savingsPercent}% token savings vs loading all schemas`,
    };
  },
};
```

### Context Stats Tracking

Track token usage to monitor optimization effectiveness:

```typescript
interface MCPContextStats {
  totalTools: number;      // Total tools available
  summaryCount: number;    // Tools as summaries only
  loadedCount: number;     // Fully loaded tools
  summaryTokens: number;   // Tokens used by summaries
  definitionTokens: number; // Tokens used by full definitions
}

function getContextStats(): MCPContextStats {
  return {
    totalTools: this.summaries.size,
    summaryCount: this.summaries.size - this.loadedTools.size,
    loadedCount: this.loadedTools.size,
    summaryTokens: estimateTokens(Array.from(this.summaries.values())),
    definitionTokens: estimateTokens(Array.from(this.loadedTools.values())),
  };
}
```

### Integration Example

```typescript
// Create MCP client with lazy loading
const mcpClient = new MCPClient({ lazyLoading: true });
await mcpClient.connect('stdio://playwright-server');
await mcpClient.connect('sse://database-server:8080');

// Only summaries are loaded initially (~2,500 tokens for 50 tools)
const summaries = mcpClient.getAllToolSummaries();

// Create meta-tools
const metaTools = createMCPMetaTools(mcpClient, {
  autoLoad: true,  // Auto-load found tools
  defaultLimit: 5, // Max results per search
  onToolsLoaded: (tools) => {
    // Update agent's tool list when new tools are loaded
    agent.updateTools([...agent.tools, ...tools]);
  },
});

// Agent uses meta-tools to discover what it needs
// "I need to click a button" → mcp_tool_search({ query: "browser click" })
// → browser_click tool is loaded on demand
```

### Best Practices

1. **Start with summaries** - Only load full schemas when needed
2. **Use descriptive search** - The agent searches based on task context
3. **Monitor stats** - Track token usage with `mcp_context_stats`
4. **Set reasonable limits** - Don't auto-load too many tools at once
5. **Clear unused tools** - Unload tools between tasks if context is tight

## Next Steps

Congratulations! You've completed the course. You now understand:
1. The agent loop
2. Multi-provider LLM support
3. Tool systems with validation
4. Streaming responses
5. Error recovery
6. Testing agents
7. MCP integration

Build your own agent and share it with the team!
