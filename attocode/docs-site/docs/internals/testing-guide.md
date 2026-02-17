---
sidebar_position: 3
title: "Testing Guide"
---

# Testing Guide

Attocode uses Vitest as its test framework. Tests are located in the `tests/` directory and cover all major subsystems.

## Setup

```bash
npm test                    # Run all tests
npm run test:watch          # Watch mode (re-run on changes)
npm run test:coverage       # Generate coverage report
```

## Configuration

From `vitest.config.ts`:

- **Timeout**: 30 seconds per test
- **Globals**: Enabled (`describe`, `it`, `expect` available without imports)
- **Coverage provider**: `v8`
- **Coverage threshold**: 20% baseline
- **Coverage exclusions**: TUI components (`src/tui/`)

## Test Organization

Tests mirror the source structure:

```
tests/
├── agent.test.ts                  # Core agent tests
├── tools.test.ts                  # Tool registry and execution
├── providers.test.ts              # Provider adapter tests
├── economics.test.ts              # Budget and economics system
├── swarm-orchestrator.test.ts     # Swarm mode tests
├── sqlite-store.test.ts           # Persistence tests
├── ...                            # ~136 test files total
```

## Writing Tests

### Basic Pattern

```typescript
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { ToolRegistry } from '../src/tools/registry.js';

describe('ToolRegistry', () => {
  let registry: ToolRegistry;

  beforeEach(() => {
    registry = new ToolRegistry('yolo');
  });

  it('should register and retrieve tools', () => {
    registry.register(mockTool);
    expect(registry.has('mock_tool')).toBe(true);
    expect(registry.get('mock_tool')).toBeDefined();
  });
});
```

### Mock Providers

Create mock LLM providers for testing without API calls:

```typescript
const mockProvider = {
  name: 'mock',
  chat: vi.fn().mockResolvedValue({
    content: 'Mock response',
    stopReason: 'end_turn',
    usage: { inputTokens: 100, outputTokens: 50, totalTokens: 150 },
  }),
};
```

### Mock Tools

Reusable mock tool factories:

```typescript
import { z } from 'zod';
import { defineTool } from '../src/tools/registry.js';

const mockReadFile = defineTool(
  'read_file',
  'Read a file',
  z.object({ path: z.string() }),
  async (input) => ({
    success: true,
    output: `Contents of ${input.path}`,
    metadata: { lines: 10, bytes: 100 },
  }),
  'safe'
);
```

### Testing Tool Sequences

For testing multi-step agent interactions, mock the provider to return a sequence of responses:

```typescript
const responses = [
  { content: '', toolCalls: [{ id: '1', name: 'read_file', arguments: { path: 'src/main.ts' } }], stopReason: 'tool_use' },
  { content: 'I have read the file.', stopReason: 'end_turn' },
];

let callIndex = 0;
mockProvider.chat = vi.fn().mockImplementation(async () => {
  return responses[callIndex++];
});
```

### Testing Events

Verify that the agent emits expected events:

```typescript
const events: AgentEvent[] = [];
agent.on((event) => events.push(event));

await agent.run('Do something');

expect(events.some(e => e.type === 'start')).toBe(true);
expect(events.some(e => e.type === 'complete')).toBe(true);
```

## CI Pipeline

GitHub Actions runs on every push to main and all pull requests:

- **Matrix**: Node.js 18.x and 20.x
- **Jobs**: `typecheck` (runs `npm run build`) and `test` (runs `npm test`)
- **Config**: `.github/workflows/ci.yml`

## Known Pre-existing Failures

8 test files with 41 tests have known pre-existing failures. These should not block new work:

| File | Tests | Issue |
|------|-------|-------|
| `modernization.test.ts` | Various | API interface changes |
| `safety.test.ts` | Various | Sandbox API updates |
| `retry.test.ts` | Various | Timing-sensitive |
| `codebase-context-lsp.test.ts` | Various | LSP mock setup |
| `decision-traceability.test.ts` | Various | Event format changes |
| `resilience-all-paths.test.ts` | Various | Provider mock mismatches |
| `economics-incremental.test.ts` | Various | Budget calculation updates |
| `bash-classification.test.ts` | Various | Command classification changes |

## Coverage

The coverage threshold is intentionally low at 20% because:

- TUI components are excluded (difficult to unit test)
- Integration tests for the full agent loop do not exist yet
- Many subsystems rely on LLM responses that are expensive to mock comprehensively

To check coverage:

```bash
npm run test:coverage
# Report generated in coverage/ directory
```

## Tips

- Use `vi.fn()` for all mock functions to get call tracking
- Set `permissionMode: 'yolo'` in tests to auto-approve all tool calls
- Use `afterEach(() => vi.restoreAllMocks())` to prevent mock leakage
- For async tests, always `await` the result or use `resolves`/`rejects` matchers
- Keep tests focused: one behavior per `it()` block
