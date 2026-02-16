/**
 * Lesson 19: Tracer
 *
 * OpenTelemetry-style distributed tracing for agents.
 * Tracks operations as spans with parent-child relationships.
 */

import { webcrypto } from 'node:crypto';
// Use webcrypto directly - it's compatible with Web Crypto API
const crypto = webcrypto;
import { logger } from '../integrations/utilities/logger.js';

import type {
  Span,
  SpanKind,
  SpanStatus,
  SpanEvent,
  SpanAttributeValue,
  Trace,
  ObservabilityEvent,
  ObservabilityEventListener,
} from './types.js';

// =============================================================================
// ID GENERATION
// =============================================================================

/**
 * Generate a trace ID (128-bit hex string).
 */
function generateTraceId(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes).map((b) => b.toString(16).padStart(2, '0')).join('');
}

/**
 * Generate a span ID (64-bit hex string).
 */
function generateSpanId(): string {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  return Array.from(bytes).map((b) => b.toString(16).padStart(2, '0')).join('');
}

// =============================================================================
// SPAN CONTEXT
// =============================================================================

/**
 * Context for propagating trace information.
 */
export interface SpanContext {
  traceId: string;
  spanId: string;
  sampled: boolean;
}

/**
 * Current context stack (for nested spans).
 */
const contextStack: SpanContext[] = [];

/**
 * Get current span context.
 */
export function getCurrentContext(): SpanContext | undefined {
  return contextStack[contextStack.length - 1];
}

/**
 * Set current span context.
 */
function pushContext(context: SpanContext): void {
  contextStack.push(context);
}

/**
 * Remove current span context.
 */
function popContext(): SpanContext | undefined {
  return contextStack.pop();
}

// =============================================================================
// TRACER
// =============================================================================

/**
 * Creates and manages spans for distributed tracing.
 */
export class Tracer {
  private spans: Map<string, Span> = new Map();
  private traces: Map<string, Trace> = new Map();
  private listeners: Set<ObservabilityEventListener> = new Set();
  private serviceName: string;
  private sampleRate: number;

  constructor(serviceName = 'agent', sampleRate = 1.0) {
    this.serviceName = serviceName;
    this.sampleRate = sampleRate;
  }

  // ===========================================================================
  // SPAN CREATION
  // ===========================================================================

  /**
   * Start a new span.
   */
  startSpan(
    name: string,
    options: {
      kind?: SpanKind;
      attributes?: Record<string, SpanAttributeValue>;
      parent?: SpanContext;
    } = {}
  ): Span {
    const parentContext = options.parent || getCurrentContext();

    // Determine if this span should be sampled
    const sampled = parentContext?.sampled ?? Math.random() < this.sampleRate;

    const traceId = parentContext?.traceId || generateTraceId();
    const spanId = generateSpanId();

    const span: Span = {
      traceId,
      spanId,
      parentId: parentContext?.spanId,
      name,
      startTime: Date.now(),
      kind: options.kind || 'internal',
      status: { code: 'unset' },
      attributes: {
        'service.name': this.serviceName,
        ...options.attributes,
      },
      events: [],
      links: [],
    };

    this.spans.set(spanId, span);

    // Push context for nested spans
    pushContext({ traceId, spanId, sampled });

    // Ensure trace exists
    if (!this.traces.has(traceId)) {
      this.traces.set(traceId, {
        traceId,
        rootSpan: span,
        spans: [],
        attributes: {},
        startTime: span.startTime,
      });
    }

    this.traces.get(traceId)!.spans.push(span);

    this.emit({ type: 'span.start', span });

    return span;
  }

  /**
   * End a span.
   */
  endSpan(span: Span, status?: SpanStatus): void {
    span.endTime = Date.now();
    span.duration = span.endTime - span.startTime;
    span.status = status || { code: 'ok' };

    // Pop context
    popContext();

    // Update trace end time
    const trace = this.traces.get(span.traceId);
    if (trace) {
      trace.endTime = span.endTime;
      trace.duration = (trace.endTime - trace.startTime);
    }

    this.emit({ type: 'span.end', span });
  }

  /**
   * Mark span as error.
   */
  setError(span: Span, error: Error): void {
    span.status = {
      code: 'error',
      message: error.message,
    };

    this.addEvent(span, 'exception', {
      'exception.type': error.name,
      'exception.message': error.message,
      'exception.stacktrace': error.stack || '',
    });
  }

  // ===========================================================================
  // SPAN ATTRIBUTES AND EVENTS
  // ===========================================================================

