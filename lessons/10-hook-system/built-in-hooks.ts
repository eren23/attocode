/**
 * Lesson 10: Built-in Hooks
 *
 * Default hooks that provide common functionality:
 * - Logging: Structured logging of all events
 * - Metrics: Performance and usage tracking
 * - Validation: Input/output validation
 * - Security: Dangerous operation blocking
 *
 * These demonstrate how to build useful hooks and serve
 * as examples for creating custom hooks.
 */

import chalk from 'chalk';
import type {
  Hook,
  AgentEvent,
  AgentEventType,
  LoggingHookConfig,
  MetricsHookConfig,
  Metric,
  ToolBeforeEvent,
} from './types.js';
import { HookRegistry } from './hook-registry.js';

// =============================================================================
// LOGGING HOOK
// =============================================================================

/**
 * Default log formatter that creates human-readable output.
 */
function defaultFormatter(event: AgentEvent): string {
  const timestamp = new Date().toISOString();

  switch (event.type) {
    case 'tool.before':
      return `${timestamp} ${chalk.blue('TOOL')} ${chalk.yellow(event.tool)} called with args: ${JSON.stringify(event.args)}`;

    case 'tool.after':
      return `${timestamp} ${chalk.blue('TOOL')} ${chalk.green(event.tool)} completed in ${event.durationMs}ms`;

    case 'tool.error':
      return `${timestamp} ${chalk.red('ERROR')} Tool ${event.tool} failed: ${event.error.message}`;

    case 'session.start':
      return `${timestamp} ${chalk.magenta('SESSION')} Started: ${event.sessionId}`;

    case 'session.end':
      return `${timestamp} ${chalk.magenta('SESSION')} Ended: ${event.sessionId} (${event.reason})`;

    case 'message.created':
      const roleColor = event.role === 'user' ? chalk.cyan : chalk.green;
      const preview = event.content.slice(0, 50) + (event.content.length > 50 ? '...' : '');
      return `${timestamp} ${chalk.gray('MSG')} ${roleColor(event.role)}: ${preview}`;

    case 'message.streaming':
      return `${timestamp} ${chalk.gray('STREAM')} +${event.chunk.length} chars (${event.totalLength} total)`;

    case 'file.read':
      return `${timestamp} ${chalk.yellow('FILE')} Read: ${event.path} (${event.size} bytes)`;

    case 'file.edited':
      return `${timestamp} ${chalk.yellow('FILE')} ${event.operation}: ${event.path}`;

    case 'error':
      const recoverableFlag = event.recoverable ? chalk.yellow('[recoverable]') : chalk.red('[fatal]');
      return `${timestamp} ${chalk.red('ERROR')} ${recoverableFlag} ${event.error.message}`;

    case 'custom':
      return `${timestamp} ${chalk.gray('CUSTOM')} ${event.name}: ${JSON.stringify(event.data)}`;

    default:
      return `${timestamp} ${chalk.gray('EVENT')} ${JSON.stringify(event)}`;
  }
}

/**
 * Log level priorities (lower = more verbose).
 */
const LOG_LEVELS = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
};

/**
 * Map event types to log levels.
 */
const EVENT_LOG_LEVELS: Record<AgentEventType, keyof typeof LOG_LEVELS> = {
  'tool.before': 'debug',
  'tool.after': 'info',
  'tool.error': 'error',
  'session.start': 'info',
  'session.end': 'info',
  'message.created': 'debug',
  'message.streaming': 'debug',
  'file.read': 'debug',
  'file.edited': 'info',
  'error': 'error',
  'custom': 'debug',
};

/**
 * Create a logging hook that outputs formatted event logs.
 *
 * @param config - Logging configuration
 * @returns Hook definition
 */
export function createLoggingHook(
  config: Partial<LoggingHookConfig> = {}
): Hook<AgentEventType> {
  const {
    level = 'info',
    events,
    formatter = defaultFormatter,
  } = config;

  const minLevel = LOG_LEVELS[level];

  return {
    id: 'builtin:logging',
    event: 'tool.before' as AgentEventType, // Will be registered for all events
    priority: 0, // Run first
    description: 'Logs all agent events to console',
    handler: (event: AgentEvent) => {
      // Filter by event type if specified
      if (events && events.length > 0 && !events.includes(event.type)) {
        return;
      }

      // Filter by log level
      const eventLevel = EVENT_LOG_LEVELS[event.type] ?? 'debug';
      if (LOG_LEVELS[eventLevel] < minLevel) {
        return;
      }

      // Format and output
      const formatted = formatter(event);
      console.log(formatted);
    },
  };
}

/**
 * Register logging hooks for all event types.
 */
