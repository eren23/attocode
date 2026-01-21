# Lesson 18: ReAct Pattern (Reasoning + Acting)

> Interleaving explicit reasoning with actions for better tool use

## What You'll Learn

1. **ReAct Pattern**: How to make agents think before acting
2. **Thought Chains**: Creating traceable reasoning paths
3. **Observation Handling**: Formatting tool results for the agent
4. **Error Recovery**: Handling malformed outputs gracefully
5. **When to Use**: Comparing ReAct vs standard execution

## Why This Matters

ReAct (Reasoning and Acting) was introduced in the paper "ReAct: Synergizing Reasoning and Acting in Language Models" (Yao et al., 2022). The key insight is that explicitly verbalizing reasoning improves:

- **Accuracy**: Agents make fewer mistakes when thinking aloud
- **Debuggability**: You can see why decisions were made
- **Recovery**: Agents can recognize and fix errors
- **Complex Tasks**: Multi-step problems become manageable

## Key Concepts

### The ReAct Loop

```
┌──────────────────────────────────────────────────────────────┐
│                          GOAL                                 │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
         ┌─────────────────────────────────────┐
         │            THOUGHT                   │
         │  "I need to find the config file.   │
         │   Let me search for it."            │
         └─────────────────────┬───────────────┘
                               │
                               ▼
         ┌─────────────────────────────────────┐
         │            ACTION                    │
         │  search({"pattern": "config"})      │
         └─────────────────────┬───────────────┘
                               │
                               ▼
         ┌─────────────────────────────────────┐
         │          OBSERVATION                 │
         │  Found: config.json, config.yaml    │
         └─────────────────────┬───────────────┘
                               │
                               ▼
         ┌─────────────────────────────────────┐
         │            THOUGHT                   │
         │  "Found two config files. Let me    │
         │   read the JSON one first."         │
         └─────────────────────┬───────────────┘
                               │
                               ▼
                        [Continue loop...]
                               │
                               ▼
         ┌─────────────────────────────────────┐
         │         FINAL ANSWER                 │
         │  "The config uses JSON format with  │
         │   settings for development mode."   │
         └─────────────────────────────────────┘
```

### Format Structure

```
Thought: [Agent's reasoning about what to do next]
Action: tool_name({"arg1": "value1", "arg2": "value2"})
Observation: [Result from tool execution]

Thought: [Agent's analysis of the observation]
Action: [Next tool call]
Observation: [Next result]

...

Final Answer: [Complete answer to the original goal]
```

## Files in This Lesson

| File | Purpose |
|------|---------|
| `types.ts` | ReAct type definitions |
| `react-loop.ts` | Core ReAct agent implementation |
| `thought-parser.ts` | Extracts thoughts from LLM output |
| `observation-formatter.ts` | Formats tool results |
| `main.ts` | Demonstration of all concepts |

## Running This Lesson

```bash
npm run lesson:18
```

## Code Examples

### Parsing ReAct Output

```typescript
import { parseReActOutput } from './thought-parser.js';

const output = `
Thought: I need to check the package.json for dependencies.

Action: read_file({"path": "package.json"})
`;

const parsed = parseReActOutput(output);

if (parsed.success) {
  console.log('Thought:', parsed.thought);
  console.log('Action:', parsed.action?.tool, parsed.action?.args);
} else {
  console.log('Errors:', parsed.errors);
}
```

### Formatting Observations

```typescript
import { formatObservation, formatFileContent } from './observation-formatter.js';

// Simple observation
const obs = formatObservation(toolResult, {
  maxLength: 500,
  truncation: 'end',
});

// File content with header
const fileObs = formatFileContent('config.json', content, {
  maxLength: 1000,
  asCodeBlock: true,
});

console.log(fileObs.content);
// File: config.json
// ────────────────────
// ```
// { "name": "my-project", ... }
// ```
```

### Using the ReAct Agent

```typescript
import { ReActAgent } from './react-loop.js';

const agent = new ReActAgent(llmProvider, toolRegistry, {
  maxSteps: 10,
  verbose: true,
});

// Stream steps as they happen
for await (const step of agent.run('Find all TODO comments')) {
  console.log(`Step ${step.stepNumber}`);
  console.log(`Thought: ${step.thought}`);
  console.log(`Action: ${step.action.tool}`);
  console.log(`Observation: ${step.observation}`);
}

// Or run to completion
const trace = await agent.runToCompletion('Find all TODO comments');
console.log('Final Answer:', trace.finalAnswer);
console.log('Steps taken:', trace.steps.length);
```

### Event Handling

```typescript
const agent = new ReActAgent(llm, tools);

