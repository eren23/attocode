/**
 * Lesson 10: Hook & Event System Types
 *
 * Type definitions for the event bus and hook system.
 * This lesson demonstrates how to build an extensible architecture
 * that allows plugins and external code to observe and intercept
 * agent behavior without modifying core code.
 */

// =============================================================================
// AGENT EVENTS
// =============================================================================

/**
 * All events that can occur during agent execution.
 * This is a discriminated union - each event has a unique 'type' field.
 */
export type AgentEvent =
  // Tool lifecycle events
  | ToolBeforeEvent
  | ToolAfterEvent
  | ToolErrorEvent
  // Session lifecycle events
  | SessionStartEvent
  | SessionEndEvent
  // Message events
  | MessageCreatedEvent
  | MessageStreamingEvent
  // File events
  | FileReadEvent
  | FileEditedEvent
  // Error events
  | ErrorEvent
  // Custom events for extensibility
  | CustomEvent;

/**
 * Event emitted before a tool is executed.
 * Hooks can modify args or prevent execution.
 */
export interface ToolBeforeEvent {
  type: 'tool.before';
  tool: string;
  args: unknown;
  /** Set to true to prevent tool execution */
  preventDefault?: boolean;
  /** Modified args to use instead */
  modifiedArgs?: unknown;
}

/**
 * Event emitted after a tool completes.
 */
export interface ToolAfterEvent {
  type: 'tool.after';
  tool: string;
  args: unknown;
  result: unknown;
  durationMs: number;
}

/**
 * Event emitted when a tool throws an error.
 */
export interface ToolErrorEvent {
  type: 'tool.error';
  tool: string;
  args: unknown;
  error: Error;
}

/**
 * Event emitted when a session starts.
 */
export interface SessionStartEvent {
  type: 'session.start';
  sessionId: string;
  config: Record<string, unknown>;
}

/**
 * Event emitted when a session ends.
 */
export interface SessionEndEvent {
  type: 'session.end';
  sessionId: string;
  reason: 'completed' | 'error' | 'cancelled' | 'timeout';
  summary?: SessionSummary;
}

/**
 * Event emitted when a message is created.
 */
export interface MessageCreatedEvent {
  type: 'message.created';
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
}

/**
 * Event emitted during message streaming.
 */
export interface MessageStreamingEvent {
  type: 'message.streaming';
  role: 'assistant';
  chunk: string;
  totalLength: number;
}

/**
 * Event emitted when a file is read.
 */
export interface FileReadEvent {
  type: 'file.read';
  path: string;
  size: number;
}

/**
 * Event emitted when a file is edited.
 */
export interface FileEditedEvent {
  type: 'file.edited';
  path: string;
  operation: 'create' | 'modify' | 'delete';
  linesChanged?: number;
}

/**
 * Event emitted when an error occurs.
 */
export interface ErrorEvent {
  type: 'error';
  error: Error;
  context?: string;
  recoverable: boolean;
}

/**
 * Custom event for extensibility.
 * Allows plugins to define their own event types.
 */
export interface CustomEvent {
  type: 'custom';
  name: string;
  data: unknown;
}

// =============================================================================
// SESSION TYPES
// =============================================================================

/**
 * Summary of a session for the session.end event.
 */
export interface SessionSummary {
  /** Total duration in milliseconds */
  durationMs: number;
  /** Number of tool calls made */
  toolCalls: number;
  /** Number of messages exchanged */
  messages: number;
  /** Token usage if available */
  tokens?: {
    input: number;
    output: number;
    cached?: number;
  };
  /** Any errors that occurred */
  errors: Error[];
}

// =============================================================================
// HOOK TYPES
// =============================================================================

/**
 * Extract the event type string from AgentEvent.
 */
export type AgentEventType = AgentEvent['type'];

/**
 * Extract the specific event interface for a given type.
 */
export type EventOfType<T extends AgentEventType> = Extract<AgentEvent, { type: T }>;

/**
 * Hook handler function type.
 * Can be sync or async, and optionally modify the event.
 */
export type HookHandler<T extends AgentEventType> = (
  event: EventOfType<T>
) => void | Promise<void>;

/**
 * A hook definition that listens to a specific event type.
 */
export interface Hook<T extends AgentEventType = AgentEventType> {
  /** Unique identifier for this hook */
  id: string;

  /** The event type to listen for */
  event: T;

  /** The handler function */
  handler: HookHandler<T>;

  /**
   * Priority for execution order.
   * Lower numbers run first. Default is 100.
   * System hooks use 0-50, plugins use 50-150, user hooks use 150+.
   */
  priority?: number;

  /** Optional description for debugging */
  description?: string;

  /** Whether this hook can modify the event (intercepting vs observing) */
  canModify?: boolean;
}

/**
 * Options for registering a hook.
 */
export interface HookRegistrationOptions {
  /** Priority for execution order (lower runs first) */
  priority?: number;
  /** Description for debugging */
  description?: string;
  /** Whether this hook can modify events */
  canModify?: boolean;
}

// =============================================================================
// EVENT BUS TYPES
// =============================================================================

/**
 * Listener callback for the event bus.
 */
export type EventListener = (event: AgentEvent) => void | Promise<void>;

/**
 * Subscription returned when adding a listener.
 */
export interface Subscription {
  /** Unsubscribe from events */
  unsubscribe(): void;
}

/**
 * Options for emitting events.
 */
export interface EmitOptions {
  /** Wait for all handlers to complete before returning */
  waitForHandlers?: boolean;
  /** Timeout for async handlers in milliseconds */
  timeout?: number;
}

// =============================================================================
// HOOK REGISTRY TYPES
// =============================================================================

/**
 * Result of executing hooks for an event.
 */
export interface HookExecutionResult {
  /** Whether all hooks completed successfully */
  success: boolean;
  /** Number of hooks executed */
  hooksExecuted: number;
  /** Any errors that occurred */
  errors: HookError[];
  /** Total execution time in milliseconds */
  durationMs: number;
  /** Whether the event was prevented */
  prevented: boolean;
}

/**
 * Error from a hook execution.
 */
export interface HookError {
  hookId: string;
  error: Error;
  event: AgentEventType;
}

/**
 * Statistics about hook performance.
 */
export interface HookStats {
  hookId: string;
  event: AgentEventType;
  invocations: number;
  errors: number;
  totalDurationMs: number;
  averageDurationMs: number;
}

// =============================================================================
// BUILT-IN HOOK TYPES
// =============================================================================

/**
 * Configuration for the logging hook.
 */
export interface LoggingHookConfig {
  /** Log level threshold */
  level: 'debug' | 'info' | 'warn' | 'error';
  /** Events to log (empty = all events) */
  events?: AgentEventType[];
  /** Custom formatter */
  formatter?: (event: AgentEvent) => string;
}

/**
 * Configuration for the metrics hook.
 */
export interface MetricsHookConfig {
  /** Prefix for metric names */
  prefix?: string;
  /** Callback to receive metrics */
  onMetric: (metric: Metric) => void;
}

/**
 * A metric data point.
 */
export interface Metric {
  name: string;
  value: number;
  type: 'counter' | 'gauge' | 'histogram';
  labels?: Record<string, string>;
  timestamp: Date;
}

// =============================================================================
// RE-EXPORTS
// =============================================================================

export type {
  ToolResult,
  ToolDefinition,
  PermissionMode,
  DangerLevel,
} from '../03-tool-system/types.js';
