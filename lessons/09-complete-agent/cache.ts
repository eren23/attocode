/**
 * Lesson 8: Prompt Caching
 *
 * Utilities for leveraging OpenRouter's prompt caching feature
 * to reduce costs on repeated conversations.
 */

import type { CacheableContent, MessageWithContent } from './types.js';

// =============================================================================
// WHY CACHING MATTERS
// =============================================================================

/**
 * ═══════════════════════════════════════════════════════════════════════════
 * PROMPT CACHING: The Economics
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * LLM APIs charge per token. In an agent loop, you resend the ENTIRE
 * conversation history on every turn. This adds up fast:
 *
 * WITHOUT CACHING (10-turn conversation):
 * ┌─────────┬─────────────────────────────────────┬──────────────┐
 * │ Turn    │ Tokens Sent                         │ Cost (est)   │
 * ├─────────┼─────────────────────────────────────┼──────────────┤
 * │ 1       │ 2,000 (system) + 100 (user)         │ $0.0063      │
 * │ 2       │ 2,000 + 100 + 500 (history)         │ $0.0078      │
 * │ 3       │ 2,000 + 100 + 1,000                 │ $0.0093      │
 * │ ...     │ ...                                 │ ...          │
 * │ 10      │ 2,000 + 100 + 5,000                 │ $0.0213      │
 * ├─────────┼─────────────────────────────────────┼──────────────┤
 * │ TOTAL   │ ~35,000 input tokens                │ ~$0.11       │
 * └─────────┴─────────────────────────────────────┴──────────────┘
 *
 * WITH CACHING (same conversation):
 * ┌─────────┬─────────────────────────────────────┬──────────────┐
 * │ Turn    │ Tokens                              │ Cost (est)   │
 * ├─────────┼─────────────────────────────────────┼──────────────┤
 * │ 1       │ 2,100 (cache write + miss)          │ $0.0079      │
 * │ 2       │ 200 (cache hit!) + 600 new          │ $0.0027      │
 * │ 3       │ 200 (cache hit!) + 1,100 new        │ $0.0042      │
 * │ ...     │ ...                                 │ ...          │
 * │ 10      │ 200 (cache hit!) + 5,100 new        │ $0.0162      │
 * ├─────────┼─────────────────────────────────────┼──────────────┤
 * │ TOTAL   │ ~15,000 effective tokens            │ ~$0.06       │
 * └─────────┴─────────────────────────────────────┴──────────────┘
 *
 * That's ~45% savings! The savings grow with conversation length.
 *
 * HOW IT WORKS:
 * 1. Mark content with cache_control: { type: 'ephemeral' }
 * 2. First request: Cache MISS - full cost + small write fee
 * 3. Subsequent requests: Cache HIT - ~90% discount on cached portion
 * 4. Cache expires after ~5 minutes of inactivity
 *
 * WHAT TO CACHE:
 * ✓ System prompts (tool definitions, instructions)
 * ✓ Large static context (documentation, file contents)
 * ✓ Conversation prefixes that don't change
 * ✗ User's latest message (always changes)
 * ✗ Small content (<1000 tokens - overhead not worth it)
 * ═══════════════════════════════════════════════════════════════════════════
 */

// =============================================================================
// CACHEABLE CONTENT BUILDERS
// =============================================================================

/**
 * Create cacheable text content.
 *
 * @param text - The text content
 * @param cache - Whether to mark for caching (default: true)
 * @returns CacheableContent object
 *
 * @example
 * ```typescript
 * const systemPrompt = createCacheableContent(
 *   'You are a helpful assistant with access to: ...',
 *   true // Mark for caching
 * );
 * ```
 */
export function createCacheableContent(text: string, cache = true): CacheableContent {
  return {
    type: 'text',
    text,
    ...(cache && { cache_control: { type: 'ephemeral' } }),
  };
}

/**
 * Create a system message with cacheable content.
 *
 * Splits the system prompt into:
 * - Static part (cached): Tool definitions, base instructions
 * - Dynamic part (not cached): Task-specific context
 *
 * @example
 * ```typescript
 * const systemMessage = createCacheableSystemMessage({
 *   static: 'You are a coding assistant with tools: read_file, write_file...',
 *   dynamic: 'The user is working on a React project in /app/src',
 * });
 * ```
 */
export function createCacheableSystemMessage(parts: {
  static: string;
  dynamic?: string;
}): MessageWithContent {
  const content: CacheableContent[] = [
    createCacheableContent(parts.static, true), // Cached
  ];

  if (parts.dynamic) {
    content.push(createCacheableContent(parts.dynamic, false)); // Not cached
  }

  return {
    role: 'system',
    content,
  };
}

/**
 * Create a user message with large context marked for caching.
 *
 * Use this when the user provides large amounts of context that
 * will be referenced across multiple turns.
 *
 * @example
 * ```typescript
 * const userMessage = createCacheableUserMessage(
 *   'Refactor this file to use async/await',
 *   fileContents // Large file - will be cached
 * );
 * ```
 */
export function createCacheableUserMessage(
  instruction: string,
  context?: string
): MessageWithContent {
  const content: CacheableContent[] = [];

  if (context) {
    content.push(createCacheableContent(context, true)); // Cache the context
  }

  content.push(createCacheableContent(instruction, false)); // Don't cache instruction

  return {
    role: 'user',
    content,
  };
}

// =============================================================================
// CACHE STATISTICS
// =============================================================================

