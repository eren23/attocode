# Exercise: Cache Marker Injection

## Objective

Implement a cache optimization system that injects cache control markers into message sequences.

## Time: ~12 minutes

## Background

LLM providers like Anthropic support prompt caching. By marking certain content as cacheable, we can:
- Reduce latency for repeated context
- Lower costs significantly
- Improve response times

## Your Task

Open `exercise-1.ts` and implement the `CacheOptimizer` class.

## Requirements

1. **Identify cacheable content** (system prompts, large context)
2. **Inject cache markers** at appropriate positions
3. **Track cache statistics** (hits, misses, savings)
4. **Respect token thresholds** (only cache above minimum size)

## Interface

```typescript
class CacheOptimizer {
  optimize(messages: Message[]): OptimizedMessage[];
  recordCacheHit(tokens: number): void;
  recordCacheMiss(tokens: number): void;
  getStats(): CacheStats;
}
```

## Example Usage

```typescript
const optimizer = new CacheOptimizer({
  minTokensForCache: 100,
  maxCacheableMessages: 3,
});

const messages = [
  { role: 'system', content: longSystemPrompt },
  { role: 'user', content: 'Hello' },
];

const optimized = optimizer.optimize(messages);
// First message now has cache_control marker
```

## Testing Your Solution

```bash
npm run test:lesson:8:exercise
```

## Hints

1. System messages are always good cache candidates
2. Use token estimation (4 chars ≈ 1 token) for threshold checking
3. Cache markers go on the message object, not content
4. Consider message position - earlier = better for caching

## Files

- `exercise-1.ts` - Your implementation (has TODOs)
- `answers/exercise-1.ts` - Reference solution