agent.on((event) => {
  switch (event.type) {
    case 'thought':
      console.log(`💭 Thinking: ${event.thought}`);
      break;
    case 'action':
      console.log(`⚡ Acting: ${event.action.tool}`);
      break;
    case 'observation':
      console.log(`👁️ Observed: ${event.observation.slice(0, 50)}...`);
      break;
    case 'final_answer':
      console.log(`✅ Answer: ${event.answer}`);
      break;
    case 'error':
      console.log(`❌ Error: ${event.error.message}`);
      break;
  }
});
```

## Prompt Template

The key to ReAct is a well-structured prompt:

```typescript
const REACT_SYSTEM_PROMPT = `
You solve problems step by step, showing your reasoning.

## Format

For each step:

Thought: [Your reasoning about what to do]
Action: tool_name({"arg1": "value1"})

After receiving an observation, continue:

Thought: [Analysis of the result]
Action: [Next action if needed]

When done:

Final Answer: [Your complete answer]

## Available Tools

${tools.getDescriptions()}

## Rules

1. Always think before acting
2. Use tools to gather information - don't assume
3. Analyze observations before next action
4. Provide Final Answer when you have enough information
`;
```

## Action Formats

The parser supports multiple action formats:

```typescript
// Format 1: Function call style
Action: search({"pattern": "TODO", "glob": "**/*.ts"})

// Format 2: Space-separated
Action: search {"pattern": "TODO"}

// Format 3: Colon-separated
Action: search: {"pattern": "TODO"}

// Format 4: No args
Action: list_files

// Format 5: Key-value pairs
Action: search pattern="TODO" directory="src"
```

## Error Recovery

```typescript
import { attemptRecovery } from './thought-parser.js';

const malformedOutput = 'I will use search to find TODO comments';
const parsed = parseReActOutput(malformedOutput);

if (!parsed.success) {
  const recovered = attemptRecovery(malformedOutput, availableTools);
  if (recovered) {
    console.log('Recovered action:', recovered.action);
  }
}
```

## ReAct vs Standard Agent

| Aspect | ReAct | Standard |
|--------|-------|----------|
| Tokens | More | Fewer |
| Speed | Slower | Faster |
| Transparency | High | Low |
| Complex tasks | Better | Worse |
| Debugging | Easy | Hard |
| Error recovery | Good | Limited |

### When to Use ReAct

**Good for:**
- Complex multi-step tasks
- Tasks requiring reasoning
- Research and exploration
- When you need audit trails
- Learning/educational contexts

**Avoid for:**
- Simple single-tool tasks
- High-volume automation
- Latency-critical applications
- Well-defined workflows

## Few-Shot Examples

Including examples improves ReAct performance:

```typescript
const examples: ReActExample[] = [
  {
    goal: 'Count lines of code in src/',
    steps: [
      {
        thought: 'I need to list all source files first.',
        action: 'list_files({"directory": "src", "pattern": "**/*.ts"})',
        observation: 'Found 5 files: index.ts, utils.ts, ...',
      },
      {
        thought: 'Now I\'ll read each file and count lines.',
        action: 'read_file({"path": "src/index.ts"})',
        observation: '[50 lines of code]',
      },
    ],
    finalAnswer: 'The src/ directory contains 250 total lines of code.',
  },
];
```

## Testing ReAct Agents

```typescript
import { describe, it, expect } from 'vitest';

describe('ReAct Parser', () => {
  it('extracts thought and action', () => {
    const output = `
      Thought: I need to search.
      Action: search({"q": "test"})
    `;

    const parsed = parseReActOutput(output);

    expect(parsed.success).toBe(true);
    expect(parsed.thought).toContain('search');
    expect(parsed.action?.tool).toBe('search');
  });

  it('handles final answer', () => {
    const output = 'Final Answer: The result is 42.';

    const parsed = parseReActOutput(output);

    expect(parsed.isFinalAnswer).toBe(true);
    expect(parsed.finalAnswer).toBe('The result is 42.');
  });
});
```

## Next Steps

In **Lesson 19: Observability & Tracing**, we'll add comprehensive monitoring to agent operations. ReAct traces are valuable for debugging, but production systems need structured tracing, metrics, and cost attribution.

ReAct also combines powerfully with patterns from earlier lessons:
- **Planning (Lesson 15)**: Create plans, then execute each step with ReAct reasoning
- **Reflection (Lesson 16)**: Reflect on ReAct traces to improve future reasoning
- **Multi-Agent (Lesson 17)**: Each agent in a team can use ReAct for its subtasks
