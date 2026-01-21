/**
 * Trick K: Cancellation Tokens
 *
 * Lightweight cancellation support for long-running operations.
 * Based on the .NET CancellationToken pattern.
 *
 * Usage:
 *   const cts = createCancellationTokenSource();
 *   await withCancellation(async () => { ... }, { token: cts.token });
 *   cts.cancel(); // Request cancellation
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
  /** Promise that resolves when cancelled */
  readonly onCancellationRequested: Promise<void>;
  /** Register a callback for cancellation */
  register(callback: () => void): { dispose: () => void };
  /** Throw if cancelled */
  throwIfCancellationRequested(): void;
}

/**
 * Source that controls a cancellation token.
 */
export interface CancellationTokenSource {
  /** The token */
  readonly token: CancellationToken;
  /** Request cancellation */
  cancel(reason?: string): void;
  /** Cancel after timeout */
  cancelAfter(ms: number): this;
  /** Dispose resources */
  dispose(): void;
}

// =============================================================================
// IMPLEMENTATION
// =============================================================================

class CancellationTokenImpl implements CancellationToken {
  private _cancelled = false;
  private _callbacks = new Set<() => void>();
  private _promise: Promise<void>;
  private _resolve!: () => void;

  constructor() {
    this._promise = new Promise(r => { this._resolve = r; });
  }

  get isCancellationRequested(): boolean {
    return this._cancelled;
  }

  get onCancellationRequested(): Promise<void> {
    return this._promise;
  }

  register(callback: () => void): { dispose: () => void } {
    if (this._cancelled) {
      callback();
      return { dispose: () => {} };
    }
    this._callbacks.add(callback);
    return { dispose: () => this._callbacks.delete(callback) };
  }

  throwIfCancellationRequested(): void {
    if (this._cancelled) {
      throw new CancellationError();
    }
  }

  _cancel(): void {
    if (this._cancelled) return;
    this._cancelled = true;
    this._resolve();
    for (const cb of this._callbacks) {
      try { cb(); } catch {}
    }
    this._callbacks.clear();
  }
}

class CancellationTokenSourceImpl implements CancellationTokenSource {
  private _token = new CancellationTokenImpl();
  private _timeoutId?: ReturnType<typeof setTimeout>;

  get token(): CancellationToken {
    return this._token;
  }

  cancel(_reason?: string): void {
    this._token._cancel();
  }

  cancelAfter(ms: number): this {
    this._timeoutId = setTimeout(() => this.cancel('timeout'), ms);
    return this;
  }

  dispose(): void {
    if (this._timeoutId) clearTimeout(this._timeoutId);
    this._token._cancel();
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
  constructor(message = 'Operation cancelled') {
    super(message);
    this.name = 'CancellationError';
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
 * Create a token source that auto-cancels after timeout.
 */
export function createTimeoutToken(ms: number): CancellationTokenSource {
  return createCancellationTokenSource().cancelAfter(ms);
}

/**
 * Create a linked token that cancels when any source cancels.
 */
export function createLinkedToken(
  ...sources: CancellationTokenSource[]
): CancellationTokenSource {
  const linked = createCancellationTokenSource();
  for (const source of sources) {
    if (source.token.isCancellationRequested) {
      linked.cancel();
      break;
    }
    source.token.register(() => linked.cancel());
  }
  return linked;
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Run a function with cancellation support.
 */
export async function withCancellation<T>(
  fn: () => Promise<T>,
  options: { token?: CancellationToken; timeout?: number } = {}
): Promise<T> {
  const { token, timeout } = options;

  let timeoutSource: CancellationTokenSource | undefined;
  if (timeout && !token) {
    timeoutSource = createTimeoutToken(timeout);
  }

  const effectiveToken = token || timeoutSource?.token;

  try {
    effectiveToken?.throwIfCancellationRequested();
    return await fn();
  } finally {
    timeoutSource?.dispose();
  }
}

/**
 * Sleep with cancellation support.
 */
export function sleep(ms: number, token?: CancellationToken): Promise<void> {
  return new Promise((resolve, reject) => {
    token?.throwIfCancellationRequested();
    const id = setTimeout(resolve, ms);
    token?.register(() => {
      clearTimeout(id);
      reject(new CancellationError());
    });
  });
}

/**
 * Race a promise against cancellation.
 */
export function race<T>(
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
