# API Reference

Core interfaces for programmatic use of attocode.

## Core Types

### Message

Represents a message in the conversation.

```typescript
interface Message {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string;
  toolCalls?: ToolCall[];
  toolResults?: ToolResult[];
  toolCallId?: string;  // For tool role messages
}
```

### ToolCall

A tool invocation requested by the LLM.

```typescript
interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}
```

### ToolResult

Result from executing a tool.

```typescript
interface ToolResult {
  callId: string;
  result: unknown;
  error?: string;
}
```

### ToolDefinition

Defines a tool the agent can use.

```typescript
interface ToolDefinition {
  name: string;
  description: string;
  parameters: Record<string, unknown>;  // JSON Schema
  execute: (args: Record<string, unknown>) => Promise<unknown>;
  dangerLevel?: 'safe' | 'moderate' | 'dangerous';
}
```

**Example:**

```typescript
const readFileTool: ToolDefinition = {
  name: 'read_file',
  description: 'Read contents of a file',
  parameters: {
    type: 'object',
    properties: {
      path: { type: 'string', description: 'File path to read' }
    },
    required: ['path']
  },
  execute: async (args) => {
    const content = await fs.readFile(args.path as string, 'utf-8');
    return content;
  },
  dangerLevel: 'safe'
};
```

## Provider Interface

### LLMProvider

Base interface for LLM providers.

```typescript
interface LLMProvider {
  name?: string;
  chat(messages: Message[], options?: ChatOptions): Promise<ChatResponse>;
  stream?(messages: Message[], options?: ChatOptions): AsyncIterable<StreamChunk>;
}
```

### LLMProviderWithTools

Extended interface with native tool support (defined in `src/providers/types.ts`).

```typescript
interface LLMProviderWithTools extends LLMProvider {
  chatWithTools(
    messages: (Message | MessageWithContent)[],
    options?: ChatOptionsWithTools
  ): Promise<ChatResponseWithTools>;
}
```

### ChatOptions

Options for chat requests.

```typescript
interface ChatOptions {
  model?: string;
  maxTokens?: number;
  temperature?: number;
  tools?: ToolDefinition[];
}
```

### ChatResponse

Response from the LLM.

```typescript
interface ChatResponse {
  content: string;
  toolCalls?: ToolCall[];
  usage?: TokenUsage;
  model?: string;
  stopReason?: 'end_turn' | 'tool_use' | 'max_tokens' | 'stop_sequence';
  thinking?: string;  // For models with extended thinking
}
```

### TokenUsage

Token usage metrics.

```typescript
interface TokenUsage {
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  cacheReadTokens?: number;
  cacheWriteTokens?: number;
  cost?: number;
}
```

## Available Providers

Providers are created via factory functions in `src/providers/provider.ts`:

```typescript
import { getProvider, createProvider } from './providers/provider.js';

// Auto-detect from environment
const provider = await getProvider();

// Or create specific provider
const anthropic = await createProvider({ type: 'anthropic' });
const openrouter = await createProvider({ type: 'openrouter' });
const openai = await createProvider({ type: 'openai' });
```

**Environment variables for auto-detection:**
- `OPENROUTER_API_KEY` - OpenRouter (priority 1)
- `ANTHROPIC_API_KEY` - Anthropic (priority 2)
- `OPENAI_API_KEY` - OpenAI (priority 3)

## Configuration

### ProductionAgentConfig

Main configuration for the agent.

```typescript
interface ProductionAgentConfig {
  // Required
  provider: LLMProvider;
  tools: ToolDefinition[];

  // Optional
  systemPrompt?: string;
  model?: string;
  maxTokens?: number;
  temperature?: number;
  maxIterations?: number;

  // Feature configs (all optional)
  hooks?: HooksConfig | false;
  memory?: MemoryConfig | false;
  planning?: PlanningConfig | false;
  sandbox?: SandboxConfig | false;
  humanInLoop?: HumanInLoopConfig | false;
  routing?: RoutingConfig | false;
  economics?: EconomicsConfig | false;
  contextEngineering?: ContextEngineeringConfig | false;
}
```

Disable a feature by setting it to `false`:

```typescript
const config = {
  provider,
  tools,
  memory: false,  // Disabled
  planning: { enabled: true, planFile: './plan.md' }  // Enabled with config
};
```

## Events

The agent emits events for observability:

```typescript
agent.on((event: AgentEvent) => {
  switch (event.type) {
    case 'start':
      console.log('Agent started');
      break;
    case 'llm.complete':
      console.log(`LLM responded, tokens: ${event.usage?.totalTokens}`);
      break;
    case 'tool.start':
      console.log(`Executing: ${event.tool}`);
      break;
    case 'tool.complete':
      console.log(`Tool result: ${event.result}`);
      break;
    case 'complete':
      console.log('Agent finished');
      break;
  }
});
```

**Event types:**
- `start` - Agent run started
- `planning` - Planning phase
- `llm.start`, `llm.complete` - LLM request lifecycle
- `tool.start`, `tool.complete` - Tool execution lifecycle
- `approval.request`, `approval.response` - Permission requests
- `complete` - Agent run finished
- `error` - Error occurred

## See Also

- [Architecture](./architecture.md) - System design and data flow
- [Extending](./extending.md) - Adding providers, tools, integrations
- [Skills & Agents Guide](./skills-and-agents-guide.md) - Custom skills and agents
