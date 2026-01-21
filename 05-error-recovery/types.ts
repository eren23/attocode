/**
 * Lesson 5: Error Recovery Types
 * 
 * Types for error classification, retry strategies, and circuit breakers.
 */

// =============================================================================
// ERROR TYPES
// =============================================================================

/**
 * Categories of errors for classification.
 */
export type ErrorCategory =
  | 'network'        // Network connectivity issues
  | 'timeout'        // Operation timed out
  | 'rate_limit'     // API rate limiting (429)
  | 'server_error'   // 5xx server errors
  | 'client_error'   // 4xx client errors (except 429)
  | 'auth'           // Authentication/authorization failures
  | 'validation'     // Invalid input/response
  | 'context_limit'  // Context length exceeded
  | 'unknown';       // Unclassified errors

/**
 * Classified error with metadata.
 */
export interface ClassifiedError {
  /** Original error */
  original: Error;
  
  /** Error category */
  category: ErrorCategory;
  
  /** Whether this error can be retried */
  recoverable: boolean;
  
  /** Suggested delay before retry (if recoverable) */
  suggestedDelay?: number;
  
  /** HTTP status code (if applicable) */
  statusCode?: number;
  
  /** Reason for classification */
  reason: string;
}

// =============================================================================
// RETRY TYPES
// =============================================================================

/**
 * Retry strategy types.
 */
export type RetryStrategy =
  | 'fixed'        // Same delay every time
  | 'linear'       // Delay increases linearly
  | 'exponential'  // Delay doubles each time
  | 'adaptive';    // Adjusts based on error type

/**
 * Configuration for retry behavior.
 */
export interface RetryConfig {
  /** Maximum number of retry attempts */
  maxRetries: number;
  
  /** Base delay in milliseconds */
  baseDelay: number;
  
  /** Maximum delay (cap) in milliseconds */
  maxDelay: number;
  
  /** Retry strategy to use */
  strategy: RetryStrategy;
  
  /** Add random jitter to delays */
  jitter: boolean;
  
  /** Multiplier for exponential backoff */
  backoffMultiplier: number;
  
  /** Which error categories are retryable */
  retryableCategories: ErrorCategory[];
}

/**
 * Default retry configuration.
 */
export const DEFAULT_RETRY_CONFIG: RetryConfig = {
  maxRetries: 3,
  baseDelay: 1000,
  maxDelay: 30000,
  strategy: 'exponential',
  jitter: true,
  backoffMultiplier: 2,
  retryableCategories: [
    'network',
    'timeout',
    'rate_limit',
    'server_error',
  ],
};

/**
 * Information about a retry attempt.
 */
export interface RetryAttempt {
  /** Attempt number (1-indexed) */
  attempt: number;
  
  /** Error that triggered the retry */
  error: ClassifiedError;
  
  /** Delay before this attempt */
  delay: number;
  
  /** Timestamp of the attempt */
  timestamp: Date;
  
  /** Whether the attempt succeeded */
  success: boolean;
}

/**
 * Result of a retried operation.
 */
export interface RetryResult<T> {
  /** Whether the operation eventually succeeded */
  success: boolean;
  
  /** The result value (if successful) */
  value?: T;
  
  /** The final error (if failed) */
  error?: ClassifiedError;
  
  /** All retry attempts made */
  attempts: RetryAttempt[];
  
  /** Total time spent */
  totalTime: number;
}

// =============================================================================
// CIRCUIT BREAKER TYPES
// =============================================================================

/**
 * Circuit breaker states.
 */
export type CircuitState = 
  | 'closed'    // Normal operation, requests flow through
  | 'open'      // Too many failures, blocking requests
  | 'half-open'; // Testing if service recovered

/**
 * Configuration for circuit breaker.
 */
export interface CircuitBreakerConfig {
  /** Number of failures before opening circuit */
  failureThreshold: number;
  
  /** Time to wait before trying again (ms) */
  resetTimeout: number;
  
  /** Number of successes needed to close from half-open */
  successThreshold: number;
  
  /** Time window for counting failures (ms) */
  windowDuration: number;
}

/**
 * Default circuit breaker configuration.
 */
export const DEFAULT_CIRCUIT_CONFIG: CircuitBreakerConfig = {
  failureThreshold: 5,
  resetTimeout: 30000,
  successThreshold: 2,
  windowDuration: 60000,
};

/**
 * Circuit breaker state snapshot.
 */
export interface CircuitBreakerState {
  state: CircuitState;
  failures: number;
  successes: number;
  lastFailure?: Date;
  lastSuccess?: Date;
  nextRetry?: Date;
}

// =============================================================================
// EVENT TYPES
// =============================================================================

/**
 * Events emitted during error recovery.
 */
export type RecoveryEvent =
  | { type: 'retry_start'; attempt: number; delay: number }
  | { type: 'retry_success'; attempt: number }
  | { type: 'retry_failed'; attempt: number; error: ClassifiedError }
  | { type: 'retry_exhausted'; totalAttempts: number; finalError: ClassifiedError }
  | { type: 'circuit_opened'; failures: number }
  | { type: 'circuit_half_opened' }
  | { type: 'circuit_closed' }
  | { type: 'circuit_rejected' };

/**
 * Event handler for recovery events.
 */
export type RecoveryEventHandler = (event: RecoveryEvent) => void;

// =============================================================================
// OPERATION TYPES
// =============================================================================

/**
 * An async operation that can be retried.
 */
export type RetryableOperation<T> = () => Promise<T>;

/**
 * Options for executing a retryable operation.
 */
export interface ExecuteOptions {
  /** Name of the operation (for logging) */
  operation?: string;
  
  /** Override retry config for this operation */
  config?: Partial<RetryConfig>;
  
  /** Abort signal for cancellation */
  signal?: AbortSignal;
  
  /** Event handler */
  onEvent?: RecoveryEventHandler;
}
