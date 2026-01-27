/**
 * Exercise Tests: Lesson 1 - Calculator Agent
 *
 * These tests verify your calculator agent implementation.
 * Run with: npm run test:lesson:1:exercise
 */

import { describe, it, expect, vi } from 'vitest';

// Import from answers for testing (swap to exercise-1 to test your solution)
import {
  runCalculatorAgent,
  parseToolCall,
  calculate,
  type MockProvider,
  type Message,
} from './exercises/answers/exercise-1.js';

// =============================================================================
// MOCK PROVIDER FACTORY
// =============================================================================

function createMockProvider(responses: string[]): MockProvider {
  let callIndex = 0;
  return {
    chat: vi.fn(async (_messages: Message[]) => {
      if (callIndex >= responses.length) {
        throw new Error('Mock provider exhausted');
      }
      return { content: responses[callIndex++] };
    }),
  };
}

// =============================================================================
// TESTS: parseToolCall helper
// =============================================================================

describe('parseToolCall', () => {
  it('should parse tool call from JSON code block', () => {
    const response = `I'll calculate that for you.
\`\`\`json
{ "tool": "calculate", "input": { "expression": "25 * 4" } }
\`\`\``;

    const result = parseToolCall(response);
    expect(result).toEqual({
      tool: 'calculate',
      input: { expression: '25 * 4' },
    });
  });

  it('should parse tool call from plain code block', () => {
    const response = `\`\`\`
{ "tool": "calculate", "input": { "expression": "10 + 5" } }
\`\`\``;

    const result = parseToolCall(response);
    expect(result).toEqual({
      tool: 'calculate',
      input: { expression: '10 + 5' },
    });
  });

  it('should parse inline JSON with tool key', () => {
    const response = `{ "tool": "calculate", "input": { "expression": "2 + 2" } }`;

    const result = parseToolCall(response);
    expect(result).toEqual({
      tool: 'calculate',
      input: { expression: '2 + 2' },
    });
  });

  it('should return null when no tool call present', () => {
    const response = `The answer is 100.`;
    const result = parseToolCall(response);
    expect(result).toBeNull();
  });

  it('should return null for invalid JSON', () => {
    const response = `\`\`\`json
{ invalid json }
\`\`\``;
    const result = parseToolCall(response);
    expect(result).toBeNull();
  });
});

// =============================================================================
// TESTS: calculate helper
// =============================================================================

describe('calculate', () => {
  it('should compute simple addition', () => {
    expect(calculate('2 + 2')).toEqual({ result: 4 });
  });

  it('should compute multiplication', () => {
    expect(calculate('25 * 4')).toEqual({ result: 100 });
  });

  it('should compute division', () => {
    expect(calculate('100 / 4')).toEqual({ result: 25 });
  });

  it('should handle parentheses', () => {
    expect(calculate('(3 + 4) * 2')).toEqual({ result: 14 });
  });

  it('should follow order of operations', () => {
    expect(calculate('2 + 3 * 4')).toEqual({ result: 14 });
  });

  it('should reject invalid expressions', () => {
    expect(() => calculate('rm -rf /')).toThrow('Invalid expression');
  });
});

// =============================================================================
// TESTS: runCalculatorAgent
// =============================================================================

describe('runCalculatorAgent', () => {
  it('should complete a simple calculation in 2 iterations', async () => {
    const mockProvider = createMockProvider([
      // First response: tool call
      `I'll calculate 25 * 4 for you.
\`\`\`json
{ "tool": "calculate", "input": { "expression": "25 * 4" } }
\`\`\``,
      // Second response: final answer
      `The answer is 100.`,
    ]);

    const result = await runCalculatorAgent(mockProvider, 'What is 25 * 4?');

    expect(result.answer).toBe(100);
    expect(result.iterations).toBe(2);
    expect(mockProvider.chat).toHaveBeenCalledTimes(2);
  });

  it('should handle multi-step calculations', async () => {
    const mockProvider = createMockProvider([
      // First calculation
      `\`\`\`json
{ "tool": "calculate", "input": { "expression": "10 + 5" } }
\`\`\``,
      // Second calculation using previous result
      `\`\`\`json
{ "tool": "calculate", "input": { "expression": "15 * 2" } }
\`\`\``,
      // Final answer
      `The result is 30.`,
    ]);

    const result = await runCalculatorAgent(
      mockProvider,
      'Add 10 and 5, then multiply by 2'
    );

    expect(result.answer).toBe(30);
    expect(result.iterations).toBe(3);
  });

  it('should maintain conversation history', async () => {
    const mockProvider = createMockProvider([
      `\`\`\`json
{ "tool": "calculate", "input": { "expression": "5 + 5" } }
\`\`\``,
      `10`,
    ]);

    await runCalculatorAgent(mockProvider, 'What is 5 + 5?');

    // Verify the second call includes the tool result
    const secondCallMessages = (mockProvider.chat as ReturnType<typeof vi.fn>).mock.calls[1][0];
    // Messages: system, user question, assistant tool call, user tool result, [optional: assistant response from prev iter]
    expect(secondCallMessages.length).toBeGreaterThanOrEqual(4);
    // Tool result should be in the messages
    const toolResultMessage = secondCallMessages.find(
      (m: Message) => m.role === 'user' && m.content.includes('10')
    );
    expect(toolResultMessage).toBeDefined();
  });

  it('should extract decimal answers', async () => {
    const mockProvider = createMockProvider([
      `\`\`\`json
{ "tool": "calculate", "input": { "expression": "10 / 4" } }
\`\`\``,
      `The answer is 2.5`,
    ]);

    const result = await runCalculatorAgent(mockProvider, 'What is 10 / 4?');
    expect(result.answer).toBe(2.5);
  });

  it('should throw on unknown tool', async () => {
    const mockProvider = createMockProvider([
      `\`\`\`json
{ "tool": "unknown_tool", "input": {} }
\`\`\``,
    ]);

    await expect(
      runCalculatorAgent(mockProvider, 'test')
    ).rejects.toThrow('Unknown tool');
  });
});
