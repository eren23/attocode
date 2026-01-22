/**
 * Lesson 19: Observability & Tracing Types
 *
 * Type definitions for tracing, metrics, and logging.
 */

// =============================================================================
// TRACE TYPES
// =============================================================================

/**
 * A single span in a trace.
 */
export interface Span {
  /** Unique trace identifier (shared by all spans in trace) */
  traceId: string;

  /** Unique span identifier */
  spanId: string;

  /** Parent span ID (if nested) */
  parentId?: string;

  /** Span name (operation being performed) */
  name: string;

  /** Start time (Unix timestamp ms) */
  startTime: number;

  /** End time (Unix timestamp ms) */
  endTime?: number;

  /** Duration in ms */
  duration?: number;

  /** Span kind */
  kind: SpanKind;

  /** Status */
  status: SpanStatus;

  /** Key-value attributes */
  attributes: Record<string, SpanAttributeValue>;

  /** Events that occurred during the span */
  events: SpanEvent[];

  /** Links to other spans */
  links: SpanLink[];
}

/**
 * Type of span.
 */
export type SpanKind =
  | 'internal'   // Internal operation
  | 'client'     // Client call (e.g., LLM API)
  | 'server'     // Handling incoming request
  | 'producer'   // Producing message
  | 'consumer';  // Consuming message

/**
 * Span status.
 */
export interface SpanStatus {
  code: 'ok' | 'error' | 'unset';
  message?: string;
}

/**
 * Attribute value types.
 */
export type SpanAttributeValue =
  | string
  | number
  | boolean
  | string[]
  | number[]
  | boolean[];

/**
 * An event within a span.
 */
export interface SpanEvent {
  /** Event name */
  name: string;

  /** Event timestamp */
  timestamp: number;

  /** Event attributes */
  attributes?: Record<string, SpanAttributeValue>;
}

/**
 * Link to another span.
 */
export interface SpanLink {
  /** Linked trace ID */
  traceId: string;

  /** Linked span ID */
  spanId: string;

  /** Link attributes */
  attributes?: Record<string, SpanAttributeValue>;
}

/**
 * A complete trace.
 */
export interface Trace {
  /** Trace ID */
  traceId: string;

  /** Root span */
  rootSpan: Span;

  /** All spans in the trace */
  spans: Span[];

  /** Trace-level attributes */
  attributes: Record<string, SpanAttributeValue>;

  /** When trace started */
  startTime: number;

  /** When trace ended */
  endTime?: number;

  /** Total duration */
  duration?: number;
}

// =============================================================================
// METRIC TYPES
// =============================================================================

/**
 * Agent-specific metrics.
 */
export interface AgentMetrics {
  /** Input tokens consumed */
  inputTokens: number;

  /** Output tokens generated */
  outputTokens: number;

  /** Tokens read from cache */
  cacheReadTokens: number;

  /** Tokens written to cache */
  cacheWriteTokens: number;

  /** Estimated cost in USD */
  estimatedCost: number;

  /** Number of tool calls made */
  toolCalls: number;

  /** Number of LLM API calls */
  llmCalls: number;

  /** Total duration in ms */
  duration: number;

  /** Number of errors */
  errors: number;

  /** Number of retries */
  retries: number;
}

/**
 * A metric data point.
 */
export interface MetricPoint {
  /** Metric name */
  name: string;

  /** Metric value */
  value: number;

  /** Timestamp */
  timestamp: number;

  /** Labels */
  labels: Record<string, string>;

  /** Metric type */
  type: MetricType;
}

/**
 * Types of metrics.
 */
export type MetricType =
  | 'counter'     // Monotonically increasing
  | 'gauge'       // Point-in-time value
  | 'histogram'   // Distribution of values
  | 'summary';    // Statistical summary

/**
 * Metric aggregations.
 */
export interface MetricAggregation {
  /** Sum of all values */
  sum: number;

  /** Number of data points */
  count: number;

  /** Minimum value */
  min: number;

  /** Maximum value */
  max: number;

  /** Average value */
  avg: number;

  /** Percentiles */
  percentiles: {
    p50: number;
    p90: number;
    p95: number;
    p99: number;
  };
}

// =============================================================================
// LOGGING TYPES
// =============================================================================

/**
 * Log levels.
 */
export type LogLevel = 'debug' | 'info' | 'warn' | 'error' | 'fatal';

/**
 * A log entry.
 */
export interface LogEntry {
  /** Log level */
  level: LogLevel;

