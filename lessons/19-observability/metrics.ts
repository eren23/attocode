/**
 * Lesson 19: Metrics
 *
 * Token and cost tracking for agent operations.
 * Provides counters, gauges, and histograms.
 *
 * USER CONTRIBUTION OPPORTUNITY:
 * The cost calculation logic depends on model pricing.
 * You could implement:
 * - Custom pricing for fine-tuned models
 * - Batch pricing discounts
 * - Time-based pricing adjustments
 */

import type {
  AgentMetrics,
  MetricPoint,
  MetricType,
  MetricAggregation,
  ModelPricing,
  ObservabilityEvent,
  ObservabilityEventListener,
} from './types.js';
import { MODEL_PRICING } from './types.js';

// =============================================================================
// METRICS COLLECTOR
// =============================================================================

/**
 * Collects and aggregates metrics.
 */
export class MetricsCollector {
  private metrics: Map<string, MetricPoint[]> = new Map();
  private listeners: Set<ObservabilityEventListener> = new Set();
  private labels: Record<string, string>;

  constructor(labels: Record<string, string> = {}) {
    this.labels = labels;
  }

  // ===========================================================================
  // METRIC RECORDING
  // ===========================================================================

  /**
   * Record a counter increment.
   */
  incrementCounter(name: string, value = 1, labels: Record<string, string> = {}): void {
    this.recordMetric(name, value, 'counter', labels);
  }

  /**
   * Record a gauge value.
   */
  setGauge(name: string, value: number, labels: Record<string, string> = {}): void {
    this.recordMetric(name, value, 'gauge', labels);
  }

  /**
   * Record a histogram value.
   */
  recordHistogram(name: string, value: number, labels: Record<string, string> = {}): void {
    this.recordMetric(name, value, 'histogram', labels);
  }

  /**
   * Record a metric point.
   */
  private recordMetric(
    name: string,
    value: number,
    type: MetricType,
    labels: Record<string, string>
  ): void {
    const point: MetricPoint = {
      name,
      value,
      timestamp: Date.now(),
      labels: { ...this.labels, ...labels },
      type,
    };

    if (!this.metrics.has(name)) {
      this.metrics.set(name, []);
    }
    this.metrics.get(name)!.push(point);

    this.emit({ type: 'metric.recorded', metric: point });
  }

  // ===========================================================================
  // AGENT-SPECIFIC METRICS
  // ===========================================================================

  /**
   * Record LLM call metrics.
   */
  recordLLMCall(
    model: string,
    inputTokens: number,
    outputTokens: number,
    durationMs: number,
    cached = false
  ): void {
    const labels = { model };

    this.incrementCounter('agent.llm.calls', 1, labels);
    this.incrementCounter('agent.tokens.input', inputTokens, labels);
    this.incrementCounter('agent.tokens.output', outputTokens, labels);
    this.recordHistogram('agent.llm.duration', durationMs, labels);

    if (cached) {
      this.incrementCounter('agent.tokens.cached', inputTokens, labels);
    }

    // Calculate and record cost
    const cost = this.calculateCost(model, inputTokens, outputTokens, cached);
    this.incrementCounter('agent.cost.usd', cost, labels);
  }

  /**
   * Record tool call metrics.
   */
  recordToolCall(
    toolName: string,
    durationMs: number,
    success: boolean
  ): void {
    const labels = { tool: toolName };

    this.incrementCounter('agent.tool.calls', 1, labels);
    this.recordHistogram('agent.tool.duration', durationMs, labels);

    if (success) {
      this.incrementCounter('agent.tool.success', 1, labels);
    } else {
      this.incrementCounter('agent.tool.errors', 1, labels);
    }
  }

  /**
   * Record error.
   */
  recordError(errorType: string, operation: string): void {
    this.incrementCounter('agent.errors', 1, { type: errorType, operation });
  }

  /**
   * Record retry.
   */
  recordRetry(operation: string, attempt: number): void {
    this.incrementCounter('agent.retries', 1, { operation });
    this.setGauge('agent.retry.attempt', attempt, { operation });
  }

  // ===========================================================================
  // COST CALCULATION
  // ===========================================================================

  /**
   * Calculate cost for an LLM call.
   *
   * USER CONTRIBUTION OPPORTUNITY:
   * Implement more sophisticated pricing logic here.
   * Consider:
   * - Volume discounts
   * - Fine-tuned model pricing
   * - Custom model pricing
   */
  calculateCost(
    model: string,
    inputTokens: number,
    outputTokens: number,
    cached = false
  ): number {
    // Find matching pricing
    let pricing: ModelPricing | undefined;

    for (const [key, p] of Object.entries(MODEL_PRICING)) {
      if (model.includes(key)) {
        pricing = p;
        break;
      }
    }

    if (!pricing) {
      // Default pricing for unknown models
      pricing = {
        inputPer1k: 0.01,
        outputPer1k: 0.03,
      };
    }

    const inputCost = cached && pricing.cachedPer1k !== undefined
      ? (inputTokens / 1000) * pricing.cachedPer1k
      : (inputTokens / 1000) * pricing.inputPer1k;

    const outputCost = (outputTokens / 1000) * pricing.outputPer1k;

    return inputCost + outputCost;
  }

