# Lesson 5: Error Recovery

## What You'll Learn

Real-world agents face many failure modes:
- Network timeouts
- Rate limiting (429 errors)
- Transient server errors
- Invalid tool inputs
- Context length exceeded

A robust agent needs to:
1. Classify errors (is this recoverable?)
2. Retry with appropriate backoff
3. Know when to give up

## Key Concepts

### Error Classification

Not all errors are the same:

| Error Type | Recoverable | Strategy |
|------------|-------------|----------|
| Network timeout | Yes | Retry immediately |
| Rate limit (429) | Yes | Exponential backoff |
| Server error (5xx) | Usually | Retry with delay |
| Bad request (400) | No | Fix and retry differently |
| Auth error (401) | No | Stop, needs user action |
| Context too long | Sometimes | Compact and retry |

### Retry Strategies

```typescript
// Fixed delay
delay = baseDelay; // Always 1s

// Linear backoff
delay = baseDelay * attempt; // 1s, 2s, 3s, 4s...

// Exponential backoff
delay = baseDelay * 2^attempt; // 1s, 2s, 4s, 8s, 16s...

// Exponential with jitter
delay = random(0, baseDelay * 2^attempt); // Randomized
```

### Circuit Breaker Pattern

After too many failures, stop trying:

```typescript
if (consecutiveFailures > threshold) {
  state = 'open'; // Stop all requests
  
  // After cooldown, try one request
  setTimeout(() => state = 'half-open', cooldown);
}
```

## Files in This Lesson

- `types.ts` - Error and retry types
- `classifier.ts` - Error classification logic
- `retry.ts` - Retry manager with strategies
- `circuit-breaker.ts` - Circuit breaker implementation
- `main.ts` - Demonstration

## Running This Lesson

```bash
npm run lesson:5
```

## The Retry Manager

```typescript
const retryManager = new RetryManager({
  maxRetries: 3,
  baseDelay: 1000,
  strategy: 'exponential',
});

// Wrap any async operation
const result = await retryManager.execute(
  () => fetchFromAPI(),
  { operation: 'api_call' }
);
```

## Composing Error Handlers

```typescript
// Compose multiple recovery strategies
const pipeline = composeRecovery([
  classifyError,           // Determine error type
  checkCircuitBreaker,     // Should we even try?
  calculateDelay,          // How long to wait?
  executeWithTimeout,      // Run with timeout
  recordOutcome,           // Track for learning
]);
```

## Next Steps

After completing this lesson, move on to:
- **Lesson 6**: Testing Agents - How to test agent behavior