export function registerLoggingHooks(
  registry: HookRegistry,
  config: Partial<LoggingHookConfig> = {}
): () => void {
  const {
    level = 'info',
    events,
    formatter = defaultFormatter,
  } = config;

  const minLevel = LOG_LEVELS[level];
  const unsubscribers: (() => void)[] = [];

  // All event types to listen to
  const allEvents: AgentEventType[] = [
    'tool.before',
    'tool.after',
    'tool.error',
    'session.start',
    'session.end',
    'message.created',
    'message.streaming',
    'file.read',
    'file.edited',
    'error',
    'custom',
  ];

  // Filter to specified events or all
  const eventsToLog = events && events.length > 0 ? events : allEvents;

  for (const eventType of eventsToLog) {
    const eventLevel = EVENT_LOG_LEVELS[eventType] ?? 'debug';
    if (LOG_LEVELS[eventLevel] < minLevel) {
      continue;
    }

    const unsubscribe = registry.on(
      eventType,
      (event) => {
        console.log(formatter(event));
      },
      {
        priority: 0,
        description: `Log ${eventType} events`,
      }
    );

    unsubscribers.push(unsubscribe);
  }

  // Return function to unregister all
  return () => {
    for (const unsub of unsubscribers) {
      unsub();
    }
  };
}

// =============================================================================
// METRICS HOOK
// =============================================================================

/**
 * Create a metrics hook that tracks performance data.
 *
 * @param config - Metrics configuration
 * @returns Hook definition
 */
export function createMetricsHook(config: MetricsHookConfig): Hook<AgentEventType> {
  const { prefix = 'agent', onMetric } = config;

  // Track in-flight tool calls for duration measurement
  const toolStartTimes = new Map<string, number>();

  return {
    id: 'builtin:metrics',
    event: 'tool.before' as AgentEventType,
    priority: 1, // Run early but after logging
    description: 'Tracks metrics for all agent events',
    handler: (event: AgentEvent) => {
      const timestamp = new Date();

      switch (event.type) {
        case 'tool.before':
          // Record start time
          const toolId = `${event.tool}-${Date.now()}`;
          toolStartTimes.set(toolId, performance.now());

          // Emit counter metric
          onMetric({
            name: `${prefix}.tool.calls`,
            value: 1,
            type: 'counter',
            labels: { tool: event.tool },
            timestamp,
          });
          break;

        case 'tool.after':
          // Emit duration histogram
          onMetric({
            name: `${prefix}.tool.duration_ms`,
            value: event.durationMs,
            type: 'histogram',
            labels: { tool: event.tool },
            timestamp,
          });
          break;

        case 'tool.error':
          onMetric({
            name: `${prefix}.tool.errors`,
            value: 1,
            type: 'counter',
            labels: { tool: event.tool },
            timestamp,
          });
          break;

        case 'session.start':
          onMetric({
            name: `${prefix}.sessions.active`,
            value: 1,
            type: 'gauge',
            timestamp,
          });
          break;

        case 'session.end':
          onMetric({
            name: `${prefix}.sessions.active`,
            value: -1,
            type: 'gauge',
            timestamp,
          });

          if (event.summary) {
            onMetric({
              name: `${prefix}.session.duration_ms`,
              value: event.summary.durationMs,
              type: 'histogram',
              timestamp,
            });

            onMetric({
              name: `${prefix}.session.tool_calls`,
              value: event.summary.toolCalls,
              type: 'histogram',
              timestamp,
            });

            if (event.summary.tokens) {
              onMetric({
                name: `${prefix}.tokens.input`,
                value: event.summary.tokens.input,
                type: 'counter',
                timestamp,
              });
              onMetric({
                name: `${prefix}.tokens.output`,
                value: event.summary.tokens.output,
                type: 'counter',
                timestamp,
              });
            }
          }
          break;

        case 'error':
          onMetric({
            name: `${prefix}.errors`,
            value: 1,
            type: 'counter',
            labels: { recoverable: String(event.recoverable) },
            timestamp,
          });
          break;
      }
    },
  };
}

/**
 * Register metrics hooks for all event types.
 */
