/**
 * Lesson 08: Cache Hitting Basics
 *
 * Fundamental patterns for prompt caching with LLM APIs.
 * These utilities help you mark content for caching and track cache effectiveness.
 */

import type {
  CacheableContent,
  MessageWithContent,
} from '../02-provider-abstraction/types.js';

// =============================================================================
// CORE TYPES
// =============================================================================

/**
 * Cache marker configuration.
 *
 * The 'ephemeral' type is the standard cache marker. Content marked with this
 * will be cached for ~5 minutes of inactivity.
 */
export interface CacheControl {
  type: 'ephemeral';
}

/**
 * Response with cache statistics from the API.
 */
export interface CacheAwareUsage {
  inputTokens: number;
  outputTokens: number;
  cachedTokens?: number;
  cacheWriteTokens?: number;
}

// =============================================================================
// CACHE MARKER BUILDERS
// =============================================================================

/**
 * Create a cacheable text content block.
 *
 * @param text - The text content to potentially cache
 * @param shouldCache - Whether to mark for caching (default: true)
 * @returns Content block with optional cache_control marker
 *
 * @example
 * ```typescript
 * // Mark for caching
 * const cached = text('Large system prompt...', true);
 *
 * // Don't cache (dynamic content)
 * const dynamic = text('Current timestamp: ' + Date.now(), false);
 * ```
 */
export function text(content: string, shouldCache = true): CacheableContent {
  const block: CacheableContent = {
    type: 'text',
    text: content,
  };

  if (shouldCache) {
    block.cache_control = { type: 'ephemeral' };
  }

  return block;
}

/**
 * Create a system message with cache-aware content.
 *
 * System prompts are prime candidates for caching because they:
 * 1. Appear at the start of every request (prefix position)
 * 2. Don't change between conversation turns
 * 3. Are often large (tool definitions, instructions)
 *
 * @param staticContent - Content that should be cached
 * @param dynamicContent - Optional content that changes (not cached)
 * @returns MessageWithContent suitable for the API
 *
 * @example
 * ```typescript
 * const systemMessage = system(
 *   'You are a coding assistant with tools: read_file, write_file...',
 *   'Current working directory: /app/src'  // Dynamic, not cached
 * );
 * ```
 */
export function system(
  staticContent: string,
  dynamicContent?: string
): MessageWithContent {
  const content: CacheableContent[] = [text(staticContent, true)];

  if (dynamicContent) {
    content.push(text(dynamicContent, false));
  }

  return { role: 'system', content };
}

/**
 * Create a user message with optional cached context.
 *
 * Use this when providing large context (file contents, documentation)
 * that will be referenced across multiple turns.
 *
 * @param instruction - The user's actual request
 * @param context - Optional large context to cache
 * @returns MessageWithContent with appropriate cache markers
 *
 * @example
 * ```typescript
 * // Large file content gets cached, instruction doesn't
 * const message = user(
 *   'Refactor this to use async/await',
 *   fs.readFileSync('large-file.ts', 'utf-8')
 * );
 * ```
 */
export function user(
  instruction: string,
  context?: string
): MessageWithContent {
  const content: CacheableContent[] = [];

  // Context goes first (cacheable) - order matters for prefix caching!
  if (context) {
    content.push(text(context, true));
  }

  // Instruction goes last (not cached - changes each turn)
  content.push(text(instruction, false));

  return { role: 'user', content };
}

/**
 * Create an assistant message, optionally caching long responses.
 *
 * @param response - The assistant's response text
 * @param shouldCache - Whether to cache (useful for long responses that won't change)
 */
export function assistant(
  response: string,
  shouldCache = false
): MessageWithContent {
  return {
    role: 'assistant',
    content: [text(response, shouldCache)],
  };
}

// =============================================================================
// CACHE ANALYSIS
// =============================================================================

/**
 * Estimate tokens in a string.
 * Rough approximation: ~4 characters per token for English text.
 */
export function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}

/**
 * Minimum tokens for caching to be beneficial.
 * Below this, the cache write overhead exceeds the savings.
 */
export const MIN_CACHEABLE_TOKENS = 1000;

/**
 * Analyze content to determine if caching is worthwhile.
 *
 * @param content - Text content to analyze
 * @returns Analysis with recommendation
 *
 * @example
 * ```typescript
 * const analysis = analyzeCacheability(systemPrompt);
 * if (analysis.worthCaching) {
 *   console.log(`Expected savings: ${analysis.estimatedSavingsPercent}%`);
 * }
 * ```
 */
export function analyzeCacheability(content: string): {
  estimatedTokens: number;
  worthCaching: boolean;
  estimatedSavingsPercent: number;
  recommendation: string;
} {
  const tokens = estimateTokens(content);
  const worthCaching = tokens >= MIN_CACHEABLE_TOKENS;

  // Cache hits are ~90% cheaper, but first request has write overhead
  // Effective savings depend on how many times the cache is hit
  const estimatedSavingsPercent = worthCaching
    ? Math.round(85 * (1 - MIN_CACHEABLE_TOKENS / tokens)) // Diminishing overhead
    : 0;

  let recommendation: string;
  if (tokens < 500) {
    recommendation = 'Too small - caching overhead exceeds benefit';
  } else if (tokens < MIN_CACHEABLE_TOKENS) {
    recommendation = 'Marginal - consider caching only for many repeated requests';
  } else if (tokens < 5000) {
    recommendation = 'Good candidate - cache for multi-turn conversations';
  } else {
    recommendation = 'Excellent candidate - significant savings expected';
  }

  return {
    estimatedTokens: tokens,
    worthCaching,
    estimatedSavingsPercent,
    recommendation,
  };
}

