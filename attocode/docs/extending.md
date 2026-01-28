# Extending Attocode

This guide covers how to extend attocode with custom tools, providers, and context engineering techniques.

## Table of Contents

1. [Adding a New Tool](#adding-a-new-tool)
2. [Adding a New Provider](#adding-a-new-provider)
3. [Adding Context Engineering Tricks](#adding-context-engineering-tricks)
4. [Adding Integration Modules](#adding-integration-modules)
5. [Testing Your Extensions](#testing-your-extensions)

## Adding a New Tool

Tools are the primary way agents interact with the external world. Follow these steps to add a new tool.

### Step 1: Define the Tool

Create a new file in `src/tools/` or add to an existing one:

```typescript
// src/tools/my-tool.ts
import type { ToolDefinition, ToolResult } from '../types.js';

/**
 * My custom tool that does something useful.
 */
export function createMyTool(config: MyToolConfig): ToolDefinition {
  return {
    name: 'my_tool',
    description: `
      Brief description of what this tool does.

      When to use: Describe the scenarios where this tool is appropriate.
      When NOT to use: Describe alternatives for other scenarios.
    `,
    inputSchema: {
      type: 'object',
      properties: {
        param1: {
          type: 'string',
          description: 'Description of param1',
        },
        param2: {
          type: 'number',
          description: 'Optional param with default',
          default: 10,
        },
      },
      required: ['param1'],
    },
    execute: async (args: unknown): Promise<ToolResult> => {
      const { param1, param2 = 10 } = args as { param1: string; param2?: number };

      try {
        // Your implementation here
        const result = await doSomething(param1, param2);

        return {
          success: true,
          output: result,
        };
      } catch (error) {
        const err = error instanceof Error ? error : new Error(String(error));
        return {
          success: false,
          error: err.message,
        };
      }
    },
  };
}

interface MyToolConfig {
  // Configuration options
}
```

### Step 2: Export from tools/index.ts

```typescript
// src/tools/index.ts
export { createMyTool } from './my-tool.js';
```

### Step 3: Register the Tool

Add to defaults when creating the agent:

```typescript
// In your agent setup
import { createMyTool } from './tools/index.js';

const tools = [
  ...defaultTools,
  createMyTool({ /* config */ }),
];

const agent = new ProductionAgent({
  provider,
  tools,
});
```

### Tool Best Practices

1. **Clear descriptions**: The LLM relies on descriptions to choose the right tool
2. **Validate inputs**: Always validate the args before using them
3. **Return structured output**: Consistent output format helps the LLM parse results
4. **Handle errors gracefully**: Return `{ success: false, error: '...' }` instead of throwing
5. **Idempotency**: Where possible, make tools safe to retry

### Example: Web Fetch Tool

```typescript
export function createWebFetchTool(): ToolDefinition {
  return {
    name: 'web_fetch',
    description: `
      Fetch content from a URL and return the text content.

      Use for: Reading web pages, API responses, documentation.
      Limitations: Only handles text content, not binary files.
    `,
    inputSchema: {
      type: 'object',
      properties: {
        url: {
          type: 'string',
          description: 'The URL to fetch',
        },
        timeout: {
          type: 'number',
          description: 'Timeout in milliseconds (default: 10000)',
          default: 10000,
        },
      },
      required: ['url'],
    },
    execute: async (args: unknown): Promise<ToolResult> => {
      const { url, timeout = 10000 } = args as { url: string; timeout?: number };

      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeout);

        const response = await fetch(url, { signal: controller.signal });
        clearTimeout(timeoutId);

        if (!response.ok) {
          return {
            success: false,
            error: `HTTP ${response.status}: ${response.statusText}`,
          };
        }

        const text = await response.text();
        return {
          success: true,
          output: text.slice(0, 50000), // Limit output size
        };
      } catch (error) {
        const err = error instanceof Error ? error : new Error(String(error));
        return {
          success: false,
          error: err.name === 'AbortError' ? 'Request timed out' : err.message,
        };
      }
    },
  };
}
```

## Adding a New Provider

Providers connect attocode to different LLM backends.

### Step 1: Create the Adapter

Create a new file in `src/providers/adapters/`:

```typescript
// src/providers/adapters/my-provider.ts
import type {
  LLMProvider,
  LLMProviderWithTools,
  Message,
  MessageWithContent,
  ChatOptions,
  ChatOptionsWithTools,
  ChatResponse,
  ChatResponseWithTools,
} from '../types.js';
import { ProviderError } from '../types.js';

export interface MyProviderConfig {
  apiKey?: string;
  baseUrl?: string;
  model?: string;
}

export class MyProvider implements LLMProviderWithTools {
  readonly name = 'my-provider';
  readonly defaultModel: string;

  private apiKey: string;
  private baseUrl: string;

  constructor(config: MyProviderConfig = {}) {
    this.apiKey = config.apiKey || process.env.MY_PROVIDER_API_KEY || '';
    this.baseUrl = config.baseUrl || 'https://api.myprovider.com/v1';
    this.defaultModel = config.model || 'default-model';
  }

  isConfigured(): boolean {
    return this.apiKey.length > 0;
  }

  async chat(messages: Message[], options?: ChatOptions): Promise<ChatResponse> {
    if (!this.isConfigured()) {
      throw new ProviderError(
        'Provider not configured - set MY_PROVIDER_API_KEY',
        this.name,
        'NOT_CONFIGURED'
      );
    }

    const response = await fetch(`${this.baseUrl}/chat`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${this.apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model: options?.model || this.defaultModel,
        messages: this.formatMessages(messages),
        max_tokens: options?.maxTokens,
        temperature: options?.temperature,
      }),
    });

    if (!response.ok) {
      throw new ProviderError(
        `API error: ${response.status}`,
        this.name,
        this.mapErrorCode(response.status)
      );
    }

    const data = await response.json();

    return {
      content: data.choices[0].message.content,
      model: data.model,
      usage: {
        inputTokens: data.usage?.prompt_tokens || 0,
        outputTokens: data.usage?.completion_tokens || 0,
        totalTokens: data.usage?.total_tokens || 0,
      },
      finishReason: data.choices[0].finish_reason,
    };
  }

  async chatWithTools(
    messages: (Message | MessageWithContent)[],
    options?: ChatOptionsWithTools
  ): Promise<ChatResponseWithTools> {
    // Similar to chat, but include tools in request
    // and parse tool_calls from response
    // ...
  }

  private formatMessages(messages: Message[]): unknown[] {
    // Convert to provider's message format
    return messages.map(m => ({
      role: m.role,
      content: m.content,
    }));
  }

  private mapErrorCode(status: number): ProviderErrorCode {
    if (status === 401) return 'AUTHENTICATION_FAILED';
    if (status === 429) return 'RATE_LIMITED';
    if (status >= 500) return 'SERVER_ERROR';
    return 'UNKNOWN';
  }
}
```

### Step 2: Register the Provider

Add to the provider registry in `src/providers/provider.ts`:

```typescript
import { registerProvider, hasEnv } from './provider.js';
import { MyProvider } from './adapters/my-provider.js';

// Register at module load
registerProvider('my-provider', {
  detect: () => hasEnv('MY_PROVIDER_API_KEY'),
  create: async () => new MyProvider(),
  priority: 5, // Lower = higher priority
});
```

### Step 3: Export Types

Add exports to `src/providers/index.ts`:

```typescript
export { MyProvider, type MyProviderConfig } from './adapters/my-provider.js';
```

### Provider Best Practices

1. **Implement both interfaces**: Support both `chat` and `chatWithTools`
2. **Handle rate limits**: Return appropriate error codes for retry logic
3. **Track usage**: Always populate the `usage` field for cost tracking
4. **Stream support**: Consider implementing streaming for better UX
5. **Test thoroughly**: Providers need robust error handling

## Adding Context Engineering Tricks

Context engineering techniques help manage long conversations and improve agent performance.

### Step 1: Create the Trick

Create a new file in `src/tricks/`:

```typescript
// src/tricks/my-trick.ts

export interface MyTrickConfig {
  enabled?: boolean;
  threshold?: number;
}

export interface MyTrickResult {
  applied: boolean;
  tokensSaved?: number;
  metadata?: Record<string, unknown>;
}

/**
 * My context engineering trick.
 *
 * Problem: Describe the problem this solves
 * Solution: Describe the approach
 *
 * @example
 * ```typescript
 * const trick = createMyTrick({ threshold: 0.8 });
 * const result = trick.apply(messages);
 * ```
 */
export class MyTrick {
  private config: Required<MyTrickConfig>;

  constructor(config: MyTrickConfig = {}) {
    this.config = {
      enabled: config.enabled ?? true,
      threshold: config.threshold ?? 0.5,
    };
  }

  /**
   * Apply the trick to a message history.
   */
  apply(messages: Message[]): { messages: Message[]; result: MyTrickResult } {
    if (!this.config.enabled) {
      return { messages, result: { applied: false } };
    }

    // Your trick implementation
    const transformed = this.transform(messages);

    return {
      messages: transformed,
      result: {
        applied: true,
        tokensSaved: this.estimateTokensSaved(messages, transformed),
      },
    };
  }

  private transform(messages: Message[]): Message[] {
    // Implementation
    return messages;
  }

  private estimateTokensSaved(original: Message[], transformed: Message[]): number {
    // Rough estimate: 4 chars per token
    const originalTokens = JSON.stringify(original).length / 4;
    const transformedTokens = JSON.stringify(transformed).length / 4;
    return Math.max(0, originalTokens - transformedTokens);
  }
}

export function createMyTrick(config: MyTrickConfig = {}): MyTrick {
  return new MyTrick(config);
}
```

### Step 2: Integrate with Context Engineering

Add to the context engineering manager:

```typescript
// In src/integrations/context-engineering.ts or your custom setup

import { createMyTrick } from '../tricks/my-trick.js';

// In the manager's constructor or setup
this.myTrick = createMyTrick(config.myTrick);

// In the process method
if (this.myTrick) {
  const { messages: transformed, result } = this.myTrick.apply(messages);
  if (result.applied) {
    this.emit({ type: 'trick.applied', trick: 'my-trick', result });
  }
  messages = transformed;
}
```

### Common Trick Patterns

**1. Summarization Trick**
```typescript
// Summarize old messages, keep recent ones verbatim
const KEEP_RECENT = 10;
const oldMessages = messages.slice(0, -KEEP_RECENT);
const recentMessages = messages.slice(-KEEP_RECENT);

const summary = await this.summarize(oldMessages);
return [
  { role: 'system', content: `[Previous context summary]: ${summary}` },
  ...recentMessages,
];
```

**2. Deduplication Trick**
```typescript
// Remove duplicate tool calls and their results
const seen = new Set<string>();
return messages.filter(m => {
  if (m.role !== 'tool_result') return true;
  const key = `${m.toolCallId}:${JSON.stringify(m.content)}`;
  if (seen.has(key)) return false;
  seen.add(key);
  return true;
});
```

**3. Priority Injection Trick**
```typescript
// Inject reminders at strategic points
const REMINDER_INTERVAL = 20;
return messages.map((m, i) => {
  if (i % REMINDER_INTERVAL === 0 && i > 0) {
    return {
      ...m,
      content: `[Reminder: Stay focused on the goal]\n${m.content}`,
    };
  }
  return m;
});
```

## Adding Integration Modules

Integration modules are larger features that plug into the agent system.

### Step 1: Create the Module

Create a new file in `src/integrations/`:

```typescript
// src/integrations/my-integration.ts

export interface MyIntegrationConfig {
  enabled?: boolean;
  // Other config...
}

export type MyIntegrationEvent =
  | { type: 'my.started'; data: string }
  | { type: 'my.completed'; result: unknown }
  | { type: 'my.error'; error: string };

export type MyIntegrationEventListener = (event: MyIntegrationEvent) => void;

/**
 * My integration module.
 *
 * Provides: Describe what this provides
 * Requires: List any dependencies
 */
export class MyIntegrationManager {
  private config: Required<MyIntegrationConfig>;
  private listeners: MyIntegrationEventListener[] = [];

  constructor(config: MyIntegrationConfig = {}) {
    this.config = {
      enabled: config.enabled ?? true,
    };
  }

  /**
   * Main functionality.
   */
  async process(input: string): Promise<ProcessResult> {
    this.emit({ type: 'my.started', data: input });

    try {
      const result = await this.doWork(input);
      this.emit({ type: 'my.completed', result });
      return result;
    } catch (error) {
      const err = error instanceof Error ? error : new Error(String(error));
      this.emit({ type: 'my.error', error: err.message });
      throw error;
    }
  }

  /**
   * Subscribe to events.
   */
  on(listener: MyIntegrationEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  private emit(event: MyIntegrationEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }

  private async doWork(input: string): Promise<ProcessResult> {
    // Implementation
  }
}

export function createMyIntegration(
  config: MyIntegrationConfig = {}
): MyIntegrationManager {
  return new MyIntegrationManager(config);
}

interface ProcessResult {
  // Result type
}
```

### Step 2: Export from integrations/index.ts

```typescript
// src/integrations/index.ts
export {
  MyIntegrationManager,
  createMyIntegration,
  type MyIntegrationConfig,
  type MyIntegrationEvent,
  type MyIntegrationEventListener,
} from './my-integration.js';
```

### Step 3: Wire into ProductionAgent

Modify `src/agent.ts` to use the new integration:

```typescript
// In ProductionAgent class
private myIntegration: MyIntegrationManager | null = null;

// In initializeFeatures()
if (isFeatureEnabled(this.config.myIntegration)) {
  this.myIntegration = createMyIntegration(this.config.myIntegration);

  // Forward events
  this.myIntegration.on(event => {
    this.emit({ type: 'integration', source: 'my-integration', event });
  });
}

// In run() or appropriate method
if (this.myIntegration) {
  await this.myIntegration.process(prompt);
}
```

### Step 4: Add Configuration Types

Update `src/types.ts`:

```typescript
export interface ProductionAgentConfig {
  // ... existing config
  myIntegration?: MyIntegrationConfig | false;
}
```

## Testing Your Extensions

### Unit Tests

Create tests in `tests/`:

```typescript
// tests/tools/my-tool.test.ts
import { describe, it, expect } from 'vitest';
import { createMyTool } from '../../src/tools/my-tool.js';

describe('MyTool', () => {
  it('should execute successfully with valid input', async () => {
    const tool = createMyTool({ /* config */ });

    const result = await tool.execute({ param1: 'test' });

    expect(result.success).toBe(true);
    expect(result.output).toBeDefined();
  });

  it('should handle errors gracefully', async () => {
    const tool = createMyTool({ /* config */ });

    const result = await tool.execute({ param1: '' });

    expect(result.success).toBe(false);
    expect(result.error).toBeDefined();
  });
});
```

### Integration Tests

```typescript
// tests/integrations/my-integration.test.ts
import { describe, it, expect, vi } from 'vitest';
import { createMyIntegration } from '../../src/integrations/my-integration.js';

describe('MyIntegration', () => {
  it('should emit events during processing', async () => {
    const integration = createMyIntegration();
    const events: MyIntegrationEvent[] = [];

    integration.on(event => events.push(event));

    await integration.process('test input');

    expect(events).toContainEqual(
      expect.objectContaining({ type: 'my.started' })
    );
    expect(events).toContainEqual(
      expect.objectContaining({ type: 'my.completed' })
    );
  });
});
```

### Running Tests

```bash
# Run all tests
npm test

# Run specific test file
npm test -- tests/tools/my-tool.test.ts

# Watch mode
npm run test:watch

# Coverage
npm run test:coverage
```

---

## See Also

- [Architecture](./architecture.md) - Overall system architecture
- [CLAUDE.md](../.claude/CLAUDE.md) - Project conventions
