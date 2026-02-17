/**
 * Tests for the streaming module and PTY shell manager.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  StreamHandler,
  createStreamHandler,
  formatChunkForTerminal,
  adaptOpenRouterStream,
  adaptAnthropicStream,
} from '../../src/integrations/streaming/streaming.js';
import type { StreamChunk, StreamEvent } from '../../src/integrations/streaming/streaming.js';
import {
  PTYShellManager,
  createPTYShell,
  formatShellState,
} from '../../src/integrations/streaming/pty-shell.js';
import type { ShellState } from '../../src/integrations/streaming/pty-shell.js';

// =============================================================================
// HELPERS
// =============================================================================

/**
 * Create a mock async iterable of StreamChunks.
 */
async function* mockStream(chunks: StreamChunk[]): AsyncIterable<StreamChunk> {
  for (const chunk of chunks) {
    yield chunk;
  }
}

/**
 * Create a mock SSE Response with a ReadableStream body.
 */
function createMockSSEResponse(events: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      for (const event of events) {
        controller.enqueue(encoder.encode(event + '\n'));
      }
      controller.close();
    },
  });
  return new Response(stream);
}

/**
 * Collect all chunks from an async iterable.
 */
async function collectChunks(iterable: AsyncIterable<StreamChunk>): Promise<StreamChunk[]> {
  const chunks: StreamChunk[] = [];
  for await (const chunk of iterable) {
    chunks.push(chunk);
  }
  return chunks;
}

// =============================================================================
// StreamHandler.processStream
// =============================================================================

