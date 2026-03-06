/**
 * Azure OpenAI Provider Adapter
 *
 * Adapts Azure OpenAI Service to our LLMProvider interface.
 * Azure uses a different endpoint and auth scheme than standard OpenAI.
 */

import type {
  LLMProvider,
  LLMProviderWithTools,
  Message,
  MessageWithContent,
  ChatOptions,
  ChatOptionsWithTools,
  ChatResponse,
  ChatResponseWithTools,
  ToolCallResponse,
  ToolDefinitionSchema,
  AzureOpenAIConfig,
} from '../types.js';
import { ProviderError } from '../types.js';
import { registerProvider, hasEnv, requireEnv } from '../provider.js';
import { resilientFetch, type NetworkConfig } from '../resilient-fetch.js';
import { logger } from '../../integrations/utilities/logger.js';

// =============================================================================
// AZURE OPENAI API TYPES (duplicated from openai.ts to avoid coupling)
// =============================================================================

/** OpenAI message format */
interface OpenAIMessage {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string | null;
  name?: string;
  tool_calls?: OpenAIToolCall[];
  tool_call_id?: string;
}

/** OpenAI tool call format */
interface OpenAIToolCall {
  id: string;
  type: 'function';
  function: {
    name: string;
    arguments: string;
  };
}

/** OpenAI tool definition format */
interface OpenAITool {
  type: 'function';
  function: {
    name: string;
    description: string;
    parameters: Record<string, unknown>;
    strict?: boolean;
  };
}

/** OpenAI chat completion response */
interface OpenAIChatCompletion {
  id: string;
  object: string;
  created: number;
  model: string;
  choices: Array<{
    index: number;
    message: {
      role: string;
      content: string | null;
      tool_calls?: OpenAIToolCall[];
    };
    finish_reason: string;
  }>;
  usage: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
}

// =============================================================================
// AZURE OPENAI PROVIDER
// =============================================================================

export class AzureOpenAIProvider implements LLMProvider, LLMProviderWithTools {
  readonly name = 'azure';
  readonly defaultModel = 'gpt-4o';

  private apiKey: string;
  private endpoint: string;
  private deployment: string;
  private apiVersion: string;
  private networkConfig: NetworkConfig;

  constructor(config?: AzureOpenAIConfig) {
    this.apiKey = config?.apiKey ?? requireEnv('AZURE_OPENAI_API_KEY');
    this.endpoint = config?.endpoint ?? requireEnv('AZURE_OPENAI_ENDPOINT');
    this.deployment = config?.deployment ?? process.env.AZURE_OPENAI_DEPLOYMENT ?? 'gpt-4o';
    this.apiVersion = config?.apiVersion ?? '2024-08-01-preview';

    // Normalize endpoint: strip trailing slash
    this.endpoint = this.endpoint.replace(/\/+$/, '');

    this.networkConfig = {
      timeout: 120000, // 2 minutes
      maxRetries: 3,
      baseRetryDelay: 1000,
    };
  }

  isConfigured(): boolean {
    return hasEnv('AZURE_OPENAI_API_KEY') && hasEnv('AZURE_OPENAI_ENDPOINT');
  }

  /**
   * Build the Azure OpenAI endpoint URL.
   * Format: https://{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={apiVersion}
   */
  private buildUrl(): string {
    return `${this.endpoint}/openai/deployments/${this.deployment}/chat/completions?api-version=${this.apiVersion}`;
  }

  /**
   * Basic chat without tool support.
   */
  async chat(
    messages: (Message | MessageWithContent)[],
    options?: ChatOptions,
  ): Promise<ChatResponse> {
    // Azure ignores the model field — the deployment determines the model
    const openaiMessages = this.convertMessagesToOpenAIFormat(messages);

    const body = {
      messages: openaiMessages,
      max_tokens: options?.maxTokens ?? 4096,
      temperature: options?.temperature ?? 0.7,
      ...(options?.stopSequences && { stop: options.stopSequences }),
    };

    const headers = this.buildHeaders();

    try {
      const { response } = await resilientFetch({
        url: this.buildUrl(),
        init: {
          method: 'POST',
          headers,
          body: JSON.stringify(body),
        },
        providerName: this.name,
        networkConfig: this.networkConfig,
        onRetry: (attempt, delay, error) => {
          logger.warn('Azure OpenAI retry attempt', {
            attempt,
            delayMs: delay,
            error: error.message,
          });
        },
      });

      if (!response.ok) {
        const error = await response.text();
        throw this.handleError(response.status, error);
      }

      const data = (await response.json()) as OpenAIChatCompletion;
      const result = this.parseResponse(data);
      result.rateLimitInfo = this.extractRateLimitInfo(response);
      return result;
    } catch (error) {
      if (error instanceof ProviderError) throw error;
      throw new ProviderError(
        `Azure OpenAI request failed: ${(error as Error).message}`,
        this.name,
        'NETWORK_ERROR',
        error as Error,
      );
    }
  }

