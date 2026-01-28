/**
 * LLM Resilience Unit Tests
 *
 * Tests for the LLM resilience utility that handles empty responses
 * and max_tokens continuation.
 */

import { describe, it, expect, vi } from 'vitest';
import {
  resilientLLMCall,
  validateResponse,
  summarizeResponse,
  LLMResilienceError,
  isLLMResilienceError,
  type LLMResilienceEvent,
} from '../../src/providers/llm-resilience.js';
import type { ChatResponse, Message } from '../../src/types.js';

// =============================================================================
// MOCK HELPERS
// =============================================================================

function createMockResponse(overrides: Partial<ChatResponse> = {}): ChatResponse {
  return {
    content: 'Hello, world!',
    stopReason: 'end_turn',
    usage: {
      inputTokens: 10,
      outputTokens: 5,
      totalTokens: 15,
    },
    ...overrides,
  };
}

// =============================================================================
// RESILIENT LLM CALL TESTS
// =============================================================================

describe('resilientLLMCall', () => {
  describe('successful calls', () => {
    it('should return response directly when valid', async () => {
      const mockCall = vi.fn().mockResolvedValue(createMockResponse());
      const messages: Message[] = [{ role: 'user', content: 'Hello' }];

      const result = await resilientLLMCall(messages, mockCall);

      expect(result.response.content).toBe('Hello, world!');
      expect(result.emptyRetries).toBe(0);
      expect(result.continuations).toBe(0);
      expect(result.wasRecovered).toBe(false);
      expect(mockCall).toHaveBeenCalledTimes(1);
    });

    it('should accept response with tool calls but no content', async () => {
      const mockCall = vi.fn().mockResolvedValue(
        createMockResponse({
          content: '',
          toolCalls: [{ id: '1', name: 'test', arguments: {} }],
        })
      );
      const messages: Message[] = [{ role: 'user', content: 'Hello' }];

      const result = await resilientLLMCall(messages, mockCall);

      expect(result.response.toolCalls).toHaveLength(1);
      expect(result.emptyRetries).toBe(0);
      expect(result.wasRecovered).toBe(false);
    });
  });

  describe('empty response handling', () => {
    it('should retry on empty response', async () => {
      const mockCall = vi
        .fn()
        .mockResolvedValueOnce(createMockResponse({ content: '' }))
        .mockResolvedValueOnce(createMockResponse({ content: 'Recovered!' }));

      const events: LLMResilienceEvent[] = [];
      const messages: Message[] = [{ role: 'user', content: 'Hello' }];

      const result = await resilientLLMCall(messages, mockCall, {
        onEvent: (e) => events.push(e),
      });

      expect(result.response.content).toBe('Recovered!');
      expect(result.emptyRetries).toBe(1);
      expect(result.wasRecovered).toBe(true);
      expect(mockCall).toHaveBeenCalledTimes(2);

      // Check events
      expect(events).toContainEqual({
        type: 'empty_response',
        attempt: 1,
        maxAttempts: 3,
      });
      expect(events).toContainEqual({
        type: 'empty_response_recovered',
        attempt: 1,
      });
    });

    it('should fail after max retries', async () => {
      const mockCall = vi.fn().mockResolvedValue(createMockResponse({ content: '' }));

      const events: LLMResilienceEvent[] = [];
      const messages: Message[] = [{ role: 'user', content: 'Hello' }];

      const result = await resilientLLMCall(messages, mockCall, {
        maxEmptyRetries: 2,
        onEvent: (e) => events.push(e),
      });

      // Still returns what we have, just marks it as failed
      expect(result.response.content).toBe('');
      expect(result.emptyRetries).toBe(2);
      expect(events).toContainEqual({ type: 'empty_response_failed', attempts: 3 });
    });
  });

  describe('max_tokens continuation', () => {
    it('should continue on max_tokens truncation', async () => {
      const mockCall = vi
        .fn()
        .mockResolvedValueOnce(
          createMockResponse({
            content: 'Part 1...',
            stopReason: 'max_tokens',
          })
        )
        .mockResolvedValueOnce(
          createMockResponse({
            content: 'Part 2!',
            stopReason: 'end_turn',
          })
        );

      const events: LLMResilienceEvent[] = [];
      const messages: Message[] = [{ role: 'user', content: 'Hello' }];

      const result = await resilientLLMCall(messages, mockCall, {
        autoContinue: true,
        onEvent: (e) => events.push(e),
      });

      expect(result.response.content).toBe('Part 1...Part 2!');
      expect(result.continuations).toBe(1);
      expect(result.wasRecovered).toBe(true);

      expect(events).toContainEqual({
        type: 'max_tokens_truncated',
        continuation: 1,
        maxContinuations: 3,
      });
      expect(events.find((e) => e.type === 'max_tokens_completed')).toBeDefined();
    });

    it('should stop at max continuations', async () => {
      const mockCall = vi.fn().mockResolvedValue(
        createMockResponse({
          content: 'Chunk...',
          stopReason: 'max_tokens',
        })
      );

      const events: LLMResilienceEvent[] = [];
      const messages: Message[] = [{ role: 'user', content: 'Hello' }];

      const result = await resilientLLMCall(messages, mockCall, {
        maxContinuations: 2,
        onEvent: (e) => events.push(e),
      });

      // Should have 3 calls total: 1 original + 2 continuations
      expect(mockCall).toHaveBeenCalledTimes(3);
      expect(result.continuations).toBe(2);
      expect(events).toContainEqual({ type: 'max_tokens_limit_reached', continuations: 2 });
    });

    it('should not continue if disabled', async () => {
      const mockCall = vi.fn().mockResolvedValue(
        createMockResponse({
          content: 'Truncated...',
          stopReason: 'max_tokens',
        })
      );

      const messages: Message[] = [{ role: 'user', content: 'Hello' }];

      const result = await resilientLLMCall(messages, mockCall, {
        autoContinue: false,
      });

      expect(mockCall).toHaveBeenCalledTimes(1);
      expect(result.continuations).toBe(0);
      expect(result.response.content).toBe('Truncated...');
    });

    it('should not continue if response has tool calls', async () => {
      const mockCall = vi.fn().mockResolvedValue(
        createMockResponse({
          content: 'Partial...',
          stopReason: 'max_tokens',
          toolCalls: [{ id: '1', name: 'test', arguments: {} }],
        })
      );

      const messages: Message[] = [{ role: 'user', content: 'Hello' }];

      const result = await resilientLLMCall(messages, mockCall);

      expect(mockCall).toHaveBeenCalledTimes(1);
      expect(result.continuations).toBe(0);
    });
  });
});

