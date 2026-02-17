/**
 * Lesson 26: Cache Boundary Tracker
 *
 * Analyzes KV cache efficiency during agent execution.
 * Tracks content hashes to detect cache invalidation,
 * compares predicted vs actual cache hit rates from API responses.
 *
 * Key insight: Anthropic returns `cache_creation_input_tokens` and
 * `cache_read_input_tokens` in the usage response, allowing us to
 * measure actual cache performance.
 *
 * @example
 * ```typescript
 * const tracker = new CacheBoundaryTracker();
 *
 * // Record request
 * tracker.recordRequest({
 *   messages: [...],
 *   systemPrompt: '...',
 * });
 *
 * // After getting API response, record actual cache stats
 * tracker.recordResponse({
 *   cacheReadTokens: response.usage.cache_read_input_tokens,
 *   cacheWriteTokens: response.usage.cache_creation_input_tokens,
 *   totalInputTokens: response.usage.input_tokens,
 * });
 *
 * // Analyze
 * const analysis = tracker.analyze();
 * console.log(`Cache hit rate: ${analysis.hitRate * 100}%`);
 * ```
 */

import {
  type CacheBreakdown,
  type CacheBreakpointInfo,
  type TracedMessage,
} from './types.js';
import { estimateTokenCount } from '../integrations/utilities/token-estimate.js';
import { stableStringify } from '../tricks/kv-cache-context.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Request data for cache tracking.
 */
export interface CacheTrackingRequest {
  /** System prompt content */
  systemPrompt: string;

  /** Messages array */
  messages: Array<{
    role: 'system' | 'user' | 'assistant' | 'tool';
    content: string;
    toolCallId?: string;
  }>;

  /** Tool definitions (affects cache) */
  toolDefinitions?: unknown[];
}

/**
 * Response data from API with cache info.
 */
export interface CacheTrackingResponse {
  /** Tokens read from cache (cache hit) */
  cacheReadTokens: number;

  /** Tokens written to cache (new cache entries) */
  cacheWriteTokens: number;

  /** Total input tokens */
  totalInputTokens: number;

  /** Output tokens */
  outputTokens: number;
}

/**
 * Historical cache data point.
 */
interface CacheHistoryEntry {
  /** Request number */
  requestNumber: number;

  /** Timestamp */
  timestamp: number;

  /** Content hash of the prefix */
  prefixHash: string;

  /** Hash of each message */
  messageHashes: string[];

  /** Predicted cacheable tokens */
  predictedCacheableTokens: number;

  /** Actual cache read from API */
  actualCacheReadTokens?: number;

  /** Actual cache write from API */
  actualCacheWriteTokens?: number;

  /** Total input tokens */
  totalInputTokens?: number;

  /** Detected breakpoints */
  breakpoints: CacheBreakpointInfo[];
}

/**
 * Cache analysis result.
 */
export interface CacheAnalysis {
  /** Overall cache hit rate (0-1) */
  hitRate: number;

  /** Average hit rate across all requests */
  avgHitRate: number;

  /** Tokens saved by caching */
  tokensSaved: number;

  /** Cost savings estimate (USD) */
  estimatedSavings: number;

  /** Cache efficiency trend */
  trend: 'improving' | 'declining' | 'stable';

  /** Most common breakpoint types */
  commonBreakpoints: Array<{
    type: CacheBreakpointInfo['type'];
    count: number;
    avgTokensAffected: number;
  }>;

  /** Recommendations for improving cache efficiency */
  recommendations: string[];
}

// =============================================================================
// CACHE BOUNDARY TRACKER
// =============================================================================

/**
 * Tracks KV cache boundaries and efficiency during agent execution.
 */
export class CacheBoundaryTracker {
  private history: CacheHistoryEntry[] = [];
  private requestCount = 0;
  private previousPrefixHash: string | null = null;
  private previousMessageHashes: string[] = [];

  // Cost assumptions for savings calculation
  private readonly cachedTokenCost = 0.00025 / 1000; // $0.25 per 1M cached
  private readonly uncachedTokenCost = 0.003 / 1000; // $3 per 1M uncached