  /**
   * Chat with native tool use support.
   */
  async chatWithTools(
    messages: (Message | MessageWithContent)[],
    options?: ChatOptionsWithTools,
  ): Promise<ChatResponseWithTools> {
    const openaiMessages = this.convertMessagesWithToolsToOpenAIFormat(messages);

    // Convert tool definitions
    const tools = options?.tools?.map(this.convertToolDefinition.bind(this));

    // Build request body — Azure ignores the model field
    const body: Record<string, unknown> = {
      messages: openaiMessages,
      max_tokens: options?.maxTokens ?? 4096,
      temperature: options?.temperature ?? 0.7,
      ...(options?.stopSequences && { stop: options.stopSequences }),
    };

    // Add tools if provided
    if (tools && tools.length > 0) {
      body.tools = tools;

      if (options?.tool_choice) {
        body.tool_choice = this.convertToolChoice(options.tool_choice);
      }
    }

    const headers = this.buildHeaders();

    try {
      const { response } = await resilientFetch({
        url: this.buildUrl(),
        init: {
          method: 'POST',
          headers,
          body: JSON.stringify(body),
        },
        providerName: this.name,
        networkConfig: this.networkConfig,
        onRetry: (attempt, delay, error) => {
          logger.warn('Azure OpenAI retry attempt', {
            attempt,
            delayMs: delay,
            error: error.message,
          });
        },
      });

      if (!response.ok) {
        const error = await response.text();
        throw this.handleError(response.status, error);
      }

      const data = (await response.json()) as OpenAIChatCompletion;
      const result = this.parseResponseWithTools(data);
      result.rateLimitInfo = this.extractRateLimitInfo(response);
      return result;
    } catch (error) {
      if (error instanceof ProviderError) throw error;
      throw new ProviderError(
        `Azure OpenAI request failed: ${(error as Error).message}`,
        this.name,
        'NETWORK_ERROR',
        error as Error,
      );
    }
  }

  // ===========================================================================
  // MESSAGE CONVERSION
  // ===========================================================================

  /**
   * Convert basic messages to OpenAI format.
   */
  private convertMessagesToOpenAIFormat(
    messages: (Message | MessageWithContent)[],
  ): OpenAIMessage[] {
    return messages.map((m) => ({
      role: m.role as OpenAIMessage['role'],
      content:
        typeof m.content === 'string'
          ? m.content
          : m.content.map((c) => (c.type === 'text' ? c.text : '')).join(''),
    }));
  }

  /**
   * Convert messages with potential tool calls to OpenAI format.
   */
  private convertMessagesWithToolsToOpenAIFormat(
    messages: (Message | MessageWithContent)[],
  ): OpenAIMessage[] {
    const result: OpenAIMessage[] = [];

    for (const msg of messages) {
      // Handle tool result messages
      if ('tool_call_id' in msg && msg.role === 'tool') {
        result.push({
          role: 'tool',
          content:
            typeof msg.content === 'string'
              ? msg.content
              : msg.content?.map((c) => (c.type === 'text' ? c.text : '')).join('') || '',
          tool_call_id: msg.tool_call_id,
          name: msg.name,
        });
        continue;
      }

      // Handle assistant messages with tool calls
      if ('tool_calls' in msg && msg.tool_calls && msg.tool_calls.length > 0) {
        const content =
          typeof msg.content === 'string'
            ? msg.content
            : msg.content?.map((c) => (c.type === 'text' ? c.text : '')).join('') || null;

        result.push({
          role: 'assistant',
          content,
          tool_calls: msg.tool_calls.map((tc) => ({
            id: tc.id,
            type: 'function' as const,
            function: {
              name: tc.function.name,
              arguments: tc.function.arguments,
            },
          })),
        });
        continue;
      }

      // Regular message
      const content =
        typeof msg.content === 'string'
          ? msg.content
          : msg.content?.map((c) => (c.type === 'text' ? c.text : '')).join('') || '';

      result.push({
        role: msg.role as OpenAIMessage['role'],
        content,
      });
    }

    return result;
  }

  // ===========================================================================
  // TOOL CONVERSION
  // ===========================================================================

