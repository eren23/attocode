# Exercise: MCP Tool Discovery

## Objective

Implement a tool discovery system that searches and summarizes available MCP tools.

## Time: ~10 minutes

## Background

MCP (Model Context Protocol) enables dynamic tool discovery. Agents need to:
- List available tools from connected servers
- Search tools by name or capability
- Summarize tools for LLM context

## Your Task

Open `exercise-1.ts` and implement the `ToolDiscovery` class.

## Requirements

1. **Register tools** from multiple MCP servers
2. **Search tools** by name pattern or description keywords
3. **Generate summaries** suitable for LLM system prompts
4. **Filter by category** or capability

## Interface

```typescript
class ToolDiscovery {
  registerTool(tool: ToolInfo): void;
  search(query: string): ToolInfo[];
  getSummary(tools?: ToolInfo[]): string;
  getByCategory(category: string): ToolInfo[];
}
```

## Example Usage

```typescript
const discovery = new ToolDiscovery();

discovery.registerTool({
  name: 'read_file',
  description: 'Read contents of a file',
  category: 'filesystem',
  parameters: { path: 'string' },
});

const fileTools = discovery.search('file');
const summary = discovery.getSummary(fileTools);
```

## Testing Your Solution

```bash
npm run test:lesson:7:exercise
```

## Hints

1. Store tools in a Map for O(1) lookup by name
2. Use case-insensitive search for name and description
3. The summary should be formatted for LLM consumption
4. Consider relevance ranking for search results

## Files

- `exercise-1.ts` - Your implementation (has TODOs)
- `answers/exercise-1.ts` - Reference solution