describe('StreamHandler', () => {
  let handler: StreamHandler;

  beforeEach(() => {
    handler = new StreamHandler();
  });

  describe('processStream', () => {
    it('should accumulate text chunks into final response content', async () => {
      const chunks: StreamChunk[] = [
        { type: 'text', content: 'Hello ' },
        { type: 'text', content: 'world!' },
        { type: 'done' },
      ];

      const response = await handler.processStream(mockStream(chunks));

      expect(response.content).toBe('Hello world!');
      expect(response.toolCalls).toBeUndefined();
    });

    it('should produce completed tool calls from start/delta/end sequence', async () => {
      const chunks: StreamChunk[] = [
        {
          type: 'tool_call_start',
          toolCallId: 'call-1',
          toolCall: { name: 'bash' },
        },
        {
          type: 'tool_call_delta',
          toolCall: { arguments: { command: 'ls -la' } },
        },
        { type: 'tool_call_end' },
        { type: 'done' },
      ];

      const response = await handler.processStream(mockStream(chunks));

      expect(response.toolCalls).toBeDefined();
      expect(response.toolCalls).toHaveLength(1);
      expect(response.toolCalls![0].id).toBe('call-1');
      expect(response.toolCalls![0].name).toBe('bash');
      expect(response.toolCalls![0].arguments).toEqual({ command: 'ls -la' });
    });

    it('should set usage stats from usage chunk', async () => {
      const chunks: StreamChunk[] = [
        { type: 'text', content: 'response' },
        { type: 'usage', usage: { inputTokens: 100, outputTokens: 50 } },
        { type: 'done' },
      ];

      const response = await handler.processStream(mockStream(chunks));

      expect(response.usage).toBeDefined();
      expect(response.usage!.inputTokens).toBe(100);
      expect(response.usage!.outputTokens).toBe(50);
      expect(response.usage!.totalTokens).toBe(150);
    });

    it('should not include usage if no usage chunk received', async () => {
      const chunks: StreamChunk[] = [
        { type: 'text', content: 'hello' },
        { type: 'done' },
      ];

      const response = await handler.processStream(mockStream(chunks));

      expect(response.usage).toBeUndefined();
    });

    it('should flush buffer on done chunk', async () => {
      const events: StreamEvent[] = [];
      handler.on((event) => events.push(event));

      // Use short text that won't exceed buffer size of 50
      const chunks: StreamChunk[] = [
        { type: 'text', content: 'short' },
        { type: 'done' },
      ];

      await handler.processStream(mockStream(chunks));

      // Should have flushed the buffered text on 'done'
      const textEvents = events.filter((e) => e.type === 'stream.text');
      expect(textEvents.length).toBeGreaterThanOrEqual(1);

      // The text content across all text events should equal 'short'
      const allText = textEvents.map((e) => (e as { type: 'stream.text'; content: string }).content).join('');
      expect(allText).toBe('short');
    });

    it('should emit error event on error chunk', async () => {
      const events: StreamEvent[] = [];
      handler.on((event) => events.push(event));

      const chunks: StreamChunk[] = [
        { type: 'error', error: 'rate limit exceeded' },
        { type: 'done' },
      ];

      await handler.processStream(mockStream(chunks));

      const errorEvents = events.filter((e) => e.type === 'stream.error');
      expect(errorEvents.length).toBe(1);
      expect((errorEvents[0] as { type: 'stream.error'; error: string }).error).toBe('rate limit exceeded');
    });

    it('should call onChunk callback for each chunk', async () => {
      const receivedChunks: StreamChunk[] = [];
      const onChunk = (chunk: StreamChunk) => receivedChunks.push(chunk);

      const chunks: StreamChunk[] = [
        { type: 'text', content: 'a' },
        { type: 'text', content: 'b' },
        { type: 'done' },
      ];

      await handler.processStream(mockStream(chunks), onChunk);

      expect(receivedChunks).toHaveLength(3);
      expect(receivedChunks[0].type).toBe('text');
      expect(receivedChunks[1].type).toBe('text');
      expect(receivedChunks[2].type).toBe('done');
    });

    it('should throw and emit error when stream throws', async () => {
      const events: StreamEvent[] = [];
      handler.on((event) => events.push(event));

      async function* failingStream(): AsyncIterable<StreamChunk> {
        yield { type: 'text', content: 'before error' };
        throw new Error('connection lost');
      }

      await expect(handler.processStream(failingStream())).rejects.toThrow('connection lost');

      const errorEvents = events.filter((e) => e.type === 'stream.error');
      expect(errorEvents.length).toBe(1);
      expect((errorEvents[0] as { type: 'stream.error'; error: string }).error).toBe('connection lost');
    });

    it('should handle multiple tool calls in sequence', async () => {
      const chunks: StreamChunk[] = [
        { type: 'tool_call_start', toolCallId: 'call-1', toolCall: { name: 'read_file' } },
        { type: 'tool_call_delta', toolCall: { arguments: { path: '/a.ts' } } },
        { type: 'tool_call_end' },
        { type: 'tool_call_start', toolCallId: 'call-2', toolCall: { name: 'write_file' } },
        { type: 'tool_call_delta', toolCall: { arguments: { path: '/b.ts', content: 'hi' } } },
        { type: 'tool_call_end' },
        { type: 'done' },
      ];

      const response = await handler.processStream(mockStream(chunks));

      expect(response.toolCalls).toHaveLength(2);
      expect(response.toolCalls![0].name).toBe('read_file');
      expect(response.toolCalls![1].name).toBe('write_file');
    });

    it('should handle interleaved text and tool calls', async () => {
      const chunks: StreamChunk[] = [
        { type: 'text', content: 'I will read the file.' },
        { type: 'tool_call_start', toolCallId: 'call-1', toolCall: { name: 'bash' } },
        { type: 'tool_call_delta', toolCall: { arguments: { command: 'cat foo' } } },
        { type: 'tool_call_end' },
        { type: 'done' },
      ];

      const response = await handler.processStream(mockStream(chunks));

      expect(response.content).toBe('I will read the file.');
      expect(response.toolCalls).toHaveLength(1);
      expect(response.toolCalls![0].name).toBe('bash');
    });

    it('should generate tool call id if not provided', async () => {
      const chunks: StreamChunk[] = [
        { type: 'tool_call_start', toolCall: { name: 'test_tool' } },
        { type: 'tool_call_end' },
        { type: 'done' },
      ];

      const response = await handler.processStream(mockStream(chunks));

      expect(response.toolCalls).toHaveLength(1);
      expect(response.toolCalls![0].id).toMatch(/^call-/);
    });

    it('should update tool call name from delta chunk', async () => {
      const chunks: StreamChunk[] = [
        { type: 'tool_call_start', toolCallId: 'call-1', toolCall: { name: 'initial' } },
        { type: 'tool_call_delta', toolCall: { name: 'updated_name', arguments: { key: 'val' } } },
        { type: 'tool_call_end' },
        { type: 'done' },
      ];

      const response = await handler.processStream(mockStream(chunks));

      expect(response.toolCalls![0].name).toBe('updated_name');
    });
  });

  // ===========================================================================
  // StreamHandler events
  // ===========================================================================

  describe('events', () => {
    it('should emit stream.start at beginning of processStream', async () => {
      const events: StreamEvent[] = [];
      handler.on((event) => events.push(event));

      const chunks: StreamChunk[] = [{ type: 'done' }];
      await handler.processStream(mockStream(chunks));

      expect(events[0].type).toBe('stream.start');
    });

    it('should emit stream.text when buffer exceeds buffer size', async () => {
      const events: StreamEvent[] = [];
      handler.on((event) => events.push(event));

      // Default buffer size is 50 chars. Generate text that exceeds it.
      const longText = 'A'.repeat(60);
      const chunks: StreamChunk[] = [
        { type: 'text', content: longText },
        { type: 'done' },
      ];

      await handler.processStream(mockStream(chunks));

      const textEvents = events.filter((e) => e.type === 'stream.text');
      expect(textEvents.length).toBeGreaterThanOrEqual(1);
      // First text event should contain the 60-char text that triggered the flush
      expect((textEvents[0] as { type: 'stream.text'; content: string }).content).toBe(longText);
    });

    it('should emit stream.tool_call when tool_call_end arrives', async () => {
      const events: StreamEvent[] = [];
      handler.on((event) => events.push(event));

      const chunks: StreamChunk[] = [
        { type: 'tool_call_start', toolCallId: 'tc-1', toolCall: { name: 'grep' } },
        { type: 'tool_call_delta', toolCall: { arguments: { pattern: 'foo' } } },
        { type: 'tool_call_end' },
        { type: 'done' },
      ];

      await handler.processStream(mockStream(chunks));

      const toolCallEvents = events.filter((e) => e.type === 'stream.tool_call');
      expect(toolCallEvents.length).toBe(1);

      const tcEvent = toolCallEvents[0] as { type: 'stream.tool_call'; toolCall: { name: string } };
      expect(tcEvent.toolCall.name).toBe('grep');
    });

    it('should emit stream.complete with final response', async () => {
      const events: StreamEvent[] = [];
      handler.on((event) => events.push(event));

      const chunks: StreamChunk[] = [
        { type: 'text', content: 'done' },
        { type: 'done' },
      ];

      await handler.processStream(mockStream(chunks));

      const completeEvents = events.filter((e) => e.type === 'stream.complete');
      expect(completeEvents.length).toBe(1);

      const completeEvent = completeEvents[0] as { type: 'stream.complete'; response: { content: string } };
      expect(completeEvent.response.content).toBe('done');
    });

    it('should emit stream.error on error chunk', async () => {
      const events: StreamEvent[] = [];
      handler.on((event) => events.push(event));

      const chunks: StreamChunk[] = [
        { type: 'error', error: 'something went wrong' },
        { type: 'done' },
      ];

      await handler.processStream(mockStream(chunks));

      const errorEvents = events.filter((e) => e.type === 'stream.error');
      expect(errorEvents.length).toBe(1);
      expect((errorEvents[0] as { type: 'stream.error'; error: string }).error).toBe('something went wrong');
    });

    it('should support unsubscribing from events', async () => {
      const events: StreamEvent[] = [];
      const unsub = handler.on((event) => events.push(event));

      unsub();

      const chunks: StreamChunk[] = [
        { type: 'text', content: 'hello' },
        { type: 'done' },
      ];

      await handler.processStream(mockStream(chunks));

      // No events should have been collected after unsubscribe
      expect(events.length).toBe(0);
    });

    it('should not throw if listener errors', async () => {
      handler.on(() => {
        throw new Error('listener bug');
      });

      const chunks: StreamChunk[] = [
        { type: 'text', content: 'hello' },
        { type: 'done' },
      ];

      // Should not throw despite the faulty listener
      const response = await handler.processStream(mockStream(chunks));
      expect(response.content).toBe('hello');
    });

    it('should support multiple listeners', async () => {
      const events1: StreamEvent[] = [];
      const events2: StreamEvent[] = [];

      handler.on((event) => events1.push(event));
      handler.on((event) => events2.push(event));

      const chunks: StreamChunk[] = [{ type: 'done' }];
      await handler.processStream(mockStream(chunks));

      // Both listeners should have received events
      expect(events1.length).toBeGreaterThan(0);
      expect(events2.length).toBeGreaterThan(0);
      expect(events1.length).toBe(events2.length);
    });
  });

  // ===========================================================================
  // isEnabled
  // ===========================================================================

  describe('isEnabled', () => {
    it('should return true by default', () => {
      expect(handler.isEnabled()).toBe(true);
    });

    it('should return false when disabled', () => {
      const disabled = new StreamHandler({ enabled: false });
      expect(disabled.isEnabled()).toBe(false);
    });
  });
});

