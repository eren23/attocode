/**
 * Lesson 23: Observability Integration
 *
 * Integrates observability (Lesson 19) into the production agent.
 * Provides tracing, metrics, and structured logging.
 */

import type { ObservabilityConfig, Span, SpanExporter, AgentMetrics } from '../types.js';

// =============================================================================
// TRACER
// =============================================================================

/**
 * Distributed tracing implementation.
 */
export class Tracer {
  private spans: Map<string, InternalSpan> = new Map();
  private currentTraceId: string | null = null;
  private spanStack: string[] = [];
  private config: NonNullable<ObservabilityConfig['tracing']>;
  private exporter: SpanExporter;

  constructor(config: NonNullable<ObservabilityConfig['tracing']>) {
    this.config = config;
    this.exporter = config.customExporter || this.createDefaultExporter(config.exporter || 'console');
  }

  /**
   * Start a new trace.
   */
  startTrace(name: string): string {
    const traceId = this.generateId();
    this.currentTraceId = traceId;

    this.startSpan(name, { isRoot: true });

    return traceId;
  }

  /**
   * Start a new span.
   */
  startSpan(name: string, options: { isRoot?: boolean; attributes?: Record<string, unknown> } = {}): string {
    const spanId = this.generateId();
    const parentId = this.spanStack[this.spanStack.length - 1];

    const span: InternalSpan = {
      traceId: this.currentTraceId || this.generateId(),
      spanId,
      parentId: options.isRoot ? undefined : parentId,
      name,
      startTime: Date.now(),
      attributes: {
        'service.name': this.config.serviceName || 'unknown',
        ...options.attributes,
      },
      events: [],
      status: 'running',
    };

    this.spans.set(spanId, span);
    this.spanStack.push(spanId);

    return spanId;
  }

  /**
   * End a span.
   */
  endSpan(spanId?: string): void {
    const id = spanId || this.spanStack[this.spanStack.length - 1];
    if (!id) return;

    const span = this.spans.get(id);
    if (span) {
      span.endTime = Date.now();
      span.status = 'completed';
    }

    // Remove from stack
    const index = this.spanStack.indexOf(id);
    if (index !== -1) {
      this.spanStack.splice(index, 1);
    }
  }

  /**
   * Add an event to the current span.
   */
  addEvent(name: string, attributes?: Record<string, unknown>): void {
    const spanId = this.spanStack[this.spanStack.length - 1];
    if (!spanId) return;

    const span = this.spans.get(spanId);
    if (span) {
      span.events.push({
        name,
        timestamp: Date.now(),
        attributes,
      });
    }
  }

  /**
   * Set attribute on current span.
   */
  setAttribute(key: string, value: unknown): void {
    const spanId = this.spanStack[this.spanStack.length - 1];
    if (!spanId) return;

    const span = this.spans.get(spanId);
    if (span) {
      span.attributes[key] = value;
    }
  }

  /**
   * Record an error on the current span.
   */
  recordError(error: Error): void {
    const spanId = this.spanStack[this.spanStack.length - 1];
    if (!spanId) return;

    const span = this.spans.get(spanId);
    if (span) {
      span.status = 'error';
      span.attributes['error'] = true;
      span.attributes['error.message'] = error.message;
      span.attributes['error.stack'] = error.stack;
    }
  }

  /**
   * End trace and export spans.
   */
  async endTrace(): Promise<void> {
    // End any remaining spans
    while (this.spanStack.length > 0) {
      this.endSpan();
    }

    // Export spans
    const spans: Span[] = Array.from(this.spans.values()).map((s) => ({
      traceId: s.traceId,
      spanId: s.spanId,
      name: s.name,
      startTime: s.startTime,
      endTime: s.endTime,
      attributes: s.attributes,
    }));

    await this.exporter.export(spans);

    // Clear
    this.spans.clear();
    this.currentTraceId = null;
  }

  /**
   * Get current trace ID.
   */
  getTraceId(): string | null {
    return this.currentTraceId;
  }

  /**
   * Execute function with span.
   */
  async withSpan<T>(name: string, fn: () => Promise<T>): Promise<T> {
    const spanId = this.startSpan(name);
    try {
      const result = await fn();
      this.endSpan(spanId);
      return result;
    } catch (err) {
      if (err instanceof Error) {
        this.recordError(err);
      }
      this.endSpan(spanId);
      throw err;
    }
  }

