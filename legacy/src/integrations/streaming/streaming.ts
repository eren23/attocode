/**
 * Lesson 25: Streaming Response Handler
 *
 * Handles streaming LLM responses for real-time output.
 * Supports text chunks, tool calls, and usage tracking.
 */

import type { ToolCall, ChatResponse } from '../../types.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * A chunk from a streaming response.
 */
export interface StreamChunk {
  type:
    | 'text'
    | 'tool_call_start'
    | 'tool_call_delta'
    | 'tool_call_end'
    | 'usage'
    | 'done'
    | 'error';
  content?: string;
  toolCall?: Partial<ToolCall>;
  toolCallId?: string;
  usage?: {
    inputTokens: number;
    outputTokens: number;
  };
  error?: string;
}

/**
 * Callback for stream chunks.
 */
export type StreamCallback = (chunk: StreamChunk) => void;

/**
 * Streaming configuration.
 */
export interface StreamConfig {
  /** Enable streaming (default: true) */
  enabled?: boolean;
  /** Buffer size before flushing (default: 50 chars for batched updates) */
  bufferSize?: number;
  /** Show typing indicator (default: true) */
  showTypingIndicator?: boolean;
}

/**
 * Accumulated streaming state.
 */
interface StreamState {
  content: string;
  toolCalls: ToolCall[];
  currentToolCall: Partial<ToolCall> | null;
  usage: { inputTokens: number; outputTokens: number };
}

/**
 * Stream events.
 */
export type StreamEvent =
  | { type: 'stream.start' }
  | { type: 'stream.text'; content: string }
  | { type: 'stream.tool_call'; toolCall: ToolCall }
  | { type: 'stream.complete'; response: ChatResponse }
  | { type: 'stream.error'; error: string };

export type StreamEventListener = (event: StreamEvent) => void;

// =============================================================================
// STREAM HANDLER
// =============================================================================

/**
 * Handles streaming responses from LLM providers.
 */
export class StreamHandler {
  private config: Required<StreamConfig>;
  private listeners: StreamEventListener[] = [];
  private buffer: string = '';

  constructor(config: StreamConfig = {}) {
    this.config = {
      enabled: config.enabled ?? true,
      bufferSize: config.bufferSize ?? 50, // Batch updates to reduce re-renders
      showTypingIndicator: config.showTypingIndicator ?? true,
    };
  }

  /**
   * Process a streaming response.
   * Accumulates chunks and returns the final ChatResponse.
   */
  async processStream(
    stream: AsyncIterable<StreamChunk>,
    onChunk?: StreamCallback,
  ): Promise<ChatResponse> {
    const state: StreamState = {
      content: '',
      toolCalls: [],
      currentToolCall: null,
      usage: { inputTokens: 0, outputTokens: 0 },
    };

    this.emit({ type: 'stream.start' });

    try {
      for await (const chunk of stream) {
        this.processChunk(chunk, state, onChunk);
      }
    } catch (err) {
      const error = err instanceof Error ? err.message : String(err);
      this.emit({ type: 'stream.error', error });
      throw err;
    }

    // Build final response
    const response: ChatResponse = {
      content: state.content,
      toolCalls: state.toolCalls.length > 0 ? state.toolCalls : undefined,
      usage:
        state.usage.inputTokens > 0
          ? {
              inputTokens: state.usage.inputTokens,
              outputTokens: state.usage.outputTokens,
              totalTokens: state.usage.inputTokens + state.usage.outputTokens,
            }
          : undefined,
    };

    this.emit({ type: 'stream.complete', response });

    return response;
  }

  /**
   * Process a single chunk.
   */
  private processChunk(chunk: StreamChunk, state: StreamState, onChunk?: StreamCallback): void {
    switch (chunk.type) {
      case 'text':
        if (chunk.content) {
          state.content += chunk.content;
          this.buffer += chunk.content;

          // Flush buffer if needed
          if (this.buffer.length >= this.config.bufferSize) {
            this.emit({ type: 'stream.text', content: this.buffer });
            this.buffer = '';
          }
        }
        break;

      case 'tool_call_start':
        state.currentToolCall = {
          id: chunk.toolCallId || `call-${Date.now()}`,
          name: chunk.toolCall?.name,
          arguments: {},
        };
        break;

      case 'tool_call_delta':
        if (state.currentToolCall && chunk.toolCall) {
          // Accumulate tool call data
          if (chunk.toolCall.name) {
            state.currentToolCall.name = chunk.toolCall.name;
          }
          if (chunk.toolCall.arguments) {
            // Simplified - just assign the latest arguments
            // Real implementation would merge partial JSON properly
            state.currentToolCall.arguments = chunk.toolCall.arguments;
          }
        }
        break;

      case 'tool_call_end':
        if (state.currentToolCall && state.currentToolCall.name) {
          const toolCall: ToolCall = {
            id: state.currentToolCall.id!,
            name: state.currentToolCall.name,
            arguments: state.currentToolCall.arguments as Record<string, unknown>,
          };
          state.toolCalls.push(toolCall);
          this.emit({ type: 'stream.tool_call', toolCall });
          state.currentToolCall = null;
        }
        break;

      case 'usage':
        if (chunk.usage) {
          state.usage = chunk.usage;
        }
        break;

      case 'error':
        if (chunk.error) {
          this.emit({ type: 'stream.error', error: chunk.error });
        }
        break;

      case 'done':
        // Flush remaining buffer
        if (this.buffer.length > 0) {
          this.emit({ type: 'stream.text', content: this.buffer });
          this.buffer = '';
        }
        break;
    }

    // Call external callback if provided
    if (onChunk) {
      onChunk(chunk);
    }
  }

