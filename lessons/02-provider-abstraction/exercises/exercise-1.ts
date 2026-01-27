/**
 * Exercise 2: Delayed Mock Provider
 *
 * Implement a mock LLM provider with configurable delays.
 * This demonstrates the provider interface pattern.
 */

// =============================================================================
// TYPES (from lesson 2)
// =============================================================================

export interface Message {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface ChatOptions {
  maxTokens?: number;
  temperature?: number;
  stopSequences?: string[];
  model?: string;
}

export interface ChatResponse {
  content: string;
  stopReason: 'end_turn' | 'max_tokens' | 'stop_sequence';
  usage?: {
    inputTokens: number;
    outputTokens: number;
  };
}

export interface LLMProvider {
  readonly name: string;
  readonly defaultModel: string;
  chat(messages: Message[], options?: ChatOptions): Promise<ChatResponse>;
  isConfigured(): boolean;
}

// =============================================================================
// CONFIGURATION
// =============================================================================

export interface DelayedMockProviderConfig {
  /** List of responses to return in order */
  responses: string[];
  /** Delay in milliseconds before each response */
  delayMs?: number;
  /** Provider name for identification */
  name?: string;
}

export interface ProviderStats {
  callCount: number;
  totalDelayMs: number;
}

// =============================================================================
// HELPER: Create delay promise
// =============================================================================

function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// =============================================================================
// TODO: Implement DelayedMockProvider
// =============================================================================

/**
 * A mock LLM provider that returns scripted responses with delays.
 *
 * TODO: Implement this class following these requirements:
 *
 * 1. Constructor should:
 *    - Store the responses array
 *    - Store the delay (default: 0ms)
 *    - Initialize call tracking
 *
 * 2. Properties:
 *    - name: string (readonly) - Provider identifier
 *    - defaultModel: string (readonly) - e.g., "mock-model"
 *
 * 3. Methods:
 *    - chat(): Wait for delay, return next response
 *    - isConfigured(): Return true if responses are provided
 *    - getStats(): Return call count and total delay
 *    - reset(): Reset the response index and stats
 *
 * 4. Error handling:
 *    - Throw if called more times than responses available
 */
export class DelayedMockProvider implements LLMProvider {
  // TODO: Add private fields
  // private responses: string[];
  // private delayMs: number;
  // private currentIndex: number = 0;
  // private stats: ProviderStats = { callCount: 0, totalDelayMs: 0 };

  // TODO: Implement readonly properties
  readonly name: string = 'TODO';
  readonly defaultModel: string = 'TODO';

  constructor(_config: DelayedMockProviderConfig) {
    // TODO: Initialize from config
    // this.responses = config.responses;
    // this.delayMs = config.delayMs ?? 0;
    // this.name = config.name ?? 'delayed-mock';
    throw new Error('TODO: Implement constructor');
  }

  async chat(_messages: Message[], _options?: ChatOptions): Promise<ChatResponse> {
    // TODO: Implement chat method
    // 1. Check if responses are exhausted
    // 2. Apply delay
    // 3. Get next response
    // 4. Update stats
    // 5. Return ChatResponse
    throw new Error('TODO: Implement chat method');
  }

  isConfigured(): boolean {
    // TODO: Return true if responses array is not empty
    throw new Error('TODO: Implement isConfigured');
  }

  getStats(): ProviderStats {
    // TODO: Return current stats
    throw new Error('TODO: Implement getStats');
  }

  reset(): void {
    // TODO: Reset index and stats
    throw new Error('TODO: Implement reset');
  }
}