  /**
   * Set span attribute.
   */
  setAttribute(span: Span, key: string, value: SpanAttributeValue): void {
    span.attributes[key] = value;
  }

  /**
   * Set multiple span attributes.
   */
  setAttributes(span: Span, attributes: Record<string, SpanAttributeValue>): void {
    Object.assign(span.attributes, attributes);
  }

  /**
   * Add an event to a span.
   */
  addEvent(
    span: Span,
    name: string,
    attributes?: Record<string, SpanAttributeValue>
  ): void {
    const event: SpanEvent = {
      name,
      timestamp: Date.now(),
      attributes,
    };
    span.events.push(event);
  }

  // ===========================================================================
  // CONVENIENCE METHODS
  // ===========================================================================

  /**
   * Wrap an async function with a span.
   */
  async withSpan<T>(
    name: string,
    fn: (span: Span) => Promise<T>,
    options: {
      kind?: SpanKind;
      attributes?: Record<string, SpanAttributeValue>;
    } = {}
  ): Promise<T> {
    const span = this.startSpan(name, options);

    try {
      const result = await fn(span);
      this.endSpan(span, { code: 'ok' });
      return result;
    } catch (error) {
      this.setError(span, error as Error);
      this.endSpan(span, { code: 'error', message: (error as Error).message });
      throw error;
    }
  }

  /**
   * Wrap a sync function with a span.
   */
  withSpanSync<T>(
    name: string,
    fn: (span: Span) => T,
    options: {
      kind?: SpanKind;
      attributes?: Record<string, SpanAttributeValue>;
    } = {}
  ): T {
    const span = this.startSpan(name, options);

    try {
      const result = fn(span);
      this.endSpan(span, { code: 'ok' });
      return result;
    } catch (error) {
      this.setError(span, error as Error);
      this.endSpan(span, { code: 'error', message: (error as Error).message });
      throw error;
    }
  }

  // ===========================================================================
  // TRACE RETRIEVAL
  // ===========================================================================

  /**
   * Get a trace by ID.
   */
  getTrace(traceId: string): Trace | undefined {
    return this.traces.get(traceId);
  }

  /**
   * Get all traces.
   */
  getAllTraces(): Trace[] {
    return Array.from(this.traces.values());
  }

  /**
   * Get a span by ID.
   */
  getSpan(spanId: string): Span | undefined {
    return this.spans.get(spanId);
  }

  /**
   * Get child spans of a span.
   */
  getChildSpans(spanId: string): Span[] {
    return Array.from(this.spans.values()).filter(
      (s) => s.parentId === spanId
    );
  }

  /**
   * Clear all traces and spans.
   */
  clear(): void {
    this.spans.clear();
    this.traces.clear();
    contextStack.length = 0;
  }

  // ===========================================================================
  // EVENT HANDLING
  // ===========================================================================

  /**
   * Subscribe to tracer events.
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
        logger.error('Error in tracer listener', { error: String(err) });
      }
    }
  }
}

// =============================================================================
// TRACE VISUALIZATION
// =============================================================================

/**
 * Format a trace as a tree.
 */
export function formatTraceTree(trace: Trace): string {
  const lines: string[] = [];
  const spanMap = new Map(trace.spans.map((s) => [s.spanId, s]));

  function formatSpan(span: Span, indent: string, isLast: boolean): void {
    const prefix = isLast ? '└── ' : '├── ';
    const duration = span.duration !== undefined ? `${span.duration}ms` : 'ongoing';
    const status = span.status.code === 'error' ? '❌' : span.status.code === 'ok' ? '✓' : '○';

    lines.push(`${indent}${prefix}${status} ${span.name} (${duration})`);

    const childIndent = indent + (isLast ? '    ' : '│   ');
    const children = trace.spans.filter((s) => s.parentId === span.spanId);

    children.forEach((child, i) => {
      formatSpan(child, childIndent, i === children.length - 1);
    });
  }

  formatSpan(trace.rootSpan, '', true);

  return lines.join('\n');
}

/**
 * Format span attributes.
 */
export function formatSpanAttributes(span: Span): string {
  return Object.entries(span.attributes)
    .map(([k, v]) => `  ${k}: ${JSON.stringify(v)}`)
    .join('\n');
}

// =============================================================================
// EXPORTS
// =============================================================================

export function createTracer(serviceName = 'agent', sampleRate = 1.0): Tracer {
  return new Tracer(serviceName, sampleRate);
}

export const globalTracer = new Tracer();
