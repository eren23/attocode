/**
 * Agent Communication
 *
 * Event-based communication system for agents and subagents.
 * Enables loose coupling and real-time status updates.
 */

// =============================================================================
// TYPES
// =============================================================================

/**
 * Agent event types.
 */
export type AgentEventType =
  | 'session:start'
  | 'session:end'
  | 'task:start'
  | 'task:complete'
  | 'task:error'
  | 'tool:call'
  | 'tool:result'
  | 'subagent:spawn'
  | 'subagent:complete'
  | 'thinking'
  | 'response'
  | 'cache:hit'
  | 'context:compact';

/**
 * Base event structure.
 */
export interface BaseAgentEvent {
  type: AgentEventType;
  sessionId: string;
  timestamp: number;
}

/**
 * Session lifecycle events.
 */
export interface SessionStartEvent extends BaseAgentEvent {
  type: 'session:start';
  isSubagent: boolean;
  parentSessionId?: string;
}

export interface SessionEndEvent extends BaseAgentEvent {
  type: 'session:end';
  reason: 'completed' | 'error' | 'cancelled';
  stats: {
    messagesCount: number;
    toolCallsCount: number;
    totalTokens: number;
  };
}

/**
 * Task events.
 */
export interface TaskStartEvent extends BaseAgentEvent {
  type: 'task:start';
  task: string;
}

export interface TaskCompleteEvent extends BaseAgentEvent {
  type: 'task:complete';
  success: boolean;
  message: string;
  iterations: number;
}

export interface TaskErrorEvent extends BaseAgentEvent {
  type: 'task:error';
  error: string;
  stack?: string;
}

/**
 * Tool events.
 */
export interface ToolCallEvent extends BaseAgentEvent {
  type: 'tool:call';
  toolName: string;
  args: Record<string, unknown>;
}

export interface ToolResultEvent extends BaseAgentEvent {
  type: 'tool:result';
  toolName: string;
  success: boolean;
  output: string;
}

/**
 * Subagent events.
 */
export interface SubagentSpawnEvent extends BaseAgentEvent {
  type: 'subagent:spawn';
  subagentId: string;
  task: string;
}

export interface SubagentCompleteEvent extends BaseAgentEvent {
  type: 'subagent:complete';
  subagentId: string;
  success: boolean;
  message: string;
}

/**
 * Status events.
 */
export interface ThinkingEvent extends BaseAgentEvent {
  type: 'thinking';
  message: string;
}

export interface ResponseEvent extends BaseAgentEvent {
  type: 'response';
  content: string;
}

export interface CacheHitEvent extends BaseAgentEvent {
  type: 'cache:hit';
  cachedTokens: number;
  totalTokens: number;
  hitRate: number;
}

export interface ContextCompactEvent extends BaseAgentEvent {
  type: 'context:compact';
  beforeCount: number;
  afterCount: number;
  strategy: string;
}

/**
 * Union of all agent events.
 */
export type AgentEvent =
  | SessionStartEvent
  | SessionEndEvent
  | TaskStartEvent
  | TaskCompleteEvent
  | TaskErrorEvent
  | ToolCallEvent
  | ToolResultEvent
  | SubagentSpawnEvent
  | SubagentCompleteEvent
  | ThinkingEvent
  | ResponseEvent
  | CacheHitEvent
  | ContextCompactEvent;

/**
 * Event handler function type.
 */
export type EventHandler<T extends AgentEvent = AgentEvent> = (event: T) => void;

/**
 * Event filter function type.
 */
export type EventFilter = (event: AgentEvent) => boolean;

// =============================================================================
// EVENT BUS
// =============================================================================

/**
 * Central event bus for agent communication.
 *
 * Features:
 * - Type-safe event handling
 * - Event filtering
 * - Session-scoped subscriptions
 * - Event history for debugging
 *
 * @example
 * ```typescript
 * const bus = new EventBus();
 *
 * // Subscribe to all events
 * bus.subscribe(event => {
 *   console.log(`[${event.type}] ${event.sessionId}`);
 * });
 *
 * // Subscribe to specific event type
 * bus.on('tool:call', event => {
 *   console.log(`Tool called: ${event.toolName}`);
 * });
 *
 * // Emit an event
 * bus.emit({
 *   type: 'task:start',
 *   sessionId: 'session-123',
 *   timestamp: Date.now(),
 *   task: 'Read the README file',
 * });
 * ```
 */
export class EventBus {
  private handlers: Set<EventHandler> = new Set();
  private typeHandlers: Map<AgentEventType, Set<EventHandler>> = new Map();
  private history: AgentEvent[] = [];
  private maxHistorySize: number;

  constructor(options: { maxHistorySize?: number } = {}) {
    this.maxHistorySize = options.maxHistorySize ?? 1000;
  }

