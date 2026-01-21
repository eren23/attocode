# Exercise: JSON Validator Tool

## Objective

Create a tool that validates JSON data against a Zod schema, demonstrating the tool definition pattern.

## Time: ~12 minutes

## Background

Tools are how agents affect the world. A robust tool system needs:
- Schema validation (with Zod)
- Clear contracts for the LLM
- Danger level classification
- Type-safe execution

## Your Task

Open `exercise-1.ts` and implement the `createValidatorTool` function.

## Requirements

1. **Define a Zod schema** for the tool's input parameters
2. **Implement the tool definition** with name, description, and execute function
3. **Validate JSON input** against a provided schema
4. **Return structured results** indicating success or validation errors

## Tool Interface

```typescript
interface ToolDefinition<TInput> {
  name: string;
  description: string;
  parameters: ZodSchema<TInput>;
  dangerLevel: 'safe' | 'moderate' | 'dangerous' | 'critical';
  execute: (input: TInput) => Promise<ToolResult>;
}
```

## Example Usage

```typescript
const userSchema = z.object({
  name: z.string().min(1),
  email: z.string().email(),
  age: z.number().min(0),
});

const validator = createValidatorTool('user', userSchema);

// Valid input
const result1 = await validator.execute({
  jsonData: '{"name": "Alice", "email": "alice@example.com", "age": 30}'
});
// { success: true, output: "Valid JSON" }

// Invalid input
const result2 = await validator.execute({
  jsonData: '{"name": "", "email": "invalid"}'
});
// { success: false, output: "Validation errors: ..." }
```

## Testing Your Solution

```bash
npm run test:lesson:3:exercise
```

## Hints

1. The tool's parameters schema should accept a `jsonData` string
2. Use `JSON.parse()` to parse the input string
3. Use `schema.safeParse()` for validation (returns success/error without throwing)
4. Format error messages clearly for the LLM to understand
5. Consider edge cases: invalid JSON, missing fields, wrong types

## Files

- `exercise-1.ts` - Your implementation (has TODOs)
- `answers/exercise-1.ts` - Reference solution