  /**
   * Create default exporter.
   */
  private createDefaultExporter(type: string): SpanExporter {
    return {
      export: async (spans: Span[]) => {
        if (type === 'console') {
          this.printSpanTree(spans);
        }
      },
    };
  }

  /**
   * Print span tree to console.
   */
  private printSpanTree(spans: Span[]): void {
    const root = spans.find((s) => !this.spans.get(s.spanId)?.parentId);
    if (!root) return;

    const printSpan = (span: Span, indent: string, isLast: boolean) => {
      const duration = span.endTime ? span.endTime - span.startTime : 0;
      const status = this.spans.get(span.spanId)?.status === 'error' ? '✗' : '✓';
      const prefix = isLast ? '└── ' : '├── ';

      console.log(`${indent}${prefix}${status} ${span.name} (${duration}ms)`);

      const children = spans.filter(
        (s) => this.spans.get(s.spanId)?.parentId === span.spanId
      );
      const newIndent = indent + (isLast ? '    ' : '│   ');

      children.forEach((child, i) => {
        printSpan(child, newIndent, i === children.length - 1);
      });
    };

    console.log('\n  Trace tree:');
    printSpan(root, '  ', true);
  }

  /**
   * Generate unique ID.
   */
  private generateId(): string {
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}`;
  }
}

// =============================================================================
// METRICS COLLECTOR
// =============================================================================

/**
 * Collects and aggregates metrics.
 */
export class MetricsCollector {
  private config: NonNullable<ObservabilityConfig['metrics']>;
  private counters: Map<string, number> = new Map();
  private gauges: Map<string, number> = new Map();
  private histograms: Map<string, number[]> = new Map();

  constructor(config: NonNullable<ObservabilityConfig['metrics']>) {
    this.config = config;
  }

  /**
   * Increment a counter.
   */
  increment(name: string, value = 1): void {
    const current = this.counters.get(name) || 0;
    this.counters.set(name, current + value);
  }

  /**
   * Set a gauge value.
   */
  setGauge(name: string, value: number): void {
    this.gauges.set(name, value);
  }

  /**
   * Record a histogram value.
   */
  recordHistogram(name: string, value: number): void {
    const values = this.histograms.get(name) || [];
    values.push(value);
    this.histograms.set(name, values);
  }

  /**
   * Record LLM call metrics.
   */
  recordLLMCall(inputTokens: number, outputTokens: number, durationMs: number, model: string): void {
    if (this.config.collectTokens) {
      this.increment('llm.input_tokens', inputTokens);
      this.increment('llm.output_tokens', outputTokens);
      this.increment('llm.total_tokens', inputTokens + outputTokens);
    }

    if (this.config.collectCosts) {
      const cost = this.estimateCost(model, inputTokens, outputTokens);
      this.increment('llm.estimated_cost_cents', Math.round(cost * 100));
    }

    if (this.config.collectLatencies) {
      this.recordHistogram('llm.duration_ms', durationMs);
    }

    this.increment('llm.calls');
  }

  /**
   * Record tool call metrics.
   */
  recordToolCall(tool: string, durationMs: number, success: boolean): void {
    this.increment(`tool.calls.${tool}`);
    this.increment(success ? 'tool.success' : 'tool.failure');

    if (this.config.collectLatencies) {
      this.recordHistogram(`tool.duration_ms.${tool}`, durationMs);
    }
  }

  /**
   * Get aggregated metrics.
   */
  getMetrics(): AgentMetrics {
    return {
      totalTokens: this.counters.get('llm.total_tokens') || 0,
      inputTokens: this.counters.get('llm.input_tokens') || 0,
      outputTokens: this.counters.get('llm.output_tokens') || 0,
      estimatedCost: (this.counters.get('llm.estimated_cost_cents') || 0) / 100,
      llmCalls: this.counters.get('llm.calls') || 0,
      toolCalls: this.counters.get('tool.success') || 0 + (this.counters.get('tool.failure') || 0),
      duration: this.getAverageHistogram('llm.duration_ms') * (this.counters.get('llm.calls') || 1),
    };
  }

  /**
   * Get average from histogram.
   */
  private getAverageHistogram(name: string): number {
    const values = this.histograms.get(name) || [];
    if (values.length === 0) return 0;
    return values.reduce((a, b) => a + b, 0) / values.length;
  }

  /**
   * Estimate cost based on model.
   */
  private estimateCost(model: string, inputTokens: number, outputTokens: number): number {
    const pricing: Record<string, { input: number; output: number }> = {
      'gpt-4': { input: 0.03, output: 0.06 },
      'gpt-4-turbo': { input: 0.01, output: 0.03 },
      'gpt-3.5-turbo': { input: 0.0005, output: 0.0015 },
      'claude-3-opus': { input: 0.015, output: 0.075 },
      'claude-3-sonnet': { input: 0.003, output: 0.015 },
      'claude-3-haiku': { input: 0.00025, output: 0.00125 },
    };

    // Find matching pricing
    for (const [key, price] of Object.entries(pricing)) {
      if (model.toLowerCase().includes(key)) {
        return (inputTokens / 1000) * price.input + (outputTokens / 1000) * price.output;
      }
    }

    // Default pricing
    return (inputTokens / 1000) * 0.01 + (outputTokens / 1000) * 0.03;
  }

  /**
   * Reset all metrics.
   */
  reset(): void {
    this.counters.clear();
    this.gauges.clear();
    this.histograms.clear();
  }
}

// =============================================================================
// LOGGER
// =============================================================================

/**
 * Structured logger.
 */
export class Logger {
  private config: NonNullable<ObservabilityConfig['logging']>;
  private context: Record<string, unknown> = {};

  constructor(config: NonNullable<ObservabilityConfig['logging']>) {
    this.config = config;
  }

  /**
   * Set context that will be included in all logs.
   */
  setContext(context: Record<string, unknown>): void {
    this.context = { ...this.context, ...context };
  }

  /**
   * Log at debug level.
   */
  debug(message: string, data?: Record<string, unknown>): void {
    this.log('debug', message, data);
  }

  /**
   * Log at info level.
   */
  info(message: string, data?: Record<string, unknown>): void {
    this.log('info', message, data);
  }

  /**
   * Log at warn level.
   */
  warn(message: string, data?: Record<string, unknown>): void {
    this.log('warn', message, data);
  }

  /**
   * Log at error level.
   */
  error(message: string, data?: Record<string, unknown>): void {
    this.log('error', message, data);
  }

  /**
   * Internal log method.
   */
  private log(level: string, message: string, data?: Record<string, unknown>): void {
    if (!this.shouldLog(level)) return;

    const entry = {
      timestamp: new Date().toISOString(),
      level,
      message,
      ...this.context,
      ...data,
    };

    if (this.config.structured) {
      console.log(JSON.stringify(entry));
    } else {
      const prefix = `[${entry.timestamp}] [${level.toUpperCase()}]`;
      console.log(`${prefix} ${message}`, data ? data : '');
    }
  }

  /**
   * Check if should log at level.
   */
  private shouldLog(level: string): boolean {
    const levels = ['debug', 'info', 'warn', 'error'];
    const configLevel = this.config.level || 'info';
    return levels.indexOf(level) >= levels.indexOf(configLevel);
  }
}

// =============================================================================
// OBSERVABILITY MANAGER
// =============================================================================

/**
 * Combined observability manager.
 */
export class ObservabilityManager {
  public tracer: Tracer | null = null;
  public metrics: MetricsCollector | null = null;
  public logger: Logger | null = null;

  constructor(config: ObservabilityConfig) {
    if (config.tracing?.enabled) {
      this.tracer = new Tracer(config.tracing);
    }

    if (config.metrics?.enabled) {
      this.metrics = new MetricsCollector(config.metrics);
    }

    if (config.logging?.enabled) {
      this.logger = new Logger(config.logging);
    }
  }
}

// =============================================================================
// TYPES
// =============================================================================

interface InternalSpan extends Span {
  parentId?: string;
  events: Array<{ name: string; timestamp: number; attributes?: Record<string, unknown> }>;
  status: 'running' | 'completed' | 'error';
}

// =============================================================================
// FACTORY
// =============================================================================

export function createObservabilityManager(config: ObservabilityConfig): ObservabilityManager {
  return new ObservabilityManager(config);
}
