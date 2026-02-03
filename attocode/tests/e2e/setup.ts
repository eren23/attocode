/**
 * E2E Test Setup
 *
 * Provides test harness for end-to-end agent testing with mock providers.
 */

import { mkdtemp, rm, writeFile, readFile, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import type { LLMProvider, Message, ChatOptions, ChatResponse, ToolCall } from '../../src/types.js';

// =============================================================================
// CONTROLLABLE MOCK PROVIDER
// =============================================================================

/**
 * A mock provider that allows test-controlled responses.
 */
export class ControllableMockProvider implements LLMProvider {
  readonly name = 'controllable-mock';

  private responseQueue: Array<{
    content?: string;
    toolCalls?: ToolCall[];
    thinking?: string;
  }> = [];

  private callHistory: Array<{
    messages: Message[];
    options?: ChatOptions;
  }> = [];

  /**
   * Queue a text response.
   */
  setResponse(content: string): void {
    this.responseQueue.push({ content });
  }

  /**
   * Queue a tool call response.
   */
  setToolCall(toolName: string, args: Record<string, unknown>): void {
    this.responseQueue.push({
      toolCalls: [{
        id: `call-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        name: toolName,
        arguments: args,
      }],
    });
  }

  /**
   * Queue multiple tool calls.
   */
  setToolCalls(calls: Array<{ name: string; args: Record<string, unknown> }>): void {
    this.responseQueue.push({
      toolCalls: calls.map(c => ({
        id: `call-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        name: c.name,
        arguments: c.args,
      })),
    });
  }

  /**
   * Queue a response with thinking.
   */
  setThinkingResponse(thinking: string, content: string): void {
    this.responseQueue.push({ thinking, content });
  }

  /**
   * Get call history.
   */
  getCallHistory(): typeof this.callHistory {
    return [...this.callHistory];
  }

  /**
   * Get the last user message.
   */
  getLastUserMessage(): string | undefined {
    const lastCall = this.callHistory[this.callHistory.length - 1];
    if (!lastCall) return undefined;

    const userMsg = [...lastCall.messages]
      .reverse()
      .find(m => m.role === 'user');

    return userMsg?.content;
  }

  /**
   * Reset the mock.
   */
  reset(): void {
    this.responseQueue = [];
    this.callHistory = [];
  }

  async chat(messages: Message[], options?: ChatOptions): Promise<ChatResponse> {
    // Record the call
    this.callHistory.push({ messages, options });

    // Get the next queued response or return default
    const queued = this.responseQueue.shift();

    if (!queued) {
      return {
        content: 'No response queued. This is a default response from the mock provider.',
        stopReason: 'end_turn',
        usage: {
          inputTokens: 100,
          outputTokens: 50,
          totalTokens: 150,
        },
      };
    }

    return {
      content: queued.content ?? '',
      thinking: queued.thinking,
      toolCalls: queued.toolCalls,
      stopReason: queued.toolCalls ? 'tool_use' : 'end_turn',
      usage: {
        inputTokens: 100,
        outputTokens: 50,
        totalTokens: 150,
      },
    };
  }
}

// =============================================================================
// E2E TEST CONTEXT
// =============================================================================

/**
 * Context for E2E tests.
 */
export interface E2ETestContext {
  /** Mock provider with test controls */
  provider: ControllableMockProvider;
  /** Temporary directory for test files */
  tempDir: string;
  /** Helper to create a file */
  createFile: (name: string, content: string) => Promise<string>;
  /** Helper to read a file */
  readFile: (name: string) => Promise<string>;
  /** Helper to check if file exists */
  fileExists: (name: string) => Promise<boolean>;
}

/**
 * Set up an E2E test context.
 */
export async function setupE2ETest(): Promise<E2ETestContext> {
  const tempDir = await mkdtemp(join(tmpdir(), 'e2e-test-'));
  const provider = new ControllableMockProvider();

  return {
    provider,
    tempDir,
    createFile: async (name: string, content: string) => {
      const filePath = join(tempDir, name);
      // Create parent directories if needed
      const dir = join(filePath, '..');
      await mkdir(dir, { recursive: true });
      await writeFile(filePath, content, 'utf-8');
      return filePath;
    },
    readFile: async (name: string) => {
      const filePath = join(tempDir, name);
      return readFile(filePath, 'utf-8');
    },
    fileExists: async (name: string) => {
      const filePath = join(tempDir, name);
      try {
        await readFile(filePath);
        return true;
      } catch {
        return false;
      }
    },
  };
}

/**
 * Tear down an E2E test context.
 */
export async function teardownE2ETest(ctx: E2ETestContext): Promise<void> {
  await rm(ctx.tempDir, { recursive: true, force: true });
}

// =============================================================================
// TEST HELPERS
// =============================================================================

/**
 * Wait for a condition with timeout.
 */
export async function waitFor(
  condition: () => boolean | Promise<boolean>,
  options: { timeout?: number; interval?: number } = {}
): Promise<void> {
  const { timeout = 5000, interval = 100 } = options;
  const start = Date.now();

  while (Date.now() - start < timeout) {
    if (await condition()) return;
    await new Promise(resolve => setTimeout(resolve, interval));
  }

  throw new Error(`Timeout waiting for condition after ${timeout}ms`);
}

/**
 * Create a sequence of mock responses for a conversation.
 */
export function createConversationSequence(
  provider: ControllableMockProvider,
  responses: Array<string | { tool: string; args: Record<string, unknown> }>
): void {
  for (const response of responses) {
    if (typeof response === 'string') {
      provider.setResponse(response);
    } else {
      provider.setToolCall(response.tool, response.args);
    }
  }
}