// =============================================================================
// createStreamHandler factory
// =============================================================================

describe('createStreamHandler', () => {
  it('should create a StreamHandler with default config', () => {
    const handler = createStreamHandler();
    expect(handler).toBeInstanceOf(StreamHandler);
    expect(handler.isEnabled()).toBe(true);
  });

  it('should create a StreamHandler with custom config', () => {
    const handler = createStreamHandler({ enabled: false, bufferSize: 100 });
    expect(handler).toBeInstanceOf(StreamHandler);
    expect(handler.isEnabled()).toBe(false);
  });

  it('should pass buffer size to handler', async () => {
    const handler = createStreamHandler({ bufferSize: 10 });
    const events: StreamEvent[] = [];
    handler.on((event) => events.push(event));

    // 15 chars should trigger a flush with bufferSize=10
    const chunks: StreamChunk[] = [
      { type: 'text', content: 'A'.repeat(15) },
      { type: 'done' },
    ];

    await handler.processStream(mockStream(chunks));

    const textEvents = events.filter((e) => e.type === 'stream.text');
    // Should have flushed at least once when buffer exceeded 10 chars
    expect(textEvents.length).toBeGreaterThanOrEqual(1);
  });
});

// =============================================================================
// formatChunkForTerminal
// =============================================================================

