/**
 * Trace Summary Generator
 *
 * Generates structured summaries of trace sessions for LLM analysis.
 * Designed to produce compact output suitable for analysis by other LLMs.
 */

import type { SessionTrace, TraceSummary, TraceAnalysisResult } from '../tracing/types.js';

/**
 * Generates TraceSummary from SessionTrace data.
 */
export class TraceSummaryGenerator {
  private trace: SessionTrace;

  constructor(trace: SessionTrace) {
    this.trace = trace;
  }

  /**
   * Generate a compact summary for LLM analysis.
   * Target size: ~4000 tokens.
   */
  generate(): TraceSummary {
    return {
      meta: this.generateMeta(),
      metrics: this.generateMetrics(),
      decisionPoints: this.extractDecisionPoints(),
      anomalies: this.detectAnomalies(),
      toolPatterns: this.analyzeToolPatterns(),
      iterationSummaries: this.summarizeIterations(),
      codeLocations: this.mapCodeLocations(),
    };
  }

  /**
   * Generate session metadata.
   */
  private generateMeta(): TraceSummary['meta'] {
    return {
      sessionId: this.trace.sessionId,
      task: this.truncate(this.trace.task, 200),
      model: this.trace.model,
      duration: this.trace.durationMs || 0,
      status: this.trace.status,
      timestamp: this.trace.startTime,
    };
  }

  /**
   * Generate aggregated metrics.
   */
  private generateMetrics(): TraceSummary['metrics'] {
    const metrics = this.trace.metrics;

    // Count unique tools
    const toolNames = new Set<string>();
    for (const iter of this.trace.iterations) {
      for (const tool of iter.toolExecutions) {
        toolNames.add(tool.toolName);
      }
    }

    return {
      iterations: this.trace.iterations.length,
      totalTokens: metrics.inputTokens + metrics.outputTokens,
      inputTokens: metrics.inputTokens,
      outputTokens: metrics.outputTokens,
      thinkingTokens: undefined, // Would need to aggregate from iterations
      cacheHitRate: metrics.avgCacheHitRate,
      cost: metrics.estimatedCost,
      costSaved: metrics.costSavedByCache,
      toolCalls: metrics.toolCalls,
      uniqueTools: toolNames.size,
      errors: metrics.errors,
    };
  }

  /**
   * Extract key decision points from trace.
   */
  private extractDecisionPoints(): TraceSummary['decisionPoints'] {
    // This would need to read from decision trace events
    // For now, return empty array - to be populated when decisions are captured
    return [];
  }

  /**
   * Detect anomalies in the trace.
   */
  private detectAnomalies(): TraceSummary['anomalies'] {
    const anomalies: TraceSummary['anomalies'] = [];
    const metrics = this.trace.metrics;

    // Check for excessive iterations
    if (this.trace.iterations.length > 10) {
      anomalies.push({
        type: 'excessive_iterations',
        severity: 'high',
        description: `Session used ${this.trace.iterations.length} iterations, significantly above typical`,
        evidence: `Iteration count: ${this.trace.iterations.length}`,
      });
    } else if (this.trace.iterations.length > 7) {
      anomalies.push({
        type: 'excessive_iterations',
        severity: 'medium',
        description: `Session used ${this.trace.iterations.length} iterations`,
        evidence: `Iteration count: ${this.trace.iterations.length}`,
      });
    }

    // Check for low cache hit rate
    if (metrics.avgCacheHitRate < 0.3 && this.trace.iterations.length > 2) {
      anomalies.push({
        type: 'cache_inefficiency',
        severity: 'high',
        description: `Very low cache hit rate: ${Math.round(metrics.avgCacheHitRate * 100)}%`,
        evidence: `Expected >50% for multi-iteration sessions`,
      });
    } else if (metrics.avgCacheHitRate < 0.5 && this.trace.iterations.length > 3) {
      anomalies.push({
        type: 'cache_inefficiency',
        severity: 'medium',
        description: `Below-average cache hit rate: ${Math.round(metrics.avgCacheHitRate * 100)}%`,
        evidence: `Expected >50% for longer sessions`,
      });
    }

    // Check for error count
    if (metrics.errors > 3) {
      anomalies.push({
        type: 'error_loop',
        severity: 'high',
        description: `Session had ${metrics.errors} errors`,
        evidence: `Error count: ${metrics.errors}`,
      });
    }

    // Check for redundant tool calls
    const toolCallCounts = new Map<string, number>();
    for (const iter of this.trace.iterations) {
      for (const tool of iter.toolExecutions) {
        toolCallCounts.set(tool.toolName, (toolCallCounts.get(tool.toolName) || 0) + 1);
      }
    }
    for (const [tool, count] of toolCallCounts) {
      if (count >= 5) {
        anomalies.push({
          type: 'redundant_tool_calls',
          severity: count >= 8 ? 'high' : 'medium',
          description: `Tool "${tool}" called ${count} times`,
          evidence: `May indicate repetitive behavior`,
        });
      }
    }

    return anomalies;
  }

