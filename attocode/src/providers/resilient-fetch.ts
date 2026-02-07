/**
 * Resilient Fetch Utility
 *
 * Provides network resilience for LLM provider requests:
 * - Configurable timeout to prevent infinite hangs
 * - Retry with exponential backoff for transient failures
 * - Rate limit handling with Retry-After header parsing
 * - Cancellation token support for user interrupts
 */

// =============================================================================
// TYPES
// =============================================================================

/**
 * Network configuration for resilient fetch.
 */
export interface NetworkConfig {
  /** Request timeout in milliseconds (default: 30000) */
  timeout?: number;
  /** Maximum retry attempts (default: 3) */
  maxRetries?: number;
  /** Base delay between retries in ms (default: 1000) */
  baseRetryDelay?: number;
  /** Maximum delay between retries in ms (default: 30000) */
  maxRetryDelay?: number;
  /** HTTP status codes that trigger retry (default: [429, 500, 502, 503, 504]) */
  retryableStatusCodes?: number[];
  /** Extra retry attempts for HTTP 429 (default: 2, so total = maxRetries + 2) */
  maxRetriesFor429?: number;
}

/**
 * Cancellation token interface for external cancellation.
 */
export interface CancellationToken {
  /** Whether cancellation has been requested */
  isCancelled: boolean;
  /** Register a callback to be called on cancellation */
  onCancel?: (callback: () => void) => void;
}

/**
 * Options for resilient fetch.
 */
export interface ResilientFetchOptions {
  /** URL to fetch */
  url: string;
  /** Fetch init options (method, headers, body, etc.) */
  init: RequestInit;
  /** Provider name for error messages */
  providerName: string;
  /** Network configuration */
  networkConfig?: NetworkConfig;
  /** External cancellation token */
  cancellationToken?: CancellationToken;
  /** Callback for retry events */
  onRetry?: (attempt: number, delay: number, error: Error) => void;
}

/**
 * Result of resilient fetch.
 */
export interface ResilientFetchResult {
  /** The fetch response */
  response: Response;
  /** Number of attempts made */
  attempts: number;
  /** Total duration in milliseconds */
  duration: number;
}

/**
 * Error thrown when fetch fails after all retries.
 */
export class ResilientFetchError extends Error {
  constructor(
    message: string,
    public readonly providerName: string,
    public readonly attempts: number,
    public readonly lastError?: Error,
    public readonly isTimeout: boolean = false,
    public readonly isCancelled: boolean = false
  ) {
    super(message);
    this.name = 'ResilientFetchError';
  }
}

// =============================================================================
// DEFAULT CONFIG
// =============================================================================

const DEFAULT_CONFIG: Required<NetworkConfig> = {
  timeout: 30000,
  maxRetries: 3,
  baseRetryDelay: 1000,
  maxRetryDelay: 30000,
  retryableStatusCodes: [429, 500, 502, 503, 504],
  maxRetriesFor429: 2,
};

// =============================================================================
// RESILIENT FETCH
// =============================================================================

/**
 * Perform a fetch with timeout, retry, and cancellation support.
 *
 * @example
 * ```typescript
 * const { response, attempts, duration } = await resilientFetch({
 *   url: 'https://api.anthropic.com/v1/messages',
 *   init: { method: 'POST', headers: {...}, body: JSON.stringify(body) },
 *   providerName: 'anthropic',
 *   networkConfig: { timeout: 60000, maxRetries: 3 },
 * });
 * ```
 */
