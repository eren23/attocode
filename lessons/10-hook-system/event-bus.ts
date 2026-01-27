/**
 * Lesson 10: Event Bus
 *
 * A typed EventEmitter implementation for agent events.
 * This provides the foundation for loose coupling between
 * components - they communicate through events rather than
 * direct function calls.
 *
 * Key concepts:
 * - Type-safe event emission and subscription
 * - Async handler support
 * - Error isolation (one handler failing doesn't break others)
 * - Memory leak prevention with max listeners
 */

import type {
  AgentEvent,
  AgentEventType,
  EventOfType,
  EventListener,
  Subscription,
  EmitOptions,
} from './types.js';

// =============================================================================
// EVENT BUS IMPLEMENTATION
// =============================================================================

/**
 * Type-safe event bus for agent events.
 *
 * Example usage:
 * ```ts
 * const bus = new EventBus();
 *
 * // Subscribe to specific event type
 * bus.on('tool.before', (event) => {
 *   console.log(`Tool ${event.tool} called with`, event.args);
 * });
 *
 * // Emit an event
 * await bus.emit({ type: 'tool.before', tool: 'bash', args: { command: 'ls' } });
 * ```
 */
export class EventBus {
  // Map of event type to listeners
  private listeners: Map<AgentEventType, Set<EventListener>> = new Map();

  // Global listeners that receive all events
  private globalListeners: Set<EventListener> = new Set();

  // Maximum listeners per event type (prevents memory leaks)
  private maxListeners: number = 10;

  // Track if we're currently emitting (for reentrancy detection)
  private emitting: boolean = false;

  // =============================================================================
  // SUBSCRIPTION METHODS
  // =============================================================================

  /**
   * Subscribe to a specific event type.
   *
   * @param eventType - The event type to listen for
   * @param listener - Callback function
   * @returns Subscription object with unsubscribe method
   */
  on<T extends AgentEventType>(
    eventType: T,
    listener: (event: EventOfType<T>) => void | Promise<void>
  ): Subscription {
    let typeListeners = this.listeners.get(eventType);

    if (!typeListeners) {
      typeListeners = new Set();
      this.listeners.set(eventType, typeListeners);
    }

    // Check max listeners
    if (typeListeners.size >= this.maxListeners) {
      console.warn(
        `Warning: Possible memory leak. ${typeListeners.size} listeners for "${eventType}". ` +
          `Use setMaxListeners() to increase limit.`
      );
    }

    // Wrap to match general listener type
    const wrappedListener: EventListener = listener as EventListener;
    typeListeners.add(wrappedListener);

    // Return subscription with unsubscribe
    return {
      unsubscribe: () => {
        typeListeners?.delete(wrappedListener);
      },
    };
  }

  /**
   * Subscribe to a specific event type for only the next occurrence.
   *
   * @param eventType - The event type to listen for
   * @param listener - Callback function
   * @returns Subscription object
   */
  once<T extends AgentEventType>(
    eventType: T,
    listener: (event: EventOfType<T>) => void | Promise<void>
  ): Subscription {
    const subscription = this.on(eventType, (event) => {
      subscription.unsubscribe();
      return listener(event);
    });
    return subscription;
  }

  /**
   * Subscribe to all events.
   *
   * @param listener - Callback that receives any event
   * @returns Subscription object
   */
  onAny(listener: EventListener): Subscription {
    if (this.globalListeners.size >= this.maxListeners) {
      console.warn(
        `Warning: Possible memory leak. ${this.globalListeners.size} global listeners.`
      );
    }

    this.globalListeners.add(listener);

    return {
      unsubscribe: () => {
        this.globalListeners.delete(listener);
      },
    };
  }

  /**
   * Remove all listeners for a specific event type.
   *
   * @param eventType - The event type to clear, or undefined to clear all
   */
  off(eventType?: AgentEventType): void {
    if (eventType) {
      this.listeners.delete(eventType);
    } else {
      this.listeners.clear();
      this.globalListeners.clear();
    }
  }

  // =============================================================================
  // EMISSION METHODS
  // =============================================================================

  /**
   * Emit an event to all subscribers.
   *
   * By default, handlers run concurrently and errors are caught.
   * Use options.waitForHandlers to wait for async handlers.
   *
   * @param event - The event to emit
   * @param options - Emission options
   * @returns The (possibly modified) event
   */
  async emit<T extends AgentEvent>(
    event: T,
    options: EmitOptions = {}
  ): Promise<T> {
    const { waitForHandlers = true, timeout = 5000 } = options;

    // Detect reentrancy
    if (this.emitting) {
      // Queue for later or handle immediately based on use case
      // For now, we allow reentrancy but log a warning
      console.warn('Warning: Reentrant event emission detected');
    }

    this.emitting = true;

    try {
      // Get listeners for this event type
      const typeListeners = this.listeners.get(event.type) ?? new Set();

      // Combine type-specific and global listeners
      const allListeners = [...typeListeners, ...this.globalListeners];

      if (allListeners.length === 0) {
        return event;
      }

      // Execute handlers
      if (waitForHandlers) {
        await this.executeHandlersSequentially(allListeners, event, timeout);
      } else {
        // Fire and forget
        this.executeHandlersAsync(allListeners, event);
      }

      return event;
    } finally {
      this.emitting = false;
    }
  }

