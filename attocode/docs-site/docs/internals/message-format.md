---
sidebar_position: 2
title: "Message Format"
---

# Message Format

Attocode uses a unified message format internally and translates to provider-specific formats when making API calls.

## Unified Format

Defined in `src/types.ts`:

```typescript
interface Message {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string;
  toolCalls?: ToolCall[];
  toolResults?: ToolResult[];
  toolCallId?: string;
  metadata?: Record<string, unknown>;
}

interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  parseError?: string;
}

interface ToolResult {
  callId: string;
  result: unknown;
  error?: string;
}
```

## Structured Content

For prompt caching, messages support structured content blocks:

```typescript
interface MessageWithStructuredContent {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string | ContentBlock[];
  toolCalls?: ToolCall[];
  toolResults?: ToolResult[];
  toolCallId?: string;
  metadata?: Record<string, unknown>;
}

interface ContentBlock {
  type: 'text';
  text: string;
  cache_control?: { type: 'ephemeral' };
}
```

The `cache_control` marker tells Anthropic's API to cache this content block across requests, reducing costs for repeated context.

## Anthropic Translation

The Anthropic adapter (`src/providers/adapters/anthropic.ts`) converts messages as follows:

| Unified | Anthropic |
|---------|-----------|
| `system` role | Extracted to separate `system` parameter |
| `assistant` with `toolCalls` | Content blocks of type `tool_use` with `id`, `name`, `input` |
| `tool` role with `toolCallId` | `user` message containing `tool_result` content block with `tool_use_id` |
| `cache_control` on content | Passed through as `cache_control: { type: 'ephemeral' }` on content blocks |

Example Anthropic request body:

```json
{
  "model": "claude-sonnet-4-20250514",
  "system": "You are a coding assistant...",
  "messages": [
    { "role": "user", "content": "Read the file" },
    { "role": "assistant", "content": [
      { "type": "tool_use", "id": "call_1", "name": "read_file",
        "input": { "path": "src/main.ts" } }
    ]},
    { "role": "user", "content": [
      { "type": "tool_result", "tool_use_id": "call_1",
        "content": "file contents here..." }
    ]}
  ]
}
```

## OpenAI Translation

The OpenAI adapter converts messages as follows:

| Unified | OpenAI |
|---------|--------|
| `system` role | `{ role: 'system', content: '...' }` |
| `assistant` with `toolCalls` | `{ role: 'assistant', tool_calls: [{ id, type: 'function', function: { name, arguments } }] }` |
| `tool` role | `{ role: 'tool', tool_call_id: '...', content: '...' }` |
| Structured content | Flattened to plain string (OpenAI does not support `cache_control`) |

## OpenRouter Translation

OpenRouter uses OpenAI-compatible format with extensions:

- **Thinking**: Models that support reasoning (DeepSeek-R1, QwQ) include a `thinking` field in the response
- **Cache tokens**: Tracked via `cachedTokens` in usage response
- **Cost**: Retrieved from OpenRouter's generation cost endpoint
- **Tool arguments**: Serialized as JSON string in `function.arguments` (not an object)

## Schema Translation

Tool definitions are described differently per provider:

```typescript
// Anthropic format (used internally)
{
  name: 'read_file',
  description: 'Read a file',
  input_schema: {
    type: 'object',
    properties: { path: { type: 'string' } },
    required: ['path']
  }
}

// OpenAI/OpenRouter format
{
  type: 'function',
  function: {
    name: 'read_file',
    description: 'Read a file',
    parameters: {
      type: 'object',
      properties: { path: { type: 'string' } },
      required: ['path']
    }
  }
}
```

The `toOpenRouterSchema()` function in `src/tools/standard.ts` performs this conversion. The schema content (`properties`, `required`, etc.) is identical; only the wrapper structure differs.

## Response Format

All providers return a unified `ChatResponse`:

```typescript
interface ChatResponse {
  content: string;
  toolCalls?: ToolCall[];
  usage?: {
    inputTokens: number;
    outputTokens: number;
    cacheReadTokens?: number;
    cacheWriteTokens?: number;
    cost?: number;
  };
  model?: string;
  stopReason?: 'end_turn' | 'tool_use' | 'max_tokens' | 'stop_sequence';
  thinking?: string;
}
```

The `stopReason` of `tool_use` indicates the model wants to call tools. The execution loop processes `toolCalls` and feeds results back as `tool` role messages.