  /**
   * Subscribe to all events.
   */
  subscribe(handler: EventHandler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  /**
   * Subscribe to a specific event type.
   */
  on<T extends AgentEventType>(
    type: T,
    handler: EventHandler<Extract<AgentEvent, { type: T }>>
  ): () => void {
    if (!this.typeHandlers.has(type)) {
      this.typeHandlers.set(type, new Set());
    }
    this.typeHandlers.get(type)!.add(handler as EventHandler);
    return () => this.typeHandlers.get(type)?.delete(handler as EventHandler);
  }

  /**
   * Subscribe with a filter function.
   */
  subscribeFiltered(
    filter: EventFilter,
    handler: EventHandler
  ): () => void {
    const wrappedHandler: EventHandler = event => {
      if (filter(event)) {
        handler(event);
      }
    };
    this.handlers.add(wrappedHandler);
    return () => this.handlers.delete(wrappedHandler);
  }

  /**
   * Subscribe to events from a specific session.
   */
  subscribeToSession(sessionId: string, handler: EventHandler): () => void {
    return this.subscribeFiltered(
      event => event.sessionId === sessionId,
      handler
    );
  }

  /**
   * Emit an event to all subscribers.
   */
  emit(event: AgentEvent): void {
    // Add to history
    this.history.push(event);
    if (this.history.length > this.maxHistorySize) {
      this.history.shift();
    }

    // Notify global handlers
    for (const handler of this.handlers) {
      try {
        handler(event);
      } catch (error) {
        console.error('Event handler error:', error);
      }
    }

    // Notify type-specific handlers
    const typeHandlers = this.typeHandlers.get(event.type);
    if (typeHandlers) {
      for (const handler of typeHandlers) {
        try {
          handler(event);
        } catch (error) {
          console.error('Event handler error:', error);
        }
      }
    }
  }

  /**
   * Get event history.
   */
  getHistory(filter?: EventFilter): AgentEvent[] {
    if (!filter) {
      return [...this.history];
    }
    return this.history.filter(filter);
  }

  /**
   * Get events for a specific session.
   */
  getSessionHistory(sessionId: string): AgentEvent[] {
    return this.history.filter(e => e.sessionId === sessionId);
  }

  /**
   * Clear event history.
   */
  clearHistory(): void {
    this.history = [];
  }

  /**
   * Remove all handlers.
   */
  clear(): void {
    this.handlers.clear();
    this.typeHandlers.clear();
  }
}

// =============================================================================
// EVENT HELPERS
// =============================================================================

/**
 * Create a session start event.
 */
export function sessionStartEvent(
  sessionId: string,
  isSubagent: boolean,
  parentSessionId?: string
): SessionStartEvent {
  return {
    type: 'session:start',
    sessionId,
    timestamp: Date.now(),
    isSubagent,
    parentSessionId,
  };
}

/**
 * Create a session end event.
 */
export function sessionEndEvent(
  sessionId: string,
  reason: 'completed' | 'error' | 'cancelled',
  stats: SessionEndEvent['stats']
): SessionEndEvent {
  return {
    type: 'session:end',
    sessionId,
    timestamp: Date.now(),
    reason,
    stats,
  };
}

/**
 * Create a task start event.
 */
export function taskStartEvent(sessionId: string, task: string): TaskStartEvent {
  return {
    type: 'task:start',
    sessionId,
    timestamp: Date.now(),
    task,
  };
}

/**
 * Create a task complete event.
 */
export function taskCompleteEvent(
  sessionId: string,
  success: boolean,
  message: string,
  iterations: number
): TaskCompleteEvent {
  return {
    type: 'task:complete',
    sessionId,
    timestamp: Date.now(),
    success,
    message,
    iterations,
  };
}

/**
 * Create a tool call event.
 */
export function toolCallEvent(
  sessionId: string,
  toolName: string,
  args: Record<string, unknown>
): ToolCallEvent {
  return {
    type: 'tool:call',
    sessionId,
    timestamp: Date.now(),
    toolName,
    args,
  };
}

/**
 * Create a tool result event.
 */
export function toolResultEvent(
  sessionId: string,
  toolName: string,
  success: boolean,
  output: string
): ToolResultEvent {
  return {
    type: 'tool:result',
    sessionId,
    timestamp: Date.now(),
    toolName,
    success,
    output,
  };
}

/**
 * Create a cache hit event.
 */
export function cacheHitEvent(
  sessionId: string,
  cachedTokens: number,
  totalTokens: number
): CacheHitEvent {
  return {
    type: 'cache:hit',
    sessionId,
    timestamp: Date.now(),
    cachedTokens,
    totalTokens,
    hitRate: totalTokens > 0 ? cachedTokens / totalTokens : 0,
  };
}

// =============================================================================
// GLOBAL EVENT BUS
// =============================================================================

/**
 * Global event bus instance.
 */
export const globalEventBus = new EventBus();
