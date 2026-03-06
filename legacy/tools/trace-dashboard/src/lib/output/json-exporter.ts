/**
 * JSON Exporter
 *
 * Exports trace data as structured JSON for LLM analysis.
 * Designed to produce compact, analyzable output under ~4000 tokens.
 */

import type { ParsedSession, Inefficiency } from '../types.js';

/**
 * TraceSummary for LLM analysis (mirrors src/tracing/types.ts).
 */
export interface TraceSummary {
  meta: {
    sessionId: string;
    task: string;
    model: string;
    duration: number;
    status: 'running' | 'completed' | 'failed' | 'cancelled';
    timestamp: number;
  };
  metrics: {
    iterations: number;
    totalTokens: number;
    inputTokens: number;
    outputTokens: number;
    thinkingTokens?: number;
    cacheHitRate: number;
    cost: number;
    costSaved: number;
    toolCalls: number;
    uniqueTools: number;
    errors: number;
  };
  decisionPoints: Array<{
    iteration: number;
    type: 'routing' | 'tool_selection' | 'policy' | 'plan_choice' | 'model_selection' | 'retry' | 'escalation';
    decision: string;
    outcome: 'allowed' | 'blocked' | 'modified' | 'deferred' | 'escalated';
    brief: string;
  }>;
  anomalies: Array<{
    type: string;
    severity: 'low' | 'medium' | 'high' | 'critical';
    description: string;
    evidence: string;
    iteration?: number;
  }>;
  toolPatterns: {
    frequency: Record<string, number>;
    redundantCalls: Array<{
      tool: string;
      count: number;
      iterations: number[];
    }>;
    slowTools: Array<{
      tool: string;
      avgDuration: number;
      maxDuration: number;
    }>;
  };
  iterationSummaries: Array<{
    number: number;
    action: string;
    outcome: 'success' | 'partial' | 'failure';
    tokensUsed: number;
    flags: string[];
  }>;
  codeLocations: Array<{
    component: string;
    file: string;
    relevance: 'primary' | 'secondary' | 'related';
    description: string;
  }>;
}
import { createSessionAnalyzer } from '../analyzer/session-analyzer.js';
import { createInefficiencyDetector } from '../analyzer/inefficiency-detector.js';

/**
 * Code location mapping for components.
 */
const COMPONENT_MAP: Record<string, Array<{ file: string; component: string; relevance: 'primary' | 'secondary' | 'related' }>> = {
  'excessive_iterations': [
    { file: 'src/agent.ts', component: 'ProductionAgent.run', relevance: 'primary' },
    { file: 'src/integrations/context-engineering.ts', component: 'ContextEngineering', relevance: 'secondary' },
  ],
  'cache_inefficiency': [
    { file: 'src/tracing/cache-boundary-tracker.ts', component: 'CacheBoundaryTracker', relevance: 'primary' },
  ],
  'redundant_tool_calls': [
    { file: 'src/agent.ts', component: 'executeToolCalls', relevance: 'primary' },
    { file: 'src/tricks/failure-evidence.ts', component: 'FailureEvidence', relevance: 'secondary' },
  ],
  'error_loop': [
    { file: 'src/tricks/failure-evidence.ts', component: 'FailureEvidence', relevance: 'primary' },
  ],
};

/**
 * Exports trace data as LLM-analyzable JSON.
 */
export class JSONExporter {
  private session: ParsedSession;
  private analyzer;
  private inefficiencyDetector;

  constructor(session: ParsedSession) {
    this.session = session;
    this.analyzer = createSessionAnalyzer(session);
    this.inefficiencyDetector = createInefficiencyDetector(session);
  }

  /**
   * Generate TraceSummary for LLM analysis.
   */
  generateSummary(): TraceSummary {
    const metrics = this.session.metrics;
    const inefficiencies = this.inefficiencyDetector.detect();

    return {
      meta: {
        sessionId: this.session.sessionId,
        task: this.truncate(this.session.task, 200),
        model: this.session.model,
        duration: this.session.durationMs || 0,
        status: this.session.status,
        timestamp: this.session.startTime.getTime(),
      },
      metrics: {
        iterations: metrics.iterations,
        totalTokens: metrics.inputTokens + metrics.outputTokens,
        inputTokens: metrics.inputTokens,
        outputTokens: metrics.outputTokens,
        thinkingTokens: metrics.thinkingTokens,
        cacheHitRate: metrics.avgCacheHitRate,
        cost: metrics.totalCost,
        costSaved: metrics.costSavedByCache,
        toolCalls: metrics.toolCalls,
        uniqueTools: metrics.uniqueTools,
        errors: metrics.errors,
      },
      decisionPoints: this.extractDecisionPoints(),
      anomalies: inefficiencies.map(i => ({
        type: i.type,
        severity: i.severity,
        description: i.description,
        evidence: i.evidence,
        iteration: i.iterations?.[0],
      })),
      toolPatterns: this.extractToolPatterns(),
      iterationSummaries: this.extractIterationSummaries(),
      codeLocations: this.extractCodeLocations(inefficiencies),
    };
  }