  /**
   * Subscribe to events.
   */
  on(listener: StreamEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  /**
   * Emit an event.
   */
  private emit(event: StreamEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }

  /**
   * Check if streaming is enabled.
   */
  isEnabled(): boolean {
    return this.config.enabled;
  }
}

// =============================================================================
// FACTORY
// =============================================================================

/**
 * Create a stream handler.
 */
export function createStreamHandler(config?: StreamConfig): StreamHandler {
  return new StreamHandler(config);
}

// =============================================================================
// TERMINAL FORMATTING
// =============================================================================

/**
 * Format a stream chunk for terminal output.
 */
export function formatChunkForTerminal(chunk: StreamChunk): string {
  switch (chunk.type) {
    case 'text':
      return chunk.content || '';

    case 'tool_call_start':
      return `\n🔧 Tool: ${chunk.toolCall?.name || 'unknown'}\n`;

    case 'tool_call_end':
      return '';

    case 'error':
      return `\n❌ Error: ${chunk.error}\n`;

    case 'done':
      return '\n';

    default:
      return '';
  }
}

// =============================================================================
// STREAM ADAPTERS
// =============================================================================

/**
 * Convert OpenRouter SSE stream to StreamChunk iterator.
 */
export async function* adaptOpenRouterStream(response: Response): AsyncIterable<StreamChunk> {
  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('No response body');
  }

  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Process complete SSE events
      const lines = buffer.split('\n');
      buffer = lines.pop() || ''; // Keep incomplete line in buffer

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6);

          if (data === '[DONE]') {
            yield { type: 'done' };
            return;
          }

          try {
            const parsed = JSON.parse(data);
            const delta = parsed.choices?.[0]?.delta;

            if (delta?.content) {
              yield { type: 'text', content: delta.content };
            }

            if (delta?.tool_calls) {
              for (const tc of delta.tool_calls) {
                if (tc.function?.name) {
                  yield {
                    type: 'tool_call_start',
                    toolCallId: tc.id,
                    toolCall: { name: tc.function.name },
                  };
                }
                if (tc.function?.arguments) {
                  try {
                    yield {
                      type: 'tool_call_delta',
                      toolCall: { arguments: JSON.parse(tc.function.arguments) },
                    };
                  } catch {
                    // Partial JSON, accumulate
                  }
                }
              }
            }

            // Check for finish reason
            if (parsed.choices?.[0]?.finish_reason === 'tool_calls') {
              yield { type: 'tool_call_end' };
            }

            // Usage in final chunk
            if (parsed.usage) {
              yield {
                type: 'usage',
                usage: {
                  inputTokens: parsed.usage.prompt_tokens,
                  outputTokens: parsed.usage.completion_tokens,
                },
              };
            }
          } catch {
            // Ignore parse errors
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }

  yield { type: 'done' };
}

/**
 * Convert Anthropic stream to StreamChunk iterator.
 */
export async function* adaptAnthropicStream(response: Response): AsyncIterable<StreamChunk> {
  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('No response body');
  }

  const decoder = new TextDecoder();
  let buffer = '';
  let currentToolId: string | undefined = undefined;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6);

          try {
            const parsed = JSON.parse(data);

            switch (parsed.type) {
              case 'content_block_start':
                if (parsed.content_block?.type === 'tool_use') {
                  currentToolId = parsed.content_block.id;
                  yield {
                    type: 'tool_call_start',
                    toolCallId: currentToolId,
                    toolCall: { name: parsed.content_block.name },
                  };
                }
                break;

              case 'content_block_delta':
                if (parsed.delta?.type === 'text_delta') {
                  yield { type: 'text', content: parsed.delta.text };
                } else if (parsed.delta?.type === 'input_json_delta') {
                  // Tool call arguments delta
                  try {
                    yield {
                      type: 'tool_call_delta',
                      toolCall: { arguments: JSON.parse(parsed.delta.partial_json) },
                    };
                  } catch {
                    // Partial JSON
                  }
                }
                break;

              case 'content_block_stop':
                if (currentToolId) {
                  yield { type: 'tool_call_end' };
                  currentToolId = undefined;
                }
                break;

              case 'message_delta':
                if (parsed.usage) {
                  yield {
                    type: 'usage',
                    usage: {
                      inputTokens: parsed.usage.input_tokens,
                      outputTokens: parsed.usage.output_tokens,
                    },
                  };
                }
                break;

              case 'message_stop':
                yield { type: 'done' };
                return;
            }
          } catch {
            // Ignore parse errors
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }

  yield { type: 'done' };
}
