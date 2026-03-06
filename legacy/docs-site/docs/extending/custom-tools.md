---
sidebar_position: 1
title: "Custom Tools"
---

# Custom Tools

Attocode tools are defined using Zod schemas and registered with the `ToolRegistry`. Each tool specifies its parameters, danger level, and execution logic.

## Defining a Tool

Use `defineTool()` from `src/tools/registry.ts`:

```typescript
import { z } from 'zod';
import { defineTool } from './tools/registry.js';
import type { ToolResult } from './tools/types.js';

const mySearchTool = defineTool(
  'search_codebase',
  'Search the codebase for a pattern and return matching files',
  z.object({
    pattern: z.string().describe('Regex pattern to search for'),
    path: z.string().optional().describe('Directory to search in'),
    maxResults: z.number().optional().default(20).describe('Maximum results'),
  }),
  async (input): Promise<ToolResult> => {
    // Tool implementation
    const matches = await performSearch(input.pattern, input.path);
    return {
      success: true,
      output: matches.join('\n'),
      metadata: { matchCount: matches.length },
    };
  },
  'safe' // default danger level
);
```

## Danger Levels

Every tool declares a `dangerLevel` that controls permission behavior:

| Level | Behavior | Examples |
|-------|----------|----------|
| `safe` | Auto-approved | `read_file`, `grep`, `glob` |
| `moderate` | May require confirmation | `write_file`, `edit_file` |
| `dangerous` | Requires confirmation | Destructive bash commands |
| `critical` | May be blocked entirely | System-level operations |

### Dynamic Danger Classification

For tools where the danger depends on the input (like `bash`), use the `getDangerLevel` callback:

```typescript
const tool = defineTool(
  'bash',
  'Execute a bash command',
  bashSchema,
  executeFunction,
  'moderate', // static default
);

// Override with dynamic classification
tool.getDangerLevel = (input) => {
  if (/rm\s+-rf/.test(input.command)) return 'dangerous';
  if (/ls|cat|echo/.test(input.command)) return 'safe';
  return 'moderate';
};
```

When `getDangerLevel` is provided, it takes precedence over the static `dangerLevel`.

## Registering with ToolRegistry

```typescript
import { ToolRegistry } from './tools/registry.js';

const registry = new ToolRegistry('interactive');
registry.register(mySearchTool);

// Check registration
registry.has('search_codebase');  // true
registry.list();                   // ['search_codebase', ...]
registry.getDescriptions();        // JSON Schema descriptions for LLM
```

## ToolResult Format

Every tool execution returns a `ToolResult`:

```typescript
interface ToolResult {
  success: boolean;
  output: string;
  metadata?: Record<string, unknown>;
}
```

The `output` field is what the LLM sees. Use `metadata` for structured data that the agent framework can use internally (line counts, byte sizes, match counts).

## Coercion Helpers

Weaker models sometimes send boolean values as strings or file content as arrays. Use coercion helpers for compatibility:

```typescript
import { coerceBoolean, coerceString } from './tools/coercion.js';

const schema = z.object({
  recursive: coerceBoolean().optional().default(false),
  content: coerceString().describe('File content to write'),
});
```

- `coerceBoolean()` accepts `"true"`, `"false"`, `"1"`, `"0"`, `"yes"`, `"no"` in addition to actual booleans.
- `coerceString()` accepts arrays of strings (joins with newlines) in addition to plain strings.

## Retry Configuration

Tools can declare retry behavior for transient failures:

```typescript
const tool = defineTool('api_call', description, schema, execute, 'safe');
tool.retryConfig = {
  maxAttempts: 3,         // Including initial attempt
  baseDelayMs: 1000,      // Exponential backoff base
  retryableErrors: [      // Error patterns that trigger retry
    'ECONNRESET',
    'ETIMEDOUT',
    'rate_limit',
  ],
};
```

## Schema Conversion

Tool schemas are automatically converted from Zod to JSON Schema for the LLM. The registry handles `ZodObject`, `ZodString`, `ZodNumber`, `ZodBoolean`, `ZodArray`, `ZodEnum`, `ZodOptional`, and `ZodDefault`. For provider-specific formats:

```typescript
import { toOpenRouterSchema } from './tools/standard.js';

// Convert to OpenAI/OpenRouter format
const openRouterTools = registry.getDescriptions().map(toOpenRouterSchema);
```
