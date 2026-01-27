/**
 * Lesson 6: Agent Tests
 * 
 * Example tests demonstrating how to test agent behavior.
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { ScriptedLLMProvider, EchoLLMProvider } from './mocks.js';
import { createTestSandbox, expectToolCall, expectConversationFlow, createMockToolExecutor } from './helpers.js';
import { extractToolCallJson } from '../tricks/json-utils.js';

// =============================================================================
// MOCK AGENT FOR TESTING
// =============================================================================

interface AgentConfig {
  llm: { chat: (messages: Array<{ role: string; content: string }>) => Promise<{ content: string }> };
  tools: {
    executor: (name: string, input: Record<string, unknown>) => Promise<{ success: boolean; output: string }>;
  };
  maxIterations?: number;
}

interface AgentResult {
  success: boolean;
  message: string;
  iterations: number;
  toolsUsed: string[];
}

/**
 * Simple agent for testing (extracted from Lesson 1).
 */
async function runTestAgent(task: string, config: AgentConfig): Promise<AgentResult> {
  const messages: Array<{ role: string; content: string }> = [
    { role: 'system', content: 'You are a helpful assistant.' },
    { role: 'user', content: task },
  ];

  const toolsUsed: string[] = [];
  let iterations = 0;
  const maxIterations = config.maxIterations ?? 10;

  while (iterations < maxIterations) {
    iterations++;

    const response = await config.llm.chat(messages);
    messages.push({ role: 'assistant', content: response.content });

    // Parse tool call using robust JSON extraction (handles nested objects)
    const toolCall = extractToolCallJson(response.content);

    if (!toolCall) {
      // No tool call, task complete
      return {
        success: true,
        message: response.content,
        iterations,
        toolsUsed,
      };
    }

    const toolName = toolCall.tool;
    const toolInput = toolCall.input;
    toolsUsed.push(toolName);

    const result = await config.tools.executor(toolName, toolInput);
    messages.push({ role: 'user', content: `Tool result: ${result.output}` });
  }

  return {
    success: false,
    message: 'Max iterations reached',
    iterations,
    toolsUsed,
  };
}

// =============================================================================
// TESTS
// =============================================================================

