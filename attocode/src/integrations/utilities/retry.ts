/**
 * Generic Retry Utility
 *
 * Provides configurable retry logic with exponential backoff for transient failures.
 * Used by tools, MCP client, and other operations that may encounter temporary errors.
 *
 * @example
 * ```typescript
 * const result = await withRetry(
 *   () => fetchData(),
 *   {
 *     maxAttempts: 3,
 *     baseDelayMs: 1000,
 *     retryableErrors: ['ETIMEDOUT', 'ECONNRESET'],
 *   }
 * );
 * ```
 */

// =============================================================================
// TYPES
// =============================================================================

/**
 * Configuration for retry behavior.
 * @see RetryConfig in config/base-types.ts for the shared base pattern.
 */
export interface RetryConfig {
  /** Maximum number of attempts (including initial) */
  maxAttempts: number;

  /** Base delay between retries in milliseconds (default: 1000) */
  baseDelayMs?: number;

  /** Maximum delay between retries in milliseconds (default: 30000) */
  maxDelayMs?: number;

  /** Multiplier for exponential backoff (default: 2) */
  backoffMultiplier?: number;

  /** Add random jitter to delays (default: true) */
  jitter?: boolean;

  /** Error message patterns that are retryable */
  retryableErrors?: string[];

  /** Error codes that are retryable (e.g., 'ETIMEDOUT', 'ECONNRESET') */
  retryableCodes?: string[];

  /** Custom function to determine if error is retryable */
  isRetryable?: (error: Error) => boolean;

  /** Callback on each retry attempt */
  onRetry?: (attempt: number, error: Error, delayMs: number) => void;

  /** Callback when all attempts exhausted */
  onExhausted?: (attempts: number, lastError: Error) => void;
}

/**
 * Result of a retry operation.
 */
export interface RetryResult<T> {
  /** Whether the operation succeeded */
  success: boolean;

  /** The result value (if successful) */
  value?: T;

  /** The error (if failed) */
  error?: Error;

  /** Number of attempts made */
  attempts: number;

  /** Total time spent (including delays) */
  totalTimeMs: number;
}

/**
 * Default retryable error patterns.
 * These are common transient errors that often resolve on retry.
 */
export const DEFAULT_RETRYABLE_ERRORS = [
  'ETIMEDOUT',
  'ECONNRESET',
  'ECONNREFUSED',
  'ENOTFOUND',
  'EPIPE',
  'EBUSY',
  'timeout',
  'socket hang up',
  'network error',
  'temporarily unavailable',
  'service unavailable',
  'rate limit',
];

/**
 * Default retryable error codes.
 */
export const DEFAULT_RETRYABLE_CODES = [
  'ETIMEDOUT',
  'ECONNRESET',
  'ECONNREFUSED',
  'ENOTFOUND',
  'EPIPE',
  'EBUSY',
  'EAGAIN',
  'ENETUNREACH',
  'EHOSTUNREACH',
];

// =============================================================================
// RETRY IMPLEMENTATION
// =============================================================================

/**
 * Execute a function with retry logic.
 *
 * @param fn - The async function to execute
 * @param config - Retry configuration
 * @returns Promise resolving to the result or throwing the last error
 *
 * @example
 * ```typescript
 * // Basic usage with defaults
 * const data = await withRetry(() => fetchData(), { maxAttempts: 3 });
 *
 * // With custom config
 * const data = await withRetry(
 *   () => unreliableApi(),
 *   {
 *     maxAttempts: 5,
 *     baseDelayMs: 500,
 *     backoffMultiplier: 1.5,
 *     retryableErrors: ['timeout'],
 *     onRetry: (attempt, err) => console.log(`Retry ${attempt}: ${err.message}`),
 *   }
 * );
 * ```
 */
export async function withRetry<T>(fn: () => Promise<T>, config: RetryConfig): Promise<T> {
  const {
    maxAttempts,
    baseDelayMs = 1000,
    maxDelayMs = 30000,
    backoffMultiplier = 2,
    jitter = true,
    retryableErrors = DEFAULT_RETRYABLE_ERRORS,
    retryableCodes = DEFAULT_RETRYABLE_CODES,
    isRetryable,
    onRetry,
    onExhausted,
  } = config;

  let lastError: Error | undefined;
  let attempt = 0;

  while (attempt < maxAttempts) {
    attempt++;

    try {
      return await fn();
    } catch (error) {
      lastError = error as Error;

      // Check if this is the last attempt
      if (attempt >= maxAttempts) {
        onExhausted?.(attempt, lastError);
        throw lastError;
      }

      // Check if error is retryable
      if (!shouldRetry(lastError, retryableErrors, retryableCodes, isRetryable)) {
        throw lastError;
      }

      // Calculate delay with exponential backoff
      let delay = Math.min(baseDelayMs * Math.pow(backoffMultiplier, attempt - 1), maxDelayMs);

      // Add jitter (±25%)
      if (jitter) {
        const jitterAmount = delay * 0.25;
        delay += (Math.random() - 0.5) * 2 * jitterAmount;
        delay = Math.max(0, delay);
      }

      onRetry?.(attempt, lastError, delay);

      // Wait before retry
      await sleep(delay);
    }
  }

  // Should never reach here, but TypeScript needs this
  throw lastError ?? new Error('Retry failed');
}

