/**
 * Lesson 19: Exporter
 *
 * Export observability data in various formats.
 * Supports console, JSON, JSONL, and OTLP-style output.
 */

import { writeFile, appendFile } from 'fs/promises';
import type {
  Exporter,
  ExporterConfig,
  ExportFormat,
  Span,
  MetricPoint,
  LogEntry,
  ObservabilityEvent,
  ObservabilityEventListener,
} from './types.js';

// =============================================================================
// CONSOLE EXPORTER
// =============================================================================

/**
 * Exports to console with human-readable formatting.
 */
export class ConsoleExporter implements Exporter {
  private colors: boolean;

  constructor(colors = true) {
    this.colors = colors;
  }

  async exportSpans(spans: Span[]): Promise<void> {
    for (const span of spans) {
      const status = span.status.code === 'ok' ? '✓' : span.status.code === 'error' ? '✗' : '○';
      const duration = span.duration !== undefined ? `${span.duration}ms` : 'ongoing';

      console.log(
        `${this.colorize('cyan', `[SPAN]`)} ${status} ${span.name} (${duration})`
      );

      if (Object.keys(span.attributes).length > 0) {
        console.log(`  Attributes: ${JSON.stringify(span.attributes)}`);
      }

      for (const event of span.events) {
        console.log(`  Event: ${event.name} @ ${new Date(event.timestamp).toISOString()}`);
      }
    }
  }

  async exportMetrics(metrics: MetricPoint[]): Promise<void> {
    for (const metric of metrics) {
      const labels = Object.entries(metric.labels)
        .map(([k, v]) => `${k}=${v}`)
        .join(', ');

      console.log(
        `${this.colorize('yellow', `[METRIC]`)} ${metric.name}: ${metric.value}` +
        (labels ? ` {${labels}}` : '')
      );
    }
  }

  async exportLogs(logs: LogEntry[]): Promise<void> {
    for (const log of logs) {
      const levelColor = {
        debug: 'gray',
        info: 'blue',
        warn: 'yellow',
        error: 'red',
        fatal: 'magenta',
      }[log.level] as string;

      const timestamp = new Date(log.timestamp).toISOString();
      const level = log.level.toUpperCase().padEnd(5);

      console.log(
        `${this.colorize(levelColor, `[${level}]`)} ${timestamp} ${log.message}`
      );

      if (log.error) {
        console.log(`  Error: ${log.error.name}: ${log.error.message}`);
      }
    }
  }

  async flush(): Promise<void> {
    // Console output is immediate
  }

  private colorize(color: string, text: string): string {
    if (!this.colors) return text;

    const codes: Record<string, string> = {
      gray: '\x1b[90m',
      red: '\x1b[31m',
      yellow: '\x1b[33m',
      blue: '\x1b[34m',
      magenta: '\x1b[35m',
      cyan: '\x1b[36m',
      reset: '\x1b[0m',
    };

    return `${codes[color] || ''}${text}${codes.reset}`;
  }
}

// =============================================================================
// JSON EXPORTER
// =============================================================================

/**
 * Exports to JSON format.
 */
export class JSONExporter implements Exporter {
  private filePath: string | null;
  private pretty: boolean;

  constructor(filePath: string | null = null, pretty = false) {
    this.filePath = filePath;
    this.pretty = pretty;
  }

  async exportSpans(spans: Span[]): Promise<void> {
    const data = {
      type: 'spans',
      timestamp: Date.now(),
      data: spans,
    };
    await this.output(data);
  }

  async exportMetrics(metrics: MetricPoint[]): Promise<void> {
    const data = {
      type: 'metrics',
      timestamp: Date.now(),
      data: metrics,
    };
    await this.output(data);
  }

  async exportLogs(logs: LogEntry[]): Promise<void> {
    const data = {
      type: 'logs',
      timestamp: Date.now(),
      data: logs,
    };
    await this.output(data);
  }

  async flush(): Promise<void> {
    // No batching, immediate output
  }

  private async output(data: unknown): Promise<void> {
    const json = this.pretty
      ? JSON.stringify(data, null, 2)
      : JSON.stringify(data);

    if (this.filePath) {
      await writeFile(this.filePath, json + '\n', { flag: 'a' });
    } else {
      console.log(json);
    }
  }
}