describe('formatChunkForTerminal', () => {
  it('should return content string for text chunk', () => {
    const result = formatChunkForTerminal({ type: 'text', content: 'Hello world' });
    expect(result).toBe('Hello world');
  });

  it('should return empty string for text chunk with no content', () => {
    const result = formatChunkForTerminal({ type: 'text' });
    expect(result).toBe('');
  });

  it('should return tool format for tool_call_start', () => {
    const result = formatChunkForTerminal({
      type: 'tool_call_start',
      toolCall: { name: 'bash' },
    });
    expect(result).toContain('Tool: bash');
  });

  it('should handle unknown tool name in tool_call_start', () => {
    const result = formatChunkForTerminal({ type: 'tool_call_start' });
    expect(result).toContain('Tool: unknown');
  });

  it('should return empty string for tool_call_end', () => {
    const result = formatChunkForTerminal({ type: 'tool_call_end' });
    expect(result).toBe('');
  });

  it('should return error format for error chunk', () => {
    const result = formatChunkForTerminal({ type: 'error', error: 'timeout' });
    expect(result).toContain('Error: timeout');
  });

  it('should return newline for done chunk', () => {
    const result = formatChunkForTerminal({ type: 'done' });
    expect(result).toBe('\n');
  });

  it('should return empty string for tool_call_delta', () => {
    const result = formatChunkForTerminal({
      type: 'tool_call_delta',
      toolCall: { arguments: { foo: 'bar' } },
    });
    expect(result).toBe('');
  });

  it('should return empty string for usage chunk', () => {
    const result = formatChunkForTerminal({
      type: 'usage',
      usage: { inputTokens: 10, outputTokens: 20 },
    });
    expect(result).toBe('');
  });
});

// =============================================================================
// adaptOpenRouterStream
// =============================================================================

