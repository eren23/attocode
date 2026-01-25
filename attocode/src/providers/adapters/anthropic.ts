/**
 * Anthropic Claude Provider Adapter
 *
 * Adapts the Anthropic SDK to our LLMProvider interface.
 */

import type {
  LLMProvider,
  Message,
  ChatOptions,
  ChatResponse,
  AnthropicConfig
} from '../types.js';
import { ProviderError } from '../types.js';
import { registerProvider, hasEnv, requireEnv } from '../provider.js';
import { resilientFetch, type NetworkConfig } from '../resilient-fetch.js';

// =============================================================================
// ANTHROPIC PROVIDER
// =============================================================================

export class AnthropicProvider implements LLMProvider {
  readonly name = 'anthropic';
  readonly defaultModel = 'claude-sonnet-4-20250514';

  private apiKey: string;
  private model: string;
  private baseUrl: string;
  private networkConfig: NetworkConfig;

  constructor(config?: AnthropicConfig) {
    this.apiKey = config?.apiKey ?? requireEnv('ANTHROPIC_API_KEY');
    this.model = config?.model ?? this.defaultModel;
    this.baseUrl = config?.baseUrl ?? 'https://api.anthropic.com';
    // Anthropic requests can be slow for complex tasks
    this.networkConfig = {
      timeout: 120000,  // 2 minutes for complex reasoning
      maxRetries: 3,
      baseRetryDelay: 1000,
    };
  }

  isConfigured(): boolean {
    return hasEnv('ANTHROPIC_API_KEY');
  }

  async chat(messages: Message[], options?: ChatOptions): Promise<ChatResponse> {
    const model = options?.model ?? this.model;
    
    // Separate system message from conversation
    const systemMessage = messages.find(m => m.role === 'system');
    const conversationMessages = messages
      .filter(m => m.role !== 'system')
      .map(m => ({
        role: m.role as 'user' | 'assistant',
        content: m.content,
      }));

    // Build request body
    const body = {
      model,
      max_tokens: options?.maxTokens ?? 4096,
      temperature: options?.temperature ?? 0.7,
      system: systemMessage?.content,
      messages: conversationMessages,
      ...(options?.stopSequences && { stop_sequences: options.stopSequences }),
    };

    try {
      const { response } = await resilientFetch({
        url: `${this.baseUrl}/v1/messages`,
        init: {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'x-api-key': this.apiKey,
            'anthropic-version': '2023-06-01',
          },
          body: JSON.stringify(body),
        },
        providerName: this.name,
        networkConfig: this.networkConfig,
        onRetry: (attempt, delay, error) => {
          console.warn(`[Anthropic] Retry attempt ${attempt} after ${delay}ms: ${error.message}`);
        },
      });

      if (!response.ok) {
        const error = await response.text();
        throw this.handleError(response.status, error);
      }

      const data = await response.json() as {
        content: Array<{ type: string; text: string }>;
        stop_reason: string;
        usage: { input_tokens: number; output_tokens: number };
      };

      // Extract text from content blocks
      const content = data.content
        .filter(block => block.type === 'text')
        .map(block => block.text)
        .join('');

      return {
        content,
        stopReason: this.mapStopReason(data.stop_reason),
        usage: {
          inputTokens: data.usage.input_tokens,
          outputTokens: data.usage.output_tokens,
        },
      };
    } catch (error) {
      if (error instanceof ProviderError) throw error;
      throw new ProviderError(
        `Anthropic request failed: ${(error as Error).message}`,
        this.name,
        'NETWORK_ERROR',
        error as Error
      );
    }
  }

  private handleError(status: number, body: string): ProviderError {
    let code: ProviderError['code'] = 'UNKNOWN';
    
    if (status === 401) code = 'AUTHENTICATION_FAILED';
    else if (status === 429) code = 'RATE_LIMITED';
    else if (status === 400) code = 'INVALID_REQUEST';
    else if (status >= 500) code = 'SERVER_ERROR';

    return new ProviderError(
      `Anthropic API error (${status}): ${body}`,
      this.name,
      code
    );
  }

  private mapStopReason(reason: string): ChatResponse['stopReason'] {
    switch (reason) {
      case 'end_turn': return 'end_turn';
      case 'max_tokens': return 'max_tokens';
      case 'stop_sequence': return 'stop_sequence';
      default: return 'end_turn';
    }
  }
}

// =============================================================================
// REGISTRATION
// =============================================================================

registerProvider('anthropic', {
  priority: 1,
  detect: () => hasEnv('ANTHROPIC_API_KEY'),
  create: async () => new AnthropicProvider(),
});