// =============================================================================
// JSONL EXPORTER
// =============================================================================

/**
 * Exports to JSON Lines format (one JSON object per line).
 */
export class JSONLExporter implements Exporter {
  private filePath: string | null;
  private buffer: string[] = [];
  private batchSize: number;

  constructor(filePath: string | null = null, batchSize = 100) {
    this.filePath = filePath;
    this.batchSize = batchSize;
  }

  async exportSpans(spans: Span[]): Promise<void> {
    for (const span of spans) {
      this.buffer.push(JSON.stringify({ type: 'span', ...span }));
    }
    await this.maybeFlush();
  }

  async exportMetrics(metrics: MetricPoint[]): Promise<void> {
    for (const metric of metrics) {
      this.buffer.push(JSON.stringify({ type: 'metric', ...metric }));
    }
    await this.maybeFlush();
  }

  async exportLogs(logs: LogEntry[]): Promise<void> {
    for (const log of logs) {
      this.buffer.push(JSON.stringify({ type: 'log', ...log }));
    }
    await this.maybeFlush();
  }

  async flush(): Promise<void> {
    if (this.buffer.length === 0) return;

    const data = this.buffer.join('\n') + '\n';
    this.buffer = [];

    if (this.filePath) {
      await appendFile(this.filePath, data);
    } else {
      console.log(data.trim());
    }
  }

  private async maybeFlush(): Promise<void> {
    if (this.buffer.length >= this.batchSize) {
      await this.flush();
    }
  }
}

// =============================================================================
// OTLP-STYLE EXPORTER
// =============================================================================

/**
 * Exports in OpenTelemetry Protocol-style format.
 */
export class OTLPExporter implements Exporter {
  private endpoint: string | null;
  private serviceName: string;
  private buffer: unknown[] = [];
  private batchSize: number;

  constructor(
    endpoint: string | null = null,
    serviceName = 'agent',
    batchSize = 100
  ) {
    this.endpoint = endpoint;
    this.serviceName = serviceName;
    this.batchSize = batchSize;
  }

  async exportSpans(spans: Span[]): Promise<void> {
    const resourceSpans = {
      resource: {
        attributes: [
          { key: 'service.name', value: { stringValue: this.serviceName } },
        ],
      },
      scopeSpans: [
        {
          scope: { name: 'agent-tracer', version: '1.0.0' },
          spans: spans.map((span) => this.convertSpan(span)),
        },
      ],
    };

    this.buffer.push({ resourceSpans: [resourceSpans] });
    await this.maybeFlush();
  }

  async exportMetrics(metrics: MetricPoint[]): Promise<void> {
    const resourceMetrics = {
      resource: {
        attributes: [
          { key: 'service.name', value: { stringValue: this.serviceName } },
        ],
      },
      scopeMetrics: [
        {
          scope: { name: 'agent-metrics', version: '1.0.0' },
          metrics: metrics.map((m) => this.convertMetric(m)),
        },
      ],
    };

    this.buffer.push({ resourceMetrics: [resourceMetrics] });
    await this.maybeFlush();
  }

  async exportLogs(logs: LogEntry[]): Promise<void> {
    const resourceLogs = {
      resource: {
        attributes: [
          { key: 'service.name', value: { stringValue: this.serviceName } },
        ],
      },
      scopeLogs: [
        {
          scope: { name: 'agent-logger', version: '1.0.0' },
          logRecords: logs.map((l) => this.convertLog(l)),
        },
      ],
    };

    this.buffer.push({ resourceLogs: [resourceLogs] });
    await this.maybeFlush();
  }

  async flush(): Promise<void> {
    if (this.buffer.length === 0) return;

    const data = this.buffer;
    this.buffer = [];

    if (this.endpoint) {
      // In production, would send HTTP request
      console.log(`[OTLP] Would send to ${this.endpoint}:`, JSON.stringify(data, null, 2));
    } else {
      console.log('[OTLP]', JSON.stringify(data, null, 2));
    }
  }

