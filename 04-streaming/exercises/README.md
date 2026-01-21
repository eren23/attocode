# Exercise: Streaming Buffer

## Objective

Implement a streaming buffer that collects chunks and emits complete lines, demonstrating async generator patterns.

## Time: ~15 minutes

## Background

Real-time streaming improves user experience by showing responses as they arrive. Key challenges:
- Data arrives in arbitrary chunks
- Need to assemble complete units (lines, JSON objects)
- Must handle backpressure gracefully

## Your Task

Open `exercise-1.ts` and implement the `LineBuffer` class.

## Requirements

1. **Accept chunks of text** via `push()` method
2. **Buffer incomplete lines** until newline received
3. **Emit complete lines** via async iterator
4. **Signal completion** via `end()` method
5. **Handle edge cases** like empty chunks, multiple newlines

## Interface

```typescript
class LineBuffer implements AsyncIterable<string> {
  push(chunk: string): void;
  end(): void;
  [Symbol.asyncIterator](): AsyncIterator<string>;
}
```

## Example Usage

```typescript
const buffer = new LineBuffer();

// Simulate streaming chunks
buffer.push('Hello ');
buffer.push('World\nHow ');
buffer.push('are you?\n');
buffer.end();

// Consume lines
for await (const line of buffer) {
  console.log(line);
}
// Output:
// "Hello World"
// "How are you?"
```

## Testing Your Solution

```bash
npm run test:lesson:4:exercise
```

## Hints

1. Use a queue to buffer emitted lines
2. Track pending data that hasn't formed a complete line yet
3. The async iterator should wait for new data when queue is empty
4. Use Promise + resolve pattern for waiting
5. When `end()` is called, emit any remaining buffered data

## Files

- `exercise-1.ts` - Your implementation (has TODOs)
- `answers/exercise-1.ts` - Reference solution
