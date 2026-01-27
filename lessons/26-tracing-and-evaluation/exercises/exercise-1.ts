/**
 * Exercise 26: Metrics Calculator
 * Implement trace metrics aggregation and cost analysis.
 */

export interface TokenUsage {
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens?: number;
  cacheWriteTokens?: number;
}

export interface IterationTrace {
  iterationNumber: number;
  durationMs: number;
  tokens: TokenUsage;
  toolCalls: number;
}

export interface SessionMetrics {
  totalInputTokens: number;
  totalOutputTokens: number;
  totalCacheHits: number;
  cacheHitRate: number;
  estimatedCost: number;
  costSavedByCache: number;
  totalToolCalls: number;
  averageIterationDuration: number;
}

/**
 * TODO: Implement MetricsCalculator
 */
export class MetricsCalculator {
  constructor(
    private _costPer1kInput: number = 0.003,
    private _costPer1kOutput: number = 0.015,
    private _cachedCostPer1k: number = 0.0003
  ) {}

  calculate(_iterations: IterationTrace[]): SessionMetrics {
    // TODO: Aggregate all iterations into session metrics
    // Calculate totals, averages, and cost analysis
    throw new Error('TODO: Implement calculate');
  }

  calculateCost(_tokens: TokenUsage): number {
    // TODO: Calculate cost accounting for cache savings
    // cached tokens cost ~10x less than fresh tokens
    throw new Error('TODO: Implement calculateCost');
  }

  calculateCacheHitRate(_iterations: IterationTrace[]): number {
    // TODO: Calculate overall cache hit rate
    // cacheReadTokens / totalInputTokens
    throw new Error('TODO: Implement calculateCacheHitRate');
  }

  calculateCostSaved(_iterations: IterationTrace[]): number {
    // TODO: Calculate how much was saved by caching
    // (cost without cache) - (cost with cache)
    throw new Error('TODO: Implement calculateCostSaved');
  }
}
