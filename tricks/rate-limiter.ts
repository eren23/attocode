/**
 * Trick G: Rate Limit Handling
 *
 * Manage API rate limits with token bucket and backpressure.
 * Handles retry-after headers and exponential backoff.
 */

// =============================================================================
// TYPES
// =============================================================================

/**
 * Rate limiter configuration.
 */
export interface RateLimiterConfig {
  /** Maximum requests per window */
  maxRequests: number;
  /** Window size in milliseconds */
  windowMs: number;
  /** Maximum concurrent requests */
  maxConcurrent?: number;
  /** Retry strategy */
  retryStrategy?: 'immediate' | 'exponential' | 'linear';
  /** Maximum retries */
  maxRetries?: number;
  /** Base delay for retries (ms) */
  baseDelay?: number;
}

/**
 * Rate limit status.
 */
export interface RateLimitStatus {
  remaining: number;
  resetAt: Date;
  limited: boolean;
  queueSize: number;
}

// =============================================================================
// RATE LIMITER
// =============================================================================

/**
 * Rate limiter with token bucket and backpressure.
 */
export class RateLimiter {
  private tokens: number;
  private maxTokens: number;
  private windowMs: number;
  private lastRefill: number;
  private queue: Array<{
    resolve: () => void;
    reject: (err: Error) => void;
    timeout: NodeJS.Timeout;
  }> = [];
  private active: number = 0;
  private maxConcurrent: number;
  private retryAfterMs: number = 0;
  private retryStrategy: 'immediate' | 'exponential' | 'linear';
  private maxRetries: number;
  private baseDelay: number;

  constructor(config: RateLimiterConfig) {
    this.maxTokens = config.maxRequests;
    this.tokens = config.maxRequests;
    this.windowMs = config.windowMs;
    this.lastRefill = Date.now();
    this.maxConcurrent = config.maxConcurrent ?? Infinity;
    this.retryStrategy = config.retryStrategy ?? 'exponential';
    this.maxRetries = config.maxRetries ?? 3;
    this.baseDelay = config.baseDelay ?? 1000;
  }

  /**
   * Acquire a permit to make a request.
   * Returns a promise that resolves when permitted.
   */
  async acquire(timeout: number = 30000): Promise<void> {
    // Refill tokens
    this.refillTokens();

    // Check if rate limited by server
    if (this.retryAfterMs > 0) {
      const waitTime = this.retryAfterMs - Date.now();
      if (waitTime > 0) {
        await this.sleep(waitTime);
        this.retryAfterMs = 0;
      }
    }

    // If we have tokens and aren't at max concurrent, proceed immediately
    if (this.tokens > 0 && this.active < this.maxConcurrent) {
      this.tokens--;
      this.active++;
      return;
    }

    // Otherwise, queue the request
    return new Promise((resolve, reject) => {
      const timeoutHandle = setTimeout(() => {
        const index = this.queue.findIndex((item) => item.resolve === resolve);
        if (index !== -1) {
          this.queue.splice(index, 1);
        }
        reject(new Error('Rate limit timeout'));
      }, timeout);

      this.queue.push({ resolve, reject, timeout: timeoutHandle });
    });
  }

  /**
   * Release a permit after request completes.
   */
  release(): void {
    this.active--;
    this.processQueue();
  }

  /**
   * Handle backpressure from server (retry-after header).
   */
  backpressure(retryAfterSeconds: number): void {
    this.retryAfterMs = Date.now() + retryAfterSeconds * 1000;
    // Clear tokens to force waiting
    this.tokens = 0;
  }

  /**
   * Get current status.
   */
  status(): RateLimitStatus {
    this.refillTokens();

    return {
      remaining: Math.max(0, this.tokens),
      resetAt: new Date(this.lastRefill + this.windowMs),
      limited: this.tokens <= 0 || this.active >= this.maxConcurrent,
      queueSize: this.queue.length,
    };
  }

  /**
   * Wrap an async function with rate limiting.
   */
  wrap<T>(fn: () => Promise<T>): () => Promise<T> {
    return async () => {
      await this.acquire();
      try {
        return await fn();
      } finally {
        this.release();
      }
    };
  }

