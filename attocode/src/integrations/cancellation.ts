/**
 * Cancellation Token Integration
 *
 * Provides graceful cancellation support for long-running agent operations.
 * Based on the .NET CancellationToken pattern, adapted from tricks/cancellation.ts.
 *
 * Usage:
 *   const cts = createCancellationTokenSource();
 *   agent.run(task, { cancellationToken: cts.token });
 *   // Later: cts.cancel('User requested cancellation');
 */

// =============================================================================
// TYPES
// =============================================================================

/**
 * Token that can be checked for cancellation.
 */
export interface CancellationToken {
  /** Whether cancellation has been requested */
  readonly isCancellationRequested: boolean;
  /** The reason for cancellation (if cancelled) */
  readonly cancellationReason?: string;
  /** Promise that resolves when cancelled */
  readonly onCancellationRequested: Promise<string | void>;
  /** Register a callback for cancellation */
  register(callback: (reason?: string) => void): { dispose: () => void };
  /** Throw if cancelled */
  throwIfCancellationRequested(): void;
}

/**
 * Source that controls a cancellation token.
 */
export interface CancellationTokenSource {
  /** The token */
  readonly token: CancellationToken;
  /** Whether cancellation has been requested */
  readonly isCancellationRequested: boolean;
  /** Request cancellation */
  cancel(reason?: string): void;
  /** Cancel after timeout */
  cancelAfter(ms: number): this;
  /** Dispose resources */
  dispose(): void;
}

/**
 * Options for cancellable operations.
 */
export interface CancellableOptions {
  /** Cancellation token */
  token?: CancellationToken;
  /** Timeout in milliseconds (creates auto-cancelling token) */
  timeout?: number;
}

/**
 * Cancellation event for agent integration.
 */
export type CancellationEvent =
  | { type: 'cancellation.requested'; reason?: string; timestamp: Date }
  | { type: 'cancellation.handled'; cleanupDuration: number };

export type CancellationEventListener = (event: CancellationEvent) => void;

// =============================================================================
// IMPLEMENTATION
// =============================================================================

class CancellationTokenImpl implements CancellationToken {
  private _cancelled = false;
  private _reason?: string;
  private _callbacks = new Set<(reason?: string) => void>();
  private _promise: Promise<string | void>;
  private _resolve!: (reason?: string) => void;

  constructor() {
    this._promise = new Promise((r) => {
      this._resolve = r;
    });
  }

  get isCancellationRequested(): boolean {
    return this._cancelled;
  }

  get cancellationReason(): string | undefined {
    return this._reason;
  }

  get onCancellationRequested(): Promise<string | void> {
    return this._promise;
  }

  register(callback: (reason?: string) => void): { dispose: () => void } {
    if (this._cancelled) {
      // Already cancelled, invoke immediately
      try {
        callback(this._reason);
      } catch {
        // Ignore callback errors
      }
      return { dispose: () => {} };
    }
    this._callbacks.add(callback);
    return { dispose: () => this._callbacks.delete(callback) };
  }

  throwIfCancellationRequested(): void {
    if (this._cancelled) {
      throw new CancellationError(this._reason);
    }
  }

  /** @internal */
  _cancel(reason?: string): void {
    if (this._cancelled) return;
    this._cancelled = true;
    this._reason = reason;
    this._resolve(reason);
    for (const cb of this._callbacks) {
      try {
        cb(reason);
      } catch {
        // Ignore callback errors to ensure all callbacks run
      }
    }
    this._callbacks.clear();
  }
}

class CancellationTokenSourceImpl implements CancellationTokenSource {
  private _token = new CancellationTokenImpl();
  private _timeoutId?: ReturnType<typeof setTimeout>;
  private _disposed = false;

  get token(): CancellationToken {
    return this._token;
  }

  get isCancellationRequested(): boolean {
    return this._token.isCancellationRequested;
  }

  cancel(reason?: string): void {
    if (this._disposed) return;
    this._token._cancel(reason);
  }

  cancelAfter(ms: number): this {
    if (this._disposed || this._token.isCancellationRequested) return this;
    this._timeoutId = setTimeout(() => this.cancel('Operation timed out'), ms);
    return this;
  }

  dispose(): void {
    if (this._disposed) return;
    this._disposed = true;
    if (this._timeoutId) {
      clearTimeout(this._timeoutId);
      this._timeoutId = undefined;
    }
    // Don't cancel on dispose - the operation completed successfully
  }
}

// =============================================================================
// ERROR
// =============================================================================

/**
 * Error thrown when an operation is cancelled.
 */
export class CancellationError extends Error {
  readonly isCancellation = true;
  readonly reason?: string;

  constructor(reason?: string) {
    super(reason || 'Operation cancelled');
    this.name = 'CancellationError';
    this.reason = reason;
  }
}

/**
 * Check if an error is a cancellation error.
 */
