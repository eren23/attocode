# Exercise: Calculator Agent

## Objective

Build a simple calculator agent that demonstrates the core agent loop pattern.

## Time: ~15 minutes

## Background

The agent loop is the heart of every AI agent:
1. Receive a task
2. Ask the LLM what to do
3. Execute the action
4. Show the result
5. Repeat until done

In this exercise, you'll implement a calculator agent that can perform basic math operations.

## Your Task

Open `exercise-1.ts` and implement the `runCalculatorAgent` function.

The agent should:
1. Parse math expressions from the user's task
2. Use the `calculate` tool to perform operations
3. Return the final result

## Requirements

1. **Implement the agent loop** that continues until the LLM says it's done
2. **Parse tool calls** from the LLM response using the provided `parseToolCall` helper
3. **Execute the calculate tool** when requested
4. **Return the final answer** when the LLM completes

## Tools Available

```typescript
calculate({ expression: string }) => { result: number }
```

The calculate tool evaluates simple math expressions like:
- `"2 + 2"` → `{ result: 4 }`
- `"10 * 5"` → `{ result: 50 }`
- `"(3 + 4) * 2"` → `{ result: 14 }`

## Example

```typescript
const result = await runCalculatorAgent(
  mockProvider,
  "What is 25 * 4?"
);

console.log(result);
// { answer: 100, iterations: 2 }
```

## Testing Your Solution

```bash
npm run test:lesson:1:exercise
```

## Hints

1. The agent loop should check if the LLM's response contains a tool call
2. If no tool call is found, the LLM is done - extract the final answer
3. Keep track of the conversation history (messages array)
4. The mock provider will simulate an LLM that knows how to use the calculate tool

## Files

- `exercise-1.ts` - Your implementation (has TODOs)
- `answers/exercise-1.ts` - Reference solution (don't peek until you try!)