/**
 * Statistics about cache usage.
 */
export interface CacheStats {
  /** Total tokens that could be cached */
  cacheableTokens: number;
  /** Estimated tokens (rough: 1 token ≈ 4 chars) */
  estimatedTokens: number;
  /** Whether caching is likely beneficial */
  worthCaching: boolean;
  /** Estimated savings percentage */
  estimatedSavings: string;
  /** Recommendation */
  recommendation: string;
}

/**
 * Estimate cache savings for a conversation.
 *
 * @param messages - Current conversation messages
 * @returns Statistics and recommendations
 *
 * @example
 * ```typescript
 * const stats = estimateCacheSavings(messages);
 * console.log(`Potential savings: ${stats.estimatedSavings}`);
 * // → "Potential savings: ~45%"
 * ```
 */
export function estimateCacheSavings(messages: MessageWithContent[]): CacheStats {
  let cacheableChars = 0;
  let totalChars = 0;

  for (const message of messages) {
    if (typeof message.content === 'string') {
      totalChars += message.content.length;
      // System messages are typically cacheable
      if (message.role === 'system') {
        cacheableChars += message.content.length;
      }
    } else if (Array.isArray(message.content)) {
      for (const part of message.content) {
        totalChars += part.text.length;
        if (part.cache_control) {
          cacheableChars += part.text.length;
        }
      }
    }
  }

  // Rough token estimate (1 token ≈ 4 characters for English)
  const estimatedTokens = Math.ceil(totalChars / 4);
  const cacheableTokens = Math.ceil(cacheableChars / 4);

  // Caching has overhead, only worth it for substantial content
  const worthCaching = cacheableTokens >= 1000;

  // Cache hits are ~90% cheaper, but there's write overhead on first request
  const cacheRatio = cacheableTokens / Math.max(estimatedTokens, 1);
  const estimatedSavingsPercent = Math.round(cacheRatio * 85); // ~85% of cache ratio

  let recommendation: string;
  if (cacheableTokens < 500) {
    recommendation = 'Content too small for caching benefit';
  } else if (cacheableTokens < 1000) {
    recommendation = 'Marginal benefit - consider caching for longer conversations';
  } else if (cacheableTokens < 5000) {
    recommendation = 'Good candidate for caching';
  } else {
    recommendation = 'Excellent candidate - significant savings expected';
  }

  return {
    cacheableTokens,
    estimatedTokens,
    worthCaching,
    estimatedSavings: `~${estimatedSavingsPercent}%`,
    recommendation,
  };
}

// =============================================================================
// CACHE-AWARE CONVERSATION BUILDER
// =============================================================================

/**
 * Build a cache-optimized conversation array.
 *
 * This helper structures messages to maximize cache hits:
 * 1. System prompt (cached)
 * 2. Large context if any (cached)
 * 3. Conversation history (partially cached based on stability)
 * 4. Latest user message (not cached - always changes)
 */
export class CacheAwareConversation {
  private systemPrompt: MessageWithContent;
  private staticContext: MessageWithContent[] = [];
  private history: MessageWithContent[] = [];

  constructor(systemPromptStatic: string, systemPromptDynamic?: string) {
    this.systemPrompt = createCacheableSystemMessage({
      static: systemPromptStatic,
      dynamic: systemPromptDynamic,
    });
  }

  /**
   * Add static context that should be cached.
   * Use for documentation, large file contents, etc.
   */
  addStaticContext(role: 'user' | 'assistant', content: string): this {
    this.staticContext.push({
      role,
      content: [createCacheableContent(content, true)],
    });
    return this;
  }

  /**
   * Add a message to the conversation history.
   * Older messages get cached, recent ones don't.
   */
  addMessage(message: MessageWithContent): this {
    this.history.push(message);
    return this;
  }

  /**
   * Build the final message array with cache markers.
   *
   * @param cacheHistoryThreshold - Messages older than this index get cached
   */
  build(cacheHistoryThreshold = 4): MessageWithContent[] {
    const messages: MessageWithContent[] = [this.systemPrompt];

    // Add static context (always cached)
    messages.push(...this.staticContext);

    // Add history with selective caching
    for (let i = 0; i < this.history.length; i++) {
      const message = this.history[i];
      const shouldCache = i < this.history.length - cacheHistoryThreshold;

      if (shouldCache && typeof message.content === 'string') {
        // Convert to cacheable format
        messages.push({
          ...message,
          content: [createCacheableContent(message.content, true)],
        });
      } else {
        messages.push(message);
      }
    }

    return messages;
  }

  /**
   * Get cache statistics for the current conversation.
   */
  getStats(): CacheStats {
    return estimateCacheSavings(this.build());
  }
}

// =============================================================================
// CONVENIENCE EXPORTS
// =============================================================================

/**
 * Quick check if a message array has any cacheable content.
 */
export function hasCacheableContent(messages: MessageWithContent[]): boolean {
  return messages.some(m => {
    if (Array.isArray(m.content)) {
      return m.content.some(c => c.cache_control !== undefined);
    }
    return false;
  });
}

/**
 * Strip cache markers from messages (for debugging/logging).
 */
export function stripCacheMarkers(messages: MessageWithContent[]): MessageWithContent[] {
  return messages.map(m => {
    if (Array.isArray(m.content)) {
      return {
        ...m,
        content: m.content.map(c => ({
          type: c.type,
          text: c.text,
        })),
      };
    }
    return m;
  });
}
