# Attocode

A comprehensive course that teaches you to build production-ready AI coding agents from scratch, using TypeScript and modern patterns that go beyond typical tutorials.

> **26 lessons** covering foundations through production deployment, with hands-on exercises and a complete working agent at the end of each major section.

## Inspiration

This course was heavily inspired by the article **["You Could've Invented Claude Code"](https://erikschluntz.com/software/2025/05/09/you-couldve-invented-claude-code.html)** by Erik Schluntz.

That article demonstrates a powerful insight: the core of Claude Code is just a loop that lets an AI read files, run commands, and iterate until a task is done. Starting from a 50-line bash script, it builds up to a ~150-line Python agent that captures the essence of how AI coding agents work.

**Attocode takes this first-principles approach and expands it into a full curriculum:**

| "You Could've Invented Claude Code" | Attocode |
|-------------------------------------|----------|
| Single tutorial | 26 progressive lessons |
| Python + bash | TypeScript throughout |
| ~150 lines of code | Production-ready patterns |
| Core concepts only | Memory, planning, reflection, multi-agent |
| Read and run | Hands-on exercises with tests |
| One provider | Multi-provider abstraction |
| Basic safety | Sandboxing, human-in-loop, observability |

If you haven't read the original article, we highly recommend it as a conceptual primer before diving into this course. It will give you the mental model; Attocode will give you the depth.

## Quick Start

```bash
# Clone and install
git clone https://github.com/eren23/attocode.git
cd attocode
npm install

# Set up your API key
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY or OPENAI_API_KEY

# Run your first lesson
npm run lesson:1
```

**New here?** See [Getting Started Guide](./docs/GETTING_STARTED.md) for detailed setup instructions.

## Documentation

| Guide | Description |
|-------|-------------|
| [Getting Started](./docs/GETTING_STARTED.md) | Installation, setup, and verification |
| [Provider Setup](./docs/PROVIDERS.md) | Configure Anthropic, OpenAI, Azure, or OpenRouter |
| [Running Lessons](./docs/RUNNING.md) | Quick reference for all 26 lessons |

## What You'll Build

By the end of this course, you'll have built a production-ready coding agent that can:

- **Use any LLM provider** (Anthropic, OpenAI, Azure, or your own)
- **Execute tools safely** with validation and permissions
- **Stream responses** in real-time
- **Recover from failures** with intelligent retry strategies
- **Be tested** with deterministic mocks
- **Extend capabilities** via MCP (Model Context Protocol)
- **Remember context** across sessions with memory systems
- **Plan and decompose** complex tasks
- **Reflect and improve** on its own outputs
- **Coordinate multiple agents** for complex workflows
- **Expose APIs** for client/server architectures
- **Monitor and trace** operations for observability
- **Execute code safely** in sandboxed environments

## Prerequisites

- Node.js 18+
- Basic TypeScript knowledge
- Understanding of async/await and Promises
- (Optional) API key from Anthropic, OpenAI, or Azure

## Getting Started

```bash
# Install dependencies
npm install

# Run any lesson (1-22)
npm run lesson:1   # Core loop
npm run lesson:2   # Provider abstraction
npm run lesson:3   # Tool system
npm run lesson:4   # Streaming
npm run lesson:5   # Error recovery
npm run lesson:6   # Testing (runs tests)
npm run lesson:7   # MCP integration
npm run lesson:8   # Cache hitting
npm run lesson:9   # Complete agent
npm run lesson:10  # Hook system
npm run lesson:11  # Plugin architecture
npm run lesson:12  # Rules system
npm run lesson:13  # Client/server
npm run lesson:14  # Memory systems
npm run lesson:15  # Planning
npm run lesson:16  # Self-reflection
npm run lesson:17  # Multi-agent
npm run lesson:18  # ReAct pattern
npm run lesson:19  # Observability
npm run lesson:20  # Sandboxing
npm run lesson:21  # Human-in-loop
npm run lesson:22  # Model routing
npm run lesson:23  # Execution policies
npm run lesson:24  # Advanced patterns
npm run lesson:25  # Production agent
npm run lesson:26  # Tracing & evaluation
```

## Course Structure

### Lesson 1: The Core Loop
**Focus**: Understanding the fundamental agent pattern

The heart of every AI agent is a simple loop: ask the LLM what to do, execute the action, show the result, repeat.

```typescript
while (task not complete) {
  response = await llm.chat(messages)
  if (response.hasToolCall) {
    result = await executeTool(response.toolCall)
    messages.push({ role: 'user', content: result })
  } else {
    return response // Done!
  }
}
```

**Files**: `01-core-loop/`
**Key Concepts**: Agent loop, tool parsing, conversation history

---

### Lesson 2: Provider Abstraction
**Focus**: Supporting multiple LLM providers

Real agents need to work with different LLM providers. We build an abstraction that lets you swap providers without changing agent code.

```typescript
// Any provider implements this interface
interface LLMProvider {
  chat(messages: Message[]): Promise<ChatResponse>
}

// Auto-detect from environment
const provider = await getProvider() // Uses ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.
```

**Files**: `02-provider-abstraction/`
**Key Concepts**: Adapter pattern, environment detection, provider registry

---

### Lesson 3: Tool System
**Focus**: Building a robust tool system with validation

Tools are how agents affect the world. A proper tool system needs:
- JSON Schema validation (with Zod)
- Permission checking for dangerous operations
- Clear contracts for the LLM

```typescript
const tool = defineTool(
  'write_file',
  'Write content to a file',
  z.object({
    path: z.string(),
    content: z.string(),
  }),
  async (input) => { /* execute */ },
  'moderate' // danger level
)
```

**Files**: `03-tool-system/`
**Key Concepts**: Zod validation, permission modes, danger classification

---

### Lesson 4: Streaming
**Focus**: Real-time response streaming

Batch responses feel sluggish. Streaming shows users what's happening in real-time using async iterators.

```typescript
async function* streamResponse(): AsyncGenerator<StreamEvent> {
  for await (const chunk of sseStream) {
    yield { type: 'text', text: chunk }
  }
  yield { type: 'done', reason: 'complete' }
}
```

**Files**: `04-streaming/`
**Key Concepts**: Async generators, SSE parsing, terminal UI

---

### Lesson 5: Error Recovery
**Focus**: Handling failures gracefully

Real APIs fail. We build retry logic with multiple strategies and circuit breakers for cascading failures.

```typescript
const result = await retryManager.execute(
  () => fetchFromAPI(),
  { 
    strategy: 'exponential',
    maxRetries: 3,
    onEvent: (e) => console.log(e)
  }
)
```

**Files**: `05-error-recovery/`
**Key Concepts**: Error classification, retry strategies, circuit breaker pattern

---

### Lesson 6: Testing Agents
**Focus**: Making agents testable

Agents are hard to test because LLMs are non-deterministic. We build mock providers and testing utilities.

```typescript
const mock = new ScriptedLLMProvider([
  { response: 'I\'ll read the file.\n```json{"tool":"read_file"...}```' },
  { response: 'Done!' },
])

const result = await runAgent('fix bug', { llm: mock })
expect(result.toolsUsed).toContain('read_file')
```

**Files**: `06-testing-agents/`
**Key Concepts**: Mock providers, fixtures, behavioral assertions

---

### Lesson 7: MCP Integration
**Focus**: Extending capabilities via protocol

MCP (Model Context Protocol) lets you add tools from external servers, making agents extensible.

```typescript
const client = new MCPClient()
await client.connect({ type: 'stdio', command: 'my-mcp-server' })

const tools = await client.listTools() // Dynamic tool discovery
const result = await client.callTool('search', { query: 'auth' })
```

**Files**: `07-mcp-integration/`
**Key Concepts**: MCP protocol, stdio transport, tool aggregation

---

### Lesson 8: Cache Hitting
**Focus**: Optimizing LLM interactions with caching

Learn to implement prompt caching strategies that reduce latency and costs.

**Files**: `08-cache-hitting/`
**Key Concepts**: Prompt caching, cache invalidation, cost optimization

---

### Lesson 9: Complete Agent
**Focus**: Putting it all together

Build a complete, production-ready agent combining all previous lessons.

**Files**: `09-complete-agent/`
**Key Concepts**: Integration, REPL interface, production patterns

---

### MILESTONE: Agent Foundations Complete

At this point, you have a fully functional agent with multi-provider support, tool execution, streaming, error handling, testing, MCP integration, and caching. This is a solid foundation for production use.

**What's next?** Choose your path:
- **Production Infrastructure** (Lessons 10-13) - Hooks, plugins, rules, client/server
- **AI Reasoning** (Lessons 14-18) - Memory, planning, reflection, multi-agent
- **Operations** (Lessons 19-22) - Observability, sandboxing, human-in-loop
- **Advanced Patterns** (Lessons 23-26) - Execution policies, advanced patterns, production agent, tracing & evaluation

---

## Part 2: Production Infrastructure (Lessons 10-13)

### Lesson 10: Hook & Event System
**Focus**: Event-driven extensibility

Build an event bus and hook system that allows extending agent behavior without modifying core code.

```typescript
eventBus.on('tool.before', async (event) => {
  console.log(`About to execute: ${event.tool}`);
  // Can block or modify
});
```

**Files**: `10-hook-system/`
**Key Concepts**: Event bus, hook priorities, sync/async hooks

---

### Lesson 11: Plugin Architecture
**Focus**: Modular extensibility

Create a plugin system that allows third-party extensions with isolated contexts.

```typescript
const plugin: Plugin = {
  name: 'security',
  initialize(ctx) {
    ctx.registerHook('tool.before', validateDangerousOps);
    ctx.registerTool(scanFileTool);
  }
};
```

**Files**: `11-plugin-system/`
**Key Concepts**: Plugin lifecycle, sandboxed context, hot-reloading

---

### Lesson 12: Rules & Instructions System
**Focus**: Dynamic configuration

Load and merge rules from multiple sources (CLAUDE.md, project files) with priority handling.

**Files**: `12-rules-system/`
**Key Concepts**: Hierarchical config, rule merging, glob patterns

---

### Lesson 13: Client/Server Separation
**Focus**: API architecture

Separate agent logic from UI with a proper client/server architecture.

```typescript
const client = createAgentClient({ serverUrl: 'http://localhost:3000' });
await client.connect();
const session = await client.createSession({ model: 'gpt-4' });
const response = await client.sendMessage(session.id, 'Hello!');
```

**Files**: `13-client-server/`
**Key Concepts**: Session management, protocol design, event streaming

---

## Part 3: AI Reasoning (Lessons 14-18)

### Lesson 14: Memory Systems
**Focus**: Persistent context

Implement episodic and semantic memory for context that persists across sessions.

```typescript
const memory = createMemorySystem({
  stores: { episodic: episodicStore, semantic: semanticStore },
  retriever: hybridRetriever,
});

const relevant = await memory.retrieve('authentication flow', { limit: 5 });
```

**Files**: `14-memory-systems/`
**Key Concepts**: Memory types, importance scoring, retrieval strategies

---

### Lesson 15: Planning & Decomposition
**Focus**: Task breakdown

Build a planning system that decomposes complex tasks into manageable steps.

```typescript
const plan = await planner.createPlan('Add user authentication', context);
// Returns: { tasks: [...], dependencies: [...], estimatedSteps: 5 }
```

**Files**: `15-planning/`
**Key Concepts**: Task decomposition, dependency graphs, re-planning

---

### Lesson 16: Self-Reflection & Critique
**Focus**: Output improvement

Implement reflection loops that improve output quality through self-critique.

```typescript
const { output, reflections } = await reflectionLoop.execute(
  generateCode,
  'Create a secure login form',
  { maxAttempts: 3 }
);
```

**Files**: `16-reflection/`
**Key Concepts**: Critique prompts, confidence scoring, iteration limits

---

### Lesson 17: Multi-Agent Coordination
**Focus**: Agent teams

Coordinate multiple specialized agents to solve complex problems.

```typescript
const team = createAgentTeam({
  roles: [coderRole, reviewerRole, testerRole],
  orchestrator: roundRobinOrchestrator,
});

const result = await team.execute(complexTask);
```

**Files**: `17-multi-agent/`
**Key Concepts**: Role specialization, orchestration, consensus

---

### Lesson 18: ReAct Pattern
**Focus**: Structured reasoning

Implement the ReAct (Reasoning + Acting) pattern for explicit thought chains.

```typescript
// Each step shows: Thought → Action → Observation
for await (const step of reactAgent.run('Find and fix the bug')) {
  console.log(`Thought: ${step.thought}`);
  console.log(`Action: ${step.action.name}`);
  console.log(`Observation: ${step.observation}`);
}
```

**Files**: `18-react-pattern/`
**Key Concepts**: Thought parsing, observation formatting, trace logging

---

## Part 4: Operations (Lessons 19-22)

### Lesson 19: Observability & Tracing
**Focus**: Production monitoring

Add comprehensive tracing and metrics collection for debugging and optimization.

```typescript
const tracer = createTracer({ exporter: consoleExporter });

await tracer.withSpan('agent.run', async (span) => {
  span.setAttribute('task', task);
  // ... agent execution
});
```

**Files**: `19-observability/`
**Key Concepts**: Spans, metrics, cost attribution

---

### Lesson 20: Sandboxing & Isolation
**Focus**: Safe execution

Execute untrusted code safely with process and container isolation.

```typescript
const sandbox = createProcessSandbox({
  allowedCommands: ['node', 'npm'],
  resourceLimits: { maxCpuSeconds: 10, maxMemoryMB: 512 },
});

const result = await sandbox.execute('node script.js');
```

**Files**: `20-sandboxing/`
**Key Concepts**: Process isolation, resource limits, security policies

---

### Lesson 21: Human-in-the-Loop Patterns
**Focus**: Oversight and approval

Implement approval workflows for high-risk operations.

```typescript
const queue = createApprovalQueue({
  policy: { riskThreshold: 'moderate', timeout: 30000 },
});

const approved = await queue.requestApproval({
  action: deleteFiles,
  risk: 'high',
  context: 'Deleting production logs',
});
```

**Files**: `21-human-in-loop/`
**Key Concepts**: Risk assessment, approval workflows, audit logging

---

### Lesson 22: Model Routing & Fallbacks
**Focus**: Intelligent model selection

Route tasks to appropriate models based on complexity, cost, and capabilities.

```typescript
const router = createSmartRouter({
  models: [gpt4, claude, haiku],
  rules: [
    { condition: isSimple, model: 'haiku' },
    { condition: needsVision, model: 'gpt-4-vision' },
  ],
  fallbackChain: ['gpt-4', 'claude-3-sonnet', 'gpt-3.5-turbo'],
});
```

**Files**: `22-model-routing/`
**Key Concepts**: Capability matching, cost optimization, circuit breakers

---

## Part 5: Advanced Patterns (Lessons 23-26)

### Lesson 23: Execution Policies
**Focus**: Policy-based execution control

Implement flexible execution policies that control how tools are executed, with support for timeouts, retries, and conditional execution.

**Files**: `23-execution-policies/`
**Key Concepts**: Policy composition, execution control, conditional logic

---

### Lesson 24: Advanced Patterns
**Focus**: Production integration patterns

Combine all previous concepts into advanced integration patterns for production systems.

**Files**: `24-advanced-patterns/`
**Key Concepts**: Pattern composition, integration strategies, best practices

---

### Lesson 25: Production Agent
**Focus**: Full production deployment

Build and deploy a complete production-ready agent with all systems integrated.

**Files**: `25-production-agent/`
**Key Concepts**: Production deployment, system integration, configuration management

---

### Lesson 26: Tracing & Evaluation (THIS PART IS WIP, NOT FULLY TESTED)
**Focus**: Performance analysis and benchmarks

Implement comprehensive tracing and evaluation systems to measure and improve agent performance.

**Files**: `26-tracing-and-evaluation/`
**Key Concepts**: Trace collection, performance metrics, evaluation frameworks

---

## Atomic Tricks

Standalone utility modules that can be used independently or integrated into agents:

| Trick | Name | Purpose |
|-------|------|---------|
| A | Structured Output | Parse LLM outputs into typed structures |
| B | Token Counting | Estimate tokens and costs |
| C | Prompt Templates | Compile and render templates |
| D | Tool Batching | Execute tools with concurrency control |
| E | Context Sliding | Manage context window limits |
| F | Semantic Cache | Cache based on semantic similarity |
| G | Rate Limiter | Handle API rate limits |
| H | Branching | Conversation tree management |
| I | File Watcher | Watch files for changes |
| J | LSP Client | Language Server Protocol integration |

**Files**: `tricks/`

---

## Key Differentiators from Typical Tutorials

| Typical Tutorials | This Course |
|------------------|-------------|
| Python + bash | TypeScript throughout |
| Single provider (Anthropic) | Multi-provider abstraction |
| Batch responses | Streaming by default |
| Basic try/catch | Retry strategies + circuit breakers |
| No testing coverage | Testability as first-class concern |
| Hard-coded tools | MCP for extensibility |
| Simple chat loops | Memory, planning, reflection |
| Single agent | Multi-agent coordination |
| No observability | Full tracing and metrics |
| Unsafe execution | Sandboxed environments |

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              Agent System                                     │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                         Client/Server Layer                          │    │
│  │   ┌──────────┐    ┌──────────────┐    ┌────────────────────┐       │    │
│  │   │  Client  │◀──▶│   Protocol   │◀──▶│   Agent Server     │       │    │
│  │   │   SDK    │    │   Handler    │    │   + Sessions       │       │    │
│  │   └──────────┘    └──────────────┘    └────────────────────┘       │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                    │                                         │
│  ┌─────────────────────────────────┼─────────────────────────────────────┐  │
│  │                         Agent Loop Core                                │  │
│  │   ┌─────────┐   ┌──────────────┐   ┌───────────────────┐             │  │
│  │   │ Provider │◀─▶│  Messages    │◀─▶│   Tool Registry   │             │  │
│  │   │  Router  │   │  + Memory    │   │   + Permissions   │             │  │
│  │   └─────────┘   └──────────────┘   └───────────────────┘             │  │
│  │        │              │                      │                        │  │
│  │        ▼              ▼                      ▼                        │  │
│  │   ┌─────────┐   ┌──────────────┐    ┌───────────────┐                │  │
│  │   │Streaming│   │   Planning   │    │  MCP Client   │                │  │
│  │   │ + Events│   │ + Reflection │    │   (tools)     │                │  │
│  │   └─────────┘   └──────────────┘    └───────────────┘                │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                    │                                         │
│  ┌─────────────────────────────────┼─────────────────────────────────────┐  │
│  │                      Infrastructure Layer                              │  │
│  │   ┌──────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────┐  │  │
│  │   │  Hooks   │   │    Error     │   │  Sandboxing  │   │ Tracing  │  │  │
│  │   │+ Plugins │   │   Recovery   │   │  + Security  │   │+ Metrics │  │  │
│  │   └──────────┘   └──────────────┘   └──────────────┘   └──────────┘  │  │
│  │                                                                       │  │
│  │   ┌──────────────────────┐   ┌────────────────────────────────────┐  │  │
│  │   │   Human-in-Loop      │   │      Model Routing + Fallbacks     │  │  │
│  │   │   Approval Queue     │   │      Cost Optimization             │  │  │
│  │   └──────────────────────┘   └────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Running with Real Providers

Set environment variables for real LLM providers:

```bash
# Anthropic Claude
export ANTHROPIC_API_KEY=sk-ant-...

# OpenAI
export OPENAI_API_KEY=sk-...

# Azure OpenAI
export AZURE_OPENAI_API_KEY=...
export AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
export AZURE_OPENAI_DEPLOYMENT=gpt-4
```

## Project Structure

```
lessons/
├── package.json
├── tsconfig.json
├── README.md
│
├── # Part 1: Foundations (Lessons 1-9)
├── 01-core-loop/           # Agent loop basics
├── 02-provider-abstraction/ # Multi-provider support
├── 03-tool-system/         # Tool registry + permissions
├── 04-streaming/           # Real-time streaming
├── 05-error-recovery/      # Retry + circuit breakers
├── 06-testing-agents/      # Mock providers + testing
├── 07-mcp-integration/     # Model Context Protocol
├── 08-cache-hitting/       # Prompt caching
├── 09-complete-agent/      # Full integration
│
├── # Part 2: Production Infrastructure (Lessons 10-13)
├── 10-hook-system/         # Event bus + hooks
├── 11-plugin-system/       # Plugin architecture
├── 12-rules-system/        # Dynamic configuration
├── 13-client-server/       # API architecture
│
├── # Part 3: AI Reasoning (Lessons 14-18)
├── 14-memory-systems/      # Episodic + semantic memory
├── 15-planning/            # Task decomposition
├── 16-reflection/          # Self-critique loops
├── 17-multi-agent/         # Agent coordination
├── 18-react-pattern/       # Reasoning + Acting
│
├── # Part 4: Operations (Lessons 19-22)
├── 19-observability/       # Tracing + metrics
├── 20-sandboxing/          # Code isolation
├── 21-human-in-loop/       # Approval workflows
├── 22-model-routing/       # Model selection
│
├── # Part 5: Advanced Patterns (Lessons 23-26)
├── 23-execution-policies/  # Policy-based execution
├── 24-advanced-patterns/   # Production patterns
├── 25-production-agent/    # Full deployment
├── 26-tracing-and-evaluation/ # Performance analysis
│
├── tricks/                 # Standalone utilities
├── testing/                # Test infrastructure
└── docs/                   # Documentation
```

## Learning Path

### Recommended Order

**Beginners** (new to AI agents):
1. Lessons 1-9 (Foundations)
2. Lesson 18 (ReAct Pattern)
3. Lessons 10-11 (Extensibility)

**Intermediate** (building production systems):
1. Lessons 10-13 (Infrastructure)
2. Lessons 19-22 (Operations)
3. Lessons 23-26 (Advanced Patterns)
4. Atomic Tricks as needed

**Advanced** (AI reasoning systems):
1. Lessons 14-17 (Memory, Planning, Reflection, Multi-Agent)
2. Integrate with production infrastructure

### Dependencies

```
Foundations (1-9)
    │
    ├─► Hooks (10) ─► Plugins (11) ─► Rules (12)
    │
    ├─► Client/Server (13)
    │
    ├─► Memory (14) ─► Multi-Agent (17)
    │
    ├─► Planning (15) ─► Reflection (16) ─► ReAct (18)
    │
    ├─► Observability (19), Sandboxing (20), Human-in-Loop (21), Routing (22)
    │
    └─► Execution Policies (23), Advanced Patterns (24), Production Agent (25), Tracing (26)
```

## What's Next?

After completing this course, you can:

1. **Build production agents** using these patterns
2. **Extend the tool system** with domain-specific tools
3. **Create MCP servers** for your team's tools
4. **Implement custom memory** with vector databases
5. **Build agent teams** for complex workflows
6. **Add observability** to existing systems
7. **Contribute back** improvements to this course

# TODO

- MORE PROVIDERS
- ADDING NOT SUPPORTED LESSONS AND TRICKS INTO THE FINAL AGENT
- MORE LESSONS

## Resources

- [Anthropic Claude API](https://docs.anthropic.com)
- [OpenAI API](https://platform.openai.com/docs)
- [MCP Specification](https://modelcontextprotocol.io)
- [Zod Documentation](https://zod.dev)
- [ReAct Paper](https://arxiv.org/abs/2210.03629)
- [OpenTelemetry](https://opentelemetry.io)

## Contributing

Attocode is an open educational project, and contributions are welcome! Here's how you can help:

### Ways to Contribute

| Contribution Type | Description | Good For |
|-------------------|-------------|----------|
| **Report Issues** | Found a bug, typo, or unclear explanation? Open an issue | Everyone |
| **Fix Existing Lessons** | Improve explanations, fix code errors, add edge cases | Beginners |
| **Add Exercises** | Create new practice problems for existing lessons | Intermediate |
| **New Lessons** | Propose and implement entirely new topics | Advanced |
| **Improve Documentation** | Better guides, diagrams, or examples | Writers |
| **Add Providers** | Implement support for additional LLM providers | Contributors familiar with LLM APIs |

### Current Priorities

Based on the project roadmap:
- More LLM providers (Google, Cohere, local models)
- Additional lessons covering emerging patterns
- Integrating remaining tricks into the production agent (Lesson 25)
- Completing Lesson 26 (Tracing & Evaluation)

### How to Contribute

1. **Fork** the repository
2. **Create a branch** for your changes (`git checkout -b add-new-lesson`)
3. **Follow the existing patterns** - each lesson has:
   - `README.md` with explanation and pseudocode
   - `types.ts` for type definitions
   - `main.ts` as the runnable entry point
   - `exercises/` directory with practice problems
   - `exercises.test.ts` for automated verification
4. **Run tests** to ensure nothing breaks: `npm test`
5. **Submit a PR** with a clear description of your changes

### Code Style

- TypeScript with strict types
- Zod for runtime validation
- Tests for all exercises (Vitest)
- Clear, educational comments in code
- Pseudocode in READMEs before implementation