  /**
   * Record a new request for cache tracking.
   */
  recordRequest(request: CacheTrackingRequest): CacheBreakdown {
    this.requestCount++;

    // Compute prefix hash (system prompt + tools)
    const prefixContent = request.systemPrompt +
      (request.toolDefinitions ? stableStringify(request.toolDefinitions) : '');
    const prefixHash = this.hashContent(prefixContent);

    // Compute message hashes
    const messageHashes = request.messages.map(msg =>
      this.hashContent(`${msg.role}:${msg.content}:${msg.toolCallId ?? ''}`)
    );

    // Detect breakpoints
    const breakpoints = this.detectBreakpoints(
      prefixHash,
      messageHashes,
      request.messages
    );

    // Estimate cacheable tokens
    const estimatedTokens = this.estimateTokens(request);
    const predictedCacheableTokens = this.predictCacheableTokens(
      prefixHash,
      messageHashes,
      estimatedTokens
    );

    // Store history entry
    const entry: CacheHistoryEntry = {
      requestNumber: this.requestCount,
      timestamp: Date.now(),
      prefixHash,
      messageHashes,
      predictedCacheableTokens,
      breakpoints,
    };
    this.history.push(entry);

    // Update previous state
    this.previousPrefixHash = prefixHash;
    this.previousMessageHashes = [...messageHashes];

    // Return breakdown (will be updated when response comes)
    return {
      cacheReadTokens: predictedCacheableTokens,
      cacheWriteTokens: estimatedTokens.total - predictedCacheableTokens,
      freshTokens: estimatedTokens.total - predictedCacheableTokens,
      hitRate: predictedCacheableTokens / estimatedTokens.total,
      estimatedSavings: this.calculateSavings(
        predictedCacheableTokens,
        estimatedTokens.total - predictedCacheableTokens
      ),
      breakpoints,
    };
  }

  /**
   * Update the last request with actual API response data.
   */
  recordResponse(response: CacheTrackingResponse): CacheBreakdown {
    if (this.history.length === 0) {
      throw new Error('No request recorded to update');
    }

    const lastEntry = this.history[this.history.length - 1];
    lastEntry.actualCacheReadTokens = response.cacheReadTokens;
    lastEntry.actualCacheWriteTokens = response.cacheWriteTokens;
    lastEntry.totalInputTokens = response.totalInputTokens;

    const freshTokens = response.totalInputTokens - response.cacheReadTokens;
    const hitRate = response.totalInputTokens > 0
      ? response.cacheReadTokens / response.totalInputTokens
      : 0;

    return {
      cacheReadTokens: response.cacheReadTokens,
      cacheWriteTokens: response.cacheWriteTokens,
      freshTokens,
      hitRate,
      estimatedSavings: this.calculateSavings(response.cacheReadTokens, freshTokens),
      breakpoints: lastEntry.breakpoints,
    };
  }

  /**
   * Get comprehensive cache analysis.
   */
  analyze(): CacheAnalysis {
    if (this.history.length === 0) {
      return {
        hitRate: 0,
        avgHitRate: 0,
        tokensSaved: 0,
        estimatedSavings: 0,
        trend: 'stable',
        commonBreakpoints: [],
        recommendations: ['No requests recorded yet'],
      };
    }

    // Calculate overall stats
    let totalCacheRead = 0;
    let totalTokens = 0;
    const hitRates: number[] = [];

    for (const entry of this.history) {
      if (entry.actualCacheReadTokens !== undefined && entry.totalInputTokens !== undefined) {
        totalCacheRead += entry.actualCacheReadTokens;
        totalTokens += entry.totalInputTokens;
        hitRates.push(entry.actualCacheReadTokens / entry.totalInputTokens);
      }
    }

    const hitRate = totalTokens > 0 ? totalCacheRead / totalTokens : 0;
    const avgHitRate = hitRates.length > 0
      ? hitRates.reduce((a, b) => a + b, 0) / hitRates.length
      : 0;

    // Calculate tokens saved and cost savings
    const tokensSaved = totalCacheRead;
    const estimatedSavings = this.calculateSavings(totalCacheRead, totalTokens - totalCacheRead);

    // Determine trend
    const trend = this.calculateTrend(hitRates);

    // Aggregate breakpoints
    const breakpointCounts = new Map<CacheBreakpointInfo['type'], { count: number; tokens: number }>();
    for (const entry of this.history) {
      for (const bp of entry.breakpoints) {
        const existing = breakpointCounts.get(bp.type) ?? { count: 0, tokens: 0 };
        existing.count++;
        existing.tokens += bp.tokensAffected;
        breakpointCounts.set(bp.type, existing);
      }
    }

    const commonBreakpoints = Array.from(breakpointCounts.entries())
      .map(([type, data]) => ({
        type,
        count: data.count,
        avgTokensAffected: data.tokens / data.count,
      }))
      .sort((a, b) => b.count - a.count);

    // Generate recommendations
    const recommendations = this.generateRecommendations(
      hitRate,
      commonBreakpoints,
      trend
    );

    return {
      hitRate,
      avgHitRate,
      tokensSaved,
      estimatedSavings,
      trend,
      commonBreakpoints,
      recommendations,
    };
  }

