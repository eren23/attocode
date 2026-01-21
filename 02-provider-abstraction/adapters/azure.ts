/**
 * Azure OpenAI Provider Adapter
 * 
 * Adapts Azure OpenAI Service to our LLMProvider interface.
 * Azure uses a different URL structure and authentication than OpenAI.
 */

import type { 
  LLMProvider, 
  Message, 
  ChatOptions, 
  ChatResponse,
  AzureOpenAIConfig 
} from '../types.js';
import { ProviderError } from '../types.js';
import { registerProvider, hasEnv, requireEnv } from '../provider.js';

// =============================================================================
// AZURE OPENAI PROVIDER
// =============================================================================

export class AzureOpenAIProvider implements LLMProvider {
  readonly name = 'azure-openai';
  readonly defaultModel: string; // Azure uses deployments, not models
  
  private apiKey: string;
  private endpoint: string;
  private deployment: string;
  private apiVersion: string;

  constructor(config?: AzureOpenAIConfig) {
    this.apiKey = config?.apiKey ?? requireEnv('AZURE_OPENAI_API_KEY');
    this.endpoint = config?.endpoint ?? requireEnv('AZURE_OPENAI_ENDPOINT');
    this.deployment = config?.deployment ?? process.env.AZURE_OPENAI_DEPLOYMENT ?? 'gpt-4';
    this.apiVersion = config?.apiVersion ?? '2024-02-15-preview';
    this.defaultModel = this.deployment;
  }

  isConfigured(): boolean {
    return hasEnv('AZURE_OPENAI_API_KEY') && hasEnv('AZURE_OPENAI_ENDPOINT');
  }

  async chat(messages: Message[], options?: ChatOptions): Promise<ChatResponse> {
    // Azure endpoint format: {endpoint}/openai/deployments/{deployment}/chat/completions
    const url = `${this.endpoint}/openai/deployments/${this.deployment}/chat/completions?api-version=${this.apiVersion}`;
    
    // Azure uses the same message format as OpenAI
    const azureMessages = messages.map(m => ({
      role: m.role,
      content: m.content,
    }));

    const body = {
      messages: azureMessages,
      max_tokens: options?.maxTokens ?? 4096,
      temperature: options?.temperature ?? 0.7,
      ...(options?.stopSequences && { stop: options.stopSequences }),
    };

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'api-key': this.apiKey,
        },
        body: JSON.stringify(body),
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
        `Azure OpenAI request failed: ${(error as Error).message}`,
        this.name,
        'NETWORK_ERROR',
        error as Error
      );
    }
  }

  private handleError(status: number, body: string): ProviderError {
    let code: ProviderError['code'] = 'UNKNOWN';
    
    if (status === 401 || status === 403) code = 'AUTHENTICATION_FAILED';
    else if (status === 429) code = 'RATE_LIMITED';
    else if (status === 400) {
      if (body.includes('context_length') || body.includes('token')) {
        code = 'CONTEXT_LENGTH_EXCEEDED';
      } else {
        code = 'INVALID_REQUEST';
      }
    }
    else if (status >= 500) code = 'SERVER_ERROR';

    return new ProviderError(
      `Azure OpenAI API error (${status}): ${body}`,
      this.name,
      code
    );
  }

  private mapStopReason(reason: string): ChatResponse['stopReason'] {
    switch (reason) {
      case 'stop': return 'end_turn';
      case 'length': return 'max_tokens';
      case 'content_filter': return 'stop_sequence';
      default: return 'end_turn';
    }
  }
}

// =============================================================================
// REGISTRATION
// =============================================================================

registerProvider('azure', {
  priority: 3,
  detect: () => hasEnv('AZURE_OPENAI_API_KEY') && hasEnv('AZURE_OPENAI_ENDPOINT'),
  create: async () => new AzureOpenAIProvider(),
});