  /**
   * Emit an event synchronously (for observers only, not modifying hooks).
   * This is faster but handlers cannot be async.
   *
   * @param event - The event to emit
   */
  emitSync<T extends AgentEvent>(event: T): T {
    const typeListeners = this.listeners.get(event.type) ?? new Set();
    const allListeners = [...typeListeners, ...this.globalListeners];

    for (const listener of allListeners) {
      try {
        const result = listener(event);
        if (result instanceof Promise) {
          // Log but don't wait
          result.catch((err) => {
            console.error(`Async handler in sync emit:`, err);
          });
        }
      } catch (err) {
        console.error(`Error in event listener for "${event.type}":`, err);
      }
    }

    return event;
  }

  // =============================================================================
  // PRIVATE METHODS
  // =============================================================================

  /**
   * Execute handlers sequentially, stopping on first error or timeout.
   */
  private async executeHandlersSequentially(
    listeners: EventListener[],
    event: AgentEvent,
    timeout: number
  ): Promise<void> {
    for (const listener of listeners) {
      try {
        const result = listener(event);

        if (result instanceof Promise) {
          // Add timeout wrapper
          await Promise.race([
            result,
            this.createTimeout(timeout, listener),
          ]);
        }
      } catch (err) {
        // Log error but continue to next listener
        console.error(`Error in event listener for "${event.type}":`, err);
      }
    }
  }

  /**
   * Execute handlers concurrently without waiting.
   */
  private executeHandlersAsync(
    listeners: EventListener[],
    event: AgentEvent
  ): void {
    for (const listener of listeners) {
      try {
        const result = listener(event);

        if (result instanceof Promise) {
          result.catch((err) => {
            console.error(`Error in async event listener for "${event.type}":`, err);
          });
        }
      } catch (err) {
        console.error(`Error in event listener for "${event.type}":`, err);
      }
    }
  }

  /**
   * Create a timeout promise that rejects after the specified time.
   */
  private createTimeout(ms: number, listener: EventListener): Promise<never> {
    return new Promise((_, reject) => {
      setTimeout(() => {
        reject(new Error(`Event handler timed out after ${ms}ms`));
      }, ms);
    });
  }

  // =============================================================================
  // CONFIGURATION
  // =============================================================================

  /**
   * Set the maximum number of listeners per event type.
   */
  setMaxListeners(max: number): void {
    this.maxListeners = max;
  }

  /**
   * Get the current listener count for an event type.
   */
  listenerCount(eventType?: AgentEventType): number {
    if (eventType) {
      return (this.listeners.get(eventType)?.size ?? 0) + this.globalListeners.size;
    }

    let total = this.globalListeners.size;
    for (const listeners of this.listeners.values()) {
      total += listeners.size;
    }
    return total;
  }

  /**
   * Get all event types that have listeners.
   */
  eventTypes(): AgentEventType[] {
    return [...this.listeners.keys()];
  }
}

// =============================================================================
// SINGLETON INSTANCE
// =============================================================================

/**
 * Global event bus instance.
 * Use this for application-wide events.
 */
export const globalEventBus = new EventBus();

// =============================================================================
// UTILITY FUNCTIONS
// =============================================================================

/**
 * Create a typed event helper for cleaner event creation.
 *
 * Example:
 * ```ts
 * const event = createEvent('tool.before', { tool: 'bash', args: { command: 'ls' } });
 * ```
 */
export function createEvent<T extends AgentEventType>(
  type: T,
  data: Omit<EventOfType<T>, 'type'>
): EventOfType<T> {
  return { type, ...data } as EventOfType<T>;
}

/**
 * Wait for a specific event to occur.
 *
 * Example:
 * ```ts
 * const event = await waitForEvent(bus, 'session.end', 30000);
 * console.log('Session ended:', event.reason);
 * ```
 */
export function waitForEvent<T extends AgentEventType>(
  bus: EventBus,
  eventType: T,
  timeout?: number
): Promise<EventOfType<T>> {
  return new Promise((resolve, reject) => {
    let timeoutId: NodeJS.Timeout | undefined;

    const subscription = bus.once(eventType, (event) => {
      if (timeoutId) clearTimeout(timeoutId);
      resolve(event);
    });

    if (timeout) {
      timeoutId = setTimeout(() => {
        subscription.unsubscribe();
        reject(new Error(`Timeout waiting for event "${eventType}"`));
      }, timeout);
    }
  });
}