describe('adaptOpenRouterStream', () => {
  it('should yield text chunks from SSE content deltas', async () => {
    const response = createMockSSEResponse([
      'data: {"choices":[{"delta":{"content":"hello"}}]}',
      'data: {"choices":[{"delta":{"content":" world"}}]}',
      'data: [DONE]',
    ]);

    const chunks = await collectChunks(adaptOpenRouterStream(response));

    const textChunks = chunks.filter((c) => c.type === 'text');
    expect(textChunks.length).toBe(2);
    expect(textChunks[0].content).toBe('hello');
    expect(textChunks[1].content).toBe(' world');
  });

  it('should yield done chunk on [DONE]', async () => {
    const response = createMockSSEResponse([
      'data: {"choices":[{"delta":{"content":"x"}}]}',
      'data: [DONE]',
    ]);

    const chunks = await collectChunks(adaptOpenRouterStream(response));

    const doneChunks = chunks.filter((c) => c.type === 'done');
    expect(doneChunks.length).toBe(1);
  });

  it('should yield tool_call_start for tool call with function name', async () => {
    const response = createMockSSEResponse([
      'data: {"choices":[{"delta":{"tool_calls":[{"id":"tc-1","function":{"name":"bash"}}]}}]}',
      'data: [DONE]',
    ]);

    const chunks = await collectChunks(adaptOpenRouterStream(response));

    const startChunks = chunks.filter((c) => c.type === 'tool_call_start');
    expect(startChunks.length).toBe(1);
    expect(startChunks[0].toolCallId).toBe('tc-1');
    expect(startChunks[0].toolCall?.name).toBe('bash');
  });

  it('should yield tool_call_delta for tool call arguments', async () => {
    const response = createMockSSEResponse([
      'data: {"choices":[{"delta":{"tool_calls":[{"function":{"arguments":"{\\"command\\":\\"ls\\"}"}}]}}]}',
      'data: [DONE]',
    ]);

    const chunks = await collectChunks(adaptOpenRouterStream(response));

    const deltaChunks = chunks.filter((c) => c.type === 'tool_call_delta');
    expect(deltaChunks.length).toBe(1);
    expect(deltaChunks[0].toolCall?.arguments).toEqual({ command: 'ls' });
  });

  it('should yield tool_call_end on finish_reason tool_calls', async () => {
    const response = createMockSSEResponse([
      'data: {"choices":[{"delta":{"tool_calls":[{"id":"tc-1","function":{"name":"bash"}}]}},{"finish_reason":null}]}',
      'data: {"choices":[{"finish_reason":"tool_calls","delta":{}}]}',
      'data: [DONE]',
    ]);

    const chunks = await collectChunks(adaptOpenRouterStream(response));

    const endChunks = chunks.filter((c) => c.type === 'tool_call_end');
    expect(endChunks.length).toBe(1);
  });

  it('should yield usage chunk when usage data present', async () => {
    const response = createMockSSEResponse([
      'data: {"choices":[{"delta":{"content":"hi"}}],"usage":{"prompt_tokens":50,"completion_tokens":25}}',
      'data: [DONE]',
    ]);

    const chunks = await collectChunks(adaptOpenRouterStream(response));

    const usageChunks = chunks.filter((c) => c.type === 'usage');
    expect(usageChunks.length).toBe(1);
    expect(usageChunks[0].usage?.inputTokens).toBe(50);
    expect(usageChunks[0].usage?.outputTokens).toBe(25);
  });

  it('should throw if response has no body', async () => {
    // Create a Response with no body by passing null
    const response = new Response(null);
    // Override body getter to return null
    Object.defineProperty(response, 'body', { value: null });

    await expect(async () => {
      await collectChunks(adaptOpenRouterStream(response));
    }).rejects.toThrow('No response body');
  });

  it('should ignore malformed JSON lines', async () => {
    const response = createMockSSEResponse([
      'data: {"choices":[{"delta":{"content":"ok"}}]}',
      'data: {not valid json',
      'data: [DONE]',
    ]);

    const chunks = await collectChunks(adaptOpenRouterStream(response));

    const textChunks = chunks.filter((c) => c.type === 'text');
    expect(textChunks.length).toBe(1);
    expect(textChunks[0].content).toBe('ok');
  });

  it('should ignore non-data lines', async () => {
    const response = createMockSSEResponse([
      ': comment line',
      'event: something',
      'data: {"choices":[{"delta":{"content":"valid"}}]}',
      'data: [DONE]',
    ]);

    const chunks = await collectChunks(adaptOpenRouterStream(response));

    const textChunks = chunks.filter((c) => c.type === 'text');
    expect(textChunks.length).toBe(1);
    expect(textChunks[0].content).toBe('valid');
  });

  it('should yield done when stream ends without [DONE] marker', async () => {
    const response = createMockSSEResponse([
      'data: {"choices":[{"delta":{"content":"hi"}}]}',
    ]);

    const chunks = await collectChunks(adaptOpenRouterStream(response));

    // Should still get a done chunk at end of stream
    const doneChunks = chunks.filter((c) => c.type === 'done');
    expect(doneChunks.length).toBe(1);
  });
});