// =============================================================================
// CONVERSATION BUILDER
// =============================================================================

/**
 * A builder for constructing cache-optimized conversations.
 *
 * Structures messages to maximize cache effectiveness:
 * 1. System prompt (always cached) - stable prefix
 * 2. Static context (cached) - documentation, files
 * 3. Old history (optionally cached) - stable conversation prefix
 * 4. Recent history (not cached) - may be edited/regenerated
 * 5. Latest message (not cached) - changes every turn
 *
 * @example
 * ```typescript
 * const conversation = new CacheOptimizedConversation(systemPrompt);
 *
 * // Add large documentation context
 * conversation.addContext(documentationText);
 *
 * // Add conversation history
 * conversation.addTurn('user', 'What does the API do?');
 * conversation.addTurn('assistant', 'The API provides...');
 *
 * // Get messages for API call
 * const messages = conversation.build();
 * ```
 */
export class CacheOptimizedConversation {
  private systemContent: CacheableContent[];
  private contexts: CacheableContent[] = [];
  private history: Array<{ role: 'user' | 'assistant'; content: string }> = [];

  constructor(systemPrompt: string, dynamicSystemPart?: string) {
    this.systemContent = [text(systemPrompt, true)];
    if (dynamicSystemPart) {
      this.systemContent.push(text(dynamicSystemPart, false));
    }
  }

  /**
   * Add static context that should be cached.
   * Call this before adding conversation history.
   */
  addContext(content: string): this {
    this.contexts.push(text(content, true));
    return this;
  }

  /**
   * Add a conversation turn.
   */
  addTurn(role: 'user' | 'assistant', content: string): this {
    this.history.push({ role, content });
    return this;
  }

  /**
   * Build the final message array with optimized cache markers.
   *
   * @param cacheHistoryOlderThan - Cache messages older than this index from the end
   *                                Default: 4 (cache all but last 4 messages)
   */
  build(cacheHistoryOlderThan = 4): MessageWithContent[] {
    const messages: MessageWithContent[] = [];

    // 1. System message (cached)
    messages.push({ role: 'system', content: this.systemContent });

    // 2. Static contexts (cached)
    if (this.contexts.length > 0) {
      messages.push({
        role: 'user',
        content: this.contexts,
      });
    }

    // 3. Conversation history (selectively cached)
    for (let i = 0; i < this.history.length; i++) {
      const turn = this.history[i];
      const distanceFromEnd = this.history.length - i;
      const shouldCache = distanceFromEnd > cacheHistoryOlderThan;

      messages.push({
        role: turn.role,
        content: [text(turn.content, shouldCache)],
      });
    }

    return messages;
  }

  /**
   * Get statistics about the current conversation's cache potential.
   */
  getStats(): {
    totalTokens: number;
    cacheableTokens: number;
    cacheRatio: number;
    estimatedSavings: string;
  } {
    const messages = this.build();
    let totalChars = 0;
    let cacheableChars = 0;

    for (const message of messages) {
      if (Array.isArray(message.content)) {
        for (const block of message.content) {
          totalChars += block.text.length;
          if (block.cache_control) {
            cacheableChars += block.text.length;
          }
        }
      }
    }

    const totalTokens = estimateTokens(String(totalChars));
    const cacheableTokens = estimateTokens(String(cacheableChars));
    const cacheRatio = totalChars > 0 ? cacheableChars / totalChars : 0;

    return {
      totalTokens,
      cacheableTokens,
      cacheRatio,
      estimatedSavings: `~${Math.round(cacheRatio * 85)}%`,
    };
  }
}

// =============================================================================
// UTILITY FUNCTIONS
// =============================================================================

/**
 * Check if a message array has any cached content.
 */
export function hasCachedContent(messages: MessageWithContent[]): boolean {
  return messages.some(m => {
    if (Array.isArray(m.content)) {
      return m.content.some(c => c.cache_control !== undefined);
    }
    return false;
  });
}

/**
 * Count cacheable tokens in a message array.
 */
export function countCacheableTokens(messages: MessageWithContent[]): number {
  let cacheableChars = 0;

  for (const message of messages) {
    if (Array.isArray(message.content)) {
      for (const block of message.content) {
        if (block.cache_control) {
          cacheableChars += block.text.length;
        }
      }
    }
  }

  return estimateTokens(String(cacheableChars));
}

/**
 * Extract cache statistics from an API response.
 *
 * @param usage - Usage object from API response
 * @returns Structured cache statistics
 */
export function extractCacheStats(usage: CacheAwareUsage): {
  cached: number;
  uncached: number;
  hitRate: number;
  estimatedSavings: number;
} {
  const cached = usage.cachedTokens ?? 0;
  const uncached = usage.inputTokens - cached;
  const hitRate = usage.inputTokens > 0 ? cached / usage.inputTokens : 0;

  // Cached tokens cost ~10% of normal (90% discount)
  const normalCost = usage.inputTokens;
  const actualCost = uncached + cached * 0.1;
  const estimatedSavings = normalCost > 0
    ? (normalCost - actualCost) / normalCost
    : 0;

  return {
    cached,
    uncached,
    hitRate,
    estimatedSavings,
  };
}