// =============================================================================
// VALIDATION TESTS
// =============================================================================

describe('validateResponse', () => {
  it('should validate response with content', () => {
    const response = createMockResponse({ content: 'Hello' });
    const result = validateResponse(response);

    expect(result.valid).toBe(true);
    expect(result.issues).toHaveLength(0);
  });

  it('should validate response with tool calls', () => {
    const response = createMockResponse({
      content: '',
      toolCalls: [{ id: '1', name: 'test', arguments: {} }],
    });
    const result = validateResponse(response);

    expect(result.valid).toBe(true);
    expect(result.issues).toHaveLength(0);
  });

  it('should flag empty response', () => {
    const response = createMockResponse({ content: '' });
    const result = validateResponse(response);

    expect(result.valid).toBe(false);
    expect(result.issues).toContain('Response has no content and no tool calls');
  });

  it('should flag max_tokens truncation', () => {
    const response = createMockResponse({ stopReason: 'max_tokens' });
    const result = validateResponse(response);

    expect(result.valid).toBe(false);
    expect(result.issues).toContain('Response was truncated due to max_tokens');
  });
});

// =============================================================================
// UTILITY TESTS
// =============================================================================

describe('summarizeResponse', () => {
  it('should summarize content-only response', () => {
    const response = createMockResponse({ content: 'Short message' });
    const summary = summarizeResponse(response);

    expect(summary).toContain('content: Short message');
    expect(summary).toContain('stop: end_turn');
    expect(summary).toContain('tokens: 10/5');
  });

  it('should summarize tool call response', () => {
    const response = createMockResponse({
      content: '',
      toolCalls: [
        { id: '1', name: 'read_file', arguments: {} },
        { id: '2', name: 'write_file', arguments: {} },
      ],
    });
    const summary = summarizeResponse(response);

    expect(summary).toContain('tools: [read_file, write_file]');
  });

  it('should truncate long content', () => {
    const response = createMockResponse({
      content: 'A'.repeat(150),
    });
    const summary = summarizeResponse(response);

    expect(summary).toContain('...');
  });
});

describe('LLMResilienceError', () => {
  it('should create error with details', () => {
    const error = new LLMResilienceError('Test error', {
      emptyRetries: 2,
      continuations: 1,
    });

    expect(error.message).toBe('Test error');
    expect(error.name).toBe('LLMResilienceError');
    expect(error.details.emptyRetries).toBe(2);
    expect(error.details.continuations).toBe(1);
  });

  it('should be identifiable with isLLMResilienceError', () => {
    const error = new LLMResilienceError('Test', { emptyRetries: 0, continuations: 0 });

    expect(isLLMResilienceError(error)).toBe(true);
    expect(isLLMResilienceError(new Error('Regular'))).toBe(false);
  });
});
