/**
 * Context Compaction Strategies
 *
 * When conversation context grows too large, these strategies
 * reduce it while preserving important information.
 */

import type { StoredMessage } from './context-manager.js';
import type { LLMProviderWithTools } from '../../02-provider-abstraction/types.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Result of a compaction operation.
 */
export interface CompactionResult {
  /** Compacted messages */
  messages: StoredMessage[];
  /** Original message count */
  originalCount: number;
  /** New message count */
  newCount: number;
  /** Estimated tokens saved */
  tokensSaved: number;
  /** Strategy used */
  strategy: string;
}

/**
 * Compaction strategy interface.
 */
export interface CompactionStrategy {
  name: string;
  compact(
    messages: StoredMessage[],
    options?: CompactionOptions
  ): Promise<CompactionResult>;
}

/**
 * Options for compaction.
 */
export interface CompactionOptions {
  /** Target message count after compaction */
  targetMessageCount?: number;
  /** Target token count after compaction */
  targetTokenCount?: number;
  /** Provider for LLM-based compaction (summarize strategy) */
  provider?: LLMProviderWithTools;
  /** Model to use for summarization */
  model?: string;
}

// =============================================================================
// TRUNCATE STRATEGY
// =============================================================================

/**
 * Simple truncation: keep system messages + last N messages.
 *
 * Pros:
 * - Fast, no LLM calls
 * - Predictable output size
 *
 * Cons:
 * - Loses context from early conversation
 * - No summary of what was discussed
 */
export const truncateStrategy: CompactionStrategy = {
  name: 'truncate',

  async compact(
    messages: StoredMessage[],
    options?: CompactionOptions
  ): Promise<CompactionResult> {
    const targetCount = options?.targetMessageCount ?? 20;

    // Separate system messages
    const systemMessages = messages.filter(m => m.role === 'system');
    const conversationMessages = messages.filter(m => m.role !== 'system');

    if (conversationMessages.length <= targetCount) {
      return {
        messages,
        originalCount: messages.length,
        newCount: messages.length,
        tokensSaved: 0,
        strategy: 'truncate',
      };
    }

    // Keep last N conversation messages
    const keptMessages = conversationMessages.slice(-targetCount);
    const compacted = [...systemMessages, ...keptMessages];

    const originalTokens = estimateTokens(messages);
    const newTokens = estimateTokens(compacted);

    return {
      messages: compacted,
      originalCount: messages.length,
      newCount: compacted.length,
      tokensSaved: originalTokens - newTokens,
      strategy: 'truncate',
    };
  },
};

// =============================================================================
// SLIDING WINDOW STRATEGY
// =============================================================================

/**
 * Sliding window: keep important messages + recent messages.
 *
 * "Important" messages include:
 * - System messages
 * - Messages with tool calls (actions taken)
 * - Messages marked as important
 *
 * Pros:
 * - Preserves key actions and decisions
 * - Better context than pure truncation
 *
 * Cons:
 * - Still loses some context
 * - Determining "importance" is heuristic
 */
export const slidingWindowStrategy: CompactionStrategy = {
  name: 'sliding-window',

  async compact(
    messages: StoredMessage[],
    options?: CompactionOptions
  ): Promise<CompactionResult> {
    const targetCount = options?.targetMessageCount ?? 30;

    // System messages always kept
    const systemMessages = messages.filter(m => m.role === 'system');

    // Important messages: tool calls, explicit markers
    const importantMessages = messages.filter(m =>
      m.role !== 'system' &&
      (m.toolCalls?.length ?? 0) > 0
    );

    // Recent messages
    const conversationMessages = messages.filter(m => m.role !== 'system');
    const recentCount = Math.max(10, targetCount - importantMessages.length);
    const recentMessages = conversationMessages.slice(-recentCount);

    // Combine, deduplicating
    const seenTimestamps = new Set<number>();
    const compacted: StoredMessage[] = [...systemMessages];

    for (const msg of importantMessages) {
      if (!seenTimestamps.has(msg.timestamp)) {
        compacted.push(msg);
        seenTimestamps.add(msg.timestamp);
      }
    }

    for (const msg of recentMessages) {
      if (!seenTimestamps.has(msg.timestamp)) {
        compacted.push(msg);
        seenTimestamps.add(msg.timestamp);
      }
    }

    // Sort by timestamp
    compacted.sort((a, b) => a.timestamp - b.timestamp);

    const originalTokens = estimateTokens(messages);
    const newTokens = estimateTokens(compacted);

    return {
      messages: compacted,
      originalCount: messages.length,
      newCount: compacted.length,
      tokensSaved: originalTokens - newTokens,
      strategy: 'sliding-window',
    };
  },
};

// =============================================================================
// SUMMARIZE STRATEGY
// =============================================================================

/**
 * LLM-based summarization: summarize old messages, keep recent ones.
 *
 * Pros:
 * - Preserves semantic meaning of old conversation
 * - Best context preservation
 *
 * Cons:
 * - Requires LLM call (cost, latency)
 * - Summary quality depends on model
 */