  /**
   * Execute with retry logic.
   */
  async withRetry<T>(
    fn: () => Promise<T>,
    shouldRetry?: (error: unknown) => boolean
  ): Promise<T> {
    let lastError: unknown;

    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      try {
        await this.acquire();
        try {
          return await fn();
        } finally {
          this.release();
        }
      } catch (err) {
        lastError = err;

        // Check if we should retry
        if (shouldRetry && !shouldRetry(err)) {
          throw err;
        }

        // Check for rate limit response
        if (isRateLimitError(err)) {
          const retryAfter = extractRetryAfter(err);
          if (retryAfter) {
            this.backpressure(retryAfter);
          }
        }

        // Calculate delay
        if (attempt < this.maxRetries) {
          const delay = this.calculateDelay(attempt);
          await this.sleep(delay);
        }
      }
    }

    throw lastError;
  }

  /**
   * Refill tokens based on elapsed time.
   */
  private refillTokens(): void {
    const now = Date.now();
    const elapsed = now - this.lastRefill;

    if (elapsed >= this.windowMs) {
      // Full refill
      this.tokens = this.maxTokens;
      this.lastRefill = now;
    } else {
      // Partial refill (sliding window)
      const tokensToAdd = Math.floor((elapsed / this.windowMs) * this.maxTokens);
      if (tokensToAdd > 0) {
        this.tokens = Math.min(this.maxTokens, this.tokens + tokensToAdd);
        this.lastRefill = now;
      }
    }
  }

  /**
   * Process queued requests.
   */
  private processQueue(): void {
    this.refillTokens();

    while (
      this.queue.length > 0 &&
      this.tokens > 0 &&
      this.active < this.maxConcurrent
    ) {
      const next = this.queue.shift();
      if (next) {
        clearTimeout(next.timeout);
        this.tokens--;
        this.active++;
        next.resolve();
      }
    }
  }

  /**
   * Calculate retry delay based on strategy.
   */
  private calculateDelay(attempt: number): number {
    switch (this.retryStrategy) {
      case 'immediate':
        return 0;
      case 'linear':
        return this.baseDelay * (attempt + 1);
      case 'exponential':
      default:
        // Exponential backoff with jitter
        const exponentialDelay = this.baseDelay * Math.pow(2, attempt);
        const jitter = Math.random() * 0.3 * exponentialDelay;
        return exponentialDelay + jitter;
    }
  }

  /**
   * Sleep for specified milliseconds.
   */
  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Check if error is a rate limit error.
 */
function isRateLimitError(error: unknown): boolean {
  if (error instanceof Error) {
    const message = error.message.toLowerCase();
    return (
      message.includes('rate limit') ||
      message.includes('too many requests') ||
      message.includes('429')
    );
  }
  return false;
}

/**
 * Extract retry-after value from error.
 */
function extractRetryAfter(error: unknown): number | null {
  if (error && typeof error === 'object') {
    const err = error as Record<string, unknown>;

    // Check headers
    if (err.headers && typeof err.headers === 'object') {
      const headers = err.headers as Record<string, string>;
      const retryAfter = headers['retry-after'] || headers['Retry-After'];
      if (retryAfter) {
        return parseInt(retryAfter, 10);
      }
    }

    // Check response
    if (err.response && typeof err.response === 'object') {
      const response = err.response as Record<string, unknown>;
      if (response.headers && typeof response.headers === 'object') {
        const headers = response.headers as Record<string, string>;
        const retryAfter = headers['retry-after'] || headers['Retry-After'];
        if (retryAfter) {
          return parseInt(retryAfter, 10);
        }
      }
    }
  }
  return null;
}

/**
 * Create a rate limiter for common API patterns.
 */
export function createRateLimiter(config: RateLimiterConfig): RateLimiter {
  return new RateLimiter(config);
}

/**
 * Pre-configured rate limiters for common providers.
 */
export const PROVIDER_LIMITS = {
  openai: () =>
    createRateLimiter({
      maxRequests: 60,
      windowMs: 60000,
      maxConcurrent: 5,
      retryStrategy: 'exponential',
    }),

  anthropic: () =>
    createRateLimiter({
      maxRequests: 50,
      windowMs: 60000,
      maxConcurrent: 5,
      retryStrategy: 'exponential',
    }),

  custom: (rps: number) =>
    createRateLimiter({
      maxRequests: rps,
      windowMs: 1000,
      retryStrategy: 'linear',
    }),
};

// Usage:
// const limiter = createRateLimiter({ maxRequests: 100, windowMs: 60000 });
//
// // Simple acquire/release
// await limiter.acquire();
// try {
//   const response = await fetch('/api/...');
// } finally {
//   limiter.release();
// }
//
// // With wrapper
// const rateLimitedFetch = limiter.wrap(() => fetch('/api/...'));
// await rateLimitedFetch();
//
// // With retry
// const response = await limiter.withRetry(
//   () => fetch('/api/...'),
//   (err) => isRetryable(err)
// );
