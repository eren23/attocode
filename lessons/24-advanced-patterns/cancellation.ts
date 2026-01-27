/**
 * Lesson 24: Cancellation Tokens
 *
 * Provides graceful cancellation of long-running operations.
 * Based on the .NET CancellationToken pattern, also used in Codex.
 *
 * Key benefits:
 * - Cooperative cancellation (operations check and respond)
 * - Clean resource cleanup
 * - Partial results preservation
 * - Timeout support
 */

import type {
  CancellationToken,
  CancellationTokenSource,
  Disposable,
  CancellableOptions,
  AdvancedPatternEvent,
  AdvancedPatternEventListener,
} from './types.js';
import { CancellationError } from './types.js';

// =============================================================================
// CANCELLATION TOKEN IMPLEMENTATION
// =============================================================================

/**
 * Implementation of CancellationToken.
 */
class CancellationTokenImpl implements CancellationToken {
  private _isCancelled = false;
  private _callbacks: Set<() => void> = new Set();
  private _promise: Promise<void>;
  private _resolve!: () => void;

  constructor() {
    this._promise = new Promise(resolve => {
      this._resolve = resolve;
    });
  }

  get isCancellationRequested(): boolean {
    return this._isCancelled;
  }

  get onCancellationRequested(): Promise<void> {
    return this._promise;
  }

  register(callback: () => void): Disposable {
    if (this._isCancelled) {
      // Already cancelled, run immediately
      callback();
      return { dispose: () => {} };
    }

    this._callbacks.add(callback);
    return {
      dispose: () => this._callbacks.delete(callback),
    };
  }

  throwIfCancellationRequested(): void {
    if (this._isCancelled) {
      throw new CancellationError();
    }
  }

  /** @internal */
  _cancel(): void {
    if (this._isCancelled) return;

    this._isCancelled = true;
    this._resolve();

    for (const callback of this._callbacks) {
      try {
        callback();
      } catch (error) {
        console.error('Cancellation callback error:', error);
      }
    }

    this._callbacks.clear();
  }
}

// =============================================================================
// CANCELLATION TOKEN SOURCE
// =============================================================================

/**
 * Implementation of CancellationTokenSource.
 */
class CancellationTokenSourceImpl implements CancellationTokenSource {
  private _token: CancellationTokenImpl;
  private _disposed = false;
  private _timeoutId?: NodeJS.Timeout;
  private eventListeners: Set<AdvancedPatternEventListener> = new Set();

  constructor() {
    this._token = new CancellationTokenImpl();
  }

  get token(): CancellationToken {
    return this._token;
  }

  cancel(reason?: string): void {
    if (this._disposed) return;

    this.emit({ type: 'cancellation.requested', reason });
    this._token._cancel();
    this.emit({ type: 'cancellation.completed', cleanedUp: true });
  }

  dispose(): void {
    if (this._disposed) return;

    this._disposed = true;

    if (this._timeoutId) {
      clearTimeout(this._timeoutId);
    }

    this._token._cancel();
  }

  /**
   * Cancel after a timeout.
   */
  cancelAfter(timeout: number): this {
    if (this._disposed) return this;

    this._timeoutId = setTimeout(() => {
      this.cancel('Timeout');
    }, timeout);

    return this;
  }

  /**
   * Subscribe to events.
   */
  subscribe(listener: AdvancedPatternEventListener): () => void {
    this.eventListeners.add(listener);
    return () => this.eventListeners.delete(listener);
  }