  /**
   * Export as JSON string.
   */
  export(pretty = false): string {
    const summary = this.generateSummary();
    return JSON.stringify(summary, null, pretty ? 2 : 0);
  }

  /**
   * Export full session data (larger, more detailed).
   */
  exportFull(pretty = false): string {
    return JSON.stringify(this.session, null, pretty ? 2 : 0);
  }

  /**
   * Extract key decision points.
   */
  private extractDecisionPoints(): TraceSummary['decisionPoints'] {
    const points: TraceSummary['decisionPoints'] = [];

    for (const iter of this.session.iterations) {
      for (const dec of iter.decisions) {
        points.push({
          iteration: iter.number,
          type: dec.type as TraceSummary['decisionPoints'][0]['type'],
          decision: this.truncate(dec.decision, 100),
          outcome: dec.outcome as TraceSummary['decisionPoints'][0]['outcome'],
          brief: this.truncate(dec.reasoning, 80),
        });
      }
    }

    // Limit to most important decisions
    return points.slice(0, 10);
  }

  /**
   * Extract tool usage patterns.
   */
  private extractToolPatterns(): TraceSummary['toolPatterns'] {
    const frequency: Record<string, number> = {};
    const toolIterations: Record<string, number[]> = {};
    const toolDurations: Record<string, number[]> = {};

    for (const iter of this.session.iterations) {
      for (const tool of iter.tools) {
        frequency[tool.name] = (frequency[tool.name] || 0) + 1;

        if (!toolIterations[tool.name]) toolIterations[tool.name] = [];
        toolIterations[tool.name].push(iter.number);

        if (!toolDurations[tool.name]) toolDurations[tool.name] = [];
        toolDurations[tool.name].push(tool.durationMs);
      }
    }

    // Find redundant calls (same tool 3+ times)
    const redundantCalls = Object.entries(toolIterations)
      .filter(([_, iters]) => iters.length >= 3)
      .map(([tool, iterations]) => ({
        tool,
        count: iterations.length,
        iterations,
      }));

    // Find slow tools (avg > 5s)
    const slowTools = Object.entries(toolDurations)
      .map(([tool, durations]) => ({
        tool,
        avgDuration: Math.round(durations.reduce((a, b) => a + b, 0) / durations.length),
        maxDuration: Math.max(...durations),
      }))
      .filter(t => t.avgDuration > 5000);

    return {
      frequency,
      redundantCalls,
      slowTools,
    };
  }

  /**
   * Extract per-iteration summaries.
   */
  private extractIterationSummaries(): TraceSummary['iterationSummaries'] {
    return this.session.iterations.map(iter => {
      const hasError = iter.tools.some(t => t.status === 'error');
      const hasBlocked = iter.decisions.some(d => d.outcome === 'blocked');

      const flags: string[] = [];
      if (hasError) flags.push('error');
      if (hasBlocked) flags.push('blocked');
      if (iter.thinking) flags.push('thinking');
      if (iter.metrics.cacheHitRate < 0.3) flags.push('low_cache');

      // Determine main action
      let action = 'processing';
      if (iter.tools.length > 0) {
        action = `Executed: ${iter.tools.map(t => t.name).join(', ')}`;
      } else if (iter.llm) {
        action = 'LLM response only';
      }

      return {
        number: iter.number,
        action: this.truncate(action, 60),
        outcome: hasError ? 'failure' : hasBlocked ? 'partial' : 'success',
        tokensUsed: iter.metrics.inputTokens + iter.metrics.outputTokens,
        flags,
      };
    });
  }

  /**
   * Extract code locations relevant to detected issues.
   */
  private extractCodeLocations(inefficiencies: Inefficiency[]): TraceSummary['codeLocations'] {
    const locations = new Map<string, TraceSummary['codeLocations'][0]>();

    for (const ineff of inefficiencies) {
      const componentLocations = COMPONENT_MAP[ineff.type] || [];
      for (const loc of componentLocations) {
        const key = `${loc.file}:${loc.component}`;
        if (!locations.has(key)) {
          locations.set(key, {
            component: loc.component,
            file: loc.file,
            relevance: loc.relevance,
            description: `Related to: ${ineff.type}`,
          });
        }
      }
    }

    return Array.from(locations.values());
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
export function createJSONExporter(session: ParsedSession): JSONExporter {
  return new JSONExporter(session);
}
