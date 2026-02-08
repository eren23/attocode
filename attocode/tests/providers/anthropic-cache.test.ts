/**
 * Anthropic Cache Pipeline Tests
 *
 * Tests for the A1-A5 cache fixes:
 * - prompt-caching-2024-07-31 beta header
 * - Structured system content with cache_control passthrough
 * - Cache usage extraction (cache_creation_input_tokens, cache_read_input_tokens)
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { AnthropicProvider } from '../../src/providers/adapters/anthropic.js';
import type { MessageWithContent } from '../../src/providers/types.js';

// =============================================================================
// MOCK SETUP
// =============================================================================

const originalFetch = globalThis.fetch;

function mockFetch(responseData: unknown, options: { status?: number; ok?: boolean } = {}) {
  const { status = 200, ok = true } = options;
  return vi.fn().mockResolvedValue({
    ok,
    status,
    json: vi.fn().mockResolvedValue(responseData),
    text: vi.fn().mockResolvedValue(JSON.stringify(responseData)),
    headers: {
      get: vi.fn().mockReturnValue(null),
    },
  });
}

function setEnvVars(vars: Record<string, string>) {
  for (const [key, value] of Object.entries(vars)) {
    process.env[key] = value;
  }
}

function clearEnvVars(keys: string[]) {
  for (const key of keys) {
    delete process.env[key];
  }
}

// =============================================================================
// TESTS
// =============================================================================

describe('Anthropic Cache Pipeline', () => {
  beforeEach(() => {
    setEnvVars({ ANTHROPIC_API_KEY: 'test-key' });
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    clearEnvVars(['ANTHROPIC_API_KEY']);
  });

  describe('prompt-caching beta header', () => {
    const standardResponse = {
      content: [{ type: 'text', text: 'Hello' }],
      stop_reason: 'end_turn',
      usage: { input_tokens: 10, output_tokens: 5 },
    };

    it('chat() should send anthropic-beta: prompt-caching-2024-07-31 header', async () => {
      const fetchMock = mockFetch(standardResponse);
      globalThis.fetch = fetchMock;

      const provider = new AnthropicProvider({ apiKey: 'test-key' });
      await provider.chat([
        { role: 'user', content: 'Hello' },
      ]);

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [, init] = fetchMock.mock.calls[0];
      expect(init.headers['anthropic-beta']).toBe('prompt-caching-2024-07-31');
    });

    it('chatWithTools() should send anthropic-beta: prompt-caching-2024-07-31 header', async () => {
      const fetchMock = mockFetch({
        id: 'msg_1',
        content: [{ type: 'text', text: 'Hello' }],
        stop_reason: 'end_turn',
        usage: { input_tokens: 10, output_tokens: 5 },
      });
      globalThis.fetch = fetchMock;

      const provider = new AnthropicProvider({ apiKey: 'test-key' });
      await provider.chatWithTools([
        { role: 'user', content: 'Hello' },
      ]);

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [, init] = fetchMock.mock.calls[0];
      expect(init.headers['anthropic-beta']).toBe('prompt-caching-2024-07-31');
    });
  });

  describe('structured system content with cache_control', () => {
    it('chatWithTools() should pass structured system content as-is', async () => {
      const fetchMock = mockFetch({
        id: 'msg_1',
        content: [{ type: 'text', text: 'OK' }],
        stop_reason: 'end_turn',
        usage: { input_tokens: 100, output_tokens: 10 },
      });
      globalThis.fetch = fetchMock;

      const structuredSystem: MessageWithContent = {
        role: 'system',
        content: [
          { type: 'text', text: 'You are an assistant.' },
          { type: 'text', text: 'Be helpful.', cache_control: { type: 'ephemeral' } },
        ],
      };

      const provider = new AnthropicProvider({ apiKey: 'test-key' });
      await provider.chatWithTools([
        structuredSystem,
        { role: 'user', content: 'Hi' },
      ]);

      const [, init] = fetchMock.mock.calls[0];
      const body = JSON.parse(init.body);

      // System content should be the structured array, not a flattened string
      expect(Array.isArray(body.system)).toBe(true);
      expect(body.system).toHaveLength(2);
      expect(body.system[0]).toEqual({ type: 'text', text: 'You are an assistant.' });
      expect(body.system[1]).toEqual({
        type: 'text',
        text: 'Be helpful.',
        cache_control: { type: 'ephemeral' },
      });
    });

    it('chat() should pass structured system content as-is', async () => {
      const fetchMock = mockFetch({
        content: [{ type: 'text', text: 'OK' }],
        stop_reason: 'end_turn',
        usage: { input_tokens: 100, output_tokens: 10 },
      });
      globalThis.fetch = fetchMock;

      const structuredSystem: MessageWithContent = {
        role: 'system',
        content: [
          { type: 'text', text: 'System prompt.', cache_control: { type: 'ephemeral' } },
        ],
      };

      const provider = new AnthropicProvider({ apiKey: 'test-key' });
      await provider.chat([
        structuredSystem,
        { role: 'user', content: 'Hi' },
      ]);

      const [, init] = fetchMock.mock.calls[0];
      const body = JSON.parse(init.body);

      expect(Array.isArray(body.system)).toBe(true);
      expect(body.system[0].cache_control).toEqual({ type: 'ephemeral' });
    });
  });

  describe('cache usage extraction', () => {
    it('chat() should extract cache_creation and cache_read tokens', async () => {
      const fetchMock = mockFetch({
        content: [{ type: 'text', text: 'cached response' }],
        stop_reason: 'end_turn',
        usage: {
          input_tokens: 2000,
          output_tokens: 100,
          cache_creation_input_tokens: 500,
          cache_read_input_tokens: 1200,
        },
      });
      globalThis.fetch = fetchMock;

      const provider = new AnthropicProvider({ apiKey: 'test-key' });
      const result = await provider.chat([
        { role: 'user', content: 'Hello' },
      ]);

      expect(result.usage?.cacheWriteTokens).toBe(500);
      expect(result.usage?.cacheReadTokens).toBe(1200);
    });

    it('chatWithTools() should extract cache_creation and cache_read tokens', async () => {
      const fetchMock = mockFetch({
        id: 'msg_1',
        content: [{ type: 'text', text: 'cached response' }],
        stop_reason: 'end_turn',
        usage: {
          input_tokens: 3000,
          output_tokens: 200,
          cache_creation_input_tokens: 800,
          cache_read_input_tokens: 1500,
        },
      });
      globalThis.fetch = fetchMock;

      const provider = new AnthropicProvider({ apiKey: 'test-key' });
      const result = await provider.chatWithTools([
        { role: 'user', content: 'Hello' },
      ]);

      expect(result.usage?.cacheWriteTokens).toBe(800);
      expect(result.usage?.cacheReadTokens).toBe(1500);
    });

    it('should handle missing cache fields gracefully', async () => {
      const fetchMock = mockFetch({
        content: [{ type: 'text', text: 'no cache' }],
        stop_reason: 'end_turn',
        usage: {
          input_tokens: 100,
          output_tokens: 50,
        },
      });
      globalThis.fetch = fetchMock;

      const provider = new AnthropicProvider({ apiKey: 'test-key' });
      const result = await provider.chat([
        { role: 'user', content: 'Hello' },
      ]);

      expect(result.usage?.cacheWriteTokens).toBeUndefined();
      expect(result.usage?.cacheReadTokens).toBeUndefined();
    });
  });
});
