/**
 * Lesson 4: Streaming Infrastructure
 * 
 * Core utilities for streaming responses.
 */

import type { 
  StreamEvent, 
  StreamMessage, 
  StreamOptions, 
  StreamingProvider,
  ConsumeOptions,
  ConsumeResult
} from './types.js';
import { parseSSE } from './parser.js';

// =============================================================================
// STREAM UTILITIES
// =============================================================================

/**
 * Create a text stream event.
 */
export function text(content: string): StreamEvent {
  return { type: 'text', text: content };
}

/**
 * Create a done event.
 */
export function done(reason: 'complete' | 'max_iterations' | 'error' = 'complete'): StreamEvent {
  return { type: 'done', reason };
}

/**
 * Create an error event.
 */
export function error(message: string, recoverable = false): StreamEvent {
  return { type: 'error', error: message, recoverable };
}

// =============================================================================
// MOCK STREAMING PROVIDER
// =============================================================================

/**
 * Mock streaming provider for testing.
 * Simulates streaming by yielding characters one at a time.
 */
export class MockStreamingProvider implements StreamingProvider {
  readonly name = 'mock-streaming';
  
  private responses: string[] = [
    `Let me analyze the task.

I'll start by listing the files in the current directory.

\`\`\`json
{ "tool": "list_files", "input": { "path": "." } }
\`\`\``,
    `I found the relevant files. Now let me read the main file.

\`\`\`json
{ "tool": "read_file", "input": { "path": "main.ts" } }
\`\`\``,
    `I understand the code structure now. The task is complete.

Here's a summary of what I found:
- The project uses TypeScript
- It has a modular structure
- Tests are located in the tests directory`,
  ];
  
  private responseIndex = 0;

  async *streamChat(
    _messages: StreamMessage[],
    _options?: StreamOptions
  ): AsyncGenerator<StreamEvent> {
    const response = this.responses[this.responseIndex % this.responses.length];
    this.responseIndex++;
    
    // Yield text character by character with varying delays
    for (let i = 0; i < response.length; i++) {
      yield text(response[i]);
      
      // Simulate variable network latency
      // Faster for punctuation, slower for words
      const delay = response[i] === ' ' ? 5 : 
                    response[i] === '\n' ? 50 : 
                    20;
      await sleep(delay);
    }
    
    yield done();
  }
}

// =============================================================================
// ANTHROPIC STREAMING PROVIDER
// =============================================================================

/**
 * Anthropic streaming provider.
 * Connects to the real Anthropic API with streaming.
 */
export class AnthropicStreamingProvider implements StreamingProvider {
  readonly name = 'anthropic-streaming';
  
  private apiKey: string;
  private model: string;
  private baseUrl: string;

  constructor(config?: { apiKey?: string; model?: string; baseUrl?: string }) {
    this.apiKey = config?.apiKey ?? process.env.ANTHROPIC_API_KEY ?? '';
    this.model = config?.model ?? 'claude-sonnet-4-20250514';
    this.baseUrl = config?.baseUrl ?? 'https://api.anthropic.com';
  }

  async *streamChat(
    messages: StreamMessage[],
    options?: StreamOptions
  ): AsyncGenerator<StreamEvent> {
    const systemMessage = messages.find(m => m.role === 'system');
    const conversationMessages = messages
      .filter(m => m.role !== 'system')
      .map(m => ({ role: m.role, content: m.content }));

    const body = {
      model: options?.model ?? this.model,
      max_tokens: options?.maxTokens ?? 4096,
      temperature: options?.temperature ?? 0.7,
      system: systemMessage?.content,
      messages: conversationMessages,
      stream: true,
    };

    const response = await fetch(`${this.baseUrl}/v1/messages`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': this.apiKey,
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const errorText = await response.text();
      yield error(`Anthropic API error: ${response.status} - ${errorText}`, false);
      yield done('error');
      return;
    }

    if (!response.body) {
      yield error('No response body', false);
      yield done('error');
      return;
    }

    // Parse SSE stream
    for await (const event of parseSSE(response.body)) {
      if (event.type === 'content_block_delta') {
        const delta = event.delta as { type: string; text?: string };
        if (delta.type === 'text_delta' && delta.text) {
          yield text(delta.text);
        }
      } else if (event.type === 'message_stop') {
        yield done();
      } else if (event.type === 'error') {
        const err = event.error as { message: string };
        yield error(err.message, false);
        yield done('error');
      }
    }
  }
}

// =============================================================================
// STREAM CONSUMPTION
// =============================================================================

/**
 * Consume a stream and handle events.
 */
export async function consumeStream(
  stream: AsyncGenerator<StreamEvent>,
  options: ConsumeOptions = {}
): Promise<ConsumeResult> {
  const { onEvent, accumulate = true, signal } = options;
  
  let text = '';
  let eventCount = 0;
  let reason: ConsumeResult['reason'] = 'complete';
  let resultError: Error | undefined;

  try {
    for await (const event of stream) {
      // Check for cancellation
      if (signal?.aborted) {
        reason = 'cancelled';
        break;
      }

      eventCount++;

      // Accumulate text
      if (accumulate && event.type === 'text') {
        text += event.text;
      }

      // Call handler
      if (onEvent) {
        await onEvent(event);
      }

      // Check for completion
      if (event.type === 'done') {
        reason = event.reason === 'error' ? 'error' : 'complete';
        break;
      }

      if (event.type === 'error' && !event.recoverable) {
        reason = 'error';
        resultError = new Error(event.error);
        break;
      }
    }
  } catch (err) {
    reason = 'error';
    resultError = err as Error;
  }

  return { text, eventCount, reason, error: resultError };
}

/**
 * Collect all text from a stream.
 */
export async function collectStream(stream: AsyncGenerator<StreamEvent>): Promise<string> {
  const result = await consumeStream(stream, { accumulate: true });
  return result.text;
}

// =============================================================================
// STREAM TRANSFORMERS
// =============================================================================

/**
 * Buffer text events and emit when a delimiter is found.
 * Useful for collecting complete JSON blocks.
 */
export async function* bufferUntil(
  stream: AsyncGenerator<StreamEvent>,
  delimiter: string
): AsyncGenerator<StreamEvent> {
  let buffer = '';

  for await (const event of stream) {
    if (event.type === 'text') {
      buffer += event.text;
      
      // Check for delimiter
      while (buffer.includes(delimiter)) {
        const index = buffer.indexOf(delimiter);
        const chunk = buffer.slice(0, index + delimiter.length);
        buffer = buffer.slice(index + delimiter.length);
        yield text(chunk);
      }
    } else {
      // Flush remaining buffer before non-text events
      if (buffer.length > 0) {
        yield text(buffer);
        buffer = '';
      }
      yield event;
    }
  }

  // Flush any remaining content
  if (buffer.length > 0) {
    yield text(buffer);
  }
}

/**
 * Rate limit stream events.
 */
export async function* throttle(
  stream: AsyncGenerator<StreamEvent>,
  minDelayMs: number
): AsyncGenerator<StreamEvent> {
  let lastTime = 0;

  for await (const event of stream) {
    const now = Date.now();
    const elapsed = now - lastTime;
    
    if (elapsed < minDelayMs) {
      await sleep(minDelayMs - elapsed);
    }
    
    yield event;
    lastTime = Date.now();
  }
}

// =============================================================================
// HELPERS
// =============================================================================

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}