describe('Agent Tests', () => {
  describe('Basic Behavior', () => {
    it('should complete a simple task without tools', async () => {
      const llm = new ScriptedLLMProvider([
        { response: 'Hello! The answer to 2+2 is 4.' },
      ]);

      const tools = createMockToolExecutor();

      const result = await runTestAgent('What is 2+2?', {
        llm: { chat: (msgs) => llm.chat(msgs as any).then(r => ({ content: r.content })) },
        tools,
      });

      expect(result.success).toBe(true);
      expect(result.toolsUsed).toHaveLength(0);
      expect(result.iterations).toBe(1);
    });

    it('should use tools when needed', async () => {
      const llm = new ScriptedLLMProvider([
        { 
          response: 'I\'ll read the file.\n```json\n{"tool": "read_file", "input": {"path": "test.txt"}}\n```' 
        },
        { response: 'The file contains: file content here' },
      ]);

      const tools = createMockToolExecutor();

      const result = await runTestAgent('Read test.txt', {
        llm: { chat: (msgs) => llm.chat(msgs as any).then(r => ({ content: r.content })) },
        tools,
      });

      expect(result.success).toBe(true);
      expect(result.toolsUsed).toContain('read_file');
      expect(tools.getCalls()).toHaveLength(1);
      expect(tools.getCalls()[0]).toEqual({
        name: 'read_file',
        input: { path: 'test.txt' },
      });
    });

    it('should handle multiple tool calls', async () => {
      const llm = new ScriptedLLMProvider([
        { response: '```json\n{"tool": "list_files", "input": {"path": "."}}\n```' },
        { response: '```json\n{"tool": "read_file", "input": {"path": "main.ts"}}\n```' },
        { response: 'Found and read the file successfully!' },
      ]);

      const tools = createMockToolExecutor();

      const result = await runTestAgent('List files and read main.ts', {
        llm: { chat: (msgs) => llm.chat(msgs as any).then(r => ({ content: r.content })) },
        tools,
      });

      expect(result.toolsUsed).toEqual(['list_files', 'read_file']);
      expect(tools.getCalls()).toHaveLength(2);
    });
  });

  describe('Error Handling', () => {
    it('should stop at max iterations', async () => {
      const llm = new ScriptedLLMProvider([
        { response: '```json\n{"tool": "read_file", "input": {"path": "a.txt"}}\n```' },
        { response: '```json\n{"tool": "read_file", "input": {"path": "b.txt"}}\n```' },
        { response: '```json\n{"tool": "read_file", "input": {"path": "c.txt"}}\n```' },
        { response: '```json\n{"tool": "read_file", "input": {"path": "d.txt"}}\n```' },
      ]);

      const tools = createMockToolExecutor();

      const result = await runTestAgent('Read all files', {
        llm: { chat: (msgs) => llm.chat(msgs as any).then(r => ({ content: r.content })) },
        tools,
        maxIterations: 3,
      });

      expect(result.success).toBe(false);
      expect(result.iterations).toBe(3);
    });

    it('should handle tool execution failures', async () => {
      const llm = new ScriptedLLMProvider([
        { response: '```json\n{"tool": "read_file", "input": {"path": "missing.txt"}}\n```' },
        { response: 'The file was not found, sorry!' },
      ]);

      const tools = createMockToolExecutor();
      tools.setResponse('read_file', { success: false, output: 'File not found' });

      const result = await runTestAgent('Read missing.txt', {
        llm: { chat: (msgs) => llm.chat(msgs as any).then(r => ({ content: r.content })) },
        tools,
      });

      expect(result.success).toBe(true);
      expect(result.message).toContain('not found');
    });
  });

  describe('Conversation Flow', () => {
    it('should maintain conversation context', async () => {
      const llm = new ScriptedLLMProvider([
        { response: '```json\n{"tool": "list_files", "input": {"path": "."}}\n```' },
        { response: 'I see the files. Now reading main.ts.\n```json\n{"tool": "read_file", "input": {"path": "main.ts"}}\n```' },
        { response: 'Done! I found src folder and main.ts file.' },
      ]);

      const tools = createMockToolExecutor();
      tools.setResponse('list_files', { success: true, output: '📁 src\n📄 main.ts' });

      await runTestAgent('Explore the project', {
        llm: { chat: (msgs) => llm.chat(msgs as any).then(r => ({ content: r.content })) },
        tools,
      });

      const callLog = llm.getCallLog();
      
      // Verify second call includes tool result from first
      const secondCallMessages = callLog[1].messages;
      const hasToolResult = secondCallMessages.some(m => 
        m.role === 'user' && m.content.includes('src')
      );
      expect(hasToolResult).toBe(true);
    });
  });
});

describe('ScriptedLLMProvider', () => {
  it('should return responses in order', async () => {
    const llm = new ScriptedLLMProvider([
      { response: 'First' },
      { response: 'Second' },
      { response: 'Third' },
    ]);

    const r1 = await llm.chat([{ role: 'user', content: 'hi' }]);
    const r2 = await llm.chat([{ role: 'user', content: 'hi' }]);
    const r3 = await llm.chat([{ role: 'user', content: 'hi' }]);

    expect(r1.content).toBe('First');
    expect(r2.content).toBe('Second');
    expect(r3.content).toBe('Third');
  });

  it('should detect tool calls in responses', async () => {
    const llm = new ScriptedLLMProvider([
      { response: 'Regular response' },
      { response: '```json\n{"tool": "read_file", "input": {}}\n```' },
    ]);

    await llm.chat([{ role: 'user', content: 'hi' }]);
    await llm.chat([{ role: 'user', content: 'hi' }]);

    const log = llm.getCallLog();
    expect(log[0].containedToolCall).toBeUndefined();
    expect(log[1].containedToolCall).toBe('read_file');
  });

  it('should throw when responses exhausted', async () => {
    const llm = new ScriptedLLMProvider([
      { response: 'Only one' },
    ]);

    await llm.chat([{ role: 'user', content: 'hi' }]);
    
    await expect(llm.chat([{ role: 'user', content: 'hi again' }]))
      .rejects.toThrow('No more responses');
  });

  it('should enforce mustContain assertions', async () => {
    const llm = new ScriptedLLMProvider([
      { response: 'Response', mustContain: 'magic-word' },
    ]);

    await expect(llm.chat([{ role: 'user', content: 'hello' }]))
      .rejects.toThrow('must contain');
  });

  it('should handle conditional responses', async () => {
    const llm = new ScriptedLLMProvider([
      { response: 'Default response' },
      { response: 'Error response', when: /error|fail/i },
    ]);

    // First call with error mention should get error response
    const r1 = await llm.chat([{ role: 'user', content: 'There was an error' }]);
    expect(r1.content).toBe('Error response');
  });
});
