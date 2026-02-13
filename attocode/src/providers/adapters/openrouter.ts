/**
 * OpenRouter Provider Adapter
 *
 * Adapts the OpenRouter API (OpenAI-compatible) to our LLMProvider interface.
 * OpenRouter provides access to 100+ models from various providers through
 * a single API key.
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
  OpenRouterConfig
} from '../types.js';
import { ProviderError } from '../types.js';
import { registerProvider, hasEnv, requireEnv } from '../provider.js';
import { resilientFetch, type NetworkConfig } from '../resilient-fetch.js';
import { logger } from '../../integrations/logger.js';

// =============================================================================
// DEFAULT MODEL SELECTION
// =============================================================================

/**
 * TODO: Choose your default model for OpenRouter.
 *
 * This is a meaningful design choice based on your priorities:
 *
 * Cost-optimized options:
 *   - 'meta-llama/llama-3.1-8b-instruct' - Very cheap, good for simple tasks
 *   - 'mistralai/mistral-7b-instruct' - Budget-friendly, solid performance
 *
 * Balanced options:
 *   - 'anthropic/claude-sonnet-4' - Good balance of quality and cost
 *   - 'openai/gpt-4o-mini' - Fast, cheap, capable
 *
 * Quality-optimized options:
 *   - 'anthropic/claude-opus-4' - Highest Claude quality
 *   - 'openai/gpt-4-turbo' - High quality, good for complex tasks
 *
 * Consider: What's your primary use case? Development/testing (use cheaper),
 * production (use quality), or experimentation (use balanced)?
 */
function getDefaultModel(): string {
  // Using Gemini Flash - fast, cheap, and good tool use support
  // Change to 'anthropic/claude-sonnet-4' for higher quality
  return 'google/gemini-2.0-flash-001';
}

// =============================================================================
// OPENROUTER PROVIDER
// =============================================================================

export class OpenRouterProvider implements LLMProvider, LLMProviderWithTools {
  readonly name = 'openrouter';
  readonly defaultModel: string;

  private apiKey: string;
  private model: string;
  private baseUrl = 'https://openrouter.ai/api/v1';
  private siteUrl?: string;
  private siteName?: string;
  private networkConfig: NetworkConfig;

  constructor(config?: OpenRouterConfig) {
    this.apiKey = config?.apiKey ?? requireEnv('OPENROUTER_API_KEY');
    this.defaultModel = getDefaultModel();
    this.model = config?.model ?? process.env.OPENROUTER_MODEL ?? this.defaultModel;
    this.siteUrl = config?.siteUrl ?? process.env.OPENROUTER_SITE_URL;
    this.siteName = config?.siteName ?? process.env.OPENROUTER_SITE_NAME;
    this.networkConfig = {
      timeout: 120000,  // 2 minutes
      maxRetries: 3,
      baseRetryDelay: 1000,
    };
  }

  isConfigured(): boolean {
    return hasEnv('OPENROUTER_API_KEY');
  }

