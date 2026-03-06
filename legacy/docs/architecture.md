# Attocode Architecture

This document provides a comprehensive overview of attocode's architecture, module relationships, and data flow patterns.

## Table of Contents

1. [Overview](#overview)
2. [Module Structure](#module-structure)
3. [Core Components](#core-components)
4. [Data Flow](#data-flow)
5. [Integration Points](#integration-points)
6. [Context Engineering](#context-engineering)
7. [Provider System](#provider-system)
8. [Tool System](#tool-system)

## Overview

Attocode is a production AI coding agent built in TypeScript. It follows a modular architecture where each component can be enabled/disabled independently. The agent composes features from multiple integration modules into a cohesive system.

```
┌─────────────────────────────────────────────────────────────────┐
│                         Entry Point                              │
│                    src/main.ts (CLI + TUI)                       │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      ProductionAgent                             │
│                       src/agent.ts                               │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ Integration Managers                                         ││
│  │ ┌────────┐ ┌──────────┐ ┌──────────┐ ┌────────────────────┐ ││
│  │ │ Hooks  │ │ Memory   │ │ Planning │ │ Context Engineering│ ││
│  │ └────────┘ └──────────┘ └──────────┘ └────────────────────┘ ││
│  │ ┌────────┐ ┌──────────┐ ┌──────────┐ ┌────────────────────┐ ││
│  │ │ Safety │ │ Routing  │ │ Economics│ │ Resource Manager   │ ││
│  │ └────────┘ └──────────┘ └──────────┘ └────────────────────┘ ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
        │                               │                    │
        ▼                               ▼                    ▼
┌───────────────┐            ┌─────────────────┐     ┌──────────────┐
│  LLM Providers│            │  Tool Registry  │     │ Integrations │
│  ┌──────────┐ │            │  ┌───────────┐  │     │ ┌──────────┐ │
│  │ Anthropic│ │            │  │ File Ops  │  │     │ │ SQLite   │ │
│  ├──────────┤ │            │  ├───────────┤  │     │ │ Store    │ │
│  │OpenRouter│ │            │  │ Bash      │  │     │ ├──────────┤ │
│  ├──────────┤ │            │  ├───────────┤  │     │ │ MCP      │ │
│  │ OpenAI   │ │            │  │ Search    │  │     │ │ Client   │ │
│  └──────────┘ │            │  ├───────────┤  │     │ └──────────┘ │
└───────────────┘            │  │ MCP Tools │  │     └──────────────┘
                             │  └───────────┘  │
                             └─────────────────┘
```

## Module Structure

```
src/
├── main.ts              # Entry point, CLI parsing, REPL loop
│                        # Contains TUIApp - the actual TUI (uses Ink's <Static>)
├── agent.ts             # ProductionAgent - core agent logic
├── types.ts             # Shared type definitions
├── defaults.ts          # Default configuration builder
├── modes.ts             # Agent modes (chat, code, architect, etc.)
│
├── providers/           # LLM provider adapters
│   ├── provider.ts      # Factory with auto-detection
│   ├── types.ts         # Provider type definitions
│   ├── circuit-breaker.ts  # Circuit breaker for resilience
│   ├── fallback-chain.ts   # Provider fallback chain
│   └── adapters/        # Individual provider implementations
│       ├── anthropic.ts # Anthropic Claude
│       ├── openrouter.ts# OpenRouter (multi-model)
│       ├── openai.ts    # OpenAI GPT models
│       └── mock.ts      # Mock for testing
│
├── tools/               # Tool implementations
│   ├── registry.ts      # Tool registration & execution
│   ├── file.ts          # File operations (read, write, edit)
│   ├── bash.ts          # Bash command execution
│   ├── search.ts        # Code search (glob, grep)
│   ├── agent.ts         # Spawn agent tool
│   └── index.ts         # Tool exports
│
├── integrations/        # Feature modules
│   ├── index.ts         # All integration exports
│   ├── hooks.ts         # Hook system
│   ├── memory.ts        # Memory management
│   ├── planning.ts      # Planning & reflection
│   ├── safety.ts        # Sandbox & human-in-loop
│   ├── routing.ts       # Model routing
│   ├── economics.ts     # Token budget management
│   ├── mcp-client.ts    # MCP server integration
│   ├── sqlite-store.ts  # Session persistence
│   ├── context-engineering.ts  # Context tricks
│   ├── interactive-planning.ts # Conversational planning
│   ├── learning-store.ts       # Persistent learnings
│   └── ...              # Many more modules
│
├── tricks/              # Context engineering techniques
│   ├── reversible-compaction.ts   # Compress with retrieval refs
│   ├── kv-cache-context.ts        # KV-cache optimization
│   ├── failure-evidence.ts        # Track & learn from failures
│   ├── recitation.ts              # Goal persistence
│   └── recursive-context.ts       # RLM implementation
│
├── tui/                 # Terminal UI layer
│   ├── index.ts         # SimpleTextRenderer, theme exports
│   ├── types.ts         # Type definitions
│   └── theme/           # Dark, light, high-contrast themes
│
└── persistence/         # Data persistence
    └── schema.ts        # SQLite schema & migrations
```

## Core Components

### ProductionAgent (src/agent.ts)

The central orchestrator that composes all features. Key responsibilities:

1. **Configuration Management**: Builds complete config from user overrides + defaults
2. **Feature Initialization**: Lazily initializes enabled integration managers
3. **Message Loop**: Handles the core think → act → observe cycle
4. **Tool Execution**: Routes tool calls through permission checks and execution
5. **State Management**: Maintains conversation history, metrics, and plan state

```typescript
// Simplified agent structure
class ProductionAgent {
  // Configuration
  private config: ProductionAgentConfig;
  private provider: LLMProvider;
  private tools: Map<string, ToolDefinition>;

  // Integration managers (null if feature disabled)
  private hooks: HookManager | null;
  private memory: MemoryManager | null;
  private planning: PlanningManager | null;
  private safety: SafetyManager | null;
  private routing: RoutingManager | null;
  private economics: ExecutionEconomicsManager | null;
  private contextEngineering: ContextEngineeringManager | null;
  // ... many more managers

  // Core loop
  async run(prompt: string): Promise<AgentResult> {
    // 1. Build context (rules, memory, learnings)
    // 2. Get LLM response
    // 3. Execute tool calls with permission checks
    // 4. Loop until done or budget exhausted
  }
}
```

### LLM Provider System (src/providers/)

The provider system abstracts different LLM backends behind a common interface:

```typescript
interface LLMProvider {
  name: string;
  defaultModel: string;
  isConfigured(): boolean;
  chat(messages: Message[], options?: ChatOptions): Promise<ChatResponse>;
}

interface LLMProviderWithTools extends LLMProvider {
  chatWithTools(
    messages: (Message | MessageWithContent)[],
    options?: ChatOptionsWithTools
  ): Promise<ChatResponseWithTools>;
}
```

**Provider Factory** (`provider.ts`):
- Auto-detects available providers from environment variables
- Priority order: OpenRouter → Anthropic → OpenAI → Mock
- Can create providers from explicit configuration

**Resilience Features**:
- `CircuitBreaker`: Prevents hammering failed services
- `FallbackChain`: Automatic failover between providers

### Tool System (src/tools/)

Tools are the agent's interface to the world:

```typescript
interface ToolDefinition {
  name: string;
  description: string;
  inputSchema: JSONSchema;
  execute: (args: unknown) => Promise<ToolResult>;
}
```

**Built-in Tools**:
| Tool | Purpose |
|------|---------|
| `read_file` | Read file contents |
| `write_file` | Create/overwrite files |
| `edit_file` | Surgical file edits |
| `bash` | Execute shell commands |
| `glob` | Find files by pattern |
| `grep` | Search file contents |
| `spawn_agent` | Delegate to subagents |

**MCP Integration**: External tools from MCP servers are dynamically registered.

## Data Flow

### Main Request Flow

```
┌──────────┐     ┌───────────────┐     ┌─────────────┐     ┌─────────────┐
│  User    │────▶│   TUIApp      │────▶│ Production  │────▶│   LLM       │
│  Input   │     │   (main.ts)   │     │   Agent     │     │  Provider   │
└──────────┘     └───────────────┘     └─────────────┘     └─────────────┘
                                              │
                                              ▼
                       ┌──────────────────────────────────────────┐
                       │            For each tool call            │
                       │                                          │
                       │  ┌─────────────┐   ┌─────────────────┐  │
                       │  │ Permission  │──▶│ Tool Execution  │  │
                       │  │   Check     │   │ (with sandbox)  │  │
                       │  └─────────────┘   └─────────────────┘  │
                       │         │                   │            │
                       │         ▼                   ▼            │
                       │  ┌─────────────┐   ┌─────────────────┐  │
                       │  │ TUI Approval│   │  Result + hook  │  │
                       │  │   Dialog    │   │   processing    │  │
                       │  └─────────────┘   └─────────────────┘  │
                       └──────────────────────────────────────────┘
                                              │
                                              ▼
                       ┌──────────────────────────────────────────┐
                       │       Continue until:                     │
                       │       - Agent produces final answer       │
                       │       - Budget exhausted                  │
                       │       - Max iterations reached            │
                       │       - User cancels                      │
                       └──────────────────────────────────────────┘
```

### Context Building Flow

Each request builds context from multiple sources:

```
┌─────────────────────────────────────────────────────────────────┐
│                     System Prompt Assembly                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ Base System  │  │ Rules from   │  │ Learning Store       │  │
│  │ Prompt       │  │ CLAUDE.md    │  │ (cross-session)      │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
│         │                │                      │               │
│         └────────────────┼──────────────────────┘               │
│                          ▼                                      │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                  Combined System Prompt                   │  │
│  └──────────────────────────────────────────────────────────┘  │
│                          │                                      │
│                          ▼                                      │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ + Memory Context (relevant prior conversations)           │  │
│  │ + Failure Evidence (avoid repeated mistakes)              │  │
│  │ + Goal Recitation (long session focus)                    │  │
│  │ + Codebase Context (relevant code snippets)               │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Integration Points

### Feature Flag System

Features can be enabled/disabled via configuration:

```typescript
const config: ProductionAgentConfig = {
  // Core settings
  maxIterations: 50,

  // Feature flags (false = disabled)
  hooks: { enabled: true, /* ... */ },
  memory: { enabled: true, /* ... */ },
  planning: { enabled: true, /* ... */ },
  routing: false,  // Disabled
  sandbox: { enabled: true, /* ... */ },
  // ...
};
```

The agent checks `isFeatureEnabled()` before initializing each manager.

### Event System

Managers emit events for observability:

```typescript
// Subscribe to agent events
agent.on((event: AgentEvent) => {
  switch (event.type) {
    case 'iteration.start':
      console.log(`Starting iteration ${event.iteration}`);
      break;
    case 'tool.execute':
      console.log(`Executing ${event.tool}`);
      break;
    case 'cancellation.requested':
      console.log('User requested cancellation');
      break;
  }
});
```

### Hook System

Hooks intercept and modify behavior at key points:

| Hook Point | When | Use Case |
|------------|------|----------|
| `PreToolUse` | Before tool execution | Validate, modify, or block |
| `PostToolUse` | After tool execution | Log, transform output |
| `SessionStart` | Session begins | Initialize context |
| `SessionEnd` | Session ends | Cleanup, save state |
| `PreCompact` | Before context compaction | Preserve important data |

## Context Engineering

Attocode implements several techniques for managing long conversations:

### Trick P: Reversible Compaction

Summarize old messages but keep retrieval references:

```
Before: [Full message history - 50K tokens]
After:  [Summary with refs - 5K tokens] + [Retrievable archive]
```

### Trick Q: KV-Cache Optimization

Structure prompts to maximize cache hits:

```
┌──────────────────────────────────────┐
│ [Stable prefix - cached]             │
│   System prompt                      │
│   Tool definitions                   │
│   Rules                              │
├──────────────────────────────────────┤
│ [Dynamic suffix - not cached]        │
│   Recent messages                    │
│   Current context                    │
└──────────────────────────────────────┘
```

### Trick R: Failure Evidence

Track failures and inject lessons:

```typescript
// When a tool call fails
failureTracker.record({
  action: 'write_file',
  error: 'Permission denied',
  context: { path: '/etc/hosts' },
});

// Later, inject into context
const lessons = failureTracker.getRelevantLessons(currentContext);
// → "Note: Writing to /etc requires elevated permissions"
```

### Trick S: Goal Recitation

Periodically reinforce objectives in long sessions:

```
Every N iterations, prepend:
"Reminder: Your current goal is to [original task].
Progress so far: [summary].
Next steps: [plan]."
```

### Trick U: Recursive Context (RLM)

Let the model browse context on-demand:

```
Instead of:  [Everything in context]
RLM:         [Navigator prompt]
             → Model requests: "Show me auth.ts"
             → [Focused snippet]
             → Model requests: "Search for 'login'"
             → [Search results]
             → Synthesize answer
```

## Provider System

### Provider Selection

```
getProvider(preferred?)
       │
       ▼
┌──────────────────────────────────────┐
│ Check environment variables          │
│                                      │
│ OPENROUTER_API_KEY? ──▶ OpenRouter   │
│         │                            │
│         ▼                            │
│ ANTHROPIC_API_KEY? ──▶ Anthropic     │
│         │                            │
│         ▼                            │
│ OPENAI_API_KEY? ────▶ OpenAI         │
│         │                            │
│         ▼                            │
│ (fallback) ─────────▶ Mock           │
└──────────────────────────────────────┘
```

### Resilience Pattern

```
┌─────────────────────────────────────────────────────────────┐
│                    FallbackChain                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │                  CircuitBreaker                        │  │
│  │  ┌─────────┐    ┌─────────┐    ┌─────────┐           │  │
│  │  │ CLOSED  │───▶│  OPEN   │───▶│HALF-OPEN│───┐       │  │
│  │  │(normal) │    │(failing)│    │ (test)  │   │       │  │
│  │  └────┬────┘    └─────────┘    └─────────┘   │       │  │
│  │       └──────────────────────────────────────┘       │  │
│  └───────────────────────────────────────────────────────┘  │
│                              │                               │
│  Provider 1 ───▶ Provider 2 ───▶ Provider 3                 │
│   (primary)      (secondary)     (fallback)                  │
└─────────────────────────────────────────────────────────────┘
```

## Tool System

### Tool Registration

```typescript
// Built-in tools are registered in defaults.ts
const defaultTools = createDefaultTools({
  workingDir: process.cwd(),
  shellTimeout: 30000,
});

// MCP tools are registered dynamically
const mcpClient = createMCPClient(config);
await mcpClient.connect();
const mcpTools = mcpClient.getTools();
registry.registerAll(mcpTools);
```

### Permission Model

```
Tool Call Request
       │
       ▼
┌──────────────────────────────────────┐
│ Execution Policy Check               │
│                                      │
│ Policy: 'allow' ──────▶ Execute      │
│          │                           │
│          ▼                           │
│ Policy: 'prompt' ─────▶ Ask User     │
│          │                    │      │
│          │              ┌─────┴────┐ │
│          │              │ Approve  │ │
│          │              │  Deny    │ │
│          │              │ Allow    │ │
│          │              │  Always  │ │
│          │              └──────────┘ │
│          ▼                           │
│ Policy: 'forbidden' ──▶ Reject       │
└──────────────────────────────────────┘
```

### Sandboxing

Dangerous operations run in restricted environments:

| Platform | Sandbox Type |
|----------|-------------|
| macOS | Seatbelt (sandbox-exec) |
| Linux | Docker / Bubblewrap |
| All | Basic (no network, limited paths) |

---

## See Also

- [Extending Attocode](./extending.md) - How to add tools, providers, and tricks
- [API Reference](./api-reference.md) - Detailed API documentation
- [CLAUDE.md](../.claude/CLAUDE.md) - Project-specific instructions
