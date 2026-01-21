# Exercise: Context Tracker

## Objective

Implement a context tracker that monitors agent execution and provides insights.

## Time: ~15 minutes

## Background

Production agents need observability. A context tracker provides:
- Conversation history management
- Token usage monitoring
- Execution statistics
- Context window management

## Your Task

Open `exercise-1.ts` and implement the `ContextTracker` class.

## Requirements

1. **Track messages** in conversation history
2. **Monitor token usage** against context limits
3. **Provide execution stats** (iterations, tool calls, timing)
4. **Warn when approaching context limits**

## Interface

```typescript
class ContextTracker {
  addMessage(message: Message): void;
  addToolCall(toolName: string, tokens: number): void;
  getMessages(): Message[];
  getStats(): ContextStats;
  isNearLimit(): boolean;
  reset(): void;
}
```

## Example Usage

```typescript
const tracker = new ContextTracker({
  maxTokens: 8000,
  warningThreshold: 0.8, // Warn at 80%
});

tracker.addMessage({ role: 'user', content: 'Hello' });
tracker.addMessage({ role: 'assistant', content: 'Hi there!' });
tracker.addToolCall('read_file', 150);

console.log(tracker.getStats());
// { messages: 2, toolCalls: 1, totalTokens: 154, ... }

console.log(tracker.isNearLimit()); // false
```

## Testing Your Solution

```bash
npm run test:lesson:9:exercise
```

## Hints

1. Use the estimateTokens helper for token counting
2. Track both message tokens and tool result tokens
3. Consider a sliding window if context gets too large
4. The warning threshold should trigger before hard limit

## Files

- `exercise-1.ts` - Your implementation (has TODOs)
- `answers/exercise-1.ts` - Reference solution
