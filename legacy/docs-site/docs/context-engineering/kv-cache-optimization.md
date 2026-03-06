---
sidebar_position: 2
title: KV-Cache Optimization (Trick P)
---

# KV-Cache Optimization (Trick P)

## Problem

LLM providers charge differently for cached vs uncached input tokens. With Anthropic's API, cached tokens cost roughly **10x less** than uncached ones. However, the KV-cache invalidates when **any** content changes in the prefix -- a single character difference in the system prompt means the entire prompt is re-processed at full price.

A naive system prompt that starts with a timestamp or session ID invalidates the cache on every single request, throwing away potential cost savings of 60-70%.

## Solution

Structure the context in layers ordered from most-stable to least-stable. Content that never changes sits at the beginning (maximizing cache prefix hits), while dynamic content is pushed to the end.

```
+------------------------------------------+
|  STATIC PREFIX (cached forever)          |  <-- Agent identity, core instructions
|  e.g. "You are a coding assistant..."    |
+------------------------------------------+
|  SEMI-STABLE: Rules (cached if same)     |  <-- .attocode/rules.md
+------------------------------------------+
|  SEMI-STABLE: Tools (cached if same)     |  <-- Tool definitions
+------------------------------------------+
|  SEMI-STABLE: Memory (cached if same)    |  <-- Codebase context
+------------------------------------------+
|  DYNAMIC (never cached)                  |  <-- Session ID, timestamp, mode
|  e.g. "Session: abc | Mode: build"      |
+------------------------------------------+
```

## Key Components

### `stableStringify(obj, indent?)`

JSON serialization with sorted keys, ensuring deterministic output. Two objects with the same keys produce identical strings regardless of insertion order:

```typescript
import { stableStringify } from './kv-cache-context';

// Standard JSON.stringify -- key order not guaranteed
JSON.stringify({ b: 1, a: 2 }); // Could be '{"b":1,"a":2}' or '{"a":2,"b":1}'

// stableStringify -- always same order
stableStringify({ b: 1, a: 2 }); // Always '{"a":2,"b":1}'
```

This is used throughout the agent for serializing tool arguments and message content.

### `CacheAwareContext`

The main class that builds layered prompts. Created via `createCacheAwareContext()`.

**Configuration:**

```typescript
interface CacheAwareConfig {
  staticPrefix: string;           // Never-changing prefix
  cacheBreakpoints?: CacheBreakpoint[];  // Where cache can safely break
  deterministicJson?: boolean;    // Use stableStringify (default: true)
  enforceAppendOnly?: boolean;    // Validate messages aren't modified (default: true)
}
```

### `buildSystemPrompt(options)`

Assembles the layered system prompt as a single string:

```typescript
const prompt = context.buildSystemPrompt({
  rules: rulesContent,       // Semi-stable
  tools: toolDescriptions,   // Semi-stable
  memory: memoryContext,     // Changes occasionally
  dynamic: {                 // Changes every request
    sessionId: 'abc123',
    mode: 'build',
    timestamp: new Date().toISOString(),
  },
});
```

### `buildCacheableSystemPrompt(options)`

Returns an array of `CacheableContentBlock[]` where each section is a separate content block. Static and semi-stable blocks get `cache_control: { type: 'ephemeral' }` so the Anthropic API can cache them:

```typescript
interface CacheableContentBlock {
  type: 'text';
  text: string;
  cache_control?: { type: 'ephemeral' };
}
```

The dynamic block at the end intentionally has **no** `cache_control` marker.

### Cache Breakpoints

Markers indicating where the cache can safely break between sections:

| Breakpoint | Position |
|------------|----------|
| `system_end` | After static prefix |
| `tools_end` | After tool definitions |
| `rules_end` | After rules content |
| `memory_end` | After memory context |
| `custom` | User-defined position |

### Append-Only Validation

The `validateAppendOnly()` method checks that past messages have not been modified. Modifying a historical message invalidates all cached content after that point. The manager hashes each message and detects changes, emitting `cache.violation` events.

### `analyzeCacheEfficiency(systemPrompt)`

Static analysis utility that checks a system prompt for cache-unfriendly patterns (timestamps at the start, session IDs at the beginning) and returns warnings with suggestions.

## Cache Statistics

```typescript
interface CacheStats {
  cacheableTokens: number;      // Tokens that can be cached
  nonCacheableTokens: number;   // Dynamic tokens (never cached)
  cacheRatio: number;           // cacheableTokens / totalTokens
  estimatedSavings: number;     // e.g., 0.72 = 72% cost reduction
}
```

## Key File

`src/tricks/kv-cache-context.ts` (~620 lines)
