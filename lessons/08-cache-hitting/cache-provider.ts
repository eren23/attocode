/**
 * Lesson 08: Cache-Aware Provider Wrapper
 *
 * A provider wrapper that automatically applies cache markers to appropriate content.
 * This abstracts away the complexity of manual cache marker placement.
 */

import type {
  Message,
  MessageWithContent,
  LLMProvider,
  LLMProviderWithTools,
  ChatOptions,
  ChatOptionsWithTools,
  ChatResponse,
  ChatResponseWithTools,
  CacheableContent,
} from '../02-provider-abstraction/types.js';

import {
  text,
  estimateTokens,
  MIN_CACHEABLE_TOKENS,
  extractCacheStats,
  type CacheAwareUsage,
} from './cache-basics.js';

// =============================================================================
// CONFIGURATION
// =============================================================================

/**
 * Configuration for the cache-aware provider.
 */
export interface CacheProviderConfig {
  /**
   * Minimum tokens for a content block to be cached.
   * Default: 1000 (below this, overhead exceeds benefit)
   */
  minCacheableTokens?: number;

  /**
   * Always cache system messages regardless of size.
   * Default: true (system prompts are reused every turn)
   */
  alwaysCacheSystem?: boolean;

  /**
   * Always cache tool definitions.
   * Default: true (tools don't change during conversation)
   */
  alwaysCacheTools?: boolean;

  /**
   * Number of recent messages to NOT cache.
   * Default: 2 (last user message + last assistant response)
   */
  recentUncachedCount?: number;

  /**
   * Callback when cache statistics are available.
   */
  onCacheStats?: (stats: CacheStatistics) => void;
}

/**
 * Statistics about cache usage for a request.
 */
export interface CacheStatistics {
  /** Total input tokens */
  totalInputTokens: number;
  /** Tokens that were cached */
  cachedTokens: number;
  /** Cache hit rate (0-1) */
  hitRate: number;
  /** Estimated cost savings percentage */
  estimatedSavings: number;
  /** Cumulative statistics across all requests */
  cumulative: {
    requests: number;
    totalInputTokens: number;
    totalCachedTokens: number;
    averageHitRate: number;
    estimatedTotalSavings: number;
  };
}

// =============================================================================
// CACHE-AWARE PROVIDER
// =============================================================================

/**
 * A provider wrapper that automatically applies cache markers.
 *
 * This wraps any LLMProviderWithTools and:
 * 1. Automatically marks system prompts for caching
 * 2. Caches large content blocks (above threshold)
 * 3. Keeps recent messages uncached for flexibility
 * 4. Tracks cache hit statistics
 *
 * @example
 * ```typescript
 * const baseProvider = new OpenRouterProvider();
 * const cachedProvider = new CacheAwareProvider(baseProvider, {
 *   minCacheableTokens: 500,
 *   onCacheStats: (stats) => {
 *     console.log(`Cache hit rate: ${(stats.hitRate * 100).toFixed(1)}%`);
 *   },
 * });
 *
 * // Use exactly like the base provider - caching happens automatically
 * const response = await cachedProvider.chatWithTools(messages, options);
 * ```
 */
export class CacheAwareProvider implements LLMProviderWithTools {
  readonly name: string;
  readonly defaultModel: string;

  private config: Required<Omit<CacheProviderConfig, 'onCacheStats'>> & {
    onCacheStats?: (stats: CacheStatistics) => void;
  };

  // Cumulative statistics
  private totalRequests = 0;
  private totalInputTokens = 0;
  private totalCachedTokens = 0;

  constructor(
    private provider: LLMProviderWithTools,
    config: CacheProviderConfig = {}
  ) {
    this.name = `cached-${provider.name}`;
    this.defaultModel = provider.defaultModel;

    this.config = {
      minCacheableTokens: config.minCacheableTokens ?? MIN_CACHEABLE_TOKENS,
      alwaysCacheSystem: config.alwaysCacheSystem ?? true,
      alwaysCacheTools: config.alwaysCacheTools ?? true,
      recentUncachedCount: config.recentUncachedCount ?? 2,
      onCacheStats: config.onCacheStats,
    };
  }

  isConfigured(): boolean {
    return this.provider.isConfigured();
  }

  /**
   * Regular chat without tools.
   * Applies cache markers to appropriate content.
   */
  async chat(messages: Message[], options?: ChatOptions): Promise<ChatResponse> {
    const cachedMessages = this.applyCacheMarkers(messages);

    // The underlying provider needs to accept MessageWithContent
    // For providers that don't support structured content, fall back to string
    const response = await (this.provider as LLMProvider).chat(
      cachedMessages.map(m => ({
        role: m.role as 'user' | 'assistant' | 'system',
        content: this.contentToString(m.content),
      })),
      options
    );

    return response;
  }

  /**
   * Chat with tools.
   * Applies cache markers and tracks statistics.
   */
  async chatWithTools(
    messages: (Message | MessageWithContent)[],
    options?: ChatOptionsWithTools
  ): Promise<ChatResponseWithTools> {
    // Apply cache markers
    const cachedMessages = this.applyCacheMarkers(messages);

    // Call underlying provider
    const response = await this.provider.chatWithTools(cachedMessages, options);

    // Track and report statistics if usage is available
    if (response.usage) {
      const cacheAwareUsage: CacheAwareUsage = {
        inputTokens: response.usage.inputTokens,
        outputTokens: response.usage.outputTokens,
        cachedTokens: response.usage.cachedTokens,
      };
      this.updateStatistics(cacheAwareUsage);
    }

    return response;
  }