  /**
   * Analyze tool usage patterns.
   */
  private analyzeToolPatterns(): TraceSummary['toolPatterns'] {
    const frequency: Record<string, number> = {};
    const toolIterations: Record<string, number[]> = {};
    const toolDurations: Record<string, number[]> = {};

    for (const iter of this.trace.iterations) {
      for (const tool of iter.toolExecutions) {
        frequency[tool.toolName] = (frequency[tool.toolName] || 0) + 1;

        if (!toolIterations[tool.toolName]) toolIterations[tool.toolName] = [];
        toolIterations[tool.toolName].push(iter.iterationNumber);

        if (!toolDurations[tool.toolName]) toolDurations[tool.toolName] = [];
        toolDurations[tool.toolName].push(tool.durationMs);
      }
    }

    // Find redundant calls
    const redundantCalls = Object.entries(toolIterations)
      .filter(([_, iters]) => iters.length >= 3)
      .map(([tool, iterations]) => ({
        tool,
        count: iterations.length,
        iterations,
      }));

    // Find slow tools
    const slowTools = Object.entries(toolDurations)
      .map(([tool, durations]) => ({
        tool,
        avgDuration: Math.round(durations.reduce((a, b) => a + b, 0) / durations.length),
        maxDuration: Math.max(...durations),
      }))
      .filter((t) => t.avgDuration > 5000);

    return {
      frequency,
      redundantCalls,
      slowTools,
    };
  }

  /**
   * Summarize each iteration.
   */
  private summarizeIterations(): TraceSummary['iterationSummaries'] {
    return this.trace.iterations.map((iter) => {
      const hasError = iter.toolExecutions.some((t) => t.status === 'error');

      const flags: string[] = [];
      if (hasError) flags.push('error');
      if (iter.metrics.cacheHitRate < 0.3) flags.push('low_cache');

      // Determine main action
      let action = 'processing';
      if (iter.toolExecutions.length > 0) {
        action = `Tools: ${iter.toolExecutions.map((t) => t.toolName).join(', ')}`;
      }

      return {
        number: iter.iterationNumber,
        action: this.truncate(action, 60),
        outcome: hasError ? 'failure' : 'success',
        tokensUsed: iter.metrics.inputTokens + iter.metrics.outputTokens,
        flags,
      };
    });
  }

  /**
   * Map anomalies to code locations.
   */
  private mapCodeLocations(): TraceSummary['codeLocations'] {
    const anomalies = this.detectAnomalies();
    const locations: TraceSummary['codeLocations'] = [];

    const CODE_MAP: Record<
      string,
      Array<{ component: string; file: string; relevance: 'primary' | 'secondary' | 'related' }>
    > = {
      excessive_iterations: [
        { file: 'src/agent.ts', component: 'ProductionAgent.run', relevance: 'primary' },
        {
          file: 'src/integrations/context-engineering.ts',
          component: 'ContextEngineering',
          relevance: 'secondary',
        },
      ],
      cache_inefficiency: [
        {
          file: 'src/tracing/cache-boundary-tracker.ts',
          component: 'CacheBoundaryTracker',
          relevance: 'primary',
        },
      ],
      redundant_tool_calls: [
        { file: 'src/agent.ts', component: 'executeToolCalls', relevance: 'primary' },
        {
          file: 'src/tricks/failure-evidence.ts',
          component: 'FailureEvidence',
          relevance: 'secondary',
        },
      ],
      error_loop: [
        {
          file: 'src/tricks/failure-evidence.ts',
          component: 'FailureEvidence',
          relevance: 'primary',
        },
      ],
    };

    for (const anomaly of anomalies) {
      const mappings = CODE_MAP[anomaly.type] || [];
      for (const mapping of mappings) {
        // Avoid duplicates
        if (!locations.some((l) => l.file === mapping.file && l.component === mapping.component)) {
          locations.push({
            ...mapping,
            description: `Related to: ${anomaly.type}`,
          });
        }
      }
    }

    return locations;
  }

  /**
   * Truncate string to max length.
   */
  private truncate(str: string, maxLen: number): string {
    if (str.length <= maxLen) return str;
    return str.slice(0, maxLen - 3) + '...';
  }
}

/**
 * Factory function.
 */
export function createTraceSummaryGenerator(trace: SessionTrace): TraceSummaryGenerator {
  return new TraceSummaryGenerator(trace);
}
