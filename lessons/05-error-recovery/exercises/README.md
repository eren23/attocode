# Exercise: Retry with Backoff

## Objective

Implement a retry function with exponential backoff that handles different error types appropriately.

## Time: ~15 minutes

## Background

Real APIs fail. A robust retry system needs to:
- Classify errors (retryable vs permanent)
- Apply appropriate delays between retries
- Respect rate limit signals
- Give up after max attempts

## Your Task

Open `exercise-1.ts` and implement the `retryWithBackoff` function.

## Requirements

1. **Classify errors** as retryable or permanent
2. **Apply exponential backoff** between retries
3. **Handle rate limit errors** with specific retry-after delays
4. **Return result or throw** after max attempts exhausted

## Error Classification

| Error Type | Retryable | Strategy |
|------------|-----------|----------|
| Network errors (ECONNRESET, ETIMEDOUT) | Yes | Exponential backoff |
| Rate limit (429) | Yes | Use retry-after header |
| Server errors (500, 502, 503) | Yes | Exponential backoff |
| Client errors (400, 401, 404) | No | Fail immediately |
| Unknown errors | No | Fail immediately |

## Example Usage

```typescript
const result = await retryWithBackoff(
  async () => fetchFromAPI(),
  {
    maxRetries: 3,
    initialDelayMs: 100,
    maxDelayMs: 5000,
  }
);
```

## Testing Your Solution

```bash
npm run test:lesson:5:exercise
```

## Hints

1. Use error properties like `code`, `status`, or message to classify
2. Exponential backoff: delay = initialDelay * 2^attempt
3. Cap delay at maxDelayMs
4. Check for `retryAfter` property on rate limit errors
5. Consider adding jitter for production use

## Files

- `exercise-1.ts` - Your implementation (has TODOs)
- `answers/exercise-1.ts` - Reference solution