/**
 * Execute a function with retry and return detailed result.
 *
 * Unlike withRetry, this never throws - it returns a result object
 * that indicates success or failure.
 *
 * @example
 * ```typescript
 * const result = await withRetryResult(() => unreliableOp(), { maxAttempts: 3 });
 * if (result.success) {
 *   console.log('Got:', result.value);
 * } else {
 *   console.log('Failed after', result.attempts, 'attempts:', result.error);
 * }
 * ```
 */
export async function withRetryResult<T>(
  fn: () => Promise<T>,
  config: RetryConfig,
): Promise<RetryResult<T>> {
  const startTime = Date.now();
  let attempts = 0;

  try {
    const result = await withRetry(async () => {
      attempts++;
      return await fn();
    }, config);

    return {
      success: true,
      value: result,
      attempts,
      totalTimeMs: Date.now() - startTime,
    };
  } catch (error) {
    return {
      success: false,
      error: error as Error,
      attempts,
      totalTimeMs: Date.now() - startTime,
    };
  }
}

// =============================================================================
// HELPERS
// =============================================================================

/**
 * Determine if an error should trigger a retry.
 */
function shouldRetry(
  error: Error,
  retryableErrors: string[],
  retryableCodes: string[],
  customIsRetryable?: (error: Error) => boolean,
): boolean {
  // Custom check takes precedence
  if (customIsRetryable) {
    return customIsRetryable(error);
  }

  // Check error code
  const code = (error as NodeJS.ErrnoException).code;
  if (code && retryableCodes.includes(code)) {
    return true;
  }

  // Check error message patterns
  const message = error.message.toLowerCase();
  for (const pattern of retryableErrors) {
    if (message.includes(pattern.toLowerCase())) {
      return true;
    }
  }

  return false;
}

/**
 * Sleep for a specified duration.
 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// =============================================================================
// SPECIALIZED RETRY CONFIGS
// =============================================================================

/**
 * Retry config for tool execution.
 * Conservative: 2 attempts, short delays.
 */
export const TOOL_RETRY_CONFIG: Omit<RetryConfig, 'maxAttempts'> = {
  baseDelayMs: 500,
  maxDelayMs: 5000,
  backoffMultiplier: 2,
  retryableCodes: ['ETIMEDOUT', 'ECONNRESET', 'EBUSY', 'EAGAIN'],
  retryableErrors: ['timeout', 'temporarily unavailable'],
};

/**
 * Retry config for MCP calls.
 * More aggressive: 3 attempts, longer delays.
 */
export const MCP_RETRY_CONFIG: Omit<RetryConfig, 'maxAttempts'> = {
  baseDelayMs: 1000,
  maxDelayMs: 10000,
  backoffMultiplier: 2,
  retryableCodes: DEFAULT_RETRYABLE_CODES,
  retryableErrors: ['timeout', 'socket hang up', 'connection reset'],
};

/**
 * Retry config for file operations.
 * Short delays, handles busy files.
 */
export const FILE_RETRY_CONFIG: Omit<RetryConfig, 'maxAttempts'> = {
  baseDelayMs: 100,
  maxDelayMs: 2000,
  backoffMultiplier: 2,
  retryableCodes: ['EBUSY', 'EAGAIN', 'EMFILE', 'ENFILE'],
  retryableErrors: ['resource busy', 'too many open files'],
};

/**
 * Retry config for network operations.
 * Standard exponential backoff.
 */
export const NETWORK_RETRY_CONFIG: Omit<RetryConfig, 'maxAttempts'> = {
  baseDelayMs: 1000,
  maxDelayMs: 30000,
  backoffMultiplier: 2,
  retryableCodes: DEFAULT_RETRYABLE_CODES,
  retryableErrors: DEFAULT_RETRYABLE_ERRORS,
};
