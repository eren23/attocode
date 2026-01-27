# Lesson 1: The Core Agent Loop

## What You'll Learn

The fundamental pattern behind every AI coding agent is surprisingly simple: a loop.

```
while (task not complete):
    1. AI decides what action to take
    2. Execute that action
    3. Show the AI the result
    4. Loop back to step 1
```

In this lesson, we'll build this loop from scratch in TypeScript with proper types.

## Key Concepts

### The Agent Loop

An agent is different from a chatbot because it can **act**. A chatbot just responds; an agent:
- Takes actions (reads files, runs commands)
- Observes results
- Decides what to do next
- Repeats until the task is done

### Why TypeScript?

Unlike the original Python examples, we start with TypeScript because:
1. **Type safety**: Catch errors at compile time, not runtime
2. **Better tooling**: Autocomplete, refactoring, documentation
3. **Same language as tools**: Most of our codebase is TypeScript

## Files in This Lesson

- `types.ts` - Core type definitions
- `loop.ts` - The agent loop implementation
- `main.ts` - Entry point to run the agent

## Running This Lesson

```bash
# From the course root
npm run lesson:1

# Or directly
npx tsx 01-core-loop/main.ts "Create a hello world file"
```

## The Minimal Agent

Here's the entire concept in pseudocode:

```typescript
async function runAgent(task: string) {
  const messages = [{ role: 'user', content: task }];
  
  while (true) {
    // 1. Ask the LLM what to do
    const response = await llm.chat(messages);
    messages.push({ role: 'assistant', content: response });
    
    // 2. Check if it wants to use a tool
    const toolCall = parseToolCall(response);
    
    if (!toolCall) {
      // No tool call = task is complete
      console.log('Done:', response);
      break;
    }
    
    // 3. Execute the tool
    const result = await executeTool(toolCall);
    
    // 4. Add result to conversation and loop
    messages.push({ role: 'user', content: `Result: ${result}` });
  }
}
```

That's it. Everything else is refinement.

## Next Steps

After completing this lesson, move on to:
- **Lesson 2**: Provider Abstraction - Support multiple LLM providers
