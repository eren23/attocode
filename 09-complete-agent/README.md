# Lesson 9: Complete Agent

## Milestone: Agent Foundations Complete

**Congratulations!** This lesson marks the completion of Part 1: Foundations. You now have a production-capable AI agent built from first principles.

---

## What You've Built

By reaching this point, your agent includes:

| Capability | Lesson | What It Does |
|------------|--------|--------------|
| **Core Loop** | 1 | The fundamental ask-execute-repeat pattern |
| **Multi-Provider** | 2 | Works with Anthropic, OpenAI, Azure, OpenRouter |
| **Tool System** | 3 | Safe tool execution with Zod validation |
| **Streaming** | 4 | Real-time response display |
| **Error Recovery** | 5 | Intelligent retry and circuit breakers |
| **Testing** | 6 | Deterministic testing with mock providers |
| **MCP Integration** | 7 | Extensible via Model Context Protocol |
| **Cache Optimization** | 8 | Reduced latency and costs via caching |

This lesson integrates everything into a "mini Claude Code" - a complete, working agent.

---

## Running the Agent

### Interactive REPL Mode

```bash
npm run lesson:9
```

This starts an interactive session where you can chat with the agent and watch it use tools.

### Single Task Mode

```bash
npm run lesson:9 -- "list all files in the current directory"
```

The agent will complete the task and exit.

### Options

```bash
npm run lesson:9 -- --help

Options:
  --model, -m        Specify LLM model to use
  --permission, -p   Permission mode: strict, interactive, auto-safe, yolo
  --max-iterations   Maximum tool use iterations (default: 20)
  --task, -t         Run a single task instead of REPL
```

---

## Features Demonstrated

### 1. Native Tool Use

Unlike lessons 1-3 which parsed JSON from markdown, this agent uses native tool calling:

```typescript
// The LLM returns structured tool calls directly
const response = await provider.chat(messages, {
  tools: getToolDefinitions(),
});

// Tool calls are already parsed
for (const toolCall of response.toolCalls) {
  const result = await executeTool(toolCall.name, toolCall.input);
}
```

### 2. Permission System

The agent supports multiple permission modes:

- **strict**: Block all dangerous operations
- **interactive**: Ask user for approval (default)
- **auto-safe**: Auto-approve safe operations, block dangerous
- **yolo**: Auto-approve everything (use with caution!)

### 3. Context Management

Conversations persist within a session:

```typescript
// Context tracks conversation history
const context = createContext({
  systemPrompt: SYSTEM_PROMPT,
  maxTokens: 8000,
});

// Messages accumulate across turns
context.addMessage({ role: 'user', content: userInput });
context.addMessage({ role: 'assistant', content: response });
```

### 4. Input Pattern Detection

The agent recognizes special patterns in user input:

```typescript
// @file references inject file contents
"Summarize @README.md"

// URLs are fetched and included
"What does https://example.com/api say?"

// Multiple files can be referenced
"Compare @file1.ts and @file2.ts"
```

---

## Code Structure

```
09-complete-agent/
├── main.ts           # Entry point and CLI parsing
├── agent.ts          # Core agent loop implementation
├── repl.ts           # Interactive REPL interface
├── tools.ts          # Tool definitions and execution
├── types.ts          # TypeScript types
├── cache.ts          # Response caching utilities
├── input-patterns.ts # @file and URL detection
├── context/          # Context management utilities
├── harness/          # Testing harness
└── examples/         # Example usage scripts
```

---

## What You Can Do With This

This foundation enables you to:

1. **Build custom agents** - Swap tools for your domain
2. **Create automation** - Run tasks programmatically
3. **Extend capabilities** - Add MCP servers
4. **Test reliably** - Use mock providers
5. **Deploy safely** - Permission system prevents accidents

---

## What's Next?

With the foundation complete, you can continue in several directions:

### Path A: Production Infrastructure (Lessons 10-13)

Add production-ready features:
- **Lesson 10**: Hook system for extensibility
- **Lesson 11**: Plugin architecture for modularity
- **Lesson 12**: Rules system for configuration
- **Lesson 13**: Client/server separation

### Path B: AI Reasoning (Lessons 14-18)

Add advanced cognitive capabilities:
- **Lesson 14**: Memory systems for context persistence
- **Lesson 15**: Planning for task decomposition
- **Lesson 16**: Reflection for self-improvement
- **Lesson 17**: Multi-agent coordination
- **Lesson 18**: ReAct for structured reasoning

### Path C: Operations (Lessons 19-22)

Add production operations:
- **Lesson 19**: Observability and tracing
- **Lesson 20**: Sandboxing for safe execution
- **Lesson 21**: Human-in-the-loop approval
- **Lesson 22**: Model routing and fallbacks

### Path D: Build Something!

You have everything you need to build a real agent. Consider:
- A code review assistant
- A documentation generator
- A test writer
- A debugging helper
- A refactoring tool

---

## Try It Yourself

### Exercise: Add a Custom Tool

Add a new tool to `tools.ts`:

```typescript
// 1. Define the schema
const myToolSchema = z.object({
  input: z.string().describe('The input to process'),
});

// 2. Create the tool
const myTool = defineTool(
  'my_tool',
  'Description of what this tool does',
  myToolSchema,
  async (params) => {
    // Your implementation here
    return `Processed: ${params.input}`;
  },
  'safe' // danger level
);

// 3. Register it in the tool registry
```

See the `exercises/` directory for more practice opportunities.

---

## Key Takeaways

1. **The agent loop is simple** - Ask, execute, repeat
2. **Abstraction enables flexibility** - Same code, different providers
3. **Tools are the interface** - LLMs act through tool calls
4. **Permissions protect users** - Safety by default
5. **Testing enables confidence** - Deterministic mocks
6. **Caching saves money** - Reuse when possible

**You've built an AI agent from first principles. The real learning starts now!**
