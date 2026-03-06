/**
 * Unbounded pub/sub event emitter for Agent to UI communication.
 * Unlike SubmissionQueue, this never blocks the producer (agent).
 * Uses fire-and-forget semantics with async dispatch.
 */

import type { AgentEvent, EventEnvelope, SubmissionId } from '../protocol/types.js';

/**
 * Generic event listener that receives all events.
 */
export type EventListener = (envelope: EventEnvelope) => void;

/**
 * Typed event listener that receives events of a specific type.
 */
export type TypedEventListener<T extends AgentEvent> = (
  envelope: EventEnvelope & { event: T },
) => void;

/**
 * Configuration for the EventQueue.
 */
export interface EventQueueConfig {
  /** Maximum number of recent events to store (default: 100) */
  maxRecentEvents?: number;
}

/**
 * Statistics about the event queue for debugging.
 */
export interface EventQueueStats {
  /** Number of global listeners */
  globalListeners: number;
  /** Number of typed listeners by event type */
  typedListeners: Record<string, number>;
  /** Number of recent events in buffer */
  recentEventsCount: number;
}

/**
 * Error thrown when a once() call times out.
 */
export class EventTimeoutError extends Error {
  constructor(eventType: string, timeout: number) {
    super(`Timed out waiting for event '${eventType}' after ${timeout}ms`);
    this.name = 'EventTimeoutError';
  }
}

/**
 * An unbounded pub/sub event emitter for Agent to UI communication.
 *
 * Features:
 * - Fire-and-forget semantics (never blocks producer)
 * - Typed event subscriptions
 * - Recent events buffer for reconnection/replay
 * - Async dispatch via queueMicrotask
 */
export class EventQueue {
  private readonly maxRecentEvents: number;
  private readonly recentEvents: EventEnvelope[] = [];
  private readonly globalListeners: Set<EventListener> = new Set();
  private readonly typedListeners: Map<AgentEvent['type'], Set<EventListener>> = new Map();

  /**
   * Creates a new EventQueue.
   * @param config - Optional configuration
   */
  constructor(config?: EventQueueConfig) {
    this.maxRecentEvents = config?.maxRecentEvents ?? 100;
  }

  /**
   * Emits an event to all listeners.
   * Never blocks - uses fire-and-forget semantics.
   *
   * @param submissionId - The submission this event relates to
   * @param event - The event to emit
   */
  emit(submissionId: SubmissionId, event: AgentEvent): void {
    const envelope: EventEnvelope = {
      submissionId,
      event,
      timestamp: Date.now(),
    };

    // Store in recent events buffer (circular)
    this.addToRecentEvents(envelope);

    // Notify all listeners asynchronously
    this.notifyListeners(envelope);
  }

  /**
   * Subscribes to all events.
   *
   * @param listener - The listener to call for each event
   * @returns Unsubscribe function
   */
  subscribe(listener: EventListener): () => void {
    this.globalListeners.add(listener);

    return () => {
      this.globalListeners.delete(listener);
    };
  }

  /**
   * Subscribes to events of a specific type.
   *
   * @param type - The event type to listen for
   * @param listener - The listener to call for matching events
   * @returns Unsubscribe function
   */
  on<T extends AgentEvent>(type: T['type'], listener: TypedEventListener<T>): () => void {
    let listeners = this.typedListeners.get(type);
    if (!listeners) {
      listeners = new Set();
      this.typedListeners.set(type, listeners);
    }

    // Cast is safe because we filter by type before calling
    listeners.add(listener as EventListener);

    return () => {
      listeners!.delete(listener as EventListener);
      // Clean up empty sets
      if (listeners!.size === 0) {
        this.typedListeners.delete(type);
      }
    };
  }

  /**
   * Returns a promise that resolves with the first matching event.
   *
   * @param type - The event type to wait for
   * @param timeout - Optional timeout in ms (rejects with EventTimeoutError)
   * @returns Promise that resolves with the matching event envelope
   */
  once<T extends AgentEvent>(
    type: T['type'],
    timeout?: number,
  ): Promise<EventEnvelope & { event: T }> {
    return new Promise((resolve, reject) => {
      let timeoutId: ReturnType<typeof setTimeout> | undefined;
      let unsubscribe: (() => void) | undefined;

      const cleanup = () => {
        if (timeoutId !== undefined) {
          clearTimeout(timeoutId);
        }
        if (unsubscribe) {
          unsubscribe();
        }
      };

      // Set up listener
      unsubscribe = this.on<T>(type, (envelope) => {
        cleanup();
        resolve(envelope);
      });

      // Set up timeout if specified
      if (timeout !== undefined && timeout > 0) {
        timeoutId = setTimeout(() => {
          cleanup();
          reject(new EventTimeoutError(type, timeout));
        }, timeout);
      }
    });
  }

  /**
   * Gets recent events, optionally filtered by timestamp.
   *
   * @param since - Optional timestamp to filter events after
   * @returns Array of recent event envelopes
   */
  getRecentEvents(since?: number): EventEnvelope[] {
    if (since === undefined) {
      return [...this.recentEvents];
    }

    return this.recentEvents.filter((envelope) => envelope.timestamp > since);
  }

  /**
   * Gets recent events filtered by submission ID.
   *
   * @param submissionId - The submission ID to filter by
   * @returns Array of event envelopes for the submission
   */
  getEventsForSubmission(submissionId: SubmissionId): EventEnvelope[] {
    return this.recentEvents.filter((envelope) => envelope.submissionId === submissionId);
  }

  /**
   * Clears all listeners and recent events.
   */
  clear(): void {
    this.globalListeners.clear();
    this.typedListeners.clear();
    this.recentEvents.length = 0;
  }

  /**
   * Returns statistics about the queue for debugging.
   */
  stats(): EventQueueStats {
    const typedListeners: Record<string, number> = {};
    for (const [type, listeners] of this.typedListeners) {
      typedListeners[type] = listeners.size;
    }

    return {
      globalListeners: this.globalListeners.size,
      typedListeners,
      recentEventsCount: this.recentEvents.length,
    };
  }

  /**
   * Adds an envelope to the recent events buffer.
   * Maintains circular buffer semantics.
   */
  private addToRecentEvents(envelope: EventEnvelope): void {
    this.recentEvents.push(envelope);

    // Trim to maxRecentEvents (circular buffer)
    while (this.recentEvents.length > this.maxRecentEvents) {
      this.recentEvents.shift();
    }
  }

  /**
   * Notifies all listeners of an event asynchronously.
   * Ignores listener errors (fire-and-forget).
   */
  private notifyListeners(envelope: EventEnvelope): void {
    // Notify global listeners
    for (const listener of this.globalListeners) {
      queueMicrotask(() => {
        try {
          listener(envelope);
        } catch {
          // Ignore listener errors - fire and forget
        }
      });
    }

    // Notify typed listeners
    const typedListeners = this.typedListeners.get(envelope.event.type);
    if (typedListeners) {
      for (const listener of typedListeners) {
        queueMicrotask(() => {
          try {
            listener(envelope);
          } catch {
            // Ignore listener errors - fire and forget
          }
        });
      }
    }
  }
}