// =============================================================================
// adaptAnthropicStream
// =============================================================================

describe('adaptAnthropicStream', () => {
  it('should yield text chunks from text_delta events', async () => {
    const response = createMockSSEResponse([
      'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello"}}',
      'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":" there"}}',
      'data: {"type":"message_stop"}',
    ]);

    const chunks = await collectChunks(adaptAnthropicStream(response));

    const textChunks = chunks.filter((c) => c.type === 'text');
    expect(textChunks.length).toBe(2);
    expect(textChunks[0].content).toBe('Hello');
    expect(textChunks[1].content).toBe(' there');
  });

  it('should yield tool_call_start from content_block_start with tool_use', async () => {
    const response = createMockSSEResponse([
      'data: {"type":"content_block_start","content_block":{"type":"tool_use","id":"toolu_01","name":"bash"}}',
      'data: {"type":"content_block_stop"}',
      'data: {"type":"message_stop"}',
    ]);

    const chunks = await collectChunks(adaptAnthropicStream(response));

    const startChunks = chunks.filter((c) => c.type === 'tool_call_start');
    expect(startChunks.length).toBe(1);
    expect(startChunks[0].toolCallId).toBe('toolu_01');
    expect(startChunks[0].toolCall?.name).toBe('bash');
  });

  it('should yield tool_call_delta from input_json_delta events', async () => {
    const response = createMockSSEResponse([
      'data: {"type":"content_block_start","content_block":{"type":"tool_use","id":"toolu_01","name":"bash"}}',
      'data: {"type":"content_block_delta","delta":{"type":"input_json_delta","partial_json":"{\\"command\\":\\"ls\\"}"}}',
      'data: {"type":"content_block_stop"}',
      'data: {"type":"message_stop"}',
    ]);

    const chunks = await collectChunks(adaptAnthropicStream(response));

    const deltaChunks = chunks.filter((c) => c.type === 'tool_call_delta');
    expect(deltaChunks.length).toBe(1);
    expect(deltaChunks[0].toolCall?.arguments).toEqual({ command: 'ls' });
  });

  it('should yield tool_call_end from content_block_stop after tool_use', async () => {
    const response = createMockSSEResponse([
      'data: {"type":"content_block_start","content_block":{"type":"tool_use","id":"toolu_01","name":"bash"}}',
      'data: {"type":"content_block_stop"}',
      'data: {"type":"message_stop"}',
    ]);

    const chunks = await collectChunks(adaptAnthropicStream(response));

    const endChunks = chunks.filter((c) => c.type === 'tool_call_end');
    expect(endChunks.length).toBe(1);
  });

  it('should not yield tool_call_end from content_block_stop without prior tool_use', async () => {
    const response = createMockSSEResponse([
      'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi"}}',
      'data: {"type":"content_block_stop"}',
      'data: {"type":"message_stop"}',
    ]);

    const chunks = await collectChunks(adaptAnthropicStream(response));

    const endChunks = chunks.filter((c) => c.type === 'tool_call_end');
    expect(endChunks.length).toBe(0);
  });

  it('should yield usage chunk from message_delta with usage', async () => {
    const response = createMockSSEResponse([
      'data: {"type":"message_delta","usage":{"input_tokens":200,"output_tokens":80}}',
      'data: {"type":"message_stop"}',
    ]);

    const chunks = await collectChunks(adaptAnthropicStream(response));

    const usageChunks = chunks.filter((c) => c.type === 'usage');
    expect(usageChunks.length).toBe(1);
    expect(usageChunks[0].usage?.inputTokens).toBe(200);
    expect(usageChunks[0].usage?.outputTokens).toBe(80);
  });

  it('should yield done chunk on message_stop', async () => {
    const response = createMockSSEResponse([
      'data: {"type":"message_stop"}',
    ]);

    const chunks = await collectChunks(adaptAnthropicStream(response));

    const doneChunks = chunks.filter((c) => c.type === 'done');
    expect(doneChunks.length).toBe(1);
  });

  it('should throw if response has no body', async () => {
    const response = new Response(null);
    Object.defineProperty(response, 'body', { value: null });

    await expect(async () => {
      await collectChunks(adaptAnthropicStream(response));
    }).rejects.toThrow('No response body');
  });

  it('should handle full tool call sequence', async () => {
    const response = createMockSSEResponse([
      'data: {"type":"content_block_start","content_block":{"type":"tool_use","id":"toolu_99","name":"read_file"}}',
      'data: {"type":"content_block_delta","delta":{"type":"input_json_delta","partial_json":"{\\"path\\":\\"/foo.ts\\"}"}}',
      'data: {"type":"content_block_stop"}',
      'data: {"type":"message_delta","usage":{"input_tokens":300,"output_tokens":120}}',
      'data: {"type":"message_stop"}',
    ]);

    const chunks = await collectChunks(adaptAnthropicStream(response));

    const types = chunks.map((c) => c.type);
    expect(types).toContain('tool_call_start');
    expect(types).toContain('tool_call_delta');
    expect(types).toContain('tool_call_end');
    expect(types).toContain('usage');
    expect(types).toContain('done');
  });

  it('should ignore partial JSON in input_json_delta', async () => {
    const response = createMockSSEResponse([
      'data: {"type":"content_block_start","content_block":{"type":"tool_use","id":"toolu_01","name":"bash"}}',
      // This is partial JSON that cannot be parsed
      'data: {"type":"content_block_delta","delta":{"type":"input_json_delta","partial_json":"{\\"comma"}}',
      'data: {"type":"content_block_stop"}',
      'data: {"type":"message_stop"}',
    ]);

    const chunks = await collectChunks(adaptAnthropicStream(response));

    // Should still produce tool_call_start and tool_call_end, but no delta
    const deltaChunks = chunks.filter((c) => c.type === 'tool_call_delta');
    expect(deltaChunks.length).toBe(0);
  });

  it('should yield done when stream ends without message_stop', async () => {
    const response = createMockSSEResponse([
      'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"partial"}}',
    ]);

    const chunks = await collectChunks(adaptAnthropicStream(response));

    const doneChunks = chunks.filter((c) => c.type === 'done');
    expect(doneChunks.length).toBe(1);
  });

  it('should handle interleaved text and tool calls', async () => {
    const response = createMockSSEResponse([
      'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Let me check."}}',
      'data: {"type":"content_block_stop"}',
      'data: {"type":"content_block_start","content_block":{"type":"tool_use","id":"toolu_02","name":"grep"}}',
      'data: {"type":"content_block_delta","delta":{"type":"input_json_delta","partial_json":"{\\"pattern\\":\\"foo\\"}"}}',
      'data: {"type":"content_block_stop"}',
      'data: {"type":"message_stop"}',
    ]);

    const chunks = await collectChunks(adaptAnthropicStream(response));

    const textChunks = chunks.filter((c) => c.type === 'text');
    const toolStartChunks = chunks.filter((c) => c.type === 'tool_call_start');

    expect(textChunks.length).toBe(1);
    expect(textChunks[0].content).toBe('Let me check.');
    expect(toolStartChunks.length).toBe(1);
    expect(toolStartChunks[0].toolCall?.name).toBe('grep');
  });
});

