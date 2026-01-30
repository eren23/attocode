/**
 * Token Flow View
 *
 * Visualizes token usage patterns across a session.
 */

import type { ParsedSession, TokenFlowAnalysis } from '../types.js';
import { createTokenAnalyzer, TokenAnalyzer } from '../analyzer/token-analyzer.js';

/**
 * Token flow view data.
 */
export interface TokenFlowViewData {
  /** Per-iteration breakdown */
  perIteration: TokenFlowAnalysis['perIteration'];
  /** Cumulative totals */
  cumulative: TokenFlowAnalysis['cumulative'];
  /** Cost breakdown */
  costBreakdown: TokenFlowAnalysis['costBreakdown'];
  /** Trend analysis */
  trend: 'increasing' | 'stable' | 'decreasing';
  /** Peak iteration */
  peak: { iteration: number; tokens: number };
  /** Chart data for visualization */
  chartData: {
    labels: string[];
    inputTokens: number[];
    outputTokens: number[];
    cachedTokens: number[];
    cumulativeTotal: number[];
  };
}

/**
 * Generates token flow view data.
 */
export class TokenFlowView {
  private session: ParsedSession;
  private analyzer: TokenAnalyzer;

  constructor(session: ParsedSession) {
    this.session = session;
    this.analyzer = createTokenAnalyzer(session);
  }

  /**
   * Generate token flow view data.
   */
  generate(): TokenFlowViewData {
    const analysis = this.analyzer.analyze();

    return {
      perIteration: analysis.perIteration,
      cumulative: analysis.cumulative,
      costBreakdown: analysis.costBreakdown,
      trend: this.analyzer.getTokenTrend(),
      peak: this.analyzer.getPeakIteration(),
      chartData: this.buildChartData(analysis),
    };
  }

  /**
   * Build chart-ready data.
   */
  private buildChartData(analysis: TokenFlowAnalysis): TokenFlowViewData['chartData'] {
    return {
      labels: analysis.perIteration.map(i => `Iter ${i.iteration}`),
      inputTokens: analysis.perIteration.map(i => i.input),
      outputTokens: analysis.perIteration.map(i => i.output),
      cachedTokens: analysis.perIteration.map(i => i.cached),
      cumulativeTotal: analysis.cumulative.map(c => c.totalInput + c.totalOutput),
    };
  }

  /**
   * Generate ASCII bar chart for terminal display.
   */
  generateAsciiChart(maxWidth = 60): string[] {
    const { perIteration } = this.analyzer.analyze();
    if (perIteration.length === 0) return ['No data'];

    const maxTokens = Math.max(...perIteration.map(i => i.input + i.output));
    const lines: string[] = [];

    lines.push('Token Usage by Iteration:');
    lines.push('');

    for (const iter of perIteration) {
      const total = iter.input + iter.output;
      const barLength = Math.round((total / maxTokens) * maxWidth);
      const inputBar = Math.round((iter.input / maxTokens) * maxWidth);
      const cachedBar = Math.round((iter.cached / maxTokens) * maxWidth);

      const bar =
        '█'.repeat(Math.min(cachedBar, inputBar)) + // Cached (overlap)
        '▓'.repeat(Math.max(0, inputBar - cachedBar)) + // Fresh input
        '░'.repeat(Math.max(0, barLength - inputBar)); // Output

      const label = `Iter ${iter.iteration.toString().padStart(2)}`;
      const tokens = TokenAnalyzer.formatTokens(total).padStart(6);

      lines.push(`${label} │${bar} ${tokens}`);
    }

    lines.push('');
    lines.push('Legend: █ Cached, ▓ Fresh Input, ░ Output');

    return lines;
  }

  /**
   * Generate cache efficiency visualization.
   */
  generateCacheChart(maxWidth = 40): string[] {
    const { perIteration } = this.analyzer.analyze();
    if (perIteration.length === 0) return ['No data'];

    const lines: string[] = [];
    lines.push('Cache Hit Rate by Iteration:');
    lines.push('');

    for (const iter of perIteration) {
      const hitRate = iter.input > 0 ? iter.cached / iter.input : 0;
      const barLength = Math.round(hitRate * maxWidth);
      const bar = '█'.repeat(barLength) + '░'.repeat(maxWidth - barLength);
      const percent = `${Math.round(hitRate * 100)}%`.padStart(4);

      const label = `Iter ${iter.iteration.toString().padStart(2)}`;
      lines.push(`${label} │${bar} ${percent}`);
    }

    return lines;
  }

  /**
   * Get summary statistics.
   */
  getSummaryStats(): Record<string, string> {
    const analysis = this.analyzer.analyze();
    const metrics = this.session.metrics;

    return {
      'Total Input': TokenAnalyzer.formatTokens(metrics.inputTokens),
      'Total Output': TokenAnalyzer.formatTokens(metrics.outputTokens),
      'Total Cached': TokenAnalyzer.formatTokens(metrics.tokensSavedByCache),
      'Avg Cache Rate': `${Math.round(metrics.avgCacheHitRate * 100)}%`,
      'Total Cost': `$${analysis.costBreakdown.totalCost.toFixed(4)}`,
      'Cost Saved': `$${analysis.costBreakdown.savings.toFixed(4)}`,
      'Trend': this.analyzer.getTokenTrend(),
      'Peak': `Iter ${this.analyzer.getPeakIteration().iteration} (${TokenAnalyzer.formatTokens(this.analyzer.getPeakIteration().tokens)})`,
    };
  }
}

/**
 * Factory function.
 */
export function createTokenFlowView(session: ParsedSession): TokenFlowView {
  return new TokenFlowView(session);
}
