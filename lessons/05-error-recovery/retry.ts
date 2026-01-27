/**
 * Lesson 5: Retry Manager
 * 
 * Intelligent retry logic with multiple strategies.
 */

import type {
  RetryConfig,
  RetryResult,
  RetryAttempt,
  RetryableOperation,
  ExecuteOptions,
  ClassifiedError,
  RecoveryEvent,
} from './types.js';
import { DEFAULT_RETRY_CONFIG } from './types.js';
import { classifyError } from './classifier.js';

// =============================================================================
// RETRY MANAGER
// =============================================================================

export class RetryManager {
  private config: RetryConfig;
  private stats: Map<string, { successes: number; failures: number }> = new Map();

  constructor(config: Partial<RetryConfig> = {}) {
    this.config = { ...DEFAULT_RETRY_CONFIG, ...config };
  }

  /**
   * Execute an operation with retry logic.
   */
  async execute<T>(
    operation: RetryableOperation<T>,
    options: ExecuteOptions = {}
  ): Promise<RetryResult<T>> {
    const config = { ...this.config, ...options.config };
    const attempts: RetryAttempt[] = [];
    const startTime = Date.now();
    const opName = options.operation ?? 'operation';

    let lastError: ClassifiedError | undefined;

    for (let attempt = 1; attempt <= config.maxRetries + 1; attempt++) {
      // Check for cancellation
      if (options.signal?.aborted) {
        return {
          success: false,
          error: lastError,
          attempts,
          totalTime: Date.now() - startTime,
        };
      }

      // Calculate delay (skip for first attempt)
      const delay = attempt > 1 ? this.calculateDelay(attempt - 1, config, lastError) : 0;

      if (delay > 0) {
        this.emit(options.onEvent, { type: 'retry_start', attempt, delay });
        await this.sleep(delay, options.signal);
      }

      try {
        const value = await operation();
        
        // Success!
        const successAttempt: RetryAttempt = {
          attempt,
          error: lastError!,
          delay,
          timestamp: new Date(),
          success: true,
        };
        attempts.push(successAttempt);
        
        this.emit(options.onEvent, { type: 'retry_success', attempt });
        this.recordSuccess(opName);

        return {
          success: true,
          value,
          attempts,
          totalTime: Date.now() - startTime,
        };
      } catch (error) {
        lastError = classifyError(error as Error);
        
        const failedAttempt: RetryAttempt = {
          attempt,
          error: lastError,
          delay,
          timestamp: new Date(),
          success: false,
        };
        attempts.push(failedAttempt);

        this.emit(options.onEvent, { type: 'retry_failed', attempt, error: lastError });
        this.recordFailure(opName);

        // Check if we should retry
        const shouldRetry = this.shouldRetry(lastError, attempt, config);
        
        if (!shouldRetry) {
          break;
        }
      }
    }

    // All retries exhausted
    this.emit(options.onEvent, {
      type: 'retry_exhausted',
      totalAttempts: attempts.length,
      finalError: lastError!,
    });

    return {
      success: false,
      error: lastError,
      attempts,
      totalTime: Date.now() - startTime,
    };
  }

  /**
   * Calculate delay for the next retry.
   */
  private calculateDelay(
    attempt: number,
    config: RetryConfig,
    error?: ClassifiedError
  ): number {
    let delay: number;

    switch (config.strategy) {
      case 'fixed':
        delay = config.baseDelay;
        break;

      case 'linear':
        delay = config.baseDelay * attempt;
        break;

      case 'exponential':
        delay = config.baseDelay * Math.pow(config.backoffMultiplier, attempt - 1);
        break;

      case 'adaptive':
        // Use error's suggested delay if available
        if (error?.suggestedDelay) {
          delay = error.suggestedDelay;
        } else {
          // Otherwise use exponential
          delay = config.baseDelay * Math.pow(config.backoffMultiplier, attempt - 1);
        }
        break;

      default:
        delay = config.baseDelay;
    }

    // Apply jitter
    if (config.jitter) {
      const jitterFactor = 0.5 + Math.random(); // 0.5 to 1.5
      delay = delay * jitterFactor;
    }

    // Cap at max delay
    return Math.min(delay, config.maxDelay);
  }

  /**
   * Determine if we should retry an error.
   */
  private shouldRetry(
    error: ClassifiedError,
    attempt: number,
    config: RetryConfig
  ): boolean {
    // Check if we've exhausted retries
    if (attempt >= config.maxRetries + 1) {
      return false;
    }

    // Check if the error is recoverable
    if (!error.recoverable) {
      return false;
    }

    // Check if the error category is retryable
    if (!config.retryableCategories.includes(error.category)) {
      return false;
    }

    return true;
  }

  /**
   * Sleep with cancellation support.
   */
  private sleep(ms: number, signal?: AbortSignal): Promise<void> {
    return new Promise((resolve, reject) => {
      if (signal?.aborted) {
        resolve();
        return;
      }

      const timer = setTimeout(resolve, ms);

      signal?.addEventListener('abort', () => {
        clearTimeout(timer);
        resolve();
      });
    });
  }

  /**
   * Emit an event if handler is provided.
   */
  private emit(handler: ExecuteOptions['onEvent'], event: RecoveryEvent): void {
    if (handler) {
      try {
        handler(event);
      } catch {
        // Ignore handler errors
      }
    }
  }

  /**
   * Record a successful operation.
   */
  private recordSuccess(operation: string): void {
    const stats = this.stats.get(operation) ?? { successes: 0, failures: 0 };
    stats.successes++;
    this.stats.set(operation, stats);
  }

  /**
   * Record a failed operation.
   */
  private recordFailure(operation: string): void {
    const stats = this.stats.get(operation) ?? { successes: 0, failures: 0 };
    stats.failures++;
    this.stats.set(operation, stats);
  }

  /**
   * Get statistics for all operations.
   */
  getStats(): Map<string, { successes: number; failures: number; successRate: number }> {
    const result = new Map<string, { successes: number; failures: number; successRate: number }>();
    
    for (const [op, stats] of this.stats) {
      const total = stats.successes + stats.failures;
      result.set(op, {
        ...stats,
        successRate: total > 0 ? stats.successes / total : 0,
      });
    }
    
    return result;
  }

  /**
   * Reset statistics.
   */
  resetStats(): void {
    this.stats.clear();
  }
}

// =============================================================================
// DECORATOR
// =============================================================================

/**
 * Create a retryable version of an async function.
 */
export function withRetry<TArgs extends unknown[], TResult>(
  fn: (...args: TArgs) => Promise<TResult>,
  config: Partial<RetryConfig> = {}
): (...args: TArgs) => Promise<TResult> {
  const manager = new RetryManager(config);

  return async (...args: TArgs): Promise<TResult> => {
    const result = await manager.execute(() => fn(...args));
    
    if (result.success) {
      return result.value!;
    }
    
    throw result.error?.original ?? new Error('Operation failed after retries');
  };
}