// =============================================================================
// PTYShellManager
// =============================================================================

describe('PTYShellManager', () => {
  describe('createPTYShell', () => {
    it('should return a PTYShellManager instance', () => {
      const shell = createPTYShell();
      expect(shell).toBeInstanceOf(PTYShellManager);
    });

    it('should accept custom config', () => {
      const shell = createPTYShell({ timeout: 5000, cwd: '/tmp' });
      expect(shell).toBeInstanceOf(PTYShellManager);
    });
  });

  describe('getState', () => {
    it('should return initial state', () => {
      const shell = createPTYShell({ cwd: '/tmp' });
      const state = shell.getState();

      expect(state.cwd).toBe('/tmp');
      expect(state.history).toEqual([]);
      expect(state.isRunning).toBe(false);
      expect(state.pid).toBeUndefined();
    });

    it('should use process.cwd() as default cwd', () => {
      const shell = createPTYShell();
      const state = shell.getState();

      expect(state.cwd).toBe(process.cwd());
    });

    it('should include env from config merged with process.env', () => {
      const shell = createPTYShell({ env: { MY_VAR: 'test' } });
      const state = shell.getState();

      expect(state.env.MY_VAR).toBe('test');
      // Should also include inherited env vars
      expect(state.env.PATH).toBeDefined();
    });
  });

  describe('getHistory', () => {
    it('should return empty array initially', () => {
      const shell = createPTYShell();
      expect(shell.getHistory()).toEqual([]);
    });

    it('should return a copy of the history', () => {
      const shell = createPTYShell();
      const history1 = shell.getHistory();
      const history2 = shell.getHistory();

      // Should be different array references
      expect(history1).not.toBe(history2);
      expect(history1).toEqual(history2);
    });
  });

  describe('clearHistory', () => {
    it('should clear the command history', () => {
      const shell = createPTYShell();

      // History starts empty
      expect(shell.getHistory()).toEqual([]);

      // Clear should work even when empty
      shell.clearHistory();
      expect(shell.getHistory()).toEqual([]);
    });
  });

  describe('subscribe', () => {
    it('should return an unsubscribe function', () => {
      const shell = createPTYShell();
      const listener = vi.fn();

      const unsub = shell.subscribe(listener);
      expect(typeof unsub).toBe('function');
    });

    it('should unsubscribe when called', () => {
      const shell = createPTYShell();
      const listener = vi.fn();

      const unsub = shell.subscribe(listener);
      unsub();

      // Verify it was removed by subscribing another and checking
      // the first doesn't receive events (we can't easily trigger events
      // without starting the shell, so just verify the function runs without error)
      expect(() => unsub()).not.toThrow();
    });

    it('should support multiple listeners', () => {
      const shell = createPTYShell();
      const listener1 = vi.fn();
      const listener2 = vi.fn();

      const unsub1 = shell.subscribe(listener1);
      const unsub2 = shell.subscribe(listener2);

      expect(typeof unsub1).toBe('function');
      expect(typeof unsub2).toBe('function');

      // Unsubscribe one, the other should still be registered
      unsub1();
      // No error on second unsubscribe
      unsub2();
    });
  });
});