  /** Log message */
  message: string;

  /** Timestamp */
  timestamp: number;

  /** Trace ID (for correlation) */
  traceId?: string;

  /** Span ID (for correlation) */
  spanId?: string;

  /** Structured data */
  data?: Record<string, unknown>;

  /** Logger name */
  logger?: string;

  /** Error details */
  error?: {
    name: string;
    message: string;
    stack?: string;
  };
}

// =============================================================================
// EXPORTER TYPES
// =============================================================================

/**
 * Export format.
 */
export type ExportFormat =
  | 'console'    // Human-readable console output
  | 'json'       // JSON format
  | 'jsonl'      // JSON Lines format
  | 'otlp';      // OpenTelemetry Protocol

/**
 * Exporter interface.
 */
export interface Exporter {
  /** Export spans */
  exportSpans(spans: Span[]): Promise<void>;

  /** Export metrics */
  exportMetrics(metrics: MetricPoint[]): Promise<void>;

  /** Export logs */
  exportLogs(logs: LogEntry[]): Promise<void>;

  /** Flush pending exports */
  flush(): Promise<void>;
}

/**
 * Exporter configuration.
 */
export interface ExporterConfig {
  /** Export format */
  format: ExportFormat;

  /** Output destination */
  destination: 'stdout' | 'file' | 'http';

  /** File path (if destination is 'file') */
  filePath?: string;

  /** HTTP endpoint (if destination is 'http') */
  endpoint?: string;

  /** Batch size */
  batchSize: number;

  /** Flush interval (ms) */
  flushIntervalMs: number;
}

// =============================================================================
// MODEL PRICING
// =============================================================================

/**
 * Pricing for different models.
 */
export interface ModelPricing {
  /** Cost per 1K input tokens */
  inputPer1k: number;

  /** Cost per 1K output tokens */
  outputPer1k: number;

  /** Cost per 1K cached tokens (if applicable) */
  cachedPer1k?: number;
}

/**
 * Known model pricing (USD).
 */
export const MODEL_PRICING: Record<string, ModelPricing> = {
  'gpt-4': {
    inputPer1k: 0.03,
    outputPer1k: 0.06,
  },
  'gpt-4-turbo': {
    inputPer1k: 0.01,
    outputPer1k: 0.03,
  },
  'gpt-3.5-turbo': {
    inputPer1k: 0.0005,
    outputPer1k: 0.0015,
  },
  'claude-3-opus': {
    inputPer1k: 0.015,
    outputPer1k: 0.075,
  },
  'claude-3-sonnet': {
    inputPer1k: 0.003,
    outputPer1k: 0.015,
  },
  'claude-3-haiku': {
    inputPer1k: 0.00025,
    outputPer1k: 0.00125,
  },
};

// =============================================================================
// CONFIGURATION
// =============================================================================

/**
 * Observability configuration.
 */
export interface ObservabilityConfig {
  /** Enable tracing */
  tracingEnabled: boolean;

  /** Enable metrics */
  metricsEnabled: boolean;

  /** Enable logging */
  loggingEnabled: boolean;

  /** Minimum log level */
  logLevel: LogLevel;

  /** Sample rate for traces (0-1) */
  sampleRate: number;

  /** Service name */
  serviceName: string;

  /** Service version */
  serviceVersion?: string;

  /** Environment (dev, staging, prod) */
  environment: string;

  /** Exporter configuration */
  exporter: ExporterConfig;
}

/**
 * Default observability configuration.
 */
export const DEFAULT_OBSERVABILITY_CONFIG: ObservabilityConfig = {
  tracingEnabled: true,
  metricsEnabled: true,
  loggingEnabled: true,
  logLevel: 'info',
  sampleRate: 1.0,
  serviceName: 'agent',
  environment: 'development',
  exporter: {
    format: 'console',
    destination: 'stdout',
    batchSize: 100,
    flushIntervalMs: 5000,
  },
};

// =============================================================================
// EVENTS
// =============================================================================

/**
 * Observability events.
 */
export type ObservabilityEvent =
  | { type: 'span.start'; span: Span }
  | { type: 'span.end'; span: Span }
  | { type: 'metric.recorded'; metric: MetricPoint }
  | { type: 'log.written'; log: LogEntry }
  | { type: 'export.completed'; format: ExportFormat; count: number };

/**
 * Event listener.
 */
export type ObservabilityEventListener = (event: ObservabilityEvent) => void;
