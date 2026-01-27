# Lesson 6: Testing Agents

## What You'll Learn

Agents are notoriously hard to test because:
- LLM responses are non-deterministic
- Tool execution has side effects
- Conversations have state

In this lesson, we'll build testing infrastructure that makes agents testable.

## Key Concepts

### The Testing Challenge

Traditional unit tests assume deterministic outputs:
```typescript
// ❌ This won't work - LLM outputs vary
expect(await agent.run("fix the bug")).toBe("I fixed the bug in line 42");
```

Agent tests need different approaches:
```typescript
// ✅ Test behavior, not exact output
expect(result.toolsUsed).toContain('edit_file');
expect(result.filesModified).toContain('auth.py');
expect(result.success).toBe(true);
```

### Testing Levels

1. **Unit Tests**: Test individual components (tools, parsers)
2. **Integration Tests**: Test tool + LLM interaction
3. **Scenario Tests**: Test complete agent flows with recorded conversations

### Mock Providers

Replace real LLMs with predictable mocks:
```typescript
const mock = new ScriptedLLMProvider([
  { response: 'I\'ll read the file first.\n```json\n{"tool":"read_file"...}```' },
  { response: 'I found the bug. Let me fix it.\n```json\n{"tool":"edit_file"...}```' },
  { response: 'Done! The bug has been fixed.' },
]);
```

### Conversation Fixtures

Record real conversations and replay them:
```typescript
const fixture = loadFixture('fix-auth-bug.json');
const result = await replayConversation(fixture);
expect(result).toMatchSnapshot();
```

## Files in This Lesson

- `mocks.ts` - Mock LLM providers for testing
- `fixtures/` - Recorded conversation fixtures
- `helpers.ts` - Testing utilities
- `agent.test.ts` - Example agent tests
- `tools.test.ts` - Example tool tests

## Running Tests

```bash
npm run lesson:6
# or
npx vitest run 06-testing-agents/
```

## Testing Strategies

### 1. Scripted Responses

Best for testing specific behaviors:
```typescript
test('agent uses read_file before editing', async () => {
  const mock = new ScriptedLLMProvider([
    { response: '```json\n{"tool":"edit_file"...}```', mustContain: 'edit_file' },
  ]);
  
  const result = await runAgent('fix bug', { llm: mock });
  
  expect(mock.getCallLog()).toEqual([
    expect.objectContaining({ containedToolCall: 'read_file' }),
    expect.objectContaining({ containedToolCall: 'edit_file' }),
  ]);
});
```

### 2. Behavioral Assertions

Test outcomes, not exact responses:
```typescript
test('agent successfully fixes a syntax error', async () => {
  const result = await runAgent('fix the syntax error in main.ts');
  
  expect(result.success).toBe(true);
  expect(result.filesModified).toContain('main.ts');
  // Verify the file no longer has syntax errors
  const lintResult = await lintFile('main.ts');
  expect(lintResult.errors).toHaveLength(0);
});
```

### 3. Snapshot Testing

Capture expected conversation flows:
```typescript
test('agent conversation matches snapshot', async () => {
  const result = await runAgent('create hello world');
  expect(result.history).toMatchSnapshot();
});
```

## Next Steps

After completing this lesson, move on to:
- **Lesson 7**: MCP Integration - Extend capabilities via protocol
