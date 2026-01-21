/**
 * Lesson 4: Streaming Types
 * 
 * Types for streaming responses and events.
 */

// =============================================================================
// STREAM EVENT TYPES
// =============================================================================

/**
 * Events emitted during streaming.
 */
export type StreamEvent =
  | TextEvent
  | ToolStartEvent
  | ToolInputEvent
  | ToolEndEvent
  | ThinkingEvent
  | ErrorEvent
  | DoneEvent;

export interface TextEvent {
  type: 'text';
  text: string;
}

export interface ToolStartEvent {
  type: 'tool_start';
  id: string;
  tool: string;
}

export interface ToolInputEvent {
  type: 'tool_input';
  id: string;
  input: Record<string, unknown>;
}

export interface ToolEndEvent {
  type: 'tool_end';
  id: string;
  success: boolean;
  output: string;
}

export interface ThinkingEvent {
  type: 'thinking';
  text: string;
}

export interface ErrorEvent {
  type: 'error';
  error: string;
  recoverable: boolean;
}

export interface DoneEvent {
  type: 'done';
  reason: 'complete' | 'max_iterations' | 'error';
}

// =============================================================================
// STREAMING PROVIDER INTERFACE
// =============================================================================

/**
 * Message format for streaming APIs.
 */
export interface StreamMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

/**
 * Options for streaming chat.
 */
export interface StreamOptions {
  maxTokens?: number;
  temperature?: number;
  model?: string;
}

/**
 * Provider that supports streaming.
 */
export interface StreamingProvider {
  /** Provider name */
  readonly name: string;
  
  /** Stream a chat response */
  streamChat(
    messages: StreamMessage[],
    options?: StreamOptions
  ): AsyncGenerator<StreamEvent>;
}

// =============================================================================
// SSE PARSING TYPES
// =============================================================================

/**
 * Raw SSE event from the API.
 */
export interface SSEEvent {
  event?: string;
  data: string;
  id?: string;
  retry?: number;
}

/**
 * Anthropic-specific SSE event types.
 */
export type AnthropicSSEEvent =
  | { type: 'message_start'; message: { id: string; model: string } }
  | { type: 'content_block_start'; index: number; content_block: { type: string; text?: string } }
  | { type: 'content_block_delta'; index: number; delta: { type: string; text?: string } }
  | { type: 'content_block_stop'; index: number }
  | { type: 'message_delta'; delta: { stop_reason?: string }; usage?: { output_tokens: number } }
  | { type: 'message_stop' }
  | { type: 'error'; error: { type: string; message: string } };

/**
 * OpenAI-specific SSE event types.
 */
export interface OpenAISSEEvent {
  id: string;
  object: string;
  choices: Array<{
    index: number;
    delta: {
      role?: string;
      content?: string;
    };
    finish_reason: string | null;
  }>;
}

// =============================================================================
// STREAM CONSUMER TYPES
// =============================================================================

/**
 * Callback for stream events.
 */
export type StreamEventHandler = (event: StreamEvent) => void | Promise<void>;

/**
 * Options for consuming a stream.
 */
export interface ConsumeOptions {
  /** Handle each event */
  onEvent?: StreamEventHandler;
  
  /** Accumulate text events */
  accumulate?: boolean;
  
  /** Abort signal for cancellation */
  signal?: AbortSignal;
}

/**
 * Result of consuming a stream.
 */
export interface ConsumeResult {
  /** All accumulated text */
  text: string;
  
  /** Number of events processed */
  eventCount: number;
  
  /** Why the stream ended */
  reason: 'complete' | 'error' | 'cancelled';
  
  /** Error if reason is 'error' */
  error?: Error;
}
