/**
 * Lesson 19: Logger
 *
 * Structured logging with trace correlation.
 * Supports different log levels and output formats.
 */

import type {
  LogLevel,
  LogEntry,
  ObservabilityEvent,
  ObservabilityEventListener,
} from './types.js';
import { getCurrentContext } from './tracer.js';

// =============================================================================
// LOG LEVEL ORDERING
// =============================================================================

const LOG_LEVELS: Record<LogLevel, number> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
  fatal: 4,
};

// =============================================================================
// LOGGER
// =============================================================================

/**
 * Structured logger with trace correlation.
 */
export class Logger {
  private name: string;
  private minLevel: LogLevel;
  private entries: LogEntry[] = [];
  private listeners: Set<ObservabilityEventListener> = new Set();
  private outputEnabled: boolean;
  private maxEntries: number;

  constructor(
    name = 'default',
    options: {
      minLevel?: LogLevel;
      outputEnabled?: boolean;
      maxEntries?: number;
    } = {}
  ) {
    this.name = name;
    this.minLevel = options.minLevel || 'info';
    this.outputEnabled = options.outputEnabled ?? true;
    this.maxEntries = options.maxEntries ?? 10000;
  }

  // ===========================================================================
  // LOG METHODS
  // ===========================================================================

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
  error(message: string, error?: Error, data?: Record<string, unknown>): void {
    this.log('error', message, data, error);
  }

  /**
   * Log at fatal level.
   */
  fatal(message: string, error?: Error, data?: Record<string, unknown>): void {
    this.log('fatal', message, data, error);
  }

  /**
   * Core log method.
   */
  private log(
    level: LogLevel,
    message: string,
    data?: Record<string, unknown>,
    error?: Error
  ): void {
    // Check log level
    if (LOG_LEVELS[level] < LOG_LEVELS[this.minLevel]) {
      return;
    }

    // Get trace context for correlation
    const context = getCurrentContext();

    const entry: LogEntry = {
      level,
      message,
      timestamp: Date.now(),
      traceId: context?.traceId,
      spanId: context?.spanId,
      data,
      logger: this.name,
    };

    if (error) {
      entry.error = {
        name: error.name,
        message: error.message,
        stack: error.stack,
      };
    }

    // Store entry
    this.entries.push(entry);

    // Trim if needed
    if (this.entries.length > this.maxEntries) {
      this.entries = this.entries.slice(-this.maxEntries);
    }

    // Output to console if enabled
    if (this.outputEnabled) {
      this.output(entry);
    }

    // Emit event
    this.emit({ type: 'log.written', log: entry });
  }

  /**
   * Output log entry to console.
   */
  private output(entry: LogEntry): void {
    const timestamp = new Date(entry.timestamp).toISOString();
    const level = entry.level.toUpperCase().padEnd(5);
    const traceInfo = entry.traceId ? ` [${entry.traceId.slice(0, 8)}]` : '';
    const logger = entry.logger !== 'default' ? ` (${entry.logger})` : '';

    let line = `${timestamp} ${level}${traceInfo}${logger}: ${entry.message}`;

    if (entry.data && Object.keys(entry.data).length > 0) {
      line += ` ${JSON.stringify(entry.data)}`;
    }

    if (entry.error) {
      line += `\n  Error: ${entry.error.name}: ${entry.error.message}`;
      if (entry.error.stack) {
        line += `\n  ${entry.error.stack.split('\n').slice(1, 4).join('\n  ')}`;
      }
    }

    // Use appropriate console method
    switch (entry.level) {
      case 'debug':
        console.debug(line);
        break;
      case 'info':
        console.info(line);
        break;
      case 'warn':
        console.warn(line);
        break;
      case 'error':
      case 'fatal':
        console.error(line);
        break;
    }
  }

  // ===========================================================================
  // CHILD LOGGERS
  // ===========================================================================

  /**
   * Create a child logger with a specific name.
   */
  child(name: string): Logger {
    const childName = this.name !== 'default'
      ? `${this.name}.${name}`
      : name;

    const child = new Logger(childName, {
      minLevel: this.minLevel,
      outputEnabled: this.outputEnabled,
      maxEntries: this.maxEntries,
    });

    // Share listeners
    for (const listener of this.listeners) {
      child.on(listener);
    }

    return child;
  }

  // ===========================================================================
  // CONFIGURATION
  // ===========================================================================

  /**
   * Set minimum log level.
   */
  setLevel(level: LogLevel): void {
    this.minLevel = level;
  }

  /**
   * Enable/disable console output.
   */
  setOutputEnabled(enabled: boolean): void {
    this.outputEnabled = enabled;
  }

  // ===========================================================================
  // RETRIEVAL
  // ===========================================================================

  /**
   * Get all log entries.
   */
  getEntries(): LogEntry[] {
    return [...this.entries];
  }

  /**
   * Get entries at a specific level.
   */
  getEntriesAtLevel(level: LogLevel): LogEntry[] {
    return this.entries.filter((e) => e.level === level);
  }

  /**
   * Get entries for a specific trace.
   */
  getEntriesForTrace(traceId: string): LogEntry[] {
    return this.entries.filter((e) => e.traceId === traceId);
  }

  /**
   * Get recent entries.
   */
  getRecentEntries(count = 10): LogEntry[] {
    return this.entries.slice(-count);
  }

  /**
   * Search entries by message.
   */
  searchEntries(query: string): LogEntry[] {
    const queryLower = query.toLowerCase();
    return this.entries.filter((e) =>
      e.message.toLowerCase().includes(queryLower)
    );
  }

  /**
   * Clear all entries.
   */
  clear(): void {
    this.entries = [];
  }

  // ===========================================================================
  // EVENT HANDLING
  // ===========================================================================

  /**
   * Subscribe to log events.
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
        console.error('Error in logger listener:', err);
      }
    }
  }
}

// =============================================================================
// LOG FORMATTING
// =============================================================================

/**
 * Format log entry as JSON.
 */
export function formatLogAsJSON(entry: LogEntry): string {
  return JSON.stringify(entry);
}

/**
 * Format log entry as human-readable text.
 */
export function formatLogAsText(entry: LogEntry): string {
  const timestamp = new Date(entry.timestamp).toISOString();
  const level = entry.level.toUpperCase().padEnd(5);
  const traceInfo = entry.traceId ? ` [${entry.traceId.slice(0, 8)}]` : '';

  let line = `${timestamp} ${level}${traceInfo}: ${entry.message}`;

  if (entry.data) {
    for (const [key, value] of Object.entries(entry.data)) {
      line += `\n  ${key}=${JSON.stringify(value)}`;
    }
  }

  if (entry.error) {
    line += `\n  error.name=${entry.error.name}`;
    line += `\n  error.message=${entry.error.message}`;
  }

  return line;
}

/**
 * Format multiple entries.
 */
export function formatLogs(entries: LogEntry[], format: 'json' | 'text' = 'text'): string {
  const formatter = format === 'json' ? formatLogAsJSON : formatLogAsText;
  return entries.map(formatter).join('\n');
}

// =============================================================================
// EXPORTS
// =============================================================================

export function createLogger(
  name = 'default',
  options: {
    minLevel?: LogLevel;
    outputEnabled?: boolean;
    maxEntries?: number;
  } = {}
): Logger {
  return new Logger(name, options);
}

export const globalLogger = new Logger('default', { outputEnabled: false });
