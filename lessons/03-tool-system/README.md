# Lesson 3: Tool System

## What You'll Learn

Tools are how agents affect the world. A well-designed tool system needs:
- **Schema validation**: Ensure inputs are correct before execution
- **Permission checks**: Prevent dangerous operations
- **Clear contracts**: Tools should be self-documenting

## Key Concepts

### Tool Definition vs Execution

We separate tool **definition** (what the tool does, what inputs it takes) from **execution** (the actual code that runs):

```typescript
// Definition - what the LLM sees
{
  name: 'write_file',
  description: 'Write content to a file',
  parameters: {
    path: { type: 'string', description: 'File path' },
    content: { type: 'string', description: 'Content to write' },
  },
  required: ['path', 'content'],
}

// Execution - what actually runs
async function executeWriteFile(input: WriteFileInput): Promise<ToolResult> {
  await fs.writeFile(input.path, input.content);
  return { success: true, output: `Wrote ${input.content.length} bytes` };
}
```

### JSON Schema Validation

We use [Zod](https://zod.dev/) for runtime validation:
- Catches invalid inputs before execution
- Generates JSON Schema for the LLM
- Provides type safety in TypeScript

### Permission System

Not all operations should be auto-approved:
- **Safe**: Reading files, listing directories
- **Moderate**: Writing files (with confirmation)
- **Dangerous**: `rm -rf`, `sudo`, network calls

Our permission system:
1. Classifies commands by danger level
2. Allows safe operations automatically
3. Prompts for dangerous ones (or blocks in strict mode)

## Files in This Lesson

- `types.ts` - Tool type definitions
- `registry.ts` - Tool registration and lookup
- `permission.ts` - Permission checking system
- `tools/file.ts` - File operation tools
- `tools/bash.ts` - Shell command tool
- `main.ts` - Demonstration

## Running This Lesson

```bash
npm run lesson:3
```

## The Tool Registry Pattern

```typescript
const registry = new ToolRegistry();

// Register tools
registry.register(readFileTool);
registry.register(writeFileTool);
registry.register(bashTool);

// Execute by name
const result = await registry.execute('read_file', { path: 'hello.txt' });
```

Benefits:
- Centralized tool management
- Easy to list available tools
- Single point for validation and permissions

## Permission Modes

```typescript
type PermissionMode = 
  | 'strict'      // Block all dangerous operations
  | 'interactive' // Ask user for dangerous operations
  | 'auto-safe'   // Auto-approve safe, ask for dangerous
  | 'yolo';       // Auto-approve everything (testing only!)
```

## Next Steps

After completing this lesson, move on to:
- **Lesson 4**: Streaming - Real-time response feedback
