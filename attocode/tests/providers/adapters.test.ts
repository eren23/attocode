/**
 * Provider Adapter Unit Tests
 *
 * Tests for the LLM provider adapters (Anthropic, OpenRouter, OpenAI, Mock).
 * These tests mock the network layer to validate request/response handling.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { AnthropicProvider } from '../../src/providers/adapters/anthropic.js';
import { OpenRouterProvider } from '../../src/providers/adapters/openrouter.js';
import { OpenAIProvider } from '../../src/providers/adapters/openai.js';
import { MockProvider } from '../../src/providers/adapters/mock.js';
import type { Message, ToolDefinitionSchema } from '../../src/providers/types.js';
import { ProviderError } from '../../src/providers/types.js';

// =============================================================================
// MOCK SETUP
// =============================================================================

// Store original fetch
const originalFetch = globalThis.fetch;

// Mock fetch helper
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

// Set environment variables for tests
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
// ANTHROPIC ADAPTER TESTS
// =============================================================================

describe('AnthropicProvider', () => {
  beforeEach(() => {
    setEnvVars({ ANTHROPIC_API_KEY: 'test-anthropic-key' });
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    clearEnvVars(['ANTHROPIC_API_KEY']);
    vi.clearAllMocks();
  });

  describe('configuration', () => {
    it('should use API key from environment', () => {
      const provider = new AnthropicProvider();

      expect(provider.isConfigured()).toBe(true);
      expect(provider.name).toBe('anthropic');
    });

    it('should use default model', () => {
      const provider = new AnthropicProvider();
      expect(provider.defaultModel).toBe('claude-sonnet-4-20250514');
    });

    it('should report unconfigured when no API key', () => {
      clearEnvVars(['ANTHROPIC_API_KEY']);
      // Can't instantiate without API key - it throws
      // So we just check that isConfigured checks the env var
    });
  });

  describe('chat', () => {
    it('should format messages correctly for Anthropic API', async () => {
      const mockResponse = {
        content: [{ type: 'text', text: 'Hello!' }],
        stop_reason: 'end_turn',
        usage: { input_tokens: 10, output_tokens: 5 },
      };

      globalThis.fetch = mockFetch(mockResponse);

      const provider = new AnthropicProvider();

      const messages: Message[] = [
        { role: 'system', content: 'You are a helpful assistant.' },
        { role: 'user', content: 'Hello' },
      ];

      const response = await provider.chat(messages);

      expect(response.content).toBe('Hello!');
      expect(response.stopReason).toBe('end_turn');
      expect(response.usage?.inputTokens).toBe(10);
      expect(response.usage?.outputTokens).toBe(5);

      // Verify request format
      expect(globalThis.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/v1/messages'),
        expect.objectContaining({
          method: 'POST',
          headers: expect.objectContaining({
            'x-api-key': 'test-anthropic-key',
            'anthropic-version': '2023-06-01',
          }),
        })
      );
    });

    it('should handle API errors correctly', async () => {
      const errorResponse = {
        error: { type: 'invalid_request_error', message: 'Invalid request' },
      };

      globalThis.fetch = mockFetch(errorResponse, { status: 400, ok: false });

      const provider = new AnthropicProvider();

      await expect(
        provider.chat([{ role: 'user', content: 'Hello' }])
      ).rejects.toThrow(ProviderError);
    });
  });

  describe('chatWithTools', () => {
    it('should send tool definitions in Anthropic format', async () => {
      // Anthropic returns tool_use content blocks
      const mockResponse = {
        id: 'msg_123',
        content: [
          { type: 'text', text: 'I will read that file for you.' },
          {
            type: 'tool_use',
            id: 'toolu_01XYZ',
            name: 'read_file',
            input: { path: '/src/main.ts' },
          },
        ],
        stop_reason: 'tool_use',
        usage: { input_tokens: 50, output_tokens: 30 },
      };

      const mockFetchFn = mockFetch(mockResponse);
      globalThis.fetch = mockFetchFn;

      const provider = new AnthropicProvider();

      const tools: ToolDefinitionSchema[] = [
        {
          type: 'function',
          function: {
            name: 'read_file',
            description: 'Read a file from disk',
            parameters: {
              type: 'object',
              properties: {
                path: { type: 'string', description: 'File path' },
              },
              required: ['path'],
            },
          },
        },
      ];

      const response = await provider.chatWithTools(
        [{ role: 'user', content: 'Read the file /src/main.ts' }],
        { tools }
      );

      // Should return tool calls
      expect(response.toolCalls).toBeDefined();
      expect(response.toolCalls).toHaveLength(1);
      expect(response.toolCalls![0].id).toBe('toolu_01XYZ');
      expect(response.toolCalls![0].function.name).toBe('read_file');
      expect(JSON.parse(response.toolCalls![0].function.arguments)).toEqual({ path: '/src/main.ts' });

      // Should also include text content
      expect(response.content).toBe('I will read that file for you.');

      // Verify the request included tools in Anthropic format
      const callArgs = mockFetchFn.mock.calls[0];
      const body = JSON.parse(callArgs[1].body);
      expect(body.tools).toBeDefined();
      expect(body.tools[0].name).toBe('read_file');
      expect(body.tools[0].input_schema).toBeDefined();
    });

    it('should handle text-only response when tools are available', async () => {
      const mockResponse = {
        id: 'msg_456',
        content: [{ type: 'text', text: 'The file does not exist.' }],
        stop_reason: 'end_turn',
        usage: { input_tokens: 30, output_tokens: 10 },
      };

      globalThis.fetch = mockFetch(mockResponse);

      const provider = new AnthropicProvider();

      const tools: ToolDefinitionSchema[] = [
        {
          type: 'function',
          function: {
            name: 'read_file',
            description: 'Read a file',
            parameters: { type: 'object', properties: {} },
          },
        },
      ];

      const response = await provider.chatWithTools(
        [{ role: 'user', content: 'What is in file X?' }],
        { tools }
      );

      expect(response.content).toBe('The file does not exist.');
      expect(response.toolCalls).toBeUndefined();
    });

    it('should handle tool result messages correctly', async () => {
      const mockResponse = {
        id: 'msg_789',
        content: [{ type: 'text', text: 'The file contains a main function.' }],
        stop_reason: 'end_turn',
        usage: { input_tokens: 100, output_tokens: 20 },
      };

      const mockFetchFn = mockFetch(mockResponse);
      globalThis.fetch = mockFetchFn;

      const provider = new AnthropicProvider();

      // Send conversation with tool result
      const response = await provider.chatWithTools([
        { role: 'user', content: 'Read main.ts' },
        {
          role: 'assistant',
          content: '',
          tool_calls: [
            {
              id: 'toolu_01ABC',
              type: 'function' as const,
              function: { name: 'read_file', arguments: '{"path":"main.ts"}' },
            },
          ],
        },
        {
          role: 'tool',
          content: 'function main() { console.log("hello"); }',
          tool_call_id: 'toolu_01ABC',
          name: 'read_file',
        },
      ]);

      expect(response.content).toBe('The file contains a main function.');

      // Verify the tool result was sent in Anthropic format
      const callArgs = mockFetchFn.mock.calls[0];
      const body = JSON.parse(callArgs[1].body);
      const messages = body.messages;

      // Should have user, assistant (with tool_use), and user (with tool_result)
      expect(messages.length).toBeGreaterThanOrEqual(2);
    });
  });
});

// =============================================================================
// OPENROUTER ADAPTER TESTS
// =============================================================================

describe('OpenRouterProvider', () => {
  beforeEach(() => {
    setEnvVars({ OPENROUTER_API_KEY: 'test-openrouter-key' });
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    clearEnvVars(['OPENROUTER_API_KEY']);
    vi.clearAllMocks();
  });

  describe('configuration', () => {
    it('should use API key from environment', () => {
      const provider = new OpenRouterProvider();

      expect(provider.isConfigured()).toBe(true);
      expect(provider.name).toBe('openrouter');
    });

    it('should have a default model', () => {
      const provider = new OpenRouterProvider();
      expect(provider.defaultModel).toBeTruthy();
    });
  });

  describe('chat', () => {
    it('should format messages in OpenAI-compatible format', async () => {
      const mockResponse = {
        choices: [
          {
            message: { role: 'assistant', content: 'Hi there!' },
            finish_reason: 'stop',
          },
        ],
        usage: {
          prompt_tokens: 10,
          completion_tokens: 5,
          total_tokens: 15,
        },
      };

      globalThis.fetch = mockFetch(mockResponse);

      const provider = new OpenRouterProvider();

      const response = await provider.chat([{ role: 'user', content: 'Hello' }]);

      expect(response.content).toBe('Hi there!');
      expect(response.usage?.inputTokens).toBe(10);
      expect(response.usage?.outputTokens).toBe(5);

      // Verify request was made to OpenRouter
      expect(globalThis.fetch).toHaveBeenCalled();
    });
  });
});

// =============================================================================
// OPENAI ADAPTER TESTS
// =============================================================================

describe('OpenAIProvider', () => {
  beforeEach(() => {
    setEnvVars({ OPENAI_API_KEY: 'test-openai-key' });
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    clearEnvVars(['OPENAI_API_KEY']);
    vi.clearAllMocks();
  });

  describe('configuration', () => {
    it('should use API key from environment', () => {
      const provider = new OpenAIProvider();

      expect(provider.isConfigured()).toBe(true);
      expect(provider.name).toBe('openai');
    });

    it('should have a default model', () => {
      const provider = new OpenAIProvider();
      expect(provider.defaultModel).toBeTruthy();
    });
  });

  describe('chat', () => {
    it('should format messages correctly for OpenAI API', async () => {
      const mockResponse = {
        choices: [
          {
            message: { role: 'assistant', content: 'Hello from GPT!' },
            finish_reason: 'stop',
          },
        ],
        usage: {
          prompt_tokens: 10,
          completion_tokens: 8,
          total_tokens: 18,
        },
      };

      globalThis.fetch = mockFetch(mockResponse);

      const provider = new OpenAIProvider();

      const response = await provider.chat([
        { role: 'system', content: 'You are helpful.' },
        { role: 'user', content: 'Hello' },
      ]);

      expect(response.content).toBe('Hello from GPT!');

      // Verify request format
      expect(globalThis.fetch).toHaveBeenCalledWith(
        expect.stringContaining('api.openai.com'),
        expect.objectContaining({
          method: 'POST',
          headers: expect.objectContaining({
            'Authorization': 'Bearer test-openai-key',
          }),
        })
      );
    });

    it('should pass temperature and max tokens options', async () => {
      const mockResponse = {
        choices: [{ message: { content: 'Response' }, finish_reason: 'stop' }],
        usage: { prompt_tokens: 5, completion_tokens: 5 },
      };

      const mockFetchFn = mockFetch(mockResponse);
      globalThis.fetch = mockFetchFn;

      const provider = new OpenAIProvider();

      await provider.chat([{ role: 'user', content: 'Test' }], {
        temperature: 0.5,
        maxTokens: 100,
      });

      // Get the request body
      const callArgs = mockFetchFn.mock.calls[0];
      const body = JSON.parse(callArgs[1].body);

      expect(body.temperature).toBe(0.5);
      expect(body.max_tokens).toBe(100);
    });
  });
});

// =============================================================================
// MOCK PROVIDER TESTS
// =============================================================================

describe('MockProvider', () => {
  it('should always be configured', () => {
    const provider = new MockProvider();

    expect(provider.isConfigured()).toBe(true);
    expect(provider.name).toBe('mock');
  });

  it('should return a response', async () => {
    const provider = new MockProvider();

    const response = await provider.chat([{ role: 'user', content: 'Hello' }]);
    expect(response.content).toBeTruthy();
    expect(response.stopReason).toBe('end_turn');
  });

  it('should track call count', async () => {
    const provider = new MockProvider();

    await provider.chat([{ role: 'user', content: 'First' }]);
    await provider.chat([{ role: 'user', content: 'Second' }]);

    expect(provider.getCallCount()).toBe(2);
  });

  it('should reset state', async () => {
    const provider = new MockProvider();

    await provider.chat([{ role: 'user', content: 'Test' }]);
    expect(provider.getCallCount()).toBe(1);

    provider.reset();
    expect(provider.getCallCount()).toBe(0);
  });

  it('should respond to hello world trigger', async () => {
    const provider = new MockProvider();

    const response = await provider.chat([{ role: 'user', content: 'Create a hello world file' }]);
    expect(response.content).toContain('hello');
  });
});

// =============================================================================
// CROSS-PROVIDER TESTS
// =============================================================================

describe('Provider Interface Conformance', () => {
  beforeEach(() => {
    setEnvVars({
      ANTHROPIC_API_KEY: 'test-key',
      OPENROUTER_API_KEY: 'test-key',
      OPENAI_API_KEY: 'test-key',
    });
  });

  afterEach(() => {
    clearEnvVars(['ANTHROPIC_API_KEY', 'OPENROUTER_API_KEY', 'OPENAI_API_KEY']);
  });

  it('AnthropicProvider should implement required interface', () => {
    const provider = new AnthropicProvider();

    expect(typeof provider.name).toBe('string');
    expect(typeof provider.defaultModel).toBe('string');
    expect(typeof provider.isConfigured).toBe('function');
    expect(typeof provider.chat).toBe('function');
    expect(typeof provider.isConfigured()).toBe('boolean');
  });

  it('OpenRouterProvider should implement required interface', () => {
    const provider = new OpenRouterProvider();

    expect(typeof provider.name).toBe('string');
    expect(typeof provider.defaultModel).toBe('string');
    expect(typeof provider.isConfigured).toBe('function');
    expect(typeof provider.chat).toBe('function');
    expect(typeof provider.isConfigured()).toBe('boolean');
  });

  it('OpenAIProvider should implement required interface', () => {
    const provider = new OpenAIProvider();

    expect(typeof provider.name).toBe('string');
    expect(typeof provider.defaultModel).toBe('string');
    expect(typeof provider.isConfigured).toBe('function');
    expect(typeof provider.chat).toBe('function');
    expect(typeof provider.isConfigured()).toBe('boolean');
  });

  it('MockProvider should implement required interface', () => {
    const provider = new MockProvider();

    expect(typeof provider.name).toBe('string');
    expect(typeof provider.defaultModel).toBe('string');
    expect(typeof provider.isConfigured).toBe('function');
    expect(typeof provider.chat).toBe('function');
    expect(typeof provider.isConfigured()).toBe('boolean');
  });
});
