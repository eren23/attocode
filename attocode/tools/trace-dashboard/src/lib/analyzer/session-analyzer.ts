/**
 * Session Analyzer
 *
 * Analyzes parsed session data to extract high-level insights.
 */

import type { ParsedSession, SessionMetrics, SummarySection } from '../types.js';

/**
 * Analyzes a session and produces summary insights.
 */
export class SessionAnalyzer {
  constructor(private session: ParsedSession) {}

  /**
   * Get session status with color coding.
   */
  getStatusInfo(): { status: string; color: 'green' | 'yellow' | 'red' } {
    switch (this.session.status) {
      case 'completed':
        return { status: 'Completed', color: 'green' };
      case 'running':
        return { status: 'Running', color: 'yellow' };
      case 'failed':
        return { status: 'Failed', color: 'red' };
      case 'cancelled':
        return { status: 'Cancelled', color: 'yellow' };
      default:
        return { status: 'Unknown', color: 'yellow' };
    }
  }

  /**
   * Calculate efficiency score (0-100).
   */
  calculateEfficiencyScore(): number {
    const metrics = this.session.metrics;
    let score = 100;

    // Penalize excessive iterations
    if (metrics.iterations > 5) {
      score -= Math.min(20, (metrics.iterations - 5) * 4);
    }

    // Penalize low cache hit rate
    if (metrics.avgCacheHitRate < 0.5) {
      score -= Math.round((0.5 - metrics.avgCacheHitRate) * 40);
    }

    // Penalize errors
    score -= metrics.errors * 5;

    // Bonus for high cache hit rate
    if (metrics.avgCacheHitRate > 0.7) {
      score += 5;
    }

    return Math.max(0, Math.min(100, score));
  }

  /**
   * Get summary sections for display.
   */
  getSummarySections(): SummarySection[] {
    const metrics = this.session.metrics;
    const efficiency = this.calculateEfficiencyScore();

    return [
      {
        title: 'Overview',
        items: [
          { label: 'Task', value: this.session.task.slice(0, 60) + (this.session.task.length > 60 ? '...' : '') },
          { label: 'Model', value: this.session.model },
          { label: 'Duration', value: this.formatDuration(this.session.durationMs || 0) },
          {
            label: 'Status',
            value: this.getStatusInfo().status,
            status: this.session.status === 'completed' ? 'good' : 'warn',
          },
        ],
      },
      {
        title: 'Metrics',
        items: [
          { label: 'Iterations', value: metrics.iterations },
          { label: 'LLM Calls', value: metrics.llmCalls },
          { label: 'Tool Calls', value: metrics.toolCalls },
          { label: 'Unique Tools', value: metrics.uniqueTools },
        ],
      },
      {
        title: 'Tokens',
        items: [
          { label: 'Input', value: this.formatNumber(metrics.inputTokens) },
          { label: 'Output', value: this.formatNumber(metrics.outputTokens) },
          {
            label: 'Cache Hit Rate',
            value: `${Math.round(metrics.avgCacheHitRate * 100)}%`,
            status: metrics.avgCacheHitRate >= 0.7 ? 'good' : metrics.avgCacheHitRate >= 0.4 ? 'warn' : 'bad',
          },
          { label: 'Tokens Saved', value: this.formatNumber(metrics.tokensSavedByCache) },
        ],
      },
      {
        title: 'Cost',
        items: [
          { label: 'Total Cost', value: `$${metrics.totalCost.toFixed(4)}` },
          { label: 'Cost Saved', value: `$${metrics.costSavedByCache.toFixed(4)}` },
        ],
      },
      {
        title: 'Efficiency',
        items: [
          {
            label: 'Score',
            value: `${efficiency}/100`,
            status: efficiency >= 80 ? 'good' : efficiency >= 60 ? 'warn' : 'bad',
          },
          { label: 'Errors', value: metrics.errors, status: metrics.errors === 0 ? 'good' : 'bad' },
          { label: 'Decisions', value: metrics.decisions },
          { label: 'Subagents', value: metrics.subagentSpawns },
        ],
      },
    ];
  }

  /**
   * Get tool usage statistics.
   */
  getToolUsageStats(): Array<{ tool: string; count: number; avgDuration: number }> {
    const toolStats = new Map<string, { count: number; totalDuration: number }>();

    for (const iter of this.session.iterations) {
      for (const tool of iter.tools) {
        const existing = toolStats.get(tool.name) || { count: 0, totalDuration: 0 };
        existing.count++;
        existing.totalDuration += tool.durationMs;
        toolStats.set(tool.name, existing);
      }
    }

    return Array.from(toolStats.entries())
      .map(([tool, stats]) => ({
        tool,
        count: stats.count,
        avgDuration: Math.round(stats.totalDuration / stats.count),
      }))
      .sort((a, b) => b.count - a.count);
  }

  /**
   * Get decision statistics.
   */
  getDecisionStats(): Array<{ type: string; count: number; outcomes: Record<string, number> }> {
    const decisionStats = new Map<string, { count: number; outcomes: Record<string, number> }>();

    for (const iter of this.session.iterations) {
      for (const decision of iter.decisions) {
        const existing = decisionStats.get(decision.type) || { count: 0, outcomes: {} };
        existing.count++;
        existing.outcomes[decision.outcome] = (existing.outcomes[decision.outcome] || 0) + 1;
        decisionStats.set(decision.type, existing);
      }
    }

    return Array.from(decisionStats.entries())
      .map(([type, stats]) => ({
        type,
        count: stats.count,
        outcomes: stats.outcomes,
      }))
      .sort((a, b) => b.count - a.count);
  }

  /**
   * Get iteration progression analysis.
   */
  getIterationProgression(): Array<{
    iteration: number;
    tokens: number;
    tools: number;
    cacheHitRate: number;
    status: 'good' | 'warn' | 'bad';
  }> {
    return this.session.iterations.map(iter => {
      const totalTokens = iter.metrics.inputTokens + iter.metrics.outputTokens;
      const hasError = iter.tools.some(t => t.status === 'error');
      const status = hasError ? 'bad' : iter.metrics.cacheHitRate >= 0.5 ? 'good' : 'warn';

      return {
        iteration: iter.number,
        tokens: totalTokens,
        tools: iter.tools.length,
        cacheHitRate: iter.metrics.cacheHitRate,
        status,
      };
    });
  }

  // Helper methods
  private formatDuration(ms: number): string {
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${Math.round(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
  }

  private formatNumber(n: number): string {
    if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
    if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
    return n.toString();
  }
}

/**
 * Factory function.
 */
export function createSessionAnalyzer(session: ParsedSession): SessionAnalyzer {
  return new SessionAnalyzer(session);
}
