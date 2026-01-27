# Lesson 08: Prompt Caching - Reducing LLM API Costs

## Overview

Prompt caching is a technique that dramatically reduces API costs for multi-turn conversations and repeated requests. Instead of processing the same tokens over and over, providers can cache and reuse processed prefixes.

## Why Caching Matters

In an agent loop, you resend the **entire conversation history** on every turn:

```
Turn 1: [System prompt] + [User message]           → ~2,000 tokens
Turn 2: [System prompt] + [User] + [Response]      → ~2,500 tokens
Turn 3: [System prompt] + [User] + [Response] × 2  → ~3,000 tokens
Turn 10: [System prompt] + [Full history]          → ~7,000 tokens
```

Without caching, you're paying for the system prompt (~2,000 tokens) **ten times**.

### Cost Comparison

| Scenario | Without Cache | With Cache | Savings |
|----------|--------------|------------|---------|
| 10-turn conversation | ~35,000 tokens | ~15,000 effective | **57%** |
| 50-turn conversation | ~250,000 tokens | ~75,000 effective | **70%** |

## How Prompt Caching Works

### The Mechanism

1. **Cache Write**: First request with a cache marker incurs a small write fee
2. **Cache Hit**: Subsequent requests with the same prefix get ~90% discount
3. **TTL**: Cached content expires after ~5 minutes of inactivity

### What Gets Cached

```typescript
// Mark content for caching with cache_control
const message = {
  role: 'system',
  content: [
    {
      type: 'text',
      text: 'You are a helpful coding assistant...',
      cache_control: { type: 'ephemeral' }  // ← This marker
    }
  ]
};
```

### Supported Models (via OpenRouter)

| Provider | Models | Cache TTL |
|----------|--------|-----------|
| Anthropic | Claude 3.5 Sonnet, Claude 3 Opus, Haiku | 5 minutes |
| Google | Gemini 2.0 Flash, Gemini 1.5 Pro | 5 minutes |
| DeepSeek | All models | Varies |

## What to Cache vs. What Not to Cache

### ✓ Good Caching Candidates

1. **System prompts** - Static instructions, don't change between turns
2. **Tool definitions** - Same tools available throughout conversation
3. **Large context** - Documentation, file contents provided upfront
4. **Conversation history** - Old messages that won't change

### ✗ Poor Caching Candidates

1. **Latest user message** - Changes every turn
2. **Small content** - Overhead exceeds benefit (<1,000 tokens)
3. **Dynamic content** - Timestamps, changing state

## Cache Breakpoints

A critical concept: caching works on **prefixes**. If you insert content in the middle, the cache breaks.

```
Request 1: [A] [B] [C]     ← Cache stores "ABC"
Request 2: [A] [B] [C] [D] ← Cache HIT on "ABC", only D is new
Request 3: [A] [X] [B] [C] ← Cache MISS - X breaks the prefix!
```

**Best Practice**: Put static content at the start, dynamic content at the end.

## Architecture Pattern

```
┌─────────────────────────────────────────────────────────────┐
│                    CacheAwareProvider                        │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Automatic Cache Marker Injection                     │    │
│  │ • System prompts → always cached                     │    │
│  │ • Tool definitions → always cached                   │    │
│  │ • User context > threshold → cached                  │    │
│  └─────────────────────────────────────────────────────┘    │
│                            │                                 │
│                            ▼                                 │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Underlying Provider (OpenRouter)                     │    │
│  │ • Passes cache_control to API                        │    │
│  │ • Tracks cached_tokens in response                   │    │
│  └─────────────────────────────────────────────────────┘    │
│                            │                                 │
│                            ▼                                 │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Statistics Tracking                                  │    │
│  │ • Cache hits vs misses                               │    │
│  │ • Estimated cost savings                             │    │
│  │ • Tokens cached per request                          │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

## Files in This Lesson

| File | Purpose |
|------|---------|
| `cache-basics.ts` | Simple examples demonstrating cache markers |
| `cache-provider.ts` | Cache-aware provider wrapper |
| `cost-calculator.ts` | Estimate savings from caching |
| `examples/basic-caching.ts` | Runnable demo of basic caching |
| `examples/system-prompt-cache.ts` | System prompt caching pattern |
| `examples/multi-turn-cache.ts` | Multi-turn conversation caching |

## Key Takeaways

1. **Cache static content**: System prompts, tool definitions, large context
2. **Order matters**: Static content first, dynamic content last
3. **Minimum size**: Don't cache content under ~1,000 tokens
4. **Track savings**: Monitor cache hits to verify benefit
5. **TTL awareness**: Keep conversations active to maintain cache

## Next Steps

After understanding caching, move to Lesson 09 where we integrate caching with:
- Persistent context management
- Multi-agent architecture
- Session-based conversations
