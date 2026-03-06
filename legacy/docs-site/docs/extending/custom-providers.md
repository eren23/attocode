---
sidebar_position: 2
title: "Custom Providers"
---

# Custom Providers

Attocode supports multiple LLM providers through a unified adapter pattern. You can add new providers by implementing the provider interface and registering them with the provider factory.

## Provider Interface

All providers implement `LLMProvider` from `src/providers/types.ts`:

```typescript
interface LLMProvider {
  name?: string;
  chat(
    messages: (Message | MessageWithContent)[],
    options?: ChatOptions
  ): Promise<ChatResponse>;
  stream?(messages: Message[], options?: ChatOptions): AsyncIterable<StreamChunk>;
}
```

For providers that support native tool calling, also implement `LLMProviderWithTools`:

```typescript
interface LLMProviderWithTools extends LLMProvider {
  chatWithTools(
    messages: (Message | MessageWithContent)[],
    tools: ToolDefinitionSchema[],
    options?: ChatOptionsWithTools
  ): Promise<ChatResponseWithTools>;
}
```

## Creating a Provider

Here is a skeleton for a custom provider adapter:

```typescript
import type {
  LLMProvider, LLMProviderWithTools,
  Message, ChatOptions, ChatResponse,
} from '../types.js';
import { registerProvider, hasEnv, requireEnv } from '../provider.js';
import { resilientFetch } from '../resilient-fetch.js';

export class CustomProvider implements LLMProvider, LLMProviderWithTools {
  readonly name = 'custom';
  readonly defaultModel = 'custom-model-v1';

  private apiKey: string;
  private model: string;

  constructor(config?: { apiKey?: string; model?: string }) {
    this.apiKey = config?.apiKey ?? requireEnv('CUSTOM_API_KEY');
    this.model = config?.model ?? this.defaultModel;
  }

  isConfigured(): boolean {
    return hasEnv('CUSTOM_API_KEY');
  }

  async chat(messages: Message[], options?: ChatOptions): Promise<ChatResponse> {
    const model = options?.model ?? this.model;
    // Convert messages to provider format
    const body = this.buildRequestBody(messages, model, options);

    const response = await resilientFetch('https://api.custom.ai/v1/chat', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${this.apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });

    return this.parseResponse(await response.json());
  }
}
```

## Message Format Conversion

Each provider has its own message format. You must convert from the unified `Message` type:

- **Anthropic**: System messages go into a separate `system` parameter. Tool calls are `tool_use` content blocks. Tool results are `tool_result` blocks inside `user` messages. Supports `cache_control` markers.
- **OpenAI**: System messages use `role: 'system'`. Tool calls go on `assistant` messages in `tool_calls` array. Tool results use `role: 'tool'` messages.
- **OpenRouter**: OpenAI-compatible format with additional `thinking` field support and cost tracking via a separate endpoint.

## Tool Definition Translation

Anthropic and OpenAI use different schema wrappers:

```typescript
// Anthropic format
{ name, description, input_schema: { type: 'object', properties, required } }

// OpenAI/OpenRouter format
{ type: 'function', function: { name, description, parameters: { ... } } }
```

Use `toOpenRouterSchema()` from `src/tools/standard.ts` to convert.

## ChatResponse Format

Your provider must return a `ChatResponse`:

```typescript
interface ChatResponse {
  content: string;
  stopReason: 'end_turn' | 'tool_use' | 'max_tokens' | 'stop_sequence';
  thinking?: string;   // For models that expose reasoning
  usage?: {
    inputTokens: number;
    outputTokens: number;
    cacheReadTokens?: number;
    cacheWriteTokens?: number;
    cost?: number;      // USD cost if provider reports it
  };
}
```

## Registering the Provider

Use `registerProvider()` from `src/providers/provider.ts`:

```typescript
registerProvider('custom', {
  detect: () => hasEnv('CUSTOM_API_KEY'),
  create: async () => new CustomProvider(),
  priority: 5, // Lower = higher priority (0=OpenRouter, 1=Anthropic, 2=OpenAI)
});
```

The provider factory auto-detects configured providers by checking environment variables. Priority determines which provider is used when multiple are configured.

## Network Resilience

Use `resilientFetch` from `src/providers/resilient-fetch.ts` for automatic retry and timeout handling:

```typescript
import { resilientFetch, type NetworkConfig } from '../resilient-fetch.js';

const networkConfig: NetworkConfig = {
  timeout: 120000,       // 2 minutes
  maxRetries: 3,
  baseRetryDelay: 1000,  // Exponential backoff
};
```

## Existing Adapters

The built-in adapters in `src/providers/adapters/` serve as reference implementations:

| Adapter | File | API Key Env Var | Priority |
|---------|------|-----------------|----------|
| OpenRouter | `openrouter.ts` | `OPENROUTER_API_KEY` | 0 |
| Anthropic | `anthropic.ts` | `ANTHROPIC_API_KEY` | 1 |
| OpenAI | `openai.ts` | `OPENAI_API_KEY` | 2 |
| Mock | `mock.ts` | Always available | 100 |