export function isCancellationError(error: unknown): error is CancellationError {
  return (
    error instanceof CancellationError ||
    (error instanceof Error && 'isCancellation' in error && (error as CancellationError).isCancellation === true)
  );
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create a new cancellation token source.
 */
export function createCancellationTokenSource(): CancellationTokenSource {
  return new CancellationTokenSourceImpl();
}

/**
 * Create a token source that auto-cancels after timeout.
 */
export function createTimeoutToken(ms: number): CancellationTokenSource {
  return createCancellationTokenSource().cancelAfter(ms);
}

/**
 * Create a linked token that cancels when any source cancels.
 */
export function createLinkedToken(...sources: CancellationTokenSource[]): CancellationTokenSource {
  const linked = createCancellationTokenSource();

  for (const source of sources) {
    if (source.isCancellationRequested) {
      linked.cancel(source.token.cancellationReason);
      break;
    }
    source.token.register((reason) => linked.cancel(reason));
  }

  return linked;
}

/**
 * Create a "none" token that is never cancelled.
 * Useful as a default when no cancellation is needed.
 */
export const CancellationToken = {
  None: {
    isCancellationRequested: false,
    cancellationReason: undefined,
    onCancellationRequested: new Promise<void>(() => {}),
    register: () => ({ dispose: () => {} }),
    throwIfCancellationRequested: () => {},
  } as CancellationToken,
};

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Run a function with cancellation support.
 */
export async function withCancellation<T>(
  fn: (token: CancellationToken) => Promise<T>,
  options: CancellableOptions = {}
): Promise<T> {
  const { token, timeout } = options;

  let timeoutSource: CancellationTokenSource | undefined;
  let effectiveToken: CancellationToken;

  if (timeout && !token) {
    timeoutSource = createTimeoutToken(timeout);
    effectiveToken = timeoutSource.token;
  } else if (timeout && token) {
    // Link user token with timeout
    timeoutSource = createTimeoutToken(timeout);
    const linkedSource = createLinkedToken(
      { token, isCancellationRequested: token.isCancellationRequested, cancel: () => {}, cancelAfter: () => ({ token, isCancellationRequested: false, cancel: () => {}, cancelAfter: () => ({} as CancellationTokenSource), dispose: () => {} }), dispose: () => {} },
      timeoutSource
    );
    effectiveToken = linkedSource.token;
  } else {
    effectiveToken = token || CancellationToken.None;
  }

  try {
    effectiveToken.throwIfCancellationRequested();
    return await fn(effectiveToken);
  } finally {
    timeoutSource?.dispose();
  }
}

/**
 * Sleep with cancellation support.
 */
export function sleep(ms: number, token?: CancellationToken): Promise<void> {
  return new Promise((resolve, reject) => {
    if (token?.isCancellationRequested) {
      reject(new CancellationError(token.cancellationReason));
      return;
    }

    const id = setTimeout(resolve, ms);
    const registration = token?.register((reason) => {
      clearTimeout(id);
      reject(new CancellationError(reason));
    });

    // Cleanup registration after timeout completes
    if (registration) {
      setTimeout(() => registration.dispose(), ms + 1);
    }
  });
}

/**
 * Race a promise against cancellation.
 */
export function race<T>(promise: Promise<T>, token: CancellationToken): Promise<T> {
  if (token.isCancellationRequested) {
    return Promise.reject(new CancellationError(token.cancellationReason));
  }

  return Promise.race([
    promise,
    token.onCancellationRequested.then((reason) => {
      throw new CancellationError(reason as string);
    }),
  ]);
}

/**
 * Create an AbortSignal from a CancellationToken.
 * Useful for integrating with fetch and other AbortSignal-based APIs.
 */
export function toAbortSignal(token: CancellationToken): AbortSignal {
  const controller = new AbortController();

  if (token.isCancellationRequested) {
    controller.abort(token.cancellationReason);
  } else {
    token.register((reason) => controller.abort(reason));
  }

  return controller.signal;
}

// =============================================================================
// CANCELLATION MANAGER (for agent integration)
// =============================================================================

/**
 * Manager that handles cancellation for agent operations.
 * Provides a clean interface for the ProductionAgent to use.
 */
export class CancellationManager {
  private currentSource: CancellationTokenSource | null = null;
  private eventListeners: Set<CancellationEventListener> = new Set();

  /**
   * Create a new cancellation context for an operation.
   * Disposes the previous context if one exists.
   */
  createContext(timeout?: number): CancellationToken {
    // Dispose previous context
    this.disposeContext();

    // Create new source
    this.currentSource = timeout ? createTimeoutToken(timeout) : createCancellationTokenSource();

    return this.currentSource.token;
  }

  /**
   * Get the current cancellation token.
   */
  get token(): CancellationToken {
    return this.currentSource?.token || CancellationToken.None;
  }

  /**
   * Check if cancellation has been requested.
   */
  get isCancelled(): boolean {
    return this.currentSource?.isCancellationRequested ?? false;
  }

  /**
   * Request cancellation of the current operation.
   */
  cancel(reason?: string): void {
    if (!this.currentSource) return;

    const effectiveReason = reason || 'User requested cancellation';
    this.emit({ type: 'cancellation.requested', reason: effectiveReason, timestamp: new Date() });
    this.currentSource.cancel(effectiveReason);
  }

  /**
   * Dispose the current cancellation context.
   */
  disposeContext(): void {
    if (this.currentSource) {
      this.currentSource.dispose();
      this.currentSource = null;
    }
  }

  /**
   * Check if there's an active cancellation context.
   */
  hasActiveContext(): boolean {
    return this.currentSource !== null;
  }

  /**
   * Get the current cancellation source for linking with other tokens.
   * Returns null if no active context.
   */
  getSource(): CancellationTokenSource | null {
    return this.currentSource;
  }

  /**
   * Subscribe to cancellation events.
   */
  subscribe(listener: CancellationEventListener): () => void {
    this.eventListeners.add(listener);
    return () => this.eventListeners.delete(listener);
  }

  /**
   * Emit a cancellation event.
   */
  private emit(event: CancellationEvent): void {
    for (const listener of this.eventListeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }

  /**
   * Cleanup all resources.
   */
  cleanup(): void {
    this.disposeContext();
    this.eventListeners.clear();
  }
}

/**
 * Create a cancellation manager.
 */
export function createCancellationManager(): CancellationManager {
  return new CancellationManager();
}
