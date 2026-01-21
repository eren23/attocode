/**
 * Exercise 5: Retry with Backoff - REFERENCE SOLUTION
 */

// =============================================================================
// TYPES
// =============================================================================

export interface RetryOptions {
  maxRetries: number;
  initialDelayMs: number;
  maxDelayMs: number;
  onRetry?: (attempt: number, error: Error, delayMs: number) => void;
}

export interface RetryableError extends Error {
  retryable?: boolean;
  code?: string;
  status?: number;
  retryAfter?: number;
}

// =============================================================================
// HELPER
// =============================================================================

function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// =============================================================================
// SOLUTION: isRetryableError
// =============================================================================

const RETRYABLE_CODES = new Set([
  'ECONNRESET',
  'ETIMEDOUT',
  'ECONNREFUSED',
  'EPIPE',
  'ENOTFOUND',
]);

const RETRYABLE_STATUS_CODES = new Set([429, 500, 502, 503, 504]);
const NON_RETRYABLE_STATUS_CODES = new Set([400, 401, 403, 404, 422]);

export function isRetryableError(error: unknown): boolean {
  if (!(error instanceof Error)) {
    return false;
  }

  const err = error as RetryableError;

  // Check explicit retryable flag
  if (err.retryable === true) return true;
  if (err.retryable === false) return false;

  // Check error codes (network errors)
  if (err.code && RETRYABLE_CODES.has(err.code)) {
    return true;
  }

  // Check HTTP status codes
  if (err.status !== undefined) {
    if (NON_RETRYABLE_STATUS_CODES.has(err.status)) {
      return false;
    }
    if (RETRYABLE_STATUS_CODES.has(err.status)) {
      return true;
    }
  }

  // Check message patterns
  const message = err.message.toLowerCase();
  if (message.includes('timeout') || message.includes('network')) {
    return true;
  }

  // Default to non-retryable
  return false;
}

// =============================================================================
// SOLUTION: calculateBackoff
// =============================================================================

export function calculateBackoff(
  attempt: number,
  options: RetryOptions,
  error?: RetryableError
): number {
  // Check for rate limit retry-after
  if (error?.retryAfter) {
    return Math.min(error.retryAfter, options.maxDelayMs);
  }

  // Exponential backoff: initialDelay * 2^attempt
  const calculatedDelay = options.initialDelayMs * Math.pow(2, attempt);

  // Cap at maxDelayMs
  return Math.min(calculatedDelay, options.maxDelayMs);
}

// =============================================================================
// SOLUTION: retryWithBackoff
// =============================================================================

export async function retryWithBackoff<T>(
  fn: () => Promise<T>,
  options: RetryOptions
): Promise<T> {
  let lastError: Error | undefined;

  for (let attempt = 0; attempt <= options.maxRetries; attempt++) {
    try {
      return await fn();
    } catch (error) {
      lastError = error as Error;

      // Check if error is retryable
      if (!isRetryableError(error)) {
        throw error;
      }

      // Check if we have retries left
      if (attempt >= options.maxRetries) {
        throw error;
      }

      // Calculate delay
      const delayMs = calculateBackoff(attempt, options, error as RetryableError);

      // Call onRetry callback if provided
      options.onRetry?.(attempt + 1, lastError, delayMs);

      // Wait before retrying
      await delay(delayMs);
    }
  }

  // This should never be reached, but TypeScript needs it
  throw lastError ?? new Error('Retry failed');
}
