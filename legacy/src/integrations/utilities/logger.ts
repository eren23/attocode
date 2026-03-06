/**
 * Structured Logger with Trace IDs and Multiple Sinks
 *
 * Phase 0.2: Replaces scattered console.log/error/warn with leveled,
 * traceable, configurable logging. Designed to be the single logging
 * entry point for all of attocode.
 *
 * Sinks:
 * - console: Human-readable output for development (default)
 * - memory: Ring buffer for TUI display and programmatic access
 * - file: Append to log file for production debugging
 *
 * Usage:
 *   import { logger } from '../integrations/logger.js';
 *   logger.info('Starting agent', { sessionId: '...' });
 *   logger.withTrace('req-123').warn('Retrying call');
 */

import { appendFileSync, mkdirSync } from 'fs';
import { dirname } from 'path';

// ─── Types ───────────────────────────────────────────────────────────

export type LogLevel = 'trace' | 'debug' | 'info' | 'warn' | 'error' | 'silent';

export interface LogEntry {
  timestamp: string;
  level: LogLevel;
  message: string;
  traceId?: string;
  data?: Record<string, unknown>;
}

export interface LogSink {
  write(entry: LogEntry): void;
}

export interface LoggerConfig {
  level?: LogLevel;
  sinks?: LogSink[];
  /** Default context merged into every log entry */
  defaultContext?: Record<string, unknown>;
}

// ─── Level Priority ──────────────────────────────────────────────────

const LEVEL_PRIORITY: Record<LogLevel, number> = {
  trace: 0,
  debug: 1,
  info: 2,
  warn: 3,
  error: 4,
  silent: 5,
};

// ─── Sinks ───────────────────────────────────────────────────────────

/** Console sink — human-readable, colorized output for development */
export class ConsoleSink implements LogSink {
  write(entry: LogEntry): void {
    const prefix = `[${entry.timestamp}] [${entry.level.toUpperCase()}]`;
    const traceStr = entry.traceId ? ` (${entry.traceId})` : '';
    const dataStr =
      entry.data && Object.keys(entry.data).length > 0 ? ' ' + JSON.stringify(entry.data) : '';
    const line = `${prefix}${traceStr} ${entry.message}${dataStr}`;

    switch (entry.level) {
      case 'error':
        // eslint-disable-next-line no-console
        console.error(line);
        break;
      case 'warn':
        // eslint-disable-next-line no-console
        console.warn(line);
        break;
      default:
        // eslint-disable-next-line no-console
        console.log(line);
        break;
    }
  }
}

/** Memory sink — ring buffer for TUI display and programmatic queries */
export class MemorySink implements LogSink {
  private buffer: LogEntry[] = [];
  private maxSize: number;

  constructor(maxSize = 1000) {
    this.maxSize = maxSize;
  }

  write(entry: LogEntry): void {
    this.buffer.push(entry);
    if (this.buffer.length > this.maxSize) {
      this.buffer.shift();
    }
  }

  getEntries(filter?: { level?: LogLevel; traceId?: string; limit?: number }): LogEntry[] {
    let entries = this.buffer;

    if (filter?.level) {
      const minPriority = LEVEL_PRIORITY[filter.level];
      entries = entries.filter((e) => LEVEL_PRIORITY[e.level] >= minPriority);
    }

    if (filter?.traceId) {
      entries = entries.filter((e) => e.traceId === filter.traceId);
    }

    if (filter?.limit) {
      entries = entries.slice(-filter.limit);
    }

    return entries;
  }

  clear(): void {
    this.buffer = [];
  }

  get size(): number {
    return this.buffer.length;
  }
}

/** File sink — append JSON lines to a log file */
export class FileSink implements LogSink {
  private filePath: string;
  private initialized = false;

  constructor(filePath: string) {
    this.filePath = filePath;
  }

  write(entry: LogEntry): void {
    if (!this.initialized) {
      try {
        mkdirSync(dirname(this.filePath), { recursive: true });
      } catch {
        // Directory may already exist
      }
      this.initialized = true;
    }

    try {
      appendFileSync(this.filePath, JSON.stringify(entry) + '\n');
    } catch {
      // Silently fail — we can't log about logging failures
    }
  }
}

// ─── Logger ──────────────────────────────────────────────────────────

export class StructuredLogger {
  private minLevel: LogLevel;
  private sinks: LogSink[];
  private defaultContext: Record<string, unknown>;
  private traceId?: string;

  constructor(config: LoggerConfig = {}) {
    this.minLevel = config.level ?? 'info';
    this.sinks = config.sinks ?? [new ConsoleSink()];
    this.defaultContext = config.defaultContext ?? {};
  }

  /** Create a child logger with a bound trace ID */
  withTrace(traceId: string): StructuredLogger {
    const child = new StructuredLogger({
      level: this.minLevel,
      sinks: this.sinks,
      defaultContext: this.defaultContext,
    });
    child.traceId = traceId;
    return child;
  }

  /** Create a child logger with additional default context */
  withContext(context: Record<string, unknown>): StructuredLogger {
    const child = new StructuredLogger({
      level: this.minLevel,
      sinks: this.sinks,
      defaultContext: { ...this.defaultContext, ...context },
    });
    child.traceId = this.traceId;
    return child;
  }

  /** Update the minimum log level at runtime */
  setLevel(level: LogLevel): void {
    this.minLevel = level;
  }

  /** Add a sink at runtime (e.g., add file sink after config is loaded) */
  addSink(sink: LogSink): void {
    this.sinks.push(sink);
  }

  trace(message: string, data?: Record<string, unknown>): void {
    this.log('trace', message, data);
  }

  debug(message: string, data?: Record<string, unknown>): void {
    this.log('debug', message, data);
  }

  info(message: string, data?: Record<string, unknown>): void {
    this.log('info', message, data);
  }

  warn(message: string, data?: Record<string, unknown>): void {
    this.log('warn', message, data);
  }

  error(message: string, data?: Record<string, unknown>): void {
    this.log('error', message, data);
  }

  private log(level: LogLevel, message: string, data?: Record<string, unknown>): void {
    if (LEVEL_PRIORITY[level] < LEVEL_PRIORITY[this.minLevel]) {
      return;
    }

    const entry: LogEntry = {
      timestamp: new Date().toISOString(),
      level,
      message,
      ...(this.traceId && { traceId: this.traceId }),
      ...(data || Object.keys(this.defaultContext).length > 0
        ? { data: { ...this.defaultContext, ...data } }
        : {}),
    };

    for (const sink of this.sinks) {
      try {
        sink.write(entry);
      } catch {
        // Never let a sink failure crash the application
      }
    }
  }
}

// ─── Global singleton ────────────────────────────────────────────────

/**
 * Global logger instance. Defaults to console sink at 'info' level.
 * Call `configureLogger()` early in startup to customize.
 */
export let logger = new StructuredLogger();

/**
 * Reconfigure the global logger. Call this at startup once config is known.
 *
 * Example:
 *   configureLogger({
 *     level: 'debug',
 *     sinks: [new ConsoleSink(), new FileSink('.agent/logs/agent.log')],
 *   });
 */
export function configureLogger(config: LoggerConfig): void {
  logger = new StructuredLogger(config);
}

/**
 * Create a logger for a specific component (adds component name to context).
 *
 * Example:
 *   const log = createComponentLogger('SwarmOrchestrator');
 *   log.info('Starting decomposition', { taskCount: 5 });
 */
export function createComponentLogger(component: string): StructuredLogger {
  return logger.withContext({ component });
}