  private async maybeFlush(): Promise<void> {
    if (this.buffer.length >= this.batchSize) {
      await this.flush();
    }
  }

  private convertSpan(span: Span): unknown {
    return {
      traceId: span.traceId,
      spanId: span.spanId,
      parentSpanId: span.parentId,
      name: span.name,
      kind: this.convertSpanKind(span.kind),
      startTimeUnixNano: span.startTime * 1000000,
      endTimeUnixNano: span.endTime ? span.endTime * 1000000 : undefined,
      attributes: this.convertAttributes(span.attributes),
      status: {
        code: span.status.code === 'ok' ? 1 : span.status.code === 'error' ? 2 : 0,
        message: span.status.message,
      },
      events: span.events.map((e) => ({
        name: e.name,
        timeUnixNano: e.timestamp * 1000000,
        attributes: e.attributes ? this.convertAttributes(e.attributes) : [],
      })),
    };
  }

  private convertMetric(metric: MetricPoint): unknown {
    return {
      name: metric.name,
      unit: '',
      gauge: {
        dataPoints: [
          {
            asDouble: metric.value,
            timeUnixNano: metric.timestamp * 1000000,
            attributes: this.convertAttributes(
              Object.fromEntries(
                Object.entries(metric.labels).map(([k, v]) => [k, v])
              )
            ),
          },
        ],
      },
    };
  }

  private convertLog(log: LogEntry): unknown {
    return {
      timeUnixNano: log.timestamp * 1000000,
      severityNumber: this.convertSeverity(log.level),
      severityText: log.level.toUpperCase(),
      body: { stringValue: log.message },
      attributes: log.data ? this.convertAttributes(log.data as Record<string, unknown>) : [],
      traceId: log.traceId,
      spanId: log.spanId,
    };
  }

  private convertSpanKind(kind: string): number {
    const kinds: Record<string, number> = {
      internal: 1,
      server: 2,
      client: 3,
      producer: 4,
      consumer: 5,
    };
    return kinds[kind] || 0;
  }

  private convertSeverity(level: string): number {
    const severities: Record<string, number> = {
      debug: 5,
      info: 9,
      warn: 13,
      error: 17,
      fatal: 21,
    };
    return severities[level] || 9;
  }

  private convertAttributes(attrs: Record<string, unknown>): unknown[] {
    return Object.entries(attrs).map(([key, value]) => ({
      key,
      value: this.convertValue(value),
    }));
  }

  private convertValue(value: unknown): unknown {
    if (typeof value === 'string') return { stringValue: value };
    if (typeof value === 'number') return { doubleValue: value };
    if (typeof value === 'boolean') return { boolValue: value };
    if (Array.isArray(value)) {
      return { arrayValue: { values: value.map((v) => this.convertValue(v)) } };
    }
    return { stringValue: String(value) };
  }
}

// =============================================================================
// COMPOSITE EXPORTER
// =============================================================================

/**
 * Exports to multiple destinations.
 */
export class CompositeExporter implements Exporter {
  private exporters: Exporter[];

  constructor(exporters: Exporter[]) {
    this.exporters = exporters;
  }

  async exportSpans(spans: Span[]): Promise<void> {
    await Promise.all(this.exporters.map((e) => e.exportSpans(spans)));
  }

  async exportMetrics(metrics: MetricPoint[]): Promise<void> {
    await Promise.all(this.exporters.map((e) => e.exportMetrics(metrics)));
  }

  async exportLogs(logs: LogEntry[]): Promise<void> {
    await Promise.all(this.exporters.map((e) => e.exportLogs(logs)));
  }

  async flush(): Promise<void> {
    await Promise.all(this.exporters.map((e) => e.flush()));
  }
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create an exporter based on config.
 */
export function createExporter(config: ExporterConfig): Exporter {
  const filePath = config.destination === 'file' ? config.filePath : null;

  switch (config.format) {
    case 'console':
      return new ConsoleExporter();
    case 'json':
      return new JSONExporter(filePath);
    case 'jsonl':
      return new JSONLExporter(filePath, config.batchSize);
    case 'otlp':
      return new OTLPExporter(config.endpoint);
    default:
      return new ConsoleExporter();
  }
}
