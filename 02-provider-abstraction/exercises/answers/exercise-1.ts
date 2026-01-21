/**
 * Exercise 2: Delayed Mock Provider - REFERENCE SOLUTION
 */

// =============================================================================
// TYPES
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

export interface DelayedMockProviderConfig {
  responses: string[];
  delayMs?: number;
  name?: string;
}

export interface ProviderStats {
  callCount: number;
  totalDelayMs: number;
}

// =============================================================================
// HELPER
// =============================================================================

function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// =============================================================================
// SOLUTION: DelayedMockProvider
// =============================================================================

export class DelayedMockProvider implements LLMProvider {
  private responses: string[];
  private delayMs: number;
  private currentIndex: number = 0;
  private stats: ProviderStats = { callCount: 0, totalDelayMs: 0 };

  readonly name: string;
  readonly defaultModel: string = 'mock-delayed-v1';

  constructor(config: DelayedMockProviderConfig) {
    this.responses = config.responses;
    this.delayMs = config.delayMs ?? 0;
    this.name = config.name ?? 'delayed-mock';
  }

  async chat(_messages: Message[], _options?: ChatOptions): Promise<ChatResponse> {
    // Check if we have responses left
    if (this.currentIndex >= this.responses.length) {
      throw new Error(
        `Mock provider exhausted: called ${this.currentIndex + 1} times but only ${this.responses.length} responses provided`
      );
    }

    // Apply delay to simulate network latency
    if (this.delayMs > 0) {
      await delay(this.delayMs);
    }

    // Get the next response
    const content = this.responses[this.currentIndex++];

    // Update stats
    this.stats.callCount++;
    this.stats.totalDelayMs += this.delayMs;

    // Return a properly formatted ChatResponse
    return {
      content,
      stopReason: 'end_turn',
      usage: {
        inputTokens: 10, // Mock values
        outputTokens: content.length,
      },
    };
  }

  isConfigured(): boolean {
    return this.responses.length > 0;
  }

  getStats(): ProviderStats {
    return { ...this.stats };
  }

  reset(): void {
    this.currentIndex = 0;
    this.stats = { callCount: 0, totalDelayMs: 0 };
  }
}
