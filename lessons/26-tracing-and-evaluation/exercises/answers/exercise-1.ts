/**
 * Exercise 26: Metrics Calculator - REFERENCE SOLUTION
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

export class MetricsCalculator {
  constructor(
    private costPer1kInput: number = 0.003,
    private costPer1kOutput: number = 0.015,
    private cachedCostPer1k: number = 0.0003
  ) {}

  calculate(iterations: IterationTrace[]): SessionMetrics {
    if (iterations.length === 0) {
      return {
        totalInputTokens: 0,
        totalOutputTokens: 0,
        totalCacheHits: 0,
        cacheHitRate: 0,
        estimatedCost: 0,
        costSavedByCache: 0,
        totalToolCalls: 0,
        averageIterationDuration: 0,
      };
    }

    let totalInputTokens = 0;
    let totalOutputTokens = 0;
    let totalCacheHits = 0;
    let totalToolCalls = 0;
    let totalDuration = 0;
    let estimatedCost = 0;

    for (const iteration of iterations) {
      totalInputTokens += iteration.tokens.inputTokens;
      totalOutputTokens += iteration.tokens.outputTokens;
      totalCacheHits += iteration.tokens.cacheReadTokens ?? 0;
      totalToolCalls += iteration.toolCalls;
      totalDuration += iteration.durationMs;
      estimatedCost += this.calculateCost(iteration.tokens);
    }

    const cacheHitRate = this.calculateCacheHitRate(iterations);
    const costSavedByCache = this.calculateCostSaved(iterations);

    return {
      totalInputTokens,
      totalOutputTokens,
      totalCacheHits,
      cacheHitRate,
      estimatedCost,
      costSavedByCache,
      totalToolCalls,
      averageIterationDuration: totalDuration / iterations.length,
    };
  }

  calculateCost(tokens: TokenUsage): number {
    const cachedTokens = tokens.cacheReadTokens ?? 0;
    const freshInputTokens = tokens.inputTokens - cachedTokens;

    return (
      (freshInputTokens / 1000) * this.costPer1kInput +
      (cachedTokens / 1000) * this.cachedCostPer1k +
      (tokens.outputTokens / 1000) * this.costPer1kOutput
    );
  }

  calculateCacheHitRate(iterations: IterationTrace[]): number {
    let totalInput = 0;
    let totalCached = 0;

    for (const iteration of iterations) {
      totalInput += iteration.tokens.inputTokens;
      totalCached += iteration.tokens.cacheReadTokens ?? 0;
    }

    return totalInput > 0 ? totalCached / totalInput : 0;
  }

  calculateCostSaved(iterations: IterationTrace[]): number {
    let costWithCache = 0;
    let costWithoutCache = 0;

    for (const iteration of iterations) {
      costWithCache += this.calculateCost(iteration.tokens);
      // Cost without cache - all input tokens at full price
      costWithoutCache +=
        (iteration.tokens.inputTokens / 1000) * this.costPer1kInput +
        (iteration.tokens.outputTokens / 1000) * this.costPer1kOutput;
    }

    return costWithoutCache - costWithCache;
  }
}