  private emit(event: AdvancedPatternEvent): void {
    for (const listener of this.eventListeners) {
      try {
        listener(event);
      } catch (error) {
        console.error('Event listener error:', error);
      }
    }
  }
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
 * Create a cancellation token source with timeout.
 */
export function createCancellationTokenSourceWithTimeout(
  timeout: number
): CancellationTokenSource {
  const source = new CancellationTokenSourceImpl();
  source.cancelAfter(timeout);
  return source;
}

/**
 * Create a token that's already cancelled (for testing).
 */
export function createCancelledToken(): CancellationToken {
  const source = createCancellationTokenSource();
  source.cancel();
  return source.token;
}

/**
 * Create a token that never cancels (for opt-out scenarios).
 */
export function createNeverCancelledToken(): CancellationToken {
  return new CancellationTokenImpl();
}

// =============================================================================
// UTILITY FUNCTIONS
// =============================================================================

/**
 * Run a function with cancellation support.
 */
export async function withCancellation<T>(
  fn: () => Promise<T>,
  options: CancellableOptions = {}
): Promise<T> {
  const { cancellationToken, timeout, onCancel } = options;

  // Create timeout source if needed
  let timeoutSource: CancellationTokenSource | undefined;
  if (timeout && !cancellationToken) {
    timeoutSource = createCancellationTokenSourceWithTimeout(timeout);
  }

  const token = cancellationToken || timeoutSource?.token;

  // Register cleanup callback
  const registration = token?.register(() => {
    onCancel?.();
  });

  try {
    // Check if already cancelled
    token?.throwIfCancellationRequested();

    // Run the function
    const result = await fn();

    // Check again after completion
    token?.throwIfCancellationRequested();

    return result;
  } finally {
    registration?.dispose();
    timeoutSource?.dispose();
  }
}

/**
 * Race a promise against cancellation.
 */
export async function raceWithCancellation<T>(
  promise: Promise<T>,
  token: CancellationToken
): Promise<T> {
  return Promise.race([
    promise,
    token.onCancellationRequested.then(() => {
      throw new CancellationError();
    }),
  ]);
}

/**
 * Create an abortable fetch using cancellation token.
 */
export function createAbortController(
  token: CancellationToken
): AbortController {
  const controller = new AbortController();

  const registration = token.register(() => {
    controller.abort();
  });

  // Note: registration should be disposed when the request completes
  // This is a simplified implementation
  return controller;
}

/**
 * Run multiple operations, cancelling if any fails.
 */
export async function allWithCancellation<T>(
  promises: Array<() => Promise<T>>,
  token?: CancellationToken
): Promise<T[]> {
  const results: T[] = [];

  for (const promiseFn of promises) {
    token?.throwIfCancellationRequested();
    const result = await promiseFn();
    results.push(result);
  }

  return results;
}

/**
 * Run operation with retry, respecting cancellation.
 */
export async function retryWithCancellation<T>(
  fn: () => Promise<T>,
  options: {
    maxRetries: number;
    delay: number;
    token?: CancellationToken;
    onRetry?: (attempt: number, error: unknown) => void;
  }
): Promise<T> {
  const { maxRetries, delay, token, onRetry } = options;
  let lastError: unknown;

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    token?.throwIfCancellationRequested();

    try {
      return await fn();
    } catch (error) {
      lastError = error;

      // Don't retry cancellation errors
      if (error instanceof CancellationError) {
        throw error;
      }

      onRetry?.(attempt, error);

      if (attempt < maxRetries) {
        await sleep(delay, token);
      }
    }
  }

  throw lastError;
}

/**
 * Sleep with cancellation support.
 */
export function sleep(ms: number, token?: CancellationToken): Promise<void> {
  return new Promise((resolve, reject) => {
    token?.throwIfCancellationRequested();

    const timeoutId = setTimeout(resolve, ms);

    token?.register(() => {
      clearTimeout(timeoutId);
      reject(new CancellationError());
    });
  });
}

// =============================================================================
// LINKED TOKENS
// =============================================================================

/**
 * Create a token that cancels when any of the provided tokens cancel.
 */
export function createLinkedToken(
  ...tokens: CancellationToken[]
): CancellationTokenSource {
  const source = createCancellationTokenSource();

  for (const token of tokens) {
    if (token.isCancellationRequested) {
      source.cancel('Linked token cancelled');
      return source;
    }

    token.register(() => {
      source.cancel('Linked token cancelled');
    });
  }

  return source;
}

// =============================================================================
// PROGRESS REPORTING WITH CANCELLATION
// =============================================================================

/**
 * Options for cancellable operations with progress.
 */
export interface CancellableProgressOptions<TProgress> extends CancellableOptions {
  /** Progress callback */
  onProgress?: (progress: TProgress) => void;
}

/**
 * Run a function with progress reporting and cancellation.
 */
export async function withCancellationAndProgress<T, TProgress>(
  fn: (reportProgress: (progress: TProgress) => void) => Promise<T>,
  options: CancellableProgressOptions<TProgress> = {}
): Promise<T> {
  const { cancellationToken, onProgress } = options;

  const reportProgress = (progress: TProgress) => {
    cancellationToken?.throwIfCancellationRequested();
    onProgress?.(progress);
  };

  return withCancellation(() => fn(reportProgress), options);
}

// =============================================================================
// RE-EXPORTS
// =============================================================================

export { CancellationError } from './types.js';
export type { CancellationToken, CancellationTokenSource, Disposable } from './types.js';