export async function resilientFetch(
  options: ResilientFetchOptions
): Promise<ResilientFetchResult> {
  const {
    url,
    init,
    providerName,
    networkConfig = {},
    cancellationToken,
    onRetry,
  } = options;

  const config = { ...DEFAULT_CONFIG, ...networkConfig };
  const startTime = Date.now();
  let lastError: Error | undefined;
  let attempts = 0;

  // Use max possible retries (429 may get extra attempts)
  const maxPossibleRetries = config.maxRetries + config.maxRetriesFor429;
  while (attempts < maxPossibleRetries) {
    attempts++;

    // Check for cancellation before each attempt
    if (cancellationToken?.isCancelled) {
      throw new ResilientFetchError(
        `Request cancelled by user`,
        providerName,
        attempts,
        lastError,
        false,
        true
      );
    }

    // Create AbortController for timeout
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), config.timeout);

    // Link external cancellation token
    let cancelCleanup: (() => void) | undefined;
    if (cancellationToken?.onCancel) {
      cancellationToken.onCancel(() => controller.abort());
      // Note: In a real implementation, you'd want proper cleanup here
    }

    try {
      const response = await fetch(url, {
        ...init,
        signal: controller.signal,
      });

      clearTimeout(timeoutId);
      if (cancelCleanup) cancelCleanup();

      // Check if response is retryable
      if (config.retryableStatusCodes.includes(response.status)) {
        const is429 = response.status === 429;
        // 429 gets extra retry budget
        const effectiveMaxRetries = is429
          ? config.maxRetries + config.maxRetriesFor429
          : config.maxRetries;

        // Parse Retry-After header for rate limits
        const retryAfter = parseRetryAfter(response.headers.get('Retry-After'));
        // 429 uses steeper backoff (3^n instead of 2^n)
        const delay = retryAfter ?? (is429
          ? calculate429Backoff(attempts, config)
          : calculateBackoff(attempts, config));

        lastError = new Error(`HTTP ${response.status}: ${response.statusText}`);

        // Don't retry if this is the last attempt
        if (attempts >= effectiveMaxRetries) {
          throw new ResilientFetchError(
            `${providerName} request failed after ${attempts} attempts: HTTP ${response.status}`,
            providerName,
            attempts,
            lastError
          );
        }

        // Notify about retry
        if (onRetry) {
          onRetry(attempts, delay, lastError);
        }

        await sleep(delay);
        continue;
      }

      // Success (or non-retryable error - let caller handle)
      return {
        response,
        attempts,
        duration: Date.now() - startTime,
      };
    } catch (error) {
      clearTimeout(timeoutId);
      if (cancelCleanup) cancelCleanup();

      // Handle abort (timeout or cancellation)
      if (error instanceof Error && error.name === 'AbortError') {
        if (cancellationToken?.isCancelled) {
          throw new ResilientFetchError(
            `Request cancelled by user`,
            providerName,
            attempts,
            error,
            false,
            true
          );
        }
        // Timeout
        lastError = new Error(`Request timeout after ${config.timeout}ms`);

        if (attempts >= config.maxRetries) {
          throw new ResilientFetchError(
            `${providerName} request timed out after ${attempts} attempts`,
            providerName,
            attempts,
            lastError,
            true
          );
        }

        const delay = calculateBackoff(attempts, config);
        if (onRetry) {
          onRetry(attempts, delay, lastError);
        }
        await sleep(delay);
        continue;
      }

      // Network error (ECONNREFUSED, DNS failure, etc.)
      lastError = error instanceof Error ? error : new Error(String(error));

      if (attempts >= config.maxRetries) {
        throw new ResilientFetchError(
          `${providerName} network error after ${attempts} attempts: ${lastError.message}`,
          providerName,
          attempts,
          lastError
        );
      }

      const delay = calculateBackoff(attempts, config);
      if (onRetry) {
        onRetry(attempts, delay, lastError);
      }
      await sleep(delay);
    }
  }

  // Should not reach here, but just in case
  throw new ResilientFetchError(
    `${providerName} request failed after ${attempts} attempts`,
    providerName,
    attempts,
    lastError
  );
}

// =============================================================================
// HELPERS
// =============================================================================

/**
 * Parse Retry-After header value.
 * Can be either a number of seconds or an HTTP-date.
 */
function parseRetryAfter(header: string | null): number | null {
  if (!header) return null;

  // Try parsing as number of seconds
  const seconds = parseInt(header, 10);
  if (!isNaN(seconds)) {
    return seconds * 1000; // Convert to milliseconds
  }

  // Try parsing as HTTP-date
  try {
    const date = new Date(header);
    const delay = date.getTime() - Date.now();
    return delay > 0 ? delay : null;
  } catch {
    return null;
  }
}

/**
 * Calculate exponential backoff delay with jitter.
 */
function calculateBackoff(
  attempt: number,
  config: Required<NetworkConfig>
): number {
  // Exponential backoff: baseDelay * 2^(attempt-1)
  const exponentialDelay = config.baseRetryDelay * Math.pow(2, attempt - 1);

  // Add jitter (±25%)
  const jitter = exponentialDelay * 0.25 * (Math.random() * 2 - 1);
  const delay = exponentialDelay + jitter;

  // Clamp to max delay
  return Math.min(delay, config.maxRetryDelay);
}

/**
 * Steeper exponential backoff for 429 rate limit errors.
 * Uses 3^n instead of 2^n to give rate limit windows more recovery time.
 */
function calculate429Backoff(
  attempt: number,
  config: Required<NetworkConfig>
): number {
  // Steeper backoff: baseDelay * 3^(attempt-1)
  const exponentialDelay = config.baseRetryDelay * Math.pow(3, attempt - 1);

  // Add jitter (±25%)
  const jitter = exponentialDelay * 0.25 * (Math.random() * 2 - 1);
  const delay = exponentialDelay + jitter;

  // Clamp to max delay
  return Math.min(delay, config.maxRetryDelay);
}

/**
 * Sleep for a given number of milliseconds.
 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Check if an error is a resilient fetch error.
 */
export function isResilientFetchError(error: unknown): error is ResilientFetchError {
  return error instanceof ResilientFetchError;
}

/**
 * Check if an error is a timeout error.
 */
export function isTimeoutError(error: unknown): boolean {
  return isResilientFetchError(error) && error.isTimeout;
}

/**
 * Check if an error is a cancellation error.
 */
export function isCancellationError(error: unknown): boolean {
  return isResilientFetchError(error) && error.isCancelled;
}
