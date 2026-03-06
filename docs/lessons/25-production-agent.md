---
title: "Lesson 25: Production Agent (Capstone)"
---

!!! info "Source Code"
    The runnable TypeScript source for this lesson is in
    [`lessons/25-production-agent/`](https://github.com/eren23/attocode/tree/main/lessons/25-production-agent/)

# Lesson 25: Production Agent (Capstone)

The capstone lesson - a **real, usable coding agent** that integrates ALL previous lessons into one powerful tool.

## Table of Contents

1. [Overview](#1-overview)
2. [Quick Start](#2-quick-start)
3. [Architecture](#3-architecture)
4. [Configuration](#4-configuration)
5. [Features by Lesson](#5-features-by-lesson)
6. [Providers](#6-providers)
7. [Tools](#7-tools)
8. [REPL Commands](#8-repl-commands)
9. [MCP Integration](#9-mcp-integration)
10. [Programmatic Usage](#10-programmatic-usage)
11. [Events](#11-events)
12. [Agent Modes](#12-agent-modes)
13. [Built-in Roles](#13-built-in-roles)
14. [Tricks Integration](#14-tricks-integration)
15. [Testing](#15-testing)
16. [Extending](#16-extending)
17. [CLI Options](#17-cli-options)
18. [Dependencies](#18-dependencies)

---

## 1. Overview

### What This Agent Does

A production-ready coding assistant that combines 24 lessons of AI agent patterns into a cohesive system. It can:

- Read, write, and modify code files
- Execute shell commands with sandboxing
- Search the web and fetch URLs
- Remember previous interactions
- Plan complex tasks automatically
- Use explicit reasoning (ReAct pattern)
- Coordinate multiple specialized agents
- Manage conversation threads and checkpoints

### Key Differentiators

| Feature | Simple Agent | Production Agent |
|---------|--------------|------------------|
| Memory | None | Episodic + Semantic + Working |
| Planning | None | Auto-plan for complex tasks |
| Safety | Basic | Sandboxing + Human-in-loop + Policies |
| Context | Fixed | Compaction + Sliding window |
| Tools | Static | Lazy-loading + MCP integration |
| Debugging | None | Observability + Thread management |

### Feature Flags Summary

All features are configurable. By default:

| Feature | Default | Purpose |
|---------|---------|---------|
| `hooks` | Enabled | Lifecycle events |
| `plugins` | Enabled | Extensibility |
| `rules` | Enabled | Dynamic instructions |
| `memory` | Enabled | Conversation memory |
| `planning` | Enabled | Task decomposition |
| `reflection` | Enabled | Self-critique |
| `observability` | Enabled | Tracing/metrics |
| `routing` | Disabled | Multi-model routing |
| `sandbox` | Enabled | Command safety |
| `humanInLoop` | Enabled | Approval workflows |
| `multiAgent` | Disabled | Team coordination |
| `react` | Disabled | Explicit reasoning |
| `executionPolicy` | Enabled | Tool access control |
| `threads` | Enabled | Checkpoints/rollback |
| `cancellation` | Enabled | Graceful interruption |
| `resources` | Enabled | Memory/CPU limits |
| `lsp` | Disabled | Code intelligence |
| `semanticCache` | Disabled | Response caching |
| `skills` | Enabled | Skill discovery |

---

## 2. Quick Start

### Prerequisites

- Node.js 18+ or Bun
- An LLM API key (OpenRouter, Anthropic, or OpenAI)

### Installation

```bash
# Clone and install
git clone <repo>
cd first-principles-agent
npm install

# Or with bun
bun install
```

### Environment Setup

```bash
# Option 1: OpenRouter (recommended - supports multiple models)
export OPENROUTER_API_KEY=your-key-here

# Option 2: Anthropic
export ANTHROPIC_API_KEY=your-key-here

# Option 3: OpenAI
export OPENAI_API_KEY=your-key-here
```

### Running the Agent

```bash
# Interactive mode
npm run lesson:25

# With specific model
npx tsx 25-production-agent/main.ts -m anthropic/claude-sonnet-4

# Single task
npx tsx 25-production-agent/main.ts "List all TypeScript files in src/"

# With strict permissions
npx tsx 25-production-agent/main.ts -p strict
```

---

## 3. Architecture

### Component Diagram

```
+-----------------------------------------------------------------------+
|                         ProductionAgent                                  |
+-----------------------------------------------------------------------+
|  +-------------+  +-------------+  +-------------+  +-------------+    |
|  |   Memory    |  |  Planning   |  |  Reflection |  |    Rules    |    |
|  |  (L14)      |  |   (L15)     |  |    (L16)    |  |    (L12)    |    |
|  +-------------+  +-------------+  +-------------+  +-------------+    |
|  +-------------+  +-------------+  +-------------+  +-------------+    |
|  | Multi-Agent |  |    ReAct    |  |  Policies   |  |   Threads   |    |
|  |   (L17)     |  |    (L18)    |  |    (L23)    |  |    (L24)    |    |
|  +-------------+  +-------------+  +-------------+  +-------------+    |
+-----------------------------------------------------------------------+
|  +---------------------------------------------------------------+    |
|  |                    Integration Layer                            |    |
|  |  +---------+ +---------+ +---------+ +---------+ +---------+  |    |
|  |  |Economics| | Session | | Skills  | |  Ignore | |   LSP   |  |    |
|  |  +---------+ +---------+ +---------+ +---------+ +---------+  |    |
|  |  +---------+ +---------+ +---------+ +---------+ +---------+  |    |
|  |  | MCP     | |Compaction| | Modes  | | Agents  | |PTY Shell|  |    |
|  |  +---------+ +---------+ +---------+ +---------+ +---------+  |    |
|  +---------------------------------------------------------------+    |
+-----------------------------------------------------------------------+
|  +-------------+  +-------------+  +-------------+  +-------------+    |
|  |  Sandbox    |  | Human Loop  |  |Observability|  |  Routing    |    |
|  |   (L20)     |  |    (L21)    |  |    (L19)    |  |    (L22)    |    |
|  +-------------+  +-------------+  +-------------+  +-------------+    |
+-----------------------------------------------------------------------+
|  +---------------------------------------------------------------+    |
|  |                    Provider Layer                               |    |
|  |  +----------+ +----------+ +----------+ +----------+           |    |
|  |  |OpenRouter| |Anthropic | |  OpenAI  | |   Mock   |           |    |
|  |  +----------+ +----------+ +----------+ +----------+           |    |
|  +---------------------------------------------------------------+    |
+-----------------------------------------------------------------------+
```

### File Structure

```
25-production-agent/
├── main.ts              # Interactive REPL + CLI entry point
├── agent.ts             # ProductionAgent class with builder pattern
├── types.ts             # Type definitions for all features
├── defaults.ts          # Default configurations for all features
├── modes.ts             # Agent modes (build/plan/review/debug)
├── providers.ts         # LLM provider implementations
├── tools.ts             # Built-in tool definitions
└── integrations/
    ├── hooks.ts         # Hook system (L10)
    ├── plugins.ts       # Plugin system (L11)
    ├── rules.ts         # Rules/instructions (L12)
    ├── memory.ts        # Episodic + semantic + working (L14)
    ├── planning.ts      # Task decomposition (L15)
    ├── reflection.ts    # Self-critique (L16)
    ├── multi-agent.ts   # Team coordination (L17)
    ├── react.ts         # ReAct pattern (L18)
    ├── observability.ts # Tracing + metrics (L19)
    ├── execution-policy.ts  # Tool access control (L23)
    ├── thread-manager.ts    # Checkpoints + rollback (L24)
    ├── economics.ts     # Token budgets + progress detection
    ├── session-store.ts # JSONL persistence
    ├── skills.ts        # Skill discovery
    ├── ignore.ts        # .agentignore support
    ├── mcp-tool-search.ts   # Lazy MCP tool loading
    ├── agent-registry.ts    # Subagent spawning
    ├── compaction.ts    # Context summarization
    ├── hierarchical-config.ts # Config layering
    ├── lsp.ts           # Language server integration
    ├── semantic-cache.ts    # Response caching
    ├── cancellation.ts  # Graceful interruption
    ├── resources.ts     # Resource monitoring
    ├── pty-shell.ts     # Persistent shell
    └── sandbox/
        ├── index.ts     # Sandbox factory
        ├── seatbelt.ts  # macOS sandbox
        ├── landlock.ts  # Linux sandbox
        ├── docker.ts    # Container sandbox
        └── basic.ts     # Fallback sandbox
```

---

## 4. Configuration

### Full Configuration Interface

```typescript
interface ProductionAgentConfig {
  // Required
  provider: LLMProvider;
  tools: ToolDefinition[];

  // Optional - all have sensible defaults
  systemPrompt?: string;
  model?: string;

  // Feature configs (set to false to disable)
  hooks?: HooksConfig | false;
  plugins?: PluginsConfig | false;
  rules?: RulesConfig | false;
  memory?: MemoryConfig | false;
  planning?: PlanningConfig | false;
  reflection?: ReflectionConfig | false;
  observability?: ObservabilityConfig | false;
  routing?: RoutingConfig | false;
  sandbox?: SandboxConfig | false;
  humanInLoop?: HumanInLoopConfig | false;
  multiAgent?: MultiAgentConfig | false;
  react?: ReActPatternConfig | false;
  executionPolicy?: ExecutionPolicyConfig | false;
  threads?: ThreadsConfig | false;
  cancellation?: CancellationConfig | false;
  resources?: ResourceConfig | false;
  lsp?: LSPAgentConfig | false;
  semanticCache?: SemanticCacheAgentConfig | false;
  skills?: SkillsAgentConfig | false;

  // Limits
  maxIterations?: number;  // Default: 50
  timeout?: number;        // Default: 300000 (5 min)

  // MCP lazy loading
  toolResolver?: (toolName: string) => ToolDefinition | null;
  mcpToolSummaries?: Array<{ name: string; description: string }>;
}
```

---

## 5. Features by Lesson

| Lesson | Feature | Integration File | Purpose |
|--------|---------|------------------|---------|
| 1-9 | Core Agent | `agent.ts` | Basic agent loop |
| 10 | Hooks | `hooks.ts` | Lifecycle events |
| 11 | Plugins | `plugins.ts` | Extensibility |
| 12 | Rules | `rules.ts` | Dynamic instructions |
| 13 | Client/Server | `session-store.ts` | JSONL persistence |
| 14 | Memory | `memory.ts` | Episodic + semantic |
| 15 | Planning | `planning.ts` | Task decomposition |
| 16 | Reflection | `reflection.ts` | Self-critique |
| 17 | Multi-Agent | `multi-agent.ts`, `agent-registry.ts` | Team coordination |
| 18 | ReAct | `react.ts` | Explicit reasoning |
| 19 | Observability | `observability.ts`, `economics.ts` | Tracing + budgets |
| 20 | Sandboxing | `sandbox/*.ts`, `pty-shell.ts` | Secure execution |
| 21 | Human-in-Loop | `safety.ts` | Approval workflows |
| 22 | Routing | `routing.ts` | Multi-model |
| 23 | Policies | `execution-policy.ts` | Access control |
| 24 | Threads | `thread-manager.ts` | Checkpoints |
| Tricks | Various | See section 14 | Utilities |

---

## 6. Providers

### OpenRouter (Primary)

```typescript
import { createOpenRouterProvider } from './providers.js';

const provider = createOpenRouterProvider({
  apiKey: process.env.OPENROUTER_API_KEY,
  defaultModel: 'anthropic/claude-sonnet-4',
});
```

### Anthropic

```typescript
import { createAnthropicProvider } from './providers.js';

const provider = createAnthropicProvider({
  apiKey: process.env.ANTHROPIC_API_KEY,
});
```

### OpenAI

```typescript
import { createOpenAIProvider } from './providers.js';

const provider = createOpenAIProvider({
  apiKey: process.env.OPENAI_API_KEY,
});
```

### Mock (for Testing)

```typescript
import { createMockProvider } from './providers.js';

const provider = createMockProvider({
  responses: [
    { content: 'Hello!', toolCalls: [] },
  ],
});
```

---

## 7. Tools

### Standard Tools

| Tool | Description | Danger Level |
|------|-------------|--------------|
| `read_file` | Read file contents | safe |
| `write_file` | Write/create files | dangerous |
| `edit_file` | Edit existing files | dangerous |
| `list_directory` | List directory contents | safe |
| `search_files` | Search files by pattern | safe |
| `bash` | Execute shell commands | dangerous |
| `web_search` | Search the web | moderate |
| `fetch_url` | Fetch URL contents | moderate |

### MCP Meta-Tools

When MCP is enabled with lazy loading:

| Tool | Description |
|------|-------------|
| `mcp_tool_search` | Search and load MCP tools |
| `mcp_tool_list` | List available MCP tools |
| `mcp_context_stats` | Show token usage stats |

---

## 8. REPL Commands

### Session Management

| Command | Description |
|---------|-------------|
| `/new` | Start new session |
| `/save [name]` | Save current session |
| `/load <id>` | Load saved session |
| `/sessions` | List all sessions |
| `/history` | Show message history |
| `/clear` | Clear current context |

### Agent Control

| Command | Description |
|---------|-------------|
| `/mode [mode]` | Switch mode (build/plan/review/debug) |
| `/cancel` | Cancel current operation |
| `/checkpoint [label]` | Create checkpoint |
| `/rollback [steps]` | Rollback messages |
| `/fork [name]` | Fork conversation |

### Information

| Command | Description |
|---------|-------------|
| `/status` | Show session stats |
| `/memory` | Show memory contents |
| `/tools` | List available tools |
| `/config` | Show current config |
| `/help` | Show help |

### Skills

| Command | Description |
|---------|-------------|
| `/skills` | List available skills |
| `/skill <name>` | Activate a skill |

### Planning

| Command | Description |
|---------|-------------|
| `/plan <goal>` | Create explicit plan |
| `/plan.status` | Show plan progress |

### Debugging

| Command | Description |
|---------|-------------|
| `/trace` | Show trace for last operation |
| `/debug` | Toggle debug mode |
| `/verbose` | Toggle verbose output |

---

## 9. MCP Integration

### Lazy Loading

MCP tools are loaded on-demand to save context:

```
Without lazy loading: ~15,000 tokens for 50 tools
With lazy loading:    ~2,500 tokens (summaries only)
Savings:              ~83%
```

The agent uses meta-tools to discover what it needs:
1. `mcp_tool_list` - see available tools
2. `mcp_tool_search` - find and load specific tools
3. Full schemas loaded only when needed

---

## 10. Programmatic Usage

### Basic Usage

```typescript
import { buildAgent } from './agent.js';
import { createOpenRouterProvider } from './providers.js';
import { createStandardTools } from './tools.js';

const agent = buildAgent()
  .provider(createOpenRouterProvider())
  .tools(createStandardTools())
  .build();

const result = await agent.run('List all TypeScript files');
console.log(result.response);
```

### Builder Pattern

```typescript
const agent = buildAgent()
  .provider(myProvider)
  .tools(myTools)
  // Core features
  .memory({ enabled: true })
  .planning({ enabled: true, autoplan: true })
  .observability({ enabled: true })
  // Multi-agent (Lesson 17)
  .multiAgent({ enabled: true, consensusStrategy: 'voting' })
  .addRole(CODER_ROLE)
  .addRole(REVIEWER_ROLE)
  // ReAct (Lesson 18)
  .react({ enabled: true, maxSteps: 15 })
  // Execution Policies (Lesson 23)
  .executionPolicy({
    enabled: true,
    defaultPolicy: 'prompt',
    intentAware: true,
  })
  // Thread Management (Lesson 24)
  .threads({
    enabled: true,
    autoCheckpoint: true,
  })
  .build();
```

---

## 11. Events

```typescript
agent.subscribe(event => {
  switch (event.type) {
    // Core events
    case 'start':          // Task started
    case 'llm.start':      // LLM call starting
    case 'llm.chunk':      // Streaming chunk
    case 'llm.complete':   // LLM call done
    case 'tool.start':     // Tool execution starting
    case 'tool.complete':  // Tool execution done
    case 'complete':       // Task finished

    // ReAct events (Lesson 18)
    case 'react.thought':       // Reasoning step
    case 'react.action':        // Action being taken
    case 'react.observation':   // Result observed

    // Multi-agent events (Lesson 17)
    case 'multiagent.spawn':    // Agent spawned
    case 'multiagent.complete': // Agent finished
    case 'consensus.reached':   // Team decision

    // Policy events (Lesson 23)
    case 'policy.evaluated':    // Access decision
    case 'intent.classified':   // Intent detected
    case 'grant.created':       // Permission granted

    // Thread events (Lesson 24)
    case 'thread.forked':       // Branch created
    case 'checkpoint.created':  // State saved
    case 'checkpoint.restored': // State restored
    case 'rollback':            // Messages removed

    // Mode events
    case 'mode.changed':        // Mode switched
  }
});
```

---

## 12. Agent Modes

Switch between operational modes for safety and focus:

| Mode | Tools | Purpose |
|------|-------|---------|
| `build` | All | Full access to modify files |
| `plan` | Read-only | Exploration and planning |
| `review` | Read-only | Code review focus |
| `debug` | Read + Test | Debugging with diagnostics |

---

## 13. Built-in Roles

For multi-agent coordination (Lesson 17):

| Role | Capabilities | Authority | Model |
|------|--------------|-----------|-------|
| `researcher` | explore, search, find | 5 | fast |
| `coder` | write, implement, fix | 8 | balanced |
| `reviewer` | review, check, audit | 7 | quality |
| `architect` | design, plan, structure | 9 | quality |
| `debugger` | debug, trace, diagnose | 6 | balanced |
| `documenter` | document, explain | 4 | fast |

---

## 14. Tricks Integration

The following tricks are integrated into the production agent:

| Trick | Production Module | Status |
|-------|-------------------|--------|
| A: Structured Output | Inline JSON extraction | Enhanced |
| B: Token Counter | `economics.ts` | Enhanced |
| C: Prompt Templates | `rules.ts` | Simplified |
| D: Tool Batching | `agent.ts` | Enhanced |
| E: Context Sliding | `compaction.ts` | Enhanced |
| F: Semantic Cache | `semantic-cache.ts` | Enhanced |
| G: Rate Limiter | Error handling | Embedded |
| H: Branching | `thread-manager.ts` | Enhanced |
| I: File Watcher | Not used | Extension point |
| J: LSP Client | `lsp.ts` | Enhanced |
| K: Cancellation | `cancellation.ts` | Enhanced |
| L: Sortable IDs | ID generation | Inline |
| M: Thread Manager | `thread-manager.ts` | Enhanced |
| N: Resource Monitor | `resources.ts` | Enhanced |
| O: JSON Utils | Tool parsing | Inline |

---

## 15. Testing

```bash
# All tests
npm test

# Production agent tests only
npm test -- --grep "Lesson 25"

# Watch mode
npm test -- --watch
```

---

## 16. Extending

### Custom Tools

```typescript
const myTool: ToolDefinition = {
  name: 'my_tool',
  description: 'Does something useful',
  parameters: {
    type: 'object',
    properties: {
      input: { type: 'string', description: 'Input value' },
    },
    required: ['input'],
  },
  dangerLevel: 'safe',
  execute: async ({ input }) => {
    return `Processed: ${input}`;
  },
};

agent.registerTool(myTool);
```

### Custom Agents

Create agents in `.agents/` directory:

```yaml
# .agents/security-reviewer.yaml
name: security-reviewer
description: Reviews code for security vulnerabilities
systemPrompt: |
  You are a security expert. Focus on:
  - Injection vulnerabilities
  - Authentication issues
  - Data exposure
tools: [read_file, grep, glob]
model: quality
capabilities: [security, vulnerability, audit]
```

### Custom Skills

Create skills in `.skills/` directory:

```markdown
---
name: code-review
description: Detailed code review workflow
triggers: ["review this code", "check for issues"]
tags: [review, quality]
---

# Code Review Skill

When reviewing code, follow this approach:

1. Security Analysis
2. Code Quality
3. Performance
```

---

## 17. CLI Options

| Option | Description | Default |
|--------|-------------|---------|
| `-m, --model <model>` | Model to use | `anthropic/claude-sonnet-4` |
| `-p, --permission <mode>` | Permission mode | `interactive` |
| `-i, --max-iterations <n>` | Max iterations | `50` |
| `-t, --task <task>` | Single task mode | - |
| `--mode <mode>` | Initial mode | `build` |
| `--no-memory` | Disable memory | - |
| `--no-sandbox` | Disable sandbox | - |
| `--debug` | Enable debug output | - |
| `-h, --help` | Show help | - |

### Permission Modes

| Mode | Description |
|------|-------------|
| `strict` | Prompt for everything |
| `interactive` | Prompt for dangerous actions |
| `auto-safe` | Auto-allow safe actions |
| `yolo` | Allow everything (dangerous!) |

---

## 18. Dependencies

| Package | Purpose |
|---------|---------|
| `@anthropic-ai/sdk` | Anthropic API client |
| `openai` | OpenAI API client |
| `tiktoken` | Token counting |
| `fast-glob` | File pattern matching |
| `ignore` | .gitignore/.agentignore parsing |
| `yaml` | YAML parsing for configs |
| `chalk` | Terminal colors |
| `ora` | Terminal spinners |
| `commander` | CLI parsing |
| `readline` | Interactive input |

---

## What's Next

This is the culmination of the educational journey. You now have:

1. **Lessons 1-9**: Core agent fundamentals
2. **Lessons 10-22**: Individual advanced features
3. **Lesson 23**: Execution Policies & Intent Classification
4. **Lesson 24**: Thread Management & Advanced Patterns
5. **Lesson 25**: Everything integrated into one powerful tool

Use this agent for actual coding tasks, or study the code to see how all the pieces fit together!