  /**
   * Convert tool definition to OpenAI format.
   */
  private convertToolDefinition(tool: ToolDefinitionSchema): OpenAITool {
    return {
      type: 'function',
      function: {
        name: tool.function.name,
        description: tool.function.description,
        parameters: tool.function.parameters,
        strict: tool.function.strict,
      },
    };
  }

  /**
   * Convert tool_choice to OpenAI format.
   */
  private convertToolChoice(
    choice: ChatOptionsWithTools['tool_choice'],
  ): 'auto' | 'required' | 'none' | { type: 'function'; function: { name: string } } {
    if (choice === 'auto') return 'auto';
    if (choice === 'required') return 'required';
    if (choice === 'none') return 'none';
    if (typeof choice === 'object' && choice.function?.name) {
      return { type: 'function', function: { name: choice.function.name } };
    }
    return 'auto';
  }

  // ===========================================================================
  // RESPONSE PARSING
  // ===========================================================================

  /**
   * Parse basic response without tools.
   */
  private parseResponse(data: OpenAIChatCompletion): ChatResponse {
    const choice = data.choices[0];

    return {
      content: choice.message.content || '',
      stopReason: this.mapStopReason(choice.finish_reason),
      usage: {
        inputTokens: data.usage.prompt_tokens,
        outputTokens: data.usage.completion_tokens,
      },
    };
  }

  /**
   * Parse response that may include tool calls.
   */
  private parseResponseWithTools(data: OpenAIChatCompletion): ChatResponseWithTools {
    const choice = data.choices[0];

    const toolCalls: ToolCallResponse[] | undefined = choice.message.tool_calls?.map((tc) => ({
      id: tc.id,
      type: 'function' as const,
      function: {
        name: tc.function.name,
        arguments: tc.function.arguments,
      },
    }));

    return {
      content: choice.message.content || '',
      stopReason: this.mapStopReason(choice.finish_reason),
      usage: {
        inputTokens: data.usage.prompt_tokens,
        outputTokens: data.usage.completion_tokens,
      },
      toolCalls: toolCalls && toolCalls.length > 0 ? toolCalls : undefined,
    };
  }

  // ===========================================================================
  // UTILITIES
  // ===========================================================================

  /**
   * Extract rate limit info from response headers.
   * Azure OpenAI returns x-ratelimit-* headers similar to OpenAI.
   */
  private extractRateLimitInfo(response: Response): ChatResponse['rateLimitInfo'] {
    const remaining = response.headers.get('x-ratelimit-remaining-requests');
    const remainingTokens = response.headers.get('x-ratelimit-remaining-tokens');
    const reset = response.headers.get('x-ratelimit-reset-requests');

    if (!remaining && !remainingTokens && !reset) return undefined;

    // Parse reset time (values like "6m0s" or "2ms")
    let resetSeconds: number | undefined;
    if (reset) {
      const match = reset.match(/(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?(?:(\d+)ms)?/);
      if (match) {
        const h = parseInt(match[1] || '0', 10);
        const m = parseInt(match[2] || '0', 10);
        const s = parseInt(match[3] || '0', 10);
        resetSeconds = h * 3600 + m * 60 + s;
      }
    }

    return {
      remainingRequests: remaining ? parseInt(remaining, 10) : undefined,
      remainingTokens: remainingTokens ? parseInt(remainingTokens, 10) : undefined,
      resetSeconds,
    };
  }

  /**
   * Build request headers.
   * Azure uses api-key header instead of Authorization: Bearer.
   */
  private buildHeaders(): Record<string, string> {
    return {
      'Content-Type': 'application/json',
      'api-key': this.apiKey,
    };
  }

  /**
   * Handle API errors.
   */
  private handleError(status: number, body: string): ProviderError {
    let code: ProviderError['code'] = 'UNKNOWN';

    if (status === 401) code = 'AUTHENTICATION_FAILED';
    else if (status === 429) code = 'RATE_LIMITED';
    else if (status === 400) {
      if (body.includes('context_length') || body.includes('maximum context length')) {
        code = 'CONTEXT_LENGTH_EXCEEDED';
      } else {
        code = 'INVALID_REQUEST';
      }
    } else if (status === 404) code = 'INVALID_REQUEST';
    else if (status >= 500) code = 'SERVER_ERROR';

    return new ProviderError(`Azure OpenAI API error (${status}): ${body}`, this.name, code);
  }

  /**
   * Map OpenAI stop reasons to our format.
   */
  private mapStopReason(reason: string): ChatResponse['stopReason'] {
    switch (reason) {
      case 'stop':
        return 'end_turn';
      case 'length':
        return 'max_tokens';
      case 'tool_calls':
        return 'end_turn';
      case 'content_filter':
        return 'end_turn';
      default:
        return 'end_turn';
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
