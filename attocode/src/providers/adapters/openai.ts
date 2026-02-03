/**
 * OpenAI Provider Adapter
 *
 * Adapts the OpenAI API to our LLMProvider interface.
 * Supports native tool use via the chatWithTools method.
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
  OpenAIConfig,
} from '../types.js';
import { ProviderError } from '../types.js';
import { registerProvider, hasEnv, requireEnv } from '../provider.js';
import { resilientFetch, type NetworkConfig } from '../resilient-fetch.js';

// =============================================================================
// OPENAI API TYPES
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
// OPENAI PROVIDER
// =============================================================================

export class OpenAIProvider implements LLMProvider, LLMProviderWithTools {
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

  /**
   * Basic chat without tool support.
   */
  async chat(messages: Message[], options?: ChatOptions): Promise<ChatResponse> {
    const model = options?.model ?? this.model;

    // Convert to OpenAI message format
    const openaiMessages = this.convertMessagesToOpenAIFormat(messages);

    // Build request body
    const body = {
      model,
      messages: openaiMessages,
      max_tokens: options?.maxTokens ?? 4096,
      temperature: options?.temperature ?? 0.7,
      ...(options?.stopSequences && { stop: options.stopSequences }),
    };

    const headers = this.buildHeaders();

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

      const data = await response.json() as OpenAIChatCompletion;
      return this.parseResponse(data);
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

  /**
   * Chat with native tool use support.
   * OpenAI's tool format is our standard format, so minimal conversion needed.
   */
  async chatWithTools(
    messages: (Message | MessageWithContent)[],
    options?: ChatOptionsWithTools
  ): Promise<ChatResponseWithTools> {
    const model = options?.model ?? this.model;

    // Convert messages to OpenAI format
    const openaiMessages = this.convertMessagesWithToolsToOpenAIFormat(messages);

    // Convert tool definitions (already in OpenAI format, just ensure structure)
    const tools = options?.tools?.map(this.convertToolDefinition.bind(this));

    // Build request body
    const body: Record<string, unknown> = {
      model,
      messages: openaiMessages,
      max_tokens: options?.maxTokens ?? 4096,
      temperature: options?.temperature ?? 0.7,
      ...(options?.stopSequences && { stop: options.stopSequences }),
    };

    // Add tools if provided
    if (tools && tools.length > 0) {
      body.tools = tools;

      // Convert tool_choice
      if (options?.tool_choice) {
        body.tool_choice = this.convertToolChoice(options.tool_choice);
      }
    }

    const headers = this.buildHeaders();

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

      const data = await response.json() as OpenAIChatCompletion;
      return this.parseResponseWithTools(data);
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

  // ===========================================================================
  // MESSAGE CONVERSION
  // ===========================================================================

  /**
   * Convert basic messages to OpenAI format.
   */
  private convertMessagesToOpenAIFormat(messages: Message[]): OpenAIMessage[] {
    return messages.map(m => ({
      role: m.role as OpenAIMessage['role'],
      content: m.content,
    }));
  }

  /**
   * Convert messages with potential tool calls to OpenAI format.
   */
  private convertMessagesWithToolsToOpenAIFormat(
    messages: (Message | MessageWithContent)[]
  ): OpenAIMessage[] {
    const result: OpenAIMessage[] = [];

    for (const msg of messages) {
      // Handle tool result messages
      if ('tool_call_id' in msg && msg.role === 'tool') {
        result.push({
          role: 'tool',
          content: typeof msg.content === 'string'
            ? msg.content
            : msg.content?.map(c => c.text).join('') || '',
          tool_call_id: msg.tool_call_id,
          name: msg.name,
        });
        continue;
      }

      // Handle assistant messages with tool calls
      if ('tool_calls' in msg && msg.tool_calls && msg.tool_calls.length > 0) {
        const content = typeof msg.content === 'string'
          ? msg.content
          : msg.content?.map(c => c.text).join('') || null;

        result.push({
          role: 'assistant',
          content,
          tool_calls: msg.tool_calls.map(tc => ({
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
      const content = typeof msg.content === 'string'
        ? msg.content
        : msg.content?.map(c => c.text).join('') || '';

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
   * Our standard format is already OpenAI-compatible.
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
    choice: ChatOptionsWithTools['tool_choice']
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

    // Convert OpenAI tool_calls to our format
    const toolCalls: ToolCallResponse[] | undefined = choice.message.tool_calls?.map(tc => ({
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
   * Build request headers.
   */
  private buildHeaders(): Record<string, string> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${this.apiKey}`,
    };

    if (this.organization) {
      headers['OpenAI-Organization'] = this.organization;
    }

    return headers;
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
    }
    else if (status === 404) code = 'INVALID_REQUEST';
    else if (status >= 500) code = 'SERVER_ERROR';

    return new ProviderError(
      `OpenAI API error (${status}): ${body}`,
      this.name,
      code
    );
  }

  /**
   * Map OpenAI stop reasons to our format.
   */
  private mapStopReason(reason: string): ChatResponse['stopReason'] {
    switch (reason) {
      case 'stop': return 'end_turn';
      case 'length': return 'max_tokens';
      case 'tool_calls': return 'end_turn'; // Tool calls treated as end_turn
      case 'content_filter': return 'end_turn';
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