export const summarizeStrategy: CompactionStrategy = {
  name: 'summarize',

  async compact(
    messages: StoredMessage[],
    options?: CompactionOptions
  ): Promise<CompactionResult> {
    const provider = options?.provider;
    if (!provider) {
      // Fall back to truncation if no provider
      return truncateStrategy.compact(messages, options);
    }

    const targetCount = options?.targetMessageCount ?? 20;

    // Separate system and conversation messages
    const systemMessages = messages.filter(m => m.role === 'system');
    const conversationMessages = messages.filter(m => m.role !== 'system');

    if (conversationMessages.length <= targetCount) {
      return {
        messages,
        originalCount: messages.length,
        newCount: messages.length,
        tokensSaved: 0,
        strategy: 'summarize',
      };
    }

    // Split into old (to summarize) and recent (to keep)
    const keepCount = Math.floor(targetCount * 0.7); // Keep 70% as recent
    const oldMessages = conversationMessages.slice(0, -keepCount);
    const recentMessages = conversationMessages.slice(-keepCount);

    // Summarize old messages
    const summary = await generateSummary(oldMessages, provider, options?.model);

    // Create summary message
    const summaryMessage: StoredMessage = {
      role: 'system',
      content: `## Previous Conversation Summary\n\n${summary}\n\n---\n\n(Conversation continues below)`,
      timestamp: oldMessages[0]?.timestamp ?? Date.now(),
    };

    const compacted = [...systemMessages, summaryMessage, ...recentMessages];

    const originalTokens = estimateTokens(messages);
    const newTokens = estimateTokens(compacted);

    return {
      messages: compacted,
      originalCount: messages.length,
      newCount: compacted.length,
      tokensSaved: originalTokens - newTokens,
      strategy: 'summarize',
    };
  },
};

// =============================================================================
// HYBRID STRATEGY
// =============================================================================

/**
 * Hybrid: combine sliding window with optional summarization.
 *
 * Uses sliding window by default, adds summarization for very long conversations.
 */
export const hybridStrategy: CompactionStrategy = {
  name: 'hybrid',

  async compact(
    messages: StoredMessage[],
    options?: CompactionOptions
  ): Promise<CompactionResult> {
    const targetCount = options?.targetMessageCount ?? 30;

    // If not too many messages, use sliding window
    if (messages.length < targetCount * 2) {
      return slidingWindowStrategy.compact(messages, options);
    }

    // For longer conversations, use summarization if provider available
    if (options?.provider) {
      return summarizeStrategy.compact(messages, options);
    }

    // Fall back to sliding window
    return slidingWindowStrategy.compact(messages, options);
  },
};

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

/**
 * Estimate tokens in messages.
 */
function estimateTokens(messages: StoredMessage[]): number {
  let totalChars = 0;

  for (const msg of messages) {
    if (typeof msg.content === 'string') {
      totalChars += msg.content.length;
    } else if (Array.isArray(msg.content)) {
      for (const part of msg.content) {
        totalChars += part.text.length;
      }
    }
  }

  return Math.ceil(totalChars / 4);
}

/**
 * Generate a summary of messages using an LLM.
 */
async function generateSummary(
  messages: StoredMessage[],
  provider: LLMProviderWithTools,
  model?: string
): Promise<string> {
  // Format messages for summarization
  const formatted = messages
    .map(m => {
      const role = m.role.charAt(0).toUpperCase() + m.role.slice(1);
      const content = typeof m.content === 'string'
        ? m.content
        : m.content.map(c => c.text).join('\n');
      return `${role}: ${content}`;
    })
    .join('\n\n');

  const prompt = `Summarize the following conversation concisely. Focus on:
1. Key topics discussed
2. Important decisions made
3. Actions taken (files read/modified, commands run)
4. Unresolved questions or tasks

Keep the summary under 500 words.

---
${formatted}
---

Summary:`;

  try {
    const response = await provider.chatWithTools(
      [{ role: 'user', content: prompt }],
      { model, maxTokens: 1000 }
    );

    return response.content || 'Unable to generate summary.';
  } catch (error) {
    console.error('Summary generation failed:', error);
    return 'Previous conversation context (summary unavailable).';
  }
}

// =============================================================================
// STRATEGY REGISTRY
// =============================================================================

/**
 * Available compaction strategies.
 */
export const compactionStrategies: Record<string, CompactionStrategy> = {
  truncate: truncateStrategy,
  'sliding-window': slidingWindowStrategy,
  summarize: summarizeStrategy,
  hybrid: hybridStrategy,
};

/**
 * Get a compaction strategy by name.
 */
export function getCompactionStrategy(name: string): CompactionStrategy {
  const strategy = compactionStrategies[name];
  if (!strategy) {
    throw new Error(`Unknown compaction strategy: ${name}`);
  }
  return strategy;
}

/**
 * Compact messages using the specified strategy.
 */
export async function compactMessages(
  messages: StoredMessage[],
  strategyName: string = 'hybrid',
  options?: CompactionOptions
): Promise<CompactionResult> {
  const strategy = getCompactionStrategy(strategyName);
  return strategy.compact(messages, options);
}
