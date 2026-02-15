/**
 * Phase 2.3: Base Manager Pattern
 *
 * Provides a common base class for managers with consistent lifecycle
 * (init/cleanup/reset), event emission, and subscription management.
 *
 * Usage:
 * ```ts
 * interface MyEvent { type: 'my.event'; data: string }
 *
 * class MyManager extends BaseManager<MyEvent> {
 *   protected managerName = 'MyManager';
 *
 *   async onInit(): Promise<void> { ... }
 *   async onCleanup(): Promise<void> { ... }
 *   onReset(): void { ... }
 * }
 * ```
 */

// =============================================================================
// TYPES
// =============================================================================

/** Standard lifecycle states for managers */
export type ManagerState = 'created' | 'initializing' | 'ready' | 'cleaning_up' | 'disposed';

/** Base event type — all manager events must have a `type` field */
export interface BaseEvent {
  type: string;
}

/** Lifecycle events emitted by all managers */
export interface ManagerLifecycleEvent extends BaseEvent {
  type: 'manager.initialized' | 'manager.cleanup' | 'manager.reset' | 'manager.error';
  manager: string;
  error?: string;
}

// =============================================================================
// BASE MANAGER
// =============================================================================

export abstract class BaseManager<TEvent extends BaseEvent = BaseEvent> {
  /** Name for logging and events */
  protected abstract readonly managerName: string;

  private _state: ManagerState = 'created';
  private _listeners: Array<(event: TEvent | ManagerLifecycleEvent) => void> = [];
  private _unsubscribers: Array<() => void> = [];
  private _initPromise: Promise<void> | null = null;

  // ---------------------------------------------------------------------------
  // LIFECYCLE
  // ---------------------------------------------------------------------------

  /** Current lifecycle state */
  get state(): ManagerState {
    return this._state;
  }

  /** Whether the manager is ready to use */
  get isReady(): boolean {
    return this._state === 'ready';
  }

  /**
   * Initialize the manager. Idempotent — calling multiple times returns the
   * same promise. Override `onInit()` for custom initialization.
   */
  async init(): Promise<void> {
    if (this._state === 'ready') return;
    if (this._initPromise) return this._initPromise;

    this._state = 'initializing';
    this._initPromise = this._doInit();
    return this._initPromise;
  }

  /**
   * Clean up resources. Override `onCleanup()` for custom cleanup.
   * Automatically unsubscribes all tracked subscriptions.
   */
  async cleanup(): Promise<void> {
    if (this._state === 'disposed') return;

    this._state = 'cleaning_up';

    // Unsubscribe all tracked subscriptions
    for (const unsub of this._unsubscribers) {
      try {
        unsub();
      } catch {
        // Ignore errors during cleanup
      }
    }
    this._unsubscribers = [];

    try {
      await this.onCleanup();
    } catch (err) {
      this.emitLifecycle('manager.error', String(err));
    }

    this._state = 'disposed';
    this._initPromise = null;
    this.emitLifecycle('manager.cleanup');
    this._listeners = [];
  }

  /**
   * Reset manager to initial state without disposing.
   * Override `onReset()` for custom reset logic.
   */
  reset(): void {
    this.onReset();
    this._state = 'ready';
    this._initPromise = null;
    this.emitLifecycle('manager.reset');
  }

  // ---------------------------------------------------------------------------
  // EVENT SYSTEM
  // ---------------------------------------------------------------------------

  /**
   * Subscribe to manager events.
   * Returns an unsubscribe function.
   */
  subscribe(listener: (event: TEvent | ManagerLifecycleEvent) => void): () => void {
    this._listeners.push(listener);
    const unsub = () => {
      const idx = this._listeners.indexOf(listener);
      if (idx >= 0) this._listeners.splice(idx, 1);
    };
    return unsub;
  }

  /**
   * Track an external unsubscription function.
   * All tracked subscriptions are cleaned up on `cleanup()`.
   */
  protected trackSubscription(unsub: () => void): void {
    this._unsubscribers.push(unsub);
  }

  /** Emit a typed event to all listeners */
  protected emit(event: TEvent): void {
    for (const listener of this._listeners) {
      try {
        listener(event);
      } catch {
        // Don't let listener errors break the manager
      }
    }
  }

  // ---------------------------------------------------------------------------
  // HOOKS (override in subclasses)
  // ---------------------------------------------------------------------------

  /** Called during init(). Override for custom initialization. */
  protected async onInit(): Promise<void> {
    // Default: no-op
  }

  /** Called during cleanup(). Override for custom resource release. */
  protected async onCleanup(): Promise<void> {
    // Default: no-op
  }

  /** Called during reset(). Override to clear state without disposing. */
  protected onReset(): void {
    // Default: no-op
  }

  // ---------------------------------------------------------------------------
  // PRIVATE
  // ---------------------------------------------------------------------------

  private async _doInit(): Promise<void> {
    try {
      await this.onInit();
      this._state = 'ready';
      this.emitLifecycle('manager.initialized');
    } catch (err) {
      this._state = 'created';
      this._initPromise = null;
      this.emitLifecycle('manager.error', String(err));
      throw err;
    }
  }

  private emitLifecycle(type: ManagerLifecycleEvent['type'], error?: string): void {
    const event: ManagerLifecycleEvent = { type, manager: this.managerName };
    if (error) event.error = error;
    for (const listener of this._listeners) {
      try {
        listener(event as TEvent | ManagerLifecycleEvent);
      } catch {
        // Ignore
      }
    }
  }
}