  // ===========================================================================
  // AGGREGATION
  // ===========================================================================

  /**
   * Get aggregated metrics for a name.
   */
  getAggregation(name: string): MetricAggregation | null {
    const points = this.metrics.get(name);
    if (!points || points.length === 0) return null;

    const values = points.map((p) => p.value).sort((a, b) => a - b);
    const sum = values.reduce((a, b) => a + b, 0);

    return {
      sum,
      count: values.length,
      min: values[0],
      max: values[values.length - 1],
      avg: sum / values.length,
      percentiles: {
        p50: this.percentile(values, 50),
        p90: this.percentile(values, 90),
        p95: this.percentile(values, 95),
        p99: this.percentile(values, 99),
      },
    };
  }

  /**
   * Calculate percentile.
   */
  private percentile(sortedValues: number[], p: number): number {
    const index = Math.ceil((p / 100) * sortedValues.length) - 1;
    return sortedValues[Math.max(0, index)];
  }

  /**
   * Get agent metrics summary.
   */
  getAgentMetrics(): AgentMetrics {
    const getSum = (name: string): number => {
      const agg = this.getAggregation(name);
      return agg?.sum || 0;
    };

    const getDuration = (): number => {
      const agg = this.getAggregation('agent.llm.duration');
      return agg?.sum || 0;
    };

    return {
      inputTokens: getSum('agent.tokens.input'),
      outputTokens: getSum('agent.tokens.output'),
      cacheReadTokens: getSum('agent.tokens.cached'),
      cacheWriteTokens: 0, // Would need separate tracking
      estimatedCost: getSum('agent.cost.usd'),
      toolCalls: getSum('agent.tool.calls'),
      llmCalls: getSum('agent.llm.calls'),
      duration: getDuration(),
      errors: getSum('agent.errors'),
      retries: getSum('agent.retries'),
    };
  }

  // ===========================================================================
  // RETRIEVAL
  // ===========================================================================

  /**
   * Get all metric points for a name.
   */
  getMetricPoints(name: string): MetricPoint[] {
    return this.metrics.get(name) || [];
  }

  /**
   * Get all metric names.
   */
  getMetricNames(): string[] {
    return Array.from(this.metrics.keys());
  }

  /**
   * Get metrics within a time range.
   */
  getMetricsInRange(name: string, startTime: number, endTime: number): MetricPoint[] {
    const points = this.metrics.get(name) || [];
    return points.filter(
      (p) => p.timestamp >= startTime && p.timestamp <= endTime
    );
  }

  /**
   * Clear all metrics.
   */
  clear(): void {
    this.metrics.clear();
  }

  // ===========================================================================
  // EVENT HANDLING
  // ===========================================================================

  /**
   * Subscribe to metric events.
   */
  on(listener: ObservabilityEventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /**
   * Emit an event.
   */
  private emit(event: ObservabilityEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch (err) {
        console.error('Error in metrics listener:', err);
      }
    }
  }
}

// =============================================================================
// METRICS FORMATTING
// =============================================================================

/**
 * Format agent metrics for display.
 */
export function formatAgentMetrics(metrics: AgentMetrics): string {
  const lines: string[] = [
    'Agent Metrics:',
    `  LLM Calls: ${metrics.llmCalls}`,
    `  Tool Calls: ${metrics.toolCalls}`,
    `  Input Tokens: ${metrics.inputTokens.toLocaleString()}`,
    `  Output Tokens: ${metrics.outputTokens.toLocaleString()}`,
    `  Cached Tokens: ${metrics.cacheReadTokens.toLocaleString()}`,
    `  Estimated Cost: $${metrics.estimatedCost.toFixed(4)}`,
    `  Duration: ${metrics.duration.toFixed(0)}ms`,
    `  Errors: ${metrics.errors}`,
    `  Retries: ${metrics.retries}`,
  ];

  return lines.join('\n');
}

/**
 * Format metric aggregation for display.
 */
export function formatAggregation(name: string, agg: MetricAggregation): string {
  return [
    `${name}:`,
    `  Count: ${agg.count}`,
    `  Sum: ${agg.sum.toFixed(2)}`,
    `  Avg: ${agg.avg.toFixed(2)}`,
    `  Min: ${agg.min.toFixed(2)}`,
    `  Max: ${agg.max.toFixed(2)}`,
    `  P50: ${agg.percentiles.p50.toFixed(2)}`,
    `  P95: ${agg.percentiles.p95.toFixed(2)}`,
    `  P99: ${agg.percentiles.p99.toFixed(2)}`,
  ].join('\n');
}

// =============================================================================
// EXPORTS
// =============================================================================

export function createMetricsCollector(labels: Record<string, string> = {}): MetricsCollector {
  return new MetricsCollector(labels);
}

export const globalMetrics = new MetricsCollector();
