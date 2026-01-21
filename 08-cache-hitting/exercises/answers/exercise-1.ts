/**
 * Exercise 8: Cache Marker Injection - REFERENCE SOLUTION
 */

// =============================================================================
// TYPES
// =============================================================================

export interface Message {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface CacheControl {
  type: 'ephemeral';
}

export interface OptimizedMessage extends Message {
  cache_control?: CacheControl;
}

export interface CacheOptimizerConfig {
  minTokensForCache: number;
  maxCacheableMessages: number;
}

export interface CacheStats {
  totalHits: number;
  totalMisses: number;
  tokensFromCache: number;
  tokensFetched: number;
  estimatedSavings: number;
}

// =============================================================================
// HELPER
// =============================================================================

export function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}

// =============================================================================
// SOLUTION: CacheOptimizer
// =============================================================================

export class CacheOptimizer {
  private config: CacheOptimizerConfig;
  private stats: CacheStats;

  constructor(config: CacheOptimizerConfig) {
    this.config = config;
    this.stats = {
      totalHits: 0,
      totalMisses: 0,
      tokensFromCache: 0,
      tokensFetched: 0,
      estimatedSavings: 0,
    };
  }

  optimize(messages: Message[]): OptimizedMessage[] {
    const result: OptimizedMessage[] = [];
    let cacheableCount = 0;

    for (const message of messages) {
      const optimized: OptimizedMessage = { ...message };
      const tokens = estimateTokens(message.content);

      // Check if eligible for caching
      const isSystemMessage = message.role === 'system';
      const meetsTokenThreshold = tokens >= this.config.minTokensForCache;
      const underCacheLimit = cacheableCount < this.config.maxCacheableMessages;

      if ((isSystemMessage || meetsTokenThreshold) && underCacheLimit) {
        optimized.cache_control = { type: 'ephemeral' };
        cacheableCount++;
      }

      result.push(optimized);
    }

    return result;
  }

  recordCacheHit(tokens: number): void {
    this.stats.totalHits++;
    this.stats.tokensFromCache += tokens;
    this.updateSavings();
  }

  recordCacheMiss(tokens: number): void {
    this.stats.totalMisses++;
    this.stats.tokensFetched += tokens;
    this.updateSavings();
  }

  private updateSavings(): void {
    const totalTokens = this.stats.tokensFromCache + this.stats.tokensFetched;
    if (totalTokens > 0) {
      this.stats.estimatedSavings = (this.stats.tokensFromCache / totalTokens) * 100;
    } else {
      this.stats.estimatedSavings = 0;
    }
  }

  getStats(): CacheStats {
    return { ...this.stats };
  }

  resetStats(): void {
    this.stats = {
      totalHits: 0,
      totalMisses: 0,
      tokensFromCache: 0,
      tokensFetched: 0,
      estimatedSavings: 0,
    };
  }
}
