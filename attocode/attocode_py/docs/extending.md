# Extending Attocode

Attocode provides several extension points: custom tools, LLM providers, integrations, MCP servers, and lifecycle hooks.

## Custom Tools

Tools are the primary way the agent interacts with the environment. Register custom tools via the `ToolRegistry`.

### Tool Structure

Every tool needs a spec and an async executor:

```python
from attocode.tools.base import Tool, ToolSpec
from attocode.types.messages import DangerLevel

# 1. Define the spec (JSON Schema for parameters)
spec = ToolSpec(
    name="my_tool",
    description="Describe what the tool does clearly",
    parameters={
        "type": "object",
        "properties": {
            "input": {
                "type": "string",
                "description": "The input to process"
            },
            "verbose": {
                "type": "boolean",
                "description": "Enable verbose output",
                "default": False
            }
        },
        "required": ["input"]
    },
    danger_level=DangerLevel.SAFE,
)

# 2. Implement the async executor
async def execute(args: dict) -> str:
    input_text = args["input"]
    verbose = args.get("verbose", False)
    # ... do work ...
    return f"Result: {input_text}"

# 3. Create and register the tool
tool = Tool(spec=spec, execute=execute, tags=["custom"])
registry.register(tool)
```

### Danger Levels

| Level | Description | Permission behavior |
|-------|-------------|-------------------|
| `SAFE` | Read-only, no side effects | Auto-allowed in interactive mode |
| `MODERATE` | Writes files or modifies state | Prompted in interactive mode |
| `DANGEROUS` | Destructive or irreversible | Always prompted (except yolo) |

### Tool Registry API

```python
registry = ToolRegistry(permission_checker=checker)

registry.register(tool)              # Add a tool
registry.unregister("my_tool")       # Remove by name
registry.get("my_tool")              # Retrieve by name
registry.has("my_tool")              # Check existence
registry.list_tools()                # All tool names
registry.get_definitions()           # LLM-consumable schemas

# Execute with permission checking and timeout
result = await registry.execute("my_tool", {"input": "hello"}, timeout=30.0)

# Batch execution
results = await registry.execute_batch([
    ("call-1", "read_file", {"path": "src/main.py"}),
    ("call-2", "grep", {"pattern": "TODO"}),
])
```

### Lazy Tool Resolution

For tools that shouldn't be loaded at startup (e.g., MCP tools):

```python
async def resolve_tool(name: str) -> Tool | None:
    # Dynamically load/create tool on first use
    if name.startswith("mcp_"):
        return await load_mcp_tool(name)
    return None

registry.set_tool_resolver(resolve_tool)
```

## Custom Providers

Implement the `LLMProvider` protocol to add support for new LLM backends.

### Provider Protocol

```python
from attocode.providers.base import LLMProvider, ChatOptions, ChatResponse

class MyProvider:
    """Custom LLM provider."""

    @property
    def name(self) -> str:
        return "myprovider"

    async def chat(
        self,
        messages: list,
        options: ChatOptions | None = None,
    ) -> ChatResponse:
        # Implement your LLM API call here
        response_text = await call_my_api(messages, options)
        return ChatResponse(
            content=response_text,
            role="assistant",
            stop_reason="end_turn",
            usage=TokenUsage(
                input_tokens=count_input,
                output_tokens=count_output,
            ),
        )

    async def close(self) -> None:
        # Clean up HTTP clients, connections, etc.
        pass
```

### Streaming Support

For streaming responses, also implement `StreamingProvider`:

```python
from attocode.providers.base import StreamingProvider, StreamChunk

class MyStreamingProvider(MyProvider):

    async def chat_stream(
        self,
        messages: list,
        options: ChatOptions | None = None,
    ) -> AsyncIterator[StreamChunk]:
        async for chunk in my_streaming_api(messages):
            yield StreamChunk(
                type="text",
                content=chunk.text,
            )
        yield StreamChunk(type="done")
```

### Capability Declaration

Declare what your provider supports:

```python
from attocode.providers.base import (
    CapableProvider,
    ModelInfo,
    ModelPricing,
    ProviderCapability,
)

class MyCapableProvider(MyStreamingProvider):

    def get_model_info(self, model_id: str) -> ModelInfo | None:
        return ModelInfo(
            model_id=model_id,
            provider="myprovider",
            display_name="My Model",
            max_context_tokens=128_000,
            max_output_tokens=4_096,
            capabilities={
                ProviderCapability.CHAT,
                ProviderCapability.STREAMING,
                ProviderCapability.TOOL_USE,
            },
            pricing=ModelPricing(
                input_per_million=1.0,
                output_per_million=3.0,
            ),
        )

    def list_models(self) -> list[str]:
        return ["my-model-v1", "my-model-v2"]

    def supports(self, capability: ProviderCapability) -> bool:
        return capability in self.get_model_info("my-model-v1").capabilities
```

### Available Capabilities

