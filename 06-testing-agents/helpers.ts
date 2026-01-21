/**
 * Lesson 6: Testing Helpers
 * 
 * Utilities for testing agents.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import type { Message, LLMProvider, CallRecord } from './mocks.js';

// =============================================================================
// TEST SANDBOX
// =============================================================================

/**
 * Create a temporary directory for testing file operations.
 */
export async function createTestSandbox(): Promise<{
  path: string;
  cleanup: () => Promise<void>;
  writeFile: (name: string, content: string) => Promise<void>;
  readFile: (name: string) => Promise<string>;
  exists: (name: string) => Promise<boolean>;
}> {
  const sandboxPath = path.join(
    process.cwd(),
    '.test-sandbox',
    `test-${Date.now()}-${Math.random().toString(36).slice(2)}`
  );

  await fs.mkdir(sandboxPath, { recursive: true });

  return {
    path: sandboxPath,
    
    cleanup: async () => {
      await fs.rm(sandboxPath, { recursive: true, force: true });
    },
    
    writeFile: async (name: string, content: string) => {
      const filePath = path.join(sandboxPath, name);
      await fs.mkdir(path.dirname(filePath), { recursive: true });
      await fs.writeFile(filePath, content);
    },
    
    readFile: async (name: string) => {
      return fs.readFile(path.join(sandboxPath, name), 'utf-8');
    },
    
    exists: async (name: string) => {
      try {
        await fs.access(path.join(sandboxPath, name));
        return true;
      } catch {
        return false;
      }
    },
  };
}

// =============================================================================
// ASSERTION HELPERS
// =============================================================================

/**
 * Assert that call log contains a specific tool call.
 */
export function expectToolCall(
  callLog: CallRecord[],
  toolName: string,
  options: { atIndex?: number; withInput?: Record<string, unknown> } = {}
): void {
  const { atIndex, withInput } = options;

  const toolCalls = callLog.filter(call => call.containedToolCall === toolName);

  if (toolCalls.length === 0) {
    throw new Error(`Expected tool call "${toolName}" but none found. Tools called: ${
      callLog.map(c => c.containedToolCall).filter(Boolean).join(', ') || 'none'
    }`);
  }

  if (atIndex !== undefined) {
    const actualAtIndex = callLog[atIndex]?.containedToolCall;
    if (actualAtIndex !== toolName) {
      throw new Error(`Expected tool "${toolName}" at index ${atIndex}, but found "${actualAtIndex}"`);
    }
  }
}

/**
 * Assert that messages contain specific content.
 */
export function expectMessageContains(
  messages: Message[],
  content: string | RegExp,
  options: { role?: Message['role'] } = {}
): void {
  const filtered = options.role 
    ? messages.filter(m => m.role === options.role)
    : messages;

  const pattern = typeof content === 'string' ? new RegExp(content) : content;
  const found = filtered.some(m => pattern.test(m.content));

  if (!found) {
    throw new Error(`Expected messages to contain "${content}"`);
  }
}

/**
 * Assert conversation flow.
 */
export function expectConversationFlow(
  callLog: CallRecord[],
  expectedFlow: Array<{ tool?: string; contains?: string | RegExp }>
): void {
  if (callLog.length < expectedFlow.length) {
    throw new Error(`Expected ${expectedFlow.length} calls but only got ${callLog.length}`);
  }

  for (let i = 0; i < expectedFlow.length; i++) {
    const expected = expectedFlow[i];
    const actual = callLog[i];

    if (expected.tool && actual.containedToolCall !== expected.tool) {
      throw new Error(
        `Call ${i}: Expected tool "${expected.tool}" but got "${actual.containedToolCall}"`
      );
    }

    if (expected.contains) {
      const pattern = typeof expected.contains === 'string' 
        ? new RegExp(expected.contains) 
        : expected.contains;
      
      if (!pattern.test(actual.response.content)) {
        throw new Error(
          `Call ${i}: Expected response to contain "${expected.contains}"`
        );
      }
    }
  }
}

// =============================================================================
// FIXTURE HELPERS
// =============================================================================

/**
 * Load a fixture file.
 */
export async function loadFixture(name: string): Promise<unknown> {
  const fixturePath = path.join(__dirname, 'fixtures', name);
  try {
    const content = await fs.readFile(fixturePath, 'utf-8');
    return JSON.parse(content);
  } catch (error) {
    throw new Error(`Failed to load fixture "${name}": ${(error as Error).message}`);
  }
}

/**
 * Save a fixture file.
 */
export async function saveFixture(name: string, data: unknown): Promise<void> {
  const fixturePath = path.join(__dirname, 'fixtures', name);
  await fs.mkdir(path.dirname(fixturePath), { recursive: true });
  await fs.writeFile(fixturePath, JSON.stringify(data, null, 2));
}

// =============================================================================
// MOCK TOOL EXECUTOR
// =============================================================================

export interface ToolResult {
  success: boolean;
  output: string;
}

/**
 * Create a mock tool executor that records calls.
 */
export function createMockToolExecutor(): {
  executor: (name: string, input: Record<string, unknown>) => Promise<ToolResult>;
  getCalls: () => Array<{ name: string; input: Record<string, unknown> }>;
  setResponse: (name: string, response: ToolResult) => void;
  reset: () => void;
} {
  const calls: Array<{ name: string; input: Record<string, unknown> }> = [];
  const responses: Map<string, ToolResult> = new Map();

  // Default responses
  responses.set('read_file', { success: true, output: 'file content here' });
  responses.set('write_file', { success: true, output: 'File written successfully' });
  responses.set('list_files', { success: true, output: '📁 src\n📄 package.json' });
  responses.set('bash', { success: true, output: 'Command completed' });

  return {
    executor: async (name: string, input: Record<string, unknown>) => {
      calls.push({ name, input });
      return responses.get(name) ?? { success: false, output: `Unknown tool: ${name}` };
    },
    
    getCalls: () => [...calls],
    
    setResponse: (name: string, response: ToolResult) => {
      responses.set(name, response);
    },
    
    reset: () => {
      calls.length = 0;
    },
  };
}

// =============================================================================
// TIMING HELPERS
// =============================================================================

/**
 * Wait for a condition to be true.
 */
export async function waitFor(
  condition: () => boolean | Promise<boolean>,
  options: { timeout?: number; interval?: number } = {}
): Promise<void> {
  const { timeout = 5000, interval = 100 } = options;
  const start = Date.now();

  while (Date.now() - start < timeout) {
    if (await condition()) {
      return;
    }
    await new Promise(resolve => setTimeout(resolve, interval));
  }

  throw new Error(`waitFor timed out after ${timeout}ms`);
}

/**
 * Measure execution time.
 */
export async function measureTime<T>(fn: () => Promise<T>): Promise<{ result: T; duration: number }> {
  const start = Date.now();
  const result = await fn();
  const duration = Date.now() - start;
  return { result, duration };
}