  /**
   * Get cache breakdown for the current state.
   */
  getCurrentBreakdown(): CacheBreakdown | null {
    if (this.history.length === 0) return null;

    const lastEntry = this.history[this.history.length - 1];
    if (lastEntry.actualCacheReadTokens === undefined) {
      return {
        cacheReadTokens: lastEntry.predictedCacheableTokens,
        cacheWriteTokens: 0,
        freshTokens: 0,
        hitRate: 0,
        estimatedSavings: 0,
        breakpoints: lastEntry.breakpoints,
      };
    }

    const freshTokens = (lastEntry.totalInputTokens ?? 0) - lastEntry.actualCacheReadTokens;
    return {
      cacheReadTokens: lastEntry.actualCacheReadTokens,
      cacheWriteTokens: lastEntry.actualCacheWriteTokens ?? 0,
      freshTokens,
      hitRate: lastEntry.totalInputTokens
        ? lastEntry.actualCacheReadTokens / lastEntry.totalInputTokens
        : 0,
      estimatedSavings: this.calculateSavings(lastEntry.actualCacheReadTokens, freshTokens),
      breakpoints: lastEntry.breakpoints,
    };
  }

  /**
   * Get history of all cache tracking entries.
   */
  getHistory(): CacheHistoryEntry[] {
    return [...this.history];
  }

  /**
   * Reset tracker state.
   */
  reset(): void {
    this.history = [];
    this.requestCount = 0;
    this.previousPrefixHash = null;
    this.previousMessageHashes = [];
  }

  // ==========================================================================
  // PRIVATE METHODS
  // ==========================================================================

  /**
   * Detect cache breakpoints by comparing with previous request.
   */
  private detectBreakpoints(
    currentPrefixHash: string,
    currentMessageHashes: string[],
    messages: CacheTrackingRequest['messages']
  ): CacheBreakpointInfo[] {
    const breakpoints: CacheBreakpointInfo[] = [];

    // First request - no breakpoints
    if (this.previousPrefixHash === null) {
      return breakpoints;
    }

    // Check prefix change (system prompt or tools changed)
    if (currentPrefixHash !== this.previousPrefixHash) {
      breakpoints.push({
        position: 0,
        type: 'dynamic_content',
        description: 'System prompt or tool definitions changed',
        tokensAffected: this.estimateTokensFromContent(messages[0]?.content ?? ''),
      });
    }

    // Check each message for changes
    let lastUnchangedIndex = -1;
    for (let i = 0; i < currentMessageHashes.length; i++) {
      if (i >= this.previousMessageHashes.length) {
        // New message (expected, not a breakpoint)
        continue;
      }

      if (currentMessageHashes[i] !== this.previousMessageHashes[i]) {
        // Message changed!
        const msg = messages[i];
        const breakpointType = this.classifyBreakpoint(msg, i, lastUnchangedIndex);

        breakpoints.push({
          position: i,
          type: breakpointType,
          description: `Message at position ${i} (${msg.role}) changed`,
          tokensAffected: this.estimateRemainingTokens(messages, i),
        });

        break; // Only report first change
      }

      lastUnchangedIndex = i;
    }

    return breakpoints;
  }

  /**
   * Classify what type of breakpoint this is.
   */
  private classifyBreakpoint(
    message: CacheTrackingRequest['messages'][0],
    position: number,
    lastUnchangedIndex: number
  ): CacheBreakpointInfo['type'] {
    // If role changed from previous position
    if (position > 0) {
      return 'role_change';
    }

    // Tool result messages
    if (message.role === 'tool') {
      return 'tool_result';
    }

    // Content change
    return 'content_change';
  }

  /**
   * Predict how many tokens will be cached based on history.
   */
  private predictCacheableTokens(
    currentPrefixHash: string,
    currentMessageHashes: string[],
    estimatedTokens: { total: number; messages: number[] }
  ): number {
    // First request - nothing cached
    if (this.previousPrefixHash === null) {
      return 0;
    }

    // Prefix changed - no cache
    if (currentPrefixHash !== this.previousPrefixHash) {
      return 0;
    }

    // Count matching message hashes from the start
    let cachedTokens = estimatedTokens.total - estimatedTokens.messages.reduce((a, b) => a + b, 0);

    for (let i = 0; i < currentMessageHashes.length && i < this.previousMessageHashes.length; i++) {
      if (currentMessageHashes[i] === this.previousMessageHashes[i]) {
        cachedTokens += estimatedTokens.messages[i] ?? 0;
      } else {
        break;
      }
    }

    return cachedTokens;
  }

