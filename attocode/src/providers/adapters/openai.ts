/**
 * OpenAI Provider Adapter
 *
 * Adapts the OpenAI API to our LLMProvider interface.
 */

import type {
  LLMProvider,
  Message,
  ChatOptions,
  ChatResponse,
  OpenAIConfig
} from '../types.js';
import { ProviderError } from '../types.js';
import { registerProvider, hasEnv, requireEnv } from '../provider.js';
import { resilientFetch, type NetworkConfig } from '../resilient-fetch.js';

// =============================================================================
// OPENAI PROVIDER
// =============================================================================

export class OpenAIProvider implements LLMProvider {
  readonly name = 'openai';
  readonly defaultModel = 'gpt-4-turbo-preview';

  private apiKey: string;
  private model: string;
  private baseUrl: string;
  private organization?: string;
  private networkConfig: NetworkConfig;

  constructor(config?: OpenAIConfig) {
    this.apiKey = config?.apiKey ?? requireEnv('OPENAI_API_KEY');
    this.model = config?.model ?? this.defaultModel;
    this.baseUrl = config?.baseUrl ?? 'https://api.openai.com';
    this.organization = config?.organization ?? process.env.OPENAI_ORG_ID;
    this.networkConfig = {
      timeout: 120000,  // 2 minutes
      maxRetries: 3,
      baseRetryDelay: 1000,
    };
  }

  isConfigured(): boolean {
    return hasEnv('OPENAI_API_KEY');
  }

  async chat(messages: Message[], options?: ChatOptions): Promise<ChatResponse> {
    const model = options?.model ?? this.model;
    
    // OpenAI uses the same message format, just need to type it correctly
    const openaiMessages = messages.map(m => ({
      role: m.role,
      content: m.content,
    }));

    // Build request body
    const body = {
      model,
      messages: openaiMessages,
      max_tokens: options?.maxTokens ?? 4096,
      temperature: options?.temperature ?? 0.7,
      ...(options?.stopSequences && { stop: options.stopSequences }),
    };

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${this.apiKey}`,
    };
    
    if (this.organization) {
      headers['OpenAI-Organization'] = this.organization;
    }

    try {
      const { response } = await resilientFetch({
        url: `${this.baseUrl}/v1/chat/completions`,
        init: {
          method: 'POST',
          headers,
          body: JSON.stringify(body),
        },
        providerName: this.name,
        networkConfig: this.networkConfig,
        onRetry: (attempt, delay, error) => {
          console.warn(`[OpenAI] Retry attempt ${attempt} after ${delay}ms: ${error.message}`);
        },
      });

      if (!response.ok) {
        const error = await response.text();
        throw this.handleError(response.status, error);
      }

      const data = await response.json() as {
        choices: Array<{
          message: { content: string };
          finish_reason: string;
        }>;
        usage: {
          prompt_tokens: number;
          completion_tokens: number;
        };
      };

      const choice = data.choices[0];

      return {
        content: choice.message.content,
        stopReason: this.mapStopReason(choice.finish_reason),
        usage: {
          inputTokens: data.usage.prompt_tokens,
          outputTokens: data.usage.completion_tokens,
        },
      };
    } catch (error) {
      if (error instanceof ProviderError) throw error;
      throw new ProviderError(
        `OpenAI request failed: ${(error as Error).message}`,
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
    else if (status === 400) {
      if (body.includes('context_length')) {
        code = 'CONTEXT_LENGTH_EXCEEDED';
      } else {
        code = 'INVALID_REQUEST';
      }
    }
    else if (status >= 500) code = 'SERVER_ERROR';

    return new ProviderError(
      `OpenAI API error (${status}): ${body}`,
      this.name,
      code
    );
  }

  private mapStopReason(reason: string): ChatResponse['stopReason'] {
    switch (reason) {
      case 'stop': return 'end_turn';
      case 'length': return 'max_tokens';
      case 'stop_sequence': return 'stop_sequence';
      default: return 'end_turn';
    }
  }
}

// =============================================================================
// REGISTRATION
// =============================================================================

registerProvider('openai', {
  priority: 2,
  detect: () => hasEnv('OPENAI_API_KEY'),
  create: async () => new OpenAIProvider(),
});