  async chat(messages: (Message | MessageWithContent)[], options?: ChatOptions): Promise<ChatResponse> {
    const model = options?.model ?? this.model;

    // OpenRouter uses OpenAI-compatible message format
    // Handles both string content and structured content with cache_control markers
    const openRouterMessages = messages.map(m => {
      if (typeof m.content !== 'string') {
        return { role: m.role, content: m.content }; // Pass structured content for caching
      }
      return { role: m.role, content: m.content };
    });

    // Build request body (OpenAI-compatible)
    const body = {
      model,
      messages: openRouterMessages,
      max_tokens: options?.maxTokens ?? 16384,
      temperature: options?.temperature ?? 0.7,
      ...(options?.stopSequences && { stop: options.stopSequences }),
      // Enable usage accounting to get actual cost from OpenRouter
      usage: { include: true },
    };

    // OpenRouter requires specific headers for analytics
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${this.apiKey}`,
    };

    // Optional headers for OpenRouter analytics/rate limits
    if (this.siteUrl) {
      headers['HTTP-Referer'] = this.siteUrl;
    }
    if (this.siteName) {
      headers['X-Title'] = this.siteName;
    }

    try {
      const { response } = await resilientFetch({
        url: `${this.baseUrl}/chat/completions`,
        init: {
          method: 'POST',
          headers,
          body: JSON.stringify(body),
        },
        providerName: this.name,
        networkConfig: this.networkConfig,
        onRetry: (attempt, delay, error) => {
          logger.warn('OpenRouter retry attempt', { attempt, delay, error: error.message });
        },
      });

      if (!response.ok) {
        const error = await response.text();
        throw this.handleError(response.status, error);
      }

      const data = await response.json() as {
        id: string;
        choices: Array<{
          message: {
            content: string | null;
            reasoning?: string;
            reasoning_content?: string;
          };
          finish_reason: string;
        }>;
        usage: {
          prompt_tokens: number;
          completion_tokens: number;
          cost?: number;
          prompt_tokens_details?: {
            cached_tokens?: number;
            cache_write_tokens?: number;
          };
        };
      };

      const choice = data.choices[0];

      // Get cost: try inline first, then query generation endpoint
      let cost = data.usage.cost;
      if (cost === undefined && data.id) {
        cost = await this.queryGenerationCost(data.id);
      }

      // Extract reasoning/thinking content (used by DeepSeek-R1, GLM-4, QwQ, etc.)
      const thinking = choice.message.reasoning
        ?? choice.message.reasoning_content
        ?? undefined;

      return {
        content: choice.message.content ?? '',
        thinking: thinking || undefined,
        stopReason: this.mapStopReason(choice.finish_reason),
        usage: {
          inputTokens: data.usage.prompt_tokens,
          outputTokens: data.usage.completion_tokens,
          cachedTokens: data.usage.prompt_tokens_details?.cached_tokens,
          cacheWriteTokens: data.usage.prompt_tokens_details?.cache_write_tokens,
          cost,
        },
        rateLimitInfo: this.extractRateLimitInfo(response),
      };
    } catch (error) {
      if (error instanceof ProviderError) throw error;
      throw new ProviderError(
        `OpenRouter request failed: ${(error as Error).message}`,
        this.name,
        'NETWORK_ERROR',
        error as Error
      );
    }
  }

  /**
   * ═══════════════════════════════════════════════════════════════════════════
   * NATIVE TOOL USE: Why This Matters
   * ═══════════════════════════════════════════════════════════════════════════
   *
   * Before (Lesson 1): Parse JSON from text response
   *   LLM returns: "I'll use the read_file tool:\n```json\n{\"path\": \"x.ts\"}\n```"
   *   We parse: Extract JSON with regex → JSON.parse → Hope it's valid
   *   Problems: Hallucinated formats, partial JSON, extra text
   *
   * After (Native tool use):
   *   LLM returns: { tool_calls: [{ function: { name: "read_file", arguments: "{\"path\":\"x.ts\"}" }}] }
   *   We use: Structured response → Always valid JSON → Type-safe
   *   Benefits: No parsing errors, proper function calling semantics
   *
   * This method enables native tool use through OpenRouter's OpenAI-compatible API.
   * ═══════════════════════════════════════════════════════════════════════════
   */
  async chatWithTools(
    messages: (Message | MessageWithContent)[],
    options?: ChatOptionsWithTools
  ): Promise<ChatResponseWithTools> {
    const model = options?.model ?? this.model;

    // Convert messages to OpenRouter format
    // This handles both simple string content and structured content with cache_control
    const openRouterMessages = messages.map(m => {
      // Handle tool role messages (results from tool execution)
      if ('tool_call_id' in m && m.role === 'tool') {
        const toolMsg: Record<string, unknown> = {
          role: 'tool' as const,
          content: typeof m.content === 'string' ? m.content : m.content.map(c => c.text).join(''),
          tool_call_id: m.tool_call_id,
        };
        // Include name if present (required for Gemini)
        if ('name' in m && m.name) {
          toolMsg.name = m.name;
        }
        return toolMsg;
      }

      // Handle assistant messages with tool calls
      if ('tool_calls' in m && m.tool_calls) {
        return {
          role: 'assistant' as const,
          content: typeof m.content === 'string' ? m.content : (m.content.length > 0 ? m.content.map(c => c.text).join('') : null),
          tool_calls: m.tool_calls,
        };
      }

      // Handle structured content (with potential cache_control)
      if (typeof m.content !== 'string') {
        return {
          role: m.role,
          content: m.content, // Pass through structured content for caching
        };
      }

      // Simple string content
      return {
        role: m.role,
        content: m.content,
      };
    });

    // Build request body with tool definitions
    const body: Record<string, unknown> = {
      model,
      messages: openRouterMessages,
      max_tokens: options?.maxTokens ?? 16384,
      temperature: options?.temperature ?? 0.7,
      ...(options?.stopSequences && { stop: options.stopSequences }),
      // Enable usage accounting to get cached_tokens in response
      usage: { include: true },
    };

    // Add tool definitions if provided
    if (options?.tools && options.tools.length > 0) {
      body.tools = options.tools;
      body.tool_choice = options?.tool_choice ?? 'auto';
    }

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${this.apiKey}`,
    };

    if (this.siteUrl) {
      headers['HTTP-Referer'] = this.siteUrl;
    }
    if (this.siteName) {
      headers['X-Title'] = this.siteName;
    }

    try {
      const { response } = await resilientFetch({
        url: `${this.baseUrl}/chat/completions`,
        init: {
          method: 'POST',
          headers,
          body: JSON.stringify(body),
        },
        providerName: this.name,
        networkConfig: this.networkConfig,
        onRetry: (attempt, delay, error) => {
          logger.warn('OpenRouter retry attempt', { attempt, delay, error: error.message });
        },
      });

      if (!response.ok) {
        const error = await response.text();
        throw this.handleError(response.status, error);
      }

      const data = await response.json() as {
        id: string;  // Generation ID for querying cost
        choices: Array<{
          message: {
            content: string | null;
            tool_calls?: Array<{
              id: string;
              type: 'function';
              function: {
                name: string;
                arguments: string;
              };
            }>;
            reasoning?: string;
            reasoning_content?: string;
          };
          finish_reason: string;
        }>;
        usage: {
          prompt_tokens: number;
          completion_tokens: number;
          // Actual cost from OpenRouter (when usage.include is true)
          cost?: number;
          // Cache info (when using Anthropic models via OpenRouter)
          prompt_tokens_details?: {
            cached_tokens?: number;
            cache_write_tokens?: number;
          };
        };
      };

      const choice = data.choices[0];

      // Get cost: try inline first, then query generation endpoint
      let cost = data.usage.cost;
      if (cost === undefined && data.id) {
        cost = await this.queryGenerationCost(data.id);
      }

      if (process.env.DEBUG_COST) {
        logger.debug('OpenRouter response details', { responseId: data.id, usage: data.usage, cost });
      }

      // Extract tool calls if present
      const toolCalls: ToolCallResponse[] | undefined = choice.message.tool_calls?.map(tc => ({
        id: tc.id,
        type: tc.type,
        function: {
          name: tc.function.name,
          arguments: tc.function.arguments,
        },
      }));

      // Extract reasoning/thinking content (used by DeepSeek-R1, GLM-4, QwQ, etc.)
      const thinking = choice.message.reasoning
        ?? choice.message.reasoning_content
        ?? undefined;

      return {
        content: choice.message.content ?? '',
        thinking: thinking || undefined,
        stopReason: this.mapStopReason(choice.finish_reason),
        usage: {
          inputTokens: data.usage.prompt_tokens,
          outputTokens: data.usage.completion_tokens,
          cachedTokens: data.usage.prompt_tokens_details?.cached_tokens,
          cacheWriteTokens: data.usage.prompt_tokens_details?.cache_write_tokens,
          cost,
        },
        toolCalls,
        rateLimitInfo: this.extractRateLimitInfo(response),
      };
    } catch (error) {
      if (error instanceof ProviderError) throw error;
      throw new ProviderError(
        `OpenRouter request failed: ${(error as Error).message}`,
        this.name,
        'NETWORK_ERROR',
        error as Error
      );
    }
  }

  /**
   * Query the generation endpoint to get actual cost with retry.
   * OpenRouter's generation data may not be immediately available after completion,
   * so we retry with exponential backoff.
   */
  private async queryGenerationCost(generationId: string): Promise<number | undefined> {
    const maxRetries = 3;
    const delays = [100, 300, 600]; // ms - exponential backoff

    for (let attempt = 0; attempt < maxRetries; attempt++) {
      try {
        // Wait before querying (generation data needs time to propagate)
        await new Promise(resolve => setTimeout(resolve, delays[attempt]));

        const response = await fetch(`${this.baseUrl}/generation?id=${generationId}`, {
          method: 'GET',
          headers: {
            'Authorization': `Bearer ${this.apiKey}`,
          },
        });

        if (!response.ok) {
          if (process.env.DEBUG_COST) {
            logger.debug('OpenRouter generation query failed', { attempt: attempt + 1, status: response.status });
          }
          continue; // Retry on non-OK response
        }

        const data = await response.json() as {
          data?: {
            total_cost?: number;
            usage?: number;
          };
        };

        // OpenRouter returns cost in data.total_cost or data.usage
        const cost = data.data?.total_cost ?? data.data?.usage;

        if (process.env.DEBUG_COST) {
          logger.debug('OpenRouter generation cost query result', { attempt: attempt + 1, data: data.data, cost });
        }

        // If we got a valid cost, return it
        if (cost !== undefined && cost > 0) {
          return cost;
        }

        // Cost not ready yet, continue to retry
        if (process.env.DEBUG_COST) {
          logger.debug('OpenRouter cost not ready', { attempt: attempt + 1, maxRetries });
        }
      } catch (err) {
        if (process.env.DEBUG_COST) {
          logger.error('OpenRouter generation query error', { attempt: attempt + 1, error: String(err) });
        }
      }
    }

    if (process.env.DEBUG_COST) {
      logger.warn('OpenRouter failed to get cost after all retries', { generationId, maxRetries });
    }
    return undefined;
  }

  /**
   * Extract rate limit info from response headers.
   * OpenRouter returns X-RateLimit-* headers on every response.
   */
  private extractRateLimitInfo(response: Response): ChatResponse['rateLimitInfo'] {
    const remaining = response.headers.get('x-ratelimit-remaining');
    const remainingTokens = response.headers.get('x-ratelimit-remaining-tokens');
    const reset = response.headers.get('x-ratelimit-reset');

    if (!remaining && !remainingTokens && !reset) return undefined;

    return {
      remainingRequests: remaining ? parseInt(remaining, 10) : undefined,
      remainingTokens: remainingTokens ? parseInt(remainingTokens, 10) : undefined,
      resetSeconds: reset ? parseInt(reset, 10) : undefined,
    };
  }

  /**
   * Pre-flight check: query OpenRouter /api/v1/key to get account limits.
   * Returns key info including rate limits and credits remaining.
   */
  static async checkKeyInfo(apiKey: string): Promise<{
    rateLimitPerMinute?: number;
    creditsRemaining?: number;
    isPaid?: boolean;
  }> {
    try {
      const response = await fetch('https://openrouter.ai/api/v1/key', {
        headers: { 'Authorization': `Bearer ${apiKey}` },
      });
      if (!response.ok) return {};
      const data = await response.json() as {
        data?: {
          rate_limit?: { requests: number; interval: string };
          limit?: number;
          usage?: number;
          is_free_tier?: boolean;
        };
      };
      return {
        rateLimitPerMinute: data.data?.rate_limit?.requests,
        creditsRemaining: data.data?.limit != null && data.data?.usage != null
          ? data.data.limit - data.data.usage
          : undefined,
        isPaid: data.data?.is_free_tier === false,
      };
    } catch {
      return {};
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
      `OpenRouter API error (${status}): ${body}`,
      this.name,
      code
    );
  }

  private mapStopReason(reason: string): ChatResponse['stopReason'] {
    switch (reason) {
      case 'stop': return 'end_turn';
      case 'length': return 'max_tokens';
      case 'stop_sequence': return 'stop_sequence';
      case 'tool_calls': return 'end_turn'; // Tool calls are a form of completion
      default: return 'end_turn';
    }
  }
}

// =============================================================================
// REGISTRATION
// =============================================================================

registerProvider('openrouter', {
  priority: 0, // Highest priority - becomes default when configured
  detect: () => hasEnv('OPENROUTER_API_KEY'),
  create: async () => new OpenRouterProvider(),
});
