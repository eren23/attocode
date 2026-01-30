/**
 * Token Analyzer
 *
 * Analyzes token flow and usage patterns across a session.
 */

import type { ParsedSession, TokenFlowAnalysis } from '../types.js';

/**
 * Pricing constants (Claude 3 Sonnet defaults).
 * Actual prices may vary by model and provider.
 */
const PRICING = {
  inputPer1k: 0.003,
  outputPer1k: 0.015,
  cachedPer1k: 0.0003, // ~10x cheaper
};

/**
 * Analyzes token flow in a session.
 */
export class TokenAnalyzer {
  constructor(private session: ParsedSession) {}

  /**
   * Perform full token flow analysis.
   */
  analyze(): TokenFlowAnalysis {
    return {
      perIteration: this.analyzePerIteration(),
      cumulative: this.analyzeCumulative(),
      costBreakdown: this.calculateCostBreakdown(),
    };
  }

  /**
   * Analyze tokens per iteration.
   */
  private analyzePerIteration(): TokenFlowAnalysis['perIteration'] {
    return this.session.iterations.map(iter => {
      const input = iter.metrics.inputTokens;
      const output = iter.metrics.outputTokens;
      const hitRate = iter.metrics.cacheHitRate;
      const cached = Math.round(input * hitRate);
      const fresh = input - cached;

      return {
        iteration: iter.number,
        input,
        output,
        thinking: iter.thinking?.estimatedTokens,
        cached,
        fresh,
      };
    });
  }

  /**
   * Analyze cumulative token usage.
   */
  private analyzeCumulative(): TokenFlowAnalysis['cumulative'] {
    let totalInput = 0;
    let totalOutput = 0;
    let totalCached = 0;

    return this.session.iterations.map(iter => {
      totalInput += iter.metrics.inputTokens;
      totalOutput += iter.metrics.outputTokens;
      totalCached += Math.round(iter.metrics.inputTokens * iter.metrics.cacheHitRate);

      return {
        iteration: iter.number,
        totalInput,
        totalOutput,
        totalCached,
      };
    });
  }

  /**
   * Calculate cost breakdown.
   */
  private calculateCostBreakdown(): TokenFlowAnalysis['costBreakdown'] {
    const metrics = this.session.metrics;
    const cachedTokens = metrics.tokensSavedByCache;
    const freshInput = metrics.inputTokens - cachedTokens;

    const inputCost = (freshInput / 1000) * PRICING.inputPer1k;
    const outputCost = (metrics.outputTokens / 1000) * PRICING.outputPer1k;
    const cachedCost = (cachedTokens / 1000) * PRICING.cachedPer1k;
    const totalCost = inputCost + outputCost + cachedCost;

    // What it would have cost without caching
    const fullInputCost = (metrics.inputTokens / 1000) * PRICING.inputPer1k;
    const savings = fullInputCost - inputCost - cachedCost;

    return {
      inputCost,
      outputCost,
      cachedCost,
      totalCost,
      savings,
    };
  }

  /**
   * Get token usage trend.
   */
  getTokenTrend(): 'increasing' | 'stable' | 'decreasing' {
    const iterations = this.session.iterations;
    if (iterations.length < 3) return 'stable';

    const firstHalf = iterations.slice(0, Math.floor(iterations.length / 2));
    const secondHalf = iterations.slice(Math.floor(iterations.length / 2));

    const firstAvg = firstHalf.reduce((sum, i) => sum + i.metrics.inputTokens, 0) / firstHalf.length;
    const secondAvg = secondHalf.reduce((sum, i) => sum + i.metrics.inputTokens, 0) / secondHalf.length;

    const change = (secondAvg - firstAvg) / firstAvg;
    if (change > 0.2) return 'increasing';
    if (change < -0.2) return 'decreasing';
    return 'stable';
  }

  /**
   * Get peak token usage iteration.
   */
  getPeakIteration(): { iteration: number; tokens: number } {
    let peak = { iteration: 0, tokens: 0 };

    for (const iter of this.session.iterations) {
      const total = iter.metrics.inputTokens + iter.metrics.outputTokens;
      if (total > peak.tokens) {
        peak = { iteration: iter.number, tokens: total };
      }
    }

    return peak;
  }

  /**
   * Format token count for display.
   */
  static formatTokens(count: number): string {
    if (count >= 1000000) return `${(count / 1000000).toFixed(1)}M`;
    if (count >= 1000) return `${(count / 1000).toFixed(1)}K`;
    return count.toString();
  }
}

/**
 * Factory function.
 */
export function createTokenAnalyzer(session: ParsedSession): TokenAnalyzer {
  return new TokenAnalyzer(session);
}