export function registerMetricsHooks(
  registry: HookRegistry,
  config: MetricsHookConfig
): () => void {
  const { prefix = 'agent', onMetric } = config;
  const unsubscribers: (() => void)[] = [];

  // Tool calls counter
  unsubscribers.push(
    registry.on('tool.before', () => {
      onMetric({
        name: `${prefix}.tool.calls`,
        value: 1,
        type: 'counter',
        timestamp: new Date(),
      });
    }, { priority: 1, description: 'Count tool calls' })
  );

  // Tool duration
  unsubscribers.push(
    registry.on('tool.after', (event) => {
      onMetric({
        name: `${prefix}.tool.duration_ms`,
        value: event.durationMs,
        type: 'histogram',
        labels: { tool: event.tool },
        timestamp: new Date(),
      });
    }, { priority: 1, description: 'Track tool duration' })
  );

  // Errors
  unsubscribers.push(
    registry.on('error', (event) => {
      onMetric({
        name: `${prefix}.errors`,
        value: 1,
        type: 'counter',
        labels: { recoverable: String(event.recoverable) },
        timestamp: new Date(),
      });
    }, { priority: 1, description: 'Count errors' })
  );

  return () => {
    for (const unsub of unsubscribers) {
      unsub();
    }
  };
}

// =============================================================================
// SECURITY HOOK
// =============================================================================

/**
 * Dangerous patterns to block.
 */
const DANGEROUS_PATTERNS = [
  { pattern: /\brm\s+-rf\s+\//, description: 'Recursive delete from root' },
  { pattern: /\bsudo\b/, description: 'Superuser command' },
  { pattern: /\b(chmod|chown)\s+.*\s+\//, description: 'Permission change on root' },
  { pattern: />\s*\/dev\//, description: 'Write to device' },
  { pattern: /\bdd\b.*if=.*of=\/dev\//, description: 'Direct disk write' },
  { pattern: /\bcurl\b.*\|\s*(ba)?sh/, description: 'Pipe URL to shell' },
];

/**
 * Create a security hook that blocks dangerous operations.
 *
 * @returns Hook definition for tool.before events
 */
export function createSecurityHook(): Hook<'tool.before'> {
  return {
    id: 'builtin:security',
    event: 'tool.before',
    priority: 10, // Run early to block before other hooks process
    description: 'Blocks dangerous tool operations',
    canModify: true,
    handler: (event: ToolBeforeEvent) => {
      // Only check bash/shell tools
      if (!['bash', 'shell', 'execute'].includes(event.tool.toLowerCase())) {
        return;
      }

      // Get command from args
      const command = typeof event.args === 'string'
        ? event.args
        : (event.args as any)?.command ?? '';

      // Check against dangerous patterns
      for (const { pattern, description } of DANGEROUS_PATTERNS) {
        if (pattern.test(command)) {
          console.warn(
            chalk.red(`[Security] Blocked dangerous operation: ${description}`)
          );
          console.warn(chalk.gray(`  Command: ${command}`));

          // Prevent execution
          event.preventDefault = true;
          return;
        }
      }
    },
  };
}

// =============================================================================
// VALIDATION HOOK
// =============================================================================

/**
 * Create a validation hook that ensures tool args are valid.
 *
 * @param validators - Map of tool name to validator function
 * @returns Hook definition
 */
export function createValidationHook(
  validators: Map<string, (args: unknown) => boolean | string>
): Hook<'tool.before'> {
  return {
    id: 'builtin:validation',
    event: 'tool.before',
    priority: 20, // After security, before execution
    description: 'Validates tool arguments',
    canModify: true,
    handler: (event: ToolBeforeEvent) => {
      const validator = validators.get(event.tool);
      if (!validator) {
        return; // No validator for this tool
      }

      const result = validator(event.args);

      if (result === false) {
        console.warn(
          chalk.yellow(`[Validation] Invalid args for tool ${event.tool}`)
        );
        event.preventDefault = true;
      } else if (typeof result === 'string') {
        console.warn(
          chalk.yellow(`[Validation] ${event.tool}: ${result}`)
        );
        event.preventDefault = true;
      }
    },
  };
}

// =============================================================================
// TIMING HOOK
// =============================================================================

/**
 * Track timing of tool executions.
 * This creates tool.after events with duration information.
 */
export class TimingTracker {
  private startTimes = new Map<string, number>();

  /**
   * Mark the start of a tool execution.
   */
  start(tool: string, callId?: string): string {
    const id = callId ?? `${tool}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    this.startTimes.set(id, performance.now());
    return id;
  }

  /**
   * Mark the end of a tool execution and get duration.
   */
  end(callId: string): number {
    const startTime = this.startTimes.get(callId);
    if (startTime === undefined) {
      return 0;
    }

    this.startTimes.delete(callId);
    return performance.now() - startTime;
  }

  /**
   * Clear all tracked timings.
   */
  clear(): void {
    this.startTimes.clear();
  }
}

// =============================================================================
// EXPORTS
// =============================================================================

export {
  defaultFormatter,
  LOG_LEVELS,
  EVENT_LOG_LEVELS,
  DANGEROUS_PATTERNS,
};
