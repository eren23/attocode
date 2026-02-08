/**
 * ProviderAdapter Cache Field Passthrough Tests
 *
 * Verifies that ProviderAdapter correctly forwards cache-related fields
 * (cacheReadTokens, cacheWriteTokens, cost) and handles the OpenRouter
 * cachedTokens → cacheReadTokens fallback.
 */

import { describe, it, expect } from 'vitest';
import { ProviderAdapter } from '../src/adapters.js';
import type {
  LLMProviderWithTools,
  ChatResponseWithTools,
} from '../src/providers/types.js';

// =============================================================================
// MOCK PROVIDER
// =============================================================================

/**
 * Creates a mock LLMProviderWithTools that returns a controlled response.
 */
function createMockProvider(response: Partial<ChatResponseWithTools>): LLMProviderWithTools {
  const fullResponse: ChatResponseWithTools = {
    content: response.content ?? 'mock response',
    stopReason: response.stopReason ?? 'end_turn',
    usage: response.usage,
    toolCalls: response.toolCalls,
  };

  return {
    name: 'mock',
    defaultModel: 'mock-model',
    chat: async () => fullResponse,
    chatWithTools: async () => fullResponse,
    isConfigured: () => true,
  };
}

// =============================================================================
// TESTS
// =============================================================================

describe('ProviderAdapter cache field passthrough', () => {
  it('should forward cacheReadTokens and cacheWriteTokens from provider', async () => {
    const mockProvider = createMockProvider({
      content: 'response with cache',
      usage: {
        inputTokens: 1000,
        outputTokens: 200,
        cacheReadTokens: 100,
        cacheWriteTokens: 200,
      },
    });

    const adapter = new ProviderAdapter(mockProvider);
    const result = await adapter.chat([
      { role: 'user', content: 'Hello' },
    ]);

    expect(result.usage).toBeDefined();
    expect(result.usage!.cacheReadTokens).toBe(100);
    expect(result.usage!.cacheWriteTokens).toBe(200);
  });

  it('should fall back cachedTokens to cacheReadTokens (OpenRouter style)', async () => {
    const mockProvider = createMockProvider({
      content: 'openrouter response',
      usage: {
        inputTokens: 500,
        outputTokens: 100,
        cachedTokens: 150,
      },
    });

    const adapter = new ProviderAdapter(mockProvider);
    const result = await adapter.chat([
      { role: 'user', content: 'Hello' },
    ]);

    expect(result.usage).toBeDefined();
    expect(result.usage!.cacheReadTokens).toBe(150);
  });

  it('should forward cost from provider', async () => {
    const mockProvider = createMockProvider({
      content: 'response with cost',
      usage: {
        inputTokens: 1000,
        outputTokens: 200,
        cost: 0.05,
      },
    });

    const adapter = new ProviderAdapter(mockProvider);
    const result = await adapter.chat([
      { role: 'user', content: 'Hello' },
    ]);

    expect(result.usage).toBeDefined();
    expect(result.usage!.cost).toBe(0.05);
  });

  it('should compute totalTokens from input + output', async () => {
    const mockProvider = createMockProvider({
      content: 'response',
      usage: {
        inputTokens: 300,
        outputTokens: 100,
      },
    });

    const adapter = new ProviderAdapter(mockProvider);
    const result = await adapter.chat([
      { role: 'user', content: 'Hello' },
    ]);

    expect(result.usage).toBeDefined();
    expect(result.usage!.totalTokens).toBe(400);
  });

  it('should handle undefined usage gracefully', async () => {
    const mockProvider = createMockProvider({
      content: 'no usage data',
    });

    const adapter = new ProviderAdapter(mockProvider);
    const result = await adapter.chat([
      { role: 'user', content: 'Hello' },
    ]);

    expect(result.usage).toBeUndefined();
  });

  it('should set parseError when tool call arguments are invalid JSON', async () => {
    const truncatedJson = '{"file_path": "/tmp/test.ts", "content": "const x = 1;\\nconst';
    const mockProvider = createMockProvider({
      content: '',
      toolCalls: [{
        id: 'call_123',
        type: 'function' as const,
        function: {
          name: 'write_file',
          arguments: truncatedJson,
        },
      }],
    });

    const adapter = new ProviderAdapter(mockProvider);
    const result = await adapter.chat([
      { role: 'user', content: 'Hello' },
    ]);

    expect(result.toolCalls).toHaveLength(1);
    expect(result.toolCalls![0].parseError).toBeDefined();
    expect(result.toolCalls![0].parseError).toContain('Failed to parse arguments as JSON');
    expect(result.toolCalls![0].parseError).toContain(truncatedJson.slice(0, 200));
    expect(result.toolCalls![0].arguments).toEqual({});
  });

  it('should not set parseError when tool call arguments are valid JSON', async () => {
    const validJson = '{"file_path": "/tmp/test.ts", "content": "hello"}';
    const mockProvider = createMockProvider({
      content: '',
      toolCalls: [{
        id: 'call_456',
        type: 'function' as const,
        function: {
          name: 'write_file',
          arguments: validJson,
        },
      }],
    });

    const adapter = new ProviderAdapter(mockProvider);
    const result = await adapter.chat([
      { role: 'user', content: 'Hello' },
    ]);

    expect(result.toolCalls).toHaveLength(1);
    expect(result.toolCalls![0].parseError).toBeUndefined();
    expect(result.toolCalls![0].arguments).toEqual({ file_path: '/tmp/test.ts', content: 'hello' });
  });

  it('should prefer cacheReadTokens over cachedTokens when both present', async () => {
    const mockProvider = createMockProvider({
      content: 'both fields',
      usage: {
        inputTokens: 1000,
        outputTokens: 200,
        cacheReadTokens: 300,
        cachedTokens: 150, // Should be ignored when cacheReadTokens is present
      },
    });

    const adapter = new ProviderAdapter(mockProvider);
    const result = await adapter.chat([
      { role: 'user', content: 'Hello' },
    ]);

    expect(result.usage!.cacheReadTokens).toBe(300);
  });
});