// =============================================================================
// formatShellState
// =============================================================================

describe('formatShellState', () => {
  it('should format running state with PID', () => {
    const state: ShellState = {
      cwd: '/home/user/project',
      env: {},
      history: [],
      isRunning: true,
      pid: 12345,
    };

    const output = formatShellState(state);

    expect(output).toContain('Running');
    expect(output).toContain('PID: 12345');
    expect(output).toContain('/home/user/project');
    expect(output).toContain('0 commands');
  });

  it('should format stopped state', () => {
    const state: ShellState = {
      cwd: '/tmp',
      env: {},
      history: [],
      isRunning: false,
    };

    const output = formatShellState(state);

    expect(output).toContain('Stopped');
    expect(output).not.toContain('PID');
    expect(output).toContain('/tmp');
  });

  it('should format state with history entries', () => {
    const state: ShellState = {
      cwd: '/tmp',
      env: {},
      history: ['ls', 'pwd', 'echo hello'],
      isRunning: true,
      pid: 99,
    };

    const output = formatShellState(state);

    expect(output).toContain('3 commands');
    expect(output).toContain('Recent commands:');
    expect(output).toContain('$ ls');
    expect(output).toContain('$ pwd');
    expect(output).toContain('$ echo hello');
  });

  it('should show only last 5 history entries', () => {
    const state: ShellState = {
      cwd: '/tmp',
      env: {},
      history: ['cmd1', 'cmd2', 'cmd3', 'cmd4', 'cmd5', 'cmd6', 'cmd7'],
      isRunning: false,
    };

    const output = formatShellState(state);

    expect(output).toContain('7 commands');
    // Should show last 5
    expect(output).toContain('$ cmd3');
    expect(output).toContain('$ cmd4');
    expect(output).toContain('$ cmd5');
    expect(output).toContain('$ cmd6');
    expect(output).toContain('$ cmd7');
    // Should not show first 2
    expect(output).not.toContain('$ cmd1');
    expect(output).not.toContain('$ cmd2');
  });

  it('should not show recent commands section when history is empty', () => {
    const state: ShellState = {
      cwd: '/tmp',
      env: {},
      history: [],
      isRunning: false,
    };

    const output = formatShellState(state);

    expect(output).not.toContain('Recent commands:');
  });

  it('should show running state without PID when PID is undefined', () => {
    const state: ShellState = {
      cwd: '/tmp',
      env: {},
      history: [],
      isRunning: true,
    };

    const output = formatShellState(state);

    expect(output).toContain('Running');
    expect(output).not.toContain('PID');
  });
});