  /**
   * Get cumulative cache statistics.
   */
  getStatistics(): CacheStatistics['cumulative'] {
    return {
      requests: this.totalRequests,
      totalInputTokens: this.totalInputTokens,
      totalCachedTokens: this.totalCachedTokens,
      averageHitRate:
        this.totalInputTokens > 0
          ? this.totalCachedTokens / this.totalInputTokens
          : 0,
      estimatedTotalSavings:
        this.totalInputTokens > 0
          ? (this.totalCachedTokens * 0.9) / this.totalInputTokens
          : 0,
    };
  }

  /**
   * Reset cumulative statistics.
   */
  resetStatistics(): void {
    this.totalRequests = 0;
    this.totalInputTokens = 0;
    this.totalCachedTokens = 0;
  }

  // ===========================================================================
  // PRIVATE: Cache Marker Application
  // ===========================================================================

  /**
   * Apply cache markers to messages based on configuration.
   */
  private applyCacheMarkers(
    messages: (Message | MessageWithContent)[]
  ): MessageWithContent[] {
    const result: MessageWithContent[] = [];
    const totalMessages = messages.length;

    for (let i = 0; i < totalMessages; i++) {
      const message = messages[i];
      const isRecent = i >= totalMessages - this.config.recentUncachedCount;

      result.push(this.processMessage(message, isRecent));
    }

    return result;
  }

  /**
   * Process a single message, applying cache markers as appropriate.
   */
  private processMessage(
    message: Message | MessageWithContent,
    isRecent: boolean
  ): MessageWithContent {
    const role = message.role;

    // System messages: always cache (unless configured otherwise)
    if (role === 'system') {
      return this.cacheMessage(message, this.config.alwaysCacheSystem);
    }

    // Recent messages: don't cache (they might change)
    if (isRecent) {
      return this.cacheMessage(message, false);
    }

    // Older messages: cache if large enough
    const content = this.getContentText(message);
    const tokens = estimateTokens(content);
    const shouldCache = tokens >= this.config.minCacheableTokens;

    return this.cacheMessage(message, shouldCache);
  }

  /**
   * Convert a message to MessageWithContent with specified cache setting.
   */
  private cacheMessage(
    message: Message | MessageWithContent,
    shouldCache: boolean
  ): MessageWithContent {
    // Already has structured content?
    if ('content' in message && Array.isArray(message.content)) {
      // Re-apply cache markers based on shouldCache
      return {
        ...message,
        content: message.content.map(block => ({
          ...block,
          cache_control: shouldCache ? { type: 'ephemeral' as const } : undefined,
        })),
      } as MessageWithContent;
    }

    // Convert string content to structured
    const contentText = typeof message.content === 'string'
      ? message.content
      : '';

    // Build base message
    const result: MessageWithContent = {
      role: message.role as 'user' | 'assistant' | 'system' | 'tool',
      content: [text(contentText, shouldCache)],
    };

    // Preserve tool-related fields (required for Gemini compatibility)
    if ('tool_call_id' in message && message.tool_call_id) {
      result.tool_call_id = message.tool_call_id;
    }
    if ('name' in message && message.name) {
      result.name = message.name;
    }
    if ('tool_calls' in message && message.tool_calls) {
      result.tool_calls = message.tool_calls;
    }

    return result;
  }

  /**
   * Extract text content from a message.
   */
  private getContentText(message: Message | MessageWithContent): string {
    if (typeof message.content === 'string') {
      return message.content;
    }

    if (Array.isArray(message.content)) {
      return message.content.map(c => c.text).join('\n');
    }

    return '';
  }

  /**
   * Convert structured content back to string.
   */
  private contentToString(content: string | CacheableContent[]): string {
    if (typeof content === 'string') {
      return content;
    }

    return content.map(c => c.text).join('\n');
  }

  /**
   * Update cumulative statistics from a response.
   */
  private updateStatistics(usage: CacheAwareUsage): void {
    this.totalRequests++;
    this.totalInputTokens += usage.inputTokens;
    this.totalCachedTokens += usage.cachedTokens ?? 0;

    // Calculate current request stats
    const stats = extractCacheStats(usage);

    // Create full statistics object
    const fullStats: CacheStatistics = {
      totalInputTokens: usage.inputTokens,
      cachedTokens: usage.cachedTokens ?? 0,
      hitRate: stats.hitRate,
      estimatedSavings: stats.estimatedSavings,
      cumulative: this.getStatistics(),
    };

    // Notify callback if configured
    this.config.onCacheStats?.(fullStats);
  }
}

// =============================================================================
// FACTORY FUNCTION
// =============================================================================

/**
 * Create a cache-aware provider wrapper.
 *
 * @param provider - The base provider to wrap
 * @param config - Optional configuration
 * @returns Cache-aware provider
 *
 * @example
 * ```typescript
 * import { OpenRouterProvider } from '../02-provider-abstraction/adapters/openrouter.js';
 *
 * const provider = createCacheAwareProvider(
 *   new OpenRouterProvider(),
 *   { minCacheableTokens: 500 }
 * );
 * ```
 */
export function createCacheAwareProvider(
  provider: LLMProviderWithTools,
  config?: CacheProviderConfig
): CacheAwareProvider {
  return new CacheAwareProvider(provider, config);
}
