/**
 * Exercise Testing Utilities
 *
 * Common helpers for testing exercises without requiring API keys.
 * These utilities enable deterministic testing of exercise solutions.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// =============================================================================
// MOCK PROVIDERS
// =============================================================================

/**
 * A mock LLM response for testing
 */
export interface MockResponse {
  content: string;
  toolCalls?: Array<{
    name: string;
    input: Record<string, unknown>;
  }>;
  stopReason?: 'end_turn' | 'tool_use' | 'max_tokens';
}

/**
 * Creates a scripted mock provider that returns predefined responses
 */
export function createMockProvider(responses: MockResponse[]) {
  let callIndex = 0;

  return {
    chat: vi.fn(async () => {
      if (callIndex >= responses.length) {
        throw new Error(`Mock provider exhausted after ${responses.length} calls`);
      }
      const response = responses[callIndex++];
      return {
        content: response.content,
        toolCalls: response.toolCalls || [],
        stopReason: response.stopReason || 'end_turn',
        usage: { inputTokens: 100, outputTokens: 50 },
      };
    }),

    getCallCount: () => callIndex,
    reset: () => { callIndex = 0; },
  };
}

// =============================================================================
// TOOL TESTING HELPERS
// =============================================================================

/**
 * Creates a mock tool registry for testing
 */
export function createMockToolRegistry() {
  const tools = new Map<string, {
    name: string;
    description: string;
    execute: ReturnType<typeof vi.fn>;
  }>();

  return {
    register(name: string, description: string, handler: (input: unknown) => unknown) {
      tools.set(name, {
        name,
        description,
        execute: vi.fn(handler),
      });
    },

    get(name: string) {
      return tools.get(name);
    },

    execute: vi.fn(async (name: string, input: unknown) => {
      const tool = tools.get(name);
      if (!tool) {
        throw new Error(`Tool not found: ${name}`);
      }
      return tool.execute(input);
    }),

    list() {
      return Array.from(tools.values()).map(t => ({
        name: t.name,
        description: t.description,
      }));
    },

    getExecutionCount(name: string) {
      const tool = tools.get(name);
      return tool ? tool.execute.mock.calls.length : 0;
    },
  };
}

// =============================================================================
// ASSERTION HELPERS
// =============================================================================

/**
 * Asserts that a function implements the expected interface
 */
export function assertImplementsInterface<T>(
  obj: unknown,
  requiredMethods: (keyof T)[]
): asserts obj is T {
  if (typeof obj !== 'object' || obj === null) {
    throw new Error('Expected an object');
  }

  for (const method of requiredMethods) {
    if (!(method in obj)) {
      throw new Error(`Missing required method: ${String(method)}`);
    }
  }
}

/**
 * Asserts that an async generator yields expected values
 */
export async function assertYields<T>(
  generator: AsyncGenerator<T>,
  expectedValues: T[],
  compareFn: (a: T, b: T) => boolean = (a, b) => JSON.stringify(a) === JSON.stringify(b)
) {
  const actualValues: T[] = [];

  for await (const value of generator) {
    actualValues.push(value);
    if (actualValues.length > expectedValues.length * 2) {
      throw new Error('Generator yielded too many values');
    }
  }

  expect(actualValues.length).toBe(expectedValues.length);

  for (let i = 0; i < expectedValues.length; i++) {
    if (!compareFn(actualValues[i], expectedValues[i])) {
      throw new Error(
        `Mismatch at index ${i}: expected ${JSON.stringify(expectedValues[i])}, got ${JSON.stringify(actualValues[i])}`
      );
    }
  }
}

// =============================================================================
// TIMING HELPERS
// =============================================================================

/**
 * Creates a controlled timer for testing retry/delay logic
 */
export function createMockTimer() {
  let currentTime = 0;
  const pendingTimers: Array<{ callback: () => void; triggerAt: number }> = [];

  return {
    now: () => currentTime,

    setTimeout: (callback: () => void, delay: number) => {
      pendingTimers.push({ callback, triggerAt: currentTime + delay });
      pendingTimers.sort((a, b) => a.triggerAt - b.triggerAt);
    },

    advance: (ms: number) => {
      const targetTime = currentTime + ms;
      while (pendingTimers.length > 0 && pendingTimers[0].triggerAt <= targetTime) {
        const timer = pendingTimers.shift()!;
        currentTime = timer.triggerAt;
        timer.callback();
      }
      currentTime = targetTime;
    },

    advanceToNext: () => {
      if (pendingTimers.length > 0) {
        const timer = pendingTimers.shift()!;
        currentTime = timer.triggerAt;
        timer.callback();
      }
    },

    getPendingCount: () => pendingTimers.length,
  };
}

// =============================================================================
// STREAM TESTING HELPERS
// =============================================================================

/**
 * Creates a mock stream that emits chunks with controlled timing
 */
export function createMockStream(chunks: string[]) {
  let index = 0;

  return {
    async *[Symbol.asyncIterator]() {
      for (const chunk of chunks) {
        yield chunk;
        index++;
      }
    },

    getEmittedCount: () => index,
  };
}

/**
 * Collects all values from an async iterable
 */
export async function collectStream<T>(stream: AsyncIterable<T>): Promise<T[]> {
  const results: T[] = [];
  for await (const item of stream) {
    results.push(item);
  }
  return results;
}

// =============================================================================
// ERROR TESTING HELPERS
// =============================================================================

/**
 * Creates a function that fails N times then succeeds
 */
export function createFailingThenSucceeding<T>(
  failCount: number,
  error: Error,
  successValue: T
) {
  let attempts = 0;

  return vi.fn(async () => {
    attempts++;
    if (attempts <= failCount) {
      throw error;
    }
    return successValue;
  });
}

/**
 * Error types for testing error classification
 */
export class RetryableError extends Error {
  readonly retryable = true;
  constructor(message: string) {
    super(message);
    this.name = 'RetryableError';
  }
}

export class NonRetryableError extends Error {
  readonly retryable = false;
  constructor(message: string) {
    super(message);
    this.name = 'NonRetryableError';
  }
}

export class RateLimitError extends Error {
  readonly retryAfter: number;
  constructor(retryAfter: number) {
    super(`Rate limited, retry after ${retryAfter}ms`);
    this.name = 'RateLimitError';
    this.retryAfter = retryAfter;
  }
}

// =============================================================================
// EXERCISE VALIDATION HELPERS
// =============================================================================

/**
 * Validates that an exercise file exports the required functions/classes
 */
export function validateExerciseExports(
  module: Record<string, unknown>,
  requiredExports: string[]
): { valid: boolean; missing: string[] } {
  const missing = requiredExports.filter(name => !(name in module));
  return {
    valid: missing.length === 0,
    missing,
  };
}

/**
 * Test wrapper that provides standard exercise test structure
 */
export function exerciseTest(
  name: string,
  setup: () => void | Promise<void>,
  tests: Array<{ name: string; test: () => void | Promise<void> }>
) {
  describe(name, () => {
    beforeEach(async () => {
      await setup();
    });

    for (const { name: testName, test } of tests) {
      it(testName, test);
    }
  });
}

// =============================================================================
// SNAPSHOT HELPERS
// =============================================================================

/**
 * Creates a simple event recorder for testing event sequences
 */
export function createEventRecorder<T>() {
  const events: Array<{ timestamp: number; event: T }> = [];
  const startTime = Date.now();

  return {
    record: (event: T) => {
      events.push({ timestamp: Date.now() - startTime, event });
    },

    getEvents: () => events.map(e => e.event),

    getTimeline: () => events,

    clear: () => { events.length = 0; },

    getCount: () => events.length,
  };
}