| Capability | Description |
|------------|-------------|
| `CHAT` | Basic chat completion |
| `STREAMING` | Streaming responses |
| `TOOL_USE` | Function/tool calling |
| `VISION` | Image input support |
| `EXTENDED_THINKING` | Extended thinking/reasoning |
| `CACHING` | Prompt caching |
| `JSON_MODE` | Structured JSON output |
| `SYSTEM_PROMPT` | System message support |
| `MULTI_TURN` | Multi-turn conversation |
| `EMBEDDINGS` | Text embeddings |

### Registering a Provider

```python
from attocode.providers.registry import ProviderRegistry

registry = ProviderRegistry()
registry.register("myprovider", MyCapableProvider(api_key="..."))

# Or use the factory with auto-detection
provider = create_provider("myprovider", api_key="...", model="my-model-v1")
```

## Hooks

Hooks are shell commands triggered by lifecycle events. Configure them in `.attocode/config.json`:

```json
{
  "hooks": [
    {
      "event": "tool.before",
      "command": "python scripts/pre_tool_check.py",
      "timeout": 30,
      "enabled": true
    },
    {
      "event": "run.after",
      "command": "bash scripts/cleanup.sh",
      "timeout": 60,
      "enabled": true
    }
  ]
}
```

### Hook Events

| Event | Fires When |
|-------|------------|
| `tool.before` | Before each tool execution |
| `tool.after` | After each tool execution |
| `run.before` | Before the agent starts |
| `run.after` | After the agent completes |

### Hook Environment

Hooks receive context via environment variables:

| Variable | Description |
|----------|-------------|
| `ATTOCODE_CONTEXT` | JSON-encoded context data |
| `TOOL_NAME` | Current tool name (for tool hooks) |

### Hook Results

Each hook returns a `HookResult` with:

- `success` — Whether the command exited 0
- `output` — stdout content
- `error` — stderr content
- `exit_code` — Process exit code

## MCP Integration

The Model Context Protocol (MCP) lets you connect external tool servers. See the [MCP Guide](MCP.md) for basic setup.

### Advanced: MCP Client Manager

For programmatic MCP management:

```python
from attocode.integrations.mcp import MCPClientManager, MCPServerConfig

manager = MCPClientManager()

# Register servers
manager.register(MCPServerConfig(
    name="filesystem",
    command="npx",
    args=["-y", "@myorg/mcp-filesystem"],
    enabled=True,
    lazy_load=False,      # Connect eagerly at startup
))

manager.register(MCPServerConfig(
    name="database",
    command="python",
    args=["-m", "mymodule.mcp_server"],
    env={"DB_URL": "postgres://..."},
    lazy_load=True,       # Connect on first tool use
))

# Connect eager servers
connected = await manager.connect_eager()

# Call a tool (lazy servers auto-connect)
result = await manager.call_tool("db_query", {"sql": "SELECT 1"})

# Get all available tools
tools = manager.get_tool_summaries()

# Cleanup
await manager.disconnect_all()
```

### MCP Config Files

MCP servers are configured in JSON with priority loading:

1. `~/.attocode/mcp.json` — User-level defaults
2. `.attocode/mcp.json` — Project-level overrides
3. `.mcp.json` — Backward compatibility

```json
{
  "servers": {
    "my-server": {
      "command": "npx",
      "args": ["-y", "@myorg/mcp-server"],
      "env": {"API_KEY": "..."},
      "enabled": true,
      "lazy_load": false
    }
  }
}
```

### Connection States

| State | Description |
|-------|-------------|
| `pending` | Registered but not connected |
| `connecting` | Connection in progress |
| `connected` | Ready to use |
| `failed` | Connection failed |
| `disconnected` | Explicitly disconnected |

## Custom Integrations

To add a new integration module:

1. Create a new file in the appropriate `src/attocode/integrations/` subdirectory
2. Export from the subdirectory's `__init__.py` barrel
3. The root `integrations/__init__.py` re-exports automatically
4. Wire into the agent via `feature_initializer.py`

### Integration Domains

| Directory | Purpose |
|-----------|---------|
| `budget/` | Economics, budget pools, loop detection |
| `context/` | Context engineering, compaction, codebase |
| `safety/` | Policy engine, sandbox, edit validation |
| `persistence/` | SQLite store, session history |
| `agents/` | Agent registry, subagent management |
| `tasks/` | Task decomposition, planning |
| `skills/` | Skill loading and execution |
| `mcp/` | MCP client management |
| `quality/` | Learning store, health checks |
| `utilities/` | Hooks, routing, retry, logging |
| `swarm/` | Multi-agent orchestration |
| `streaming/` | Response streaming, PTY shell |
| `lsp/` | Language Server Protocol |

## Related Pages

- [Architecture](ARCHITECTURE.md) — Module relationships and data flow
- [MCP Integration](MCP.md) — Basic MCP setup guide
- [Skills & Agents](skills-and-agents.md) — Skill and agent definitions
