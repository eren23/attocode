# Lesson 4: Streaming Responses

## What You'll Learn

Batch responses feel sluggish. Users want to see:
- Text appearing character by character
- Real-time feedback on tool execution
- Progress during long operations

In this lesson, we'll implement streaming with async iterators.

## Key Concepts

### Why Streaming?

Without streaming:
```
User: "Fix the bug in auth.py"
[10 seconds of silence...]
Response appears all at once
```

With streaming:
```
User: "Fix the bug in auth.py"
Let me read the file...
[tool executes]
I see the issue. The problem is...
[text appears as it's generated]
```

### Async Iterators

JavaScript's async iterators are perfect for streaming:

```typescript
async function* streamResponse(): AsyncGenerator<string> {
  for (const chunk of chunks) {
    yield chunk;
    await delay(10); // Simulate network latency
  }
}

// Usage
for await (const chunk of streamResponse()) {
  process.stdout.write(chunk);
}
```

### Server-Sent Events (SSE)

Most LLM APIs use SSE for streaming:
- `data: {"type": "text", "text": "Hello"}`
- `data: {"type": "text", "text": " world"}`
- `data: [DONE]`

We'll parse these events into a clean stream.

## Files in This Lesson

- `types.ts` - Streaming event types
- `stream.ts` - Core streaming infrastructure
- `parser.ts` - SSE event parser
- `ui.ts` - Terminal UI for streaming output
- `main.ts` - Demonstration

## Running This Lesson

```bash
npm run lesson:4
```

## Streaming Event Types

```typescript
type StreamEvent =
  | { type: 'text'; text: string }        // Text chunk
  | { type: 'tool_start'; tool: string }  // Tool execution starting
  | { type: 'tool_end'; result: string }  // Tool execution complete
  | { type: 'error'; error: string }      // Error occurred
  | { type: 'done' };                     // Stream complete
```

## Handling Partial JSON

Challenge: Tool calls come as JSON, but streaming gives partial data:
- `{"tool": "rea`
- `d_file", "inpu`
- `t": {"path": "hello.txt"}}`

Solution: Buffer until we have valid JSON:
```typescript
let buffer = '';
for await (const chunk of stream) {
  buffer += chunk;
  const toolCall = tryParseToolCall(buffer);
  if (toolCall) {
    // Execute tool
    buffer = '';
  }
}
```

## Next Steps

After completing this lesson, move on to:
- **Lesson 5**: Error Recovery - Graceful failure handling
