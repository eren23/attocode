# Exercise: Delayed Mock Provider

## Objective

Implement a mock LLM provider that adds realistic delays, demonstrating the provider interface pattern.

## Time: ~10 minutes

## Background

The provider abstraction pattern allows agents to work with any LLM (Anthropic, OpenAI, etc.) through a common interface. Mock providers are essential for:
- Testing without API costs
- Simulating network latency
- Deterministic test scenarios

## Your Task

Open `exercise-1.ts` and implement the `DelayedMockProvider` class.

## Requirements

1. **Implement the LLMProvider interface** with all required properties and methods
2. **Add configurable delay** before returning responses
3. **Return responses from a scripted list** in order
4. **Track usage statistics** (call count, total delay)

## Interface to Implement

```typescript
interface LLMProvider {
  readonly name: string;
  readonly defaultModel: string;
  chat(messages: Message[], options?: ChatOptions): Promise<ChatResponse>;
  isConfigured(): boolean;
}
```

## Example Usage

```typescript
const provider = new DelayedMockProvider({
  responses: ['Hello!', 'How can I help?'],
  delayMs: 100,
});

const response = await provider.chat([
  { role: 'user', content: 'Hi' }
]);

console.log(response.content); // "Hello!"
console.log(provider.getStats().totalDelayMs); // ~100
```

## Testing Your Solution

```bash
npm run test:lesson:2:exercise
```

## Hints

1. Use `setTimeout` wrapped in a Promise for delays
2. Keep an index to track which response to return next
3. The `isConfigured()` method should return true if responses are provided
4. Consider what happens when responses are exhausted

## Files

- `exercise-1.ts` - Your implementation (has TODOs)
- `answers/exercise-1.ts` - Reference solution