  /**
   * Estimate tokens for a request.
   */
  private estimateTokens(request: CacheTrackingRequest): { total: number; messages: number[] } {
    const systemTokens = this.estimateTokensFromContent(request.systemPrompt);
    const toolTokens = request.toolDefinitions
      ? this.estimateTokensFromContent(stableStringify(request.toolDefinitions))
      : 0;

    const messageTokens = request.messages.map(msg =>
      this.estimateTokensFromContent(msg.content)
    );

    const total = systemTokens + toolTokens + messageTokens.reduce((a, b) => a + b, 0);

    return { total, messages: messageTokens };
  }

  /**
   * Estimate tokens from content (rough approximation).
   */
  private estimateTokensFromContent(content: string): number {
    return estimateTokenCount(content);
  }

  /**
   * Estimate tokens remaining after a position.
   */
  private estimateRemainingTokens(
    messages: CacheTrackingRequest['messages'],
    fromIndex: number
  ): number {
    let tokens = 0;
    for (let i = fromIndex; i < messages.length; i++) {
      tokens += this.estimateTokensFromContent(messages[i].content);
    }
    return tokens;
  }

  /**
   * Calculate cost savings from caching.
   */
  private calculateSavings(cachedTokens: number, uncachedTokens: number): number {
    // What it would have cost without caching
    const withoutCacheCost = (cachedTokens + uncachedTokens) * this.uncachedTokenCost;

    // What it actually costs with caching
    const withCacheCost = cachedTokens * this.cachedTokenCost + uncachedTokens * this.uncachedTokenCost;

    return withoutCacheCost - withCacheCost;
  }

  /**
   * Calculate trend from hit rate history.
   */
  private calculateTrend(hitRates: number[]): CacheAnalysis['trend'] {
    if (hitRates.length < 3) return 'stable';

    // Compare first half to second half
    const midpoint = Math.floor(hitRates.length / 2);
    const firstHalf = hitRates.slice(0, midpoint);
    const secondHalf = hitRates.slice(midpoint);

    const firstAvg = firstHalf.reduce((a, b) => a + b, 0) / firstHalf.length;
    const secondAvg = secondHalf.reduce((a, b) => a + b, 0) / secondHalf.length;

    const diff = secondAvg - firstAvg;

    if (diff > 0.05) return 'improving';
    if (diff < -0.05) return 'declining';
    return 'stable';
  }

  /**
   * Generate recommendations based on analysis.
   */
  private generateRecommendations(
    hitRate: number,
    breakpoints: CacheAnalysis['commonBreakpoints'],
    trend: CacheAnalysis['trend']
  ): string[] {
    const recommendations: string[] = [];

    if (hitRate < 0.5) {
      recommendations.push('Cache hit rate is low (<50%). Consider stabilizing system prompts.');
    }

    if (hitRate < 0.3) {
      recommendations.push('Very low cache efficiency. Check for timestamps or dynamic content at the start of prompts.');
    }

    // Check for common breakpoint types
    const dynamicBreaks = breakpoints.find(b => b.type === 'dynamic_content');
    if (dynamicBreaks && dynamicBreaks.count > 2) {
      recommendations.push('Frequent dynamic content changes detected. Move variable content to the end of prompts.');
    }

    const contentChanges = breakpoints.find(b => b.type === 'content_change');
    if (contentChanges && contentChanges.count > 3) {
      recommendations.push('Message content is being modified. Ensure append-only message history.');
    }

    if (trend === 'declining') {
      recommendations.push('Cache efficiency is declining over time. Review recent prompt structure changes.');
    }

    if (recommendations.length === 0 && hitRate > 0.7) {
      recommendations.push('Good cache efficiency! Current patterns are working well.');
    }

    return recommendations;
  }

  /**
   * Simple hash function for content comparison.
   */
  private hashContent(content: string): string {
    let hash = 0;
    for (let i = 0; i < content.length; i++) {
      const char = content.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash = hash & hash;
    }
    return hash.toString(16);
  }
}

// =============================================================================
// FACTORY FUNCTION
// =============================================================================

/**
 * Create a new cache boundary tracker.
 */
export function createCacheBoundaryTracker(): CacheBoundaryTracker {
  return new CacheBoundaryTracker();
}
