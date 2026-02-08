/**
 * Anthropic Claude Provider Adapter
 *
 * Adapts the Anthropic SDK to our LLMProvider interface.
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
  AnthropicConfig
} from '../types.js';
import { ProviderError } from '../types.js';
import { registerProvider, hasEnv, requireEnv } from '../provider.js';
import { resilientFetch, type NetworkConfig } from '../resilient-fetch.js';

// =============================================================================
// ANTHROPIC API TYPES
// =============================================================================

/** Anthropic tool definition format */
interface AnthropicTool {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}

/** Anthropic content block types */
type AnthropicContentBlock =
  | { type: 'text'; text: string }
  | { type: 'tool_use'; id: string; name: string; input: Record<string, unknown> }
  | { type: 'tool_result'; tool_use_id: string; content: string };

// =============================================================================
// ANTHROPIC PROVIDER
// =============================================================================

export class AnthropicProvider implements LLMProvider, LLMProviderWithTools {
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

  async chat(messages: (Message | MessageWithContent)[], options?: ChatOptions): Promise<ChatResponse> {
    const model = options?.model ?? this.model;

    // Separate system message from conversation
    const systemMessage = messages.find(m => m.role === 'system');
    const conversationMessages = messages
      .filter(m => m.role !== 'system')
      .map(m => ({
        role: m.role as 'user' | 'assistant',
        content: typeof m.content === 'string' ? m.content : m.content.map(c => c.text).join(''),
      }));

    // Build system content — supports structured blocks with cache_control for prompt caching
    let systemContent: string | Array<{ type: 'text'; text: string; cache_control?: { type: 'ephemeral' } }> | undefined;
    if (systemMessage) {
      if (typeof systemMessage.content !== 'string' && Array.isArray(systemMessage.content)) {
        // Structured content with cache_control markers
        systemContent = systemMessage.content;
      } else {
        systemContent = typeof systemMessage.content === 'string'
          ? systemMessage.content
          : (systemMessage.content as Array<{ text: string }>).map(c => c.text).join('');
      }
    }

    // Build request body
    const body = {
      model,
      max_tokens: options?.maxTokens ?? 4096,
      temperature: options?.temperature ?? 0.7,
      system: systemContent,
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
            'anthropic-beta': 'prompt-caching-2024-07-31',
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
        usage: {
          input_tokens: number;
          output_tokens: number;
          cache_creation_input_tokens?: number;
          cache_read_input_tokens?: number;
        };
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
          cacheReadTokens: data.usage.cache_read_input_tokens,
          cacheWriteTokens: data.usage.cache_creation_input_tokens,
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

  /**
   * Send a chat request with tool definitions.
   * Anthropic's native tool use format differs from OpenAI's:
   * - Tools use `input_schema` instead of `parameters`
   * - Tool calls are in content blocks with type `tool_use`
   * - Tool results are sent as `tool_result` content blocks
   */
  async chatWithTools(
    messages: (Message | MessageWithContent)[],
    options?: ChatOptionsWithTools
  ): Promise<ChatResponseWithTools> {
    const model = options?.model ?? this.model;

    // Separate system message from conversation
    const systemMessage = messages.find(m => m.role === 'system');

    // Convert messages to Anthropic format
    const anthropicMessages = this.convertMessagesToAnthropicFormat(
      messages.filter(m => m.role !== 'system')
    );

    // Convert tool definitions from OpenAI format to Anthropic format
    const anthropicTools = options?.tools?.map(this.convertToolToAnthropicFormat);

    // Build system content — supports structured blocks with cache_control for prompt caching
    let systemContent: string | Array<{ type: 'text'; text: string; cache_control?: { type: 'ephemeral' } }> | undefined;
    if (systemMessage) {
      if (typeof systemMessage.content !== 'string' && Array.isArray(systemMessage.content)) {
        // Structured content with cache_control markers - pass through directly
        systemContent = systemMessage.content;
      } else {
        systemContent = typeof systemMessage.content === 'string'
          ? systemMessage.content
          : (systemMessage.content as Array<{ text: string }>).map(c => c.text).join('');
      }
    }

    // Build request body
    const body: Record<string, unknown> = {
      model,
      max_tokens: options?.maxTokens ?? 4096,
      temperature: options?.temperature ?? 0.7,
      system: systemContent,
      messages: anthropicMessages,
      ...(options?.stopSequences && { stop_sequences: options.stopSequences }),
    };

    // Add tools if provided
    if (anthropicTools && anthropicTools.length > 0) {
      body.tools = anthropicTools;
      // Map tool_choice to Anthropic format
      if (options?.tool_choice) {
        body.tool_choice = this.convertToolChoice(options.tool_choice);
      }
    }

    try {
      const { response } = await resilientFetch({
        url: `${this.baseUrl}/v1/messages`,
        init: {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'x-api-key': this.apiKey,
            'anthropic-version': '2023-06-01',
            'anthropic-beta': 'prompt-caching-2024-07-31',
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
        id: string;
        content: AnthropicContentBlock[];
        stop_reason: string;
        usage: {
          input_tokens: number;
          output_tokens: number;
          cache_creation_input_tokens?: number;
          cache_read_input_tokens?: number;
        };
      };

      // Extract text content and tool calls from content blocks
      const textContent = data.content
        .filter((block): block is { type: 'text'; text: string } => block.type === 'text')
        .map(block => block.text)
        .join('');

      const toolUseBlocks = data.content.filter(
        (block): block is { type: 'tool_use'; id: string; name: string; input: Record<string, unknown> } =>
          block.type === 'tool_use'
      );

      // Convert Anthropic tool_use blocks to our ToolCallResponse format
      const toolCalls: ToolCallResponse[] | undefined = toolUseBlocks.length > 0
        ? toolUseBlocks.map(block => ({
            id: block.id,
            type: 'function' as const,
            function: {
              name: block.name,
              // Anthropic returns input as object, we need to stringify it
              arguments: JSON.stringify(block.input),
            },
          }))
        : undefined;

      return {
        content: textContent,
        stopReason: this.mapStopReason(data.stop_reason),
        usage: {
          inputTokens: data.usage.input_tokens,
          outputTokens: data.usage.output_tokens,
          cacheReadTokens: data.usage.cache_read_input_tokens,
          cacheWriteTokens: data.usage.cache_creation_input_tokens,
        },
        toolCalls,
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

  /**
   * Convert messages to Anthropic's expected format.
   * Handles tool result messages specially.
   */
  private convertMessagesToAnthropicFormat(
    messages: (Message | MessageWithContent)[]
  ): Array<{ role: string; content: string | AnthropicContentBlock[] }> {
    const result: Array<{ role: string; content: string | AnthropicContentBlock[] }> = [];

    for (const msg of messages) {
      // Handle tool result messages
      if ('tool_call_id' in msg && msg.role === 'tool') {
        // Anthropic expects tool results as user messages with tool_result content blocks
        const toolResultBlock: AnthropicContentBlock = {
          type: 'tool_result',
          tool_use_id: msg.tool_call_id!,
          content: typeof msg.content === 'string' ? msg.content : msg.content.map(c => c.text).join(''),
        };

        // Check if the last message is already a user message we can add to
        const lastMsg = result[result.length - 1];
        if (lastMsg && lastMsg.role === 'user' && Array.isArray(lastMsg.content)) {
          lastMsg.content.push(toolResultBlock);
        } else {
          result.push({
            role: 'user',
            content: [toolResultBlock],
          });
        }
        continue;
      }

      // Handle assistant messages with tool calls
      if ('tool_calls' in msg && msg.tool_calls && msg.tool_calls.length > 0) {
        const contentBlocks: AnthropicContentBlock[] = [];

        // Add text content if present
        const textContent = typeof msg.content === 'string'
          ? msg.content
          : msg.content?.map(c => c.text).join('') || '';
        if (textContent) {
          contentBlocks.push({ type: 'text', text: textContent });
        }

        // Convert tool calls to tool_use blocks
        for (const tc of msg.tool_calls) {
          contentBlocks.push({
            type: 'tool_use',
            id: tc.id,
            name: tc.function.name,
            input: JSON.parse(tc.function.arguments),
          });
        }

        result.push({
          role: 'assistant',
          content: contentBlocks,
        });
        continue;
      }

      // Regular user/assistant message
      const content = typeof msg.content === 'string'
        ? msg.content
        : msg.content?.map(c => c.text).join('') || '';

      result.push({
        role: msg.role as 'user' | 'assistant',
        content,
      });
    }

    return result;
  }

  /**
   * Convert OpenAI-format tool definition to Anthropic format.
   */
  private convertToolToAnthropicFormat(tool: ToolDefinitionSchema): AnthropicTool {
    return {
      name: tool.function.name,
      description: tool.function.description,
      input_schema: tool.function.parameters,
    };
  }

  /**
   * Convert tool_choice from OpenAI format to Anthropic format.
   */
  private convertToolChoice(
    choice: ChatOptionsWithTools['tool_choice']
  ): { type: 'auto' | 'any' | 'tool'; name?: string } {
    if (choice === 'auto') {
      return { type: 'auto' };
    }
    if (choice === 'required') {
      return { type: 'any' }; // Anthropic's equivalent of "must use a tool"
    }
    if (choice === 'none') {
      return { type: 'auto' }; // No direct equivalent, use auto
    }
    if (typeof choice === 'object' && choice.function?.name) {
      return { type: 'tool', name: choice.function.name };
    }
    return { type: 'auto' };
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
