/**
 * Circuit Breaker for LLM Providers
 *
 * Implements the circuit breaker pattern to prevent hammering failed services.
 *
 * States:
 * - CLOSED: Normal operation, requests pass through
 * - OPEN: Service is failing, requests are rejected immediately
 * - HALF_OPEN: Testing if service has recovered
 *
 * @example
 * ```typescript
 * const breaker = createCircuitBreaker({
 *   failureThreshold: 5,
 *   resetTimeout: 30000,
 *   halfOpenRequests: 1,
 * });
 *
 * const wrappedProvider = breaker.wrap(anthropicProvider);
 *
 * // Or use manually
 * if (breaker.canRequest()) {
 *   try {
 *     const result = await provider.chat(messages);
 *     breaker.recordSuccess();
 *     return result;
 *   } catch (error) {
 *     breaker.recordFailure(error);
 *     throw error;
 *   }
 * }
 * ```
 */

import type {
  LLMProvider,
  LLMProviderWithTools,
  Message,
  MessageWithContent,
  ChatOptions,
  ChatOptionsWithTools,
} from './types.js';
import { ProviderError } from './types.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Circuit breaker states.
 */
export type CircuitState = 'CLOSED' | 'OPEN' | 'HALF_OPEN';

/**
 * Configuration for the circuit breaker.
 * @see RetryConfig in config/base-types.ts for the shared retry pattern.
 */
export interface CircuitBreakerConfig {
  /** Number of failures before opening circuit (default: 5) */
  failureThreshold?: number;
  /** Time in ms before attempting to close circuit (default: 30000) */
  resetTimeout?: number;
  /** Number of test requests in half-open state (default: 1) */
  halfOpenRequests?: number;
  /** Timeout for individual requests in ms (default: undefined - no timeout) */
  requestTimeout?: number;
  /** Error types that should trip the breaker (default: all errors) */
  tripOnErrors?: Array<'RATE_LIMITED' | 'SERVER_ERROR' | 'NETWORK_ERROR' | 'TIMEOUT' | 'ALL'>;
}

/**
 * Circuit breaker metrics.
 */
export interface CircuitBreakerMetrics {
  /** Current state */
  state: CircuitState;
  /** Number of consecutive failures */
  failures: number;
  /** Number of successful requests */
  successes: number;
  /** Total requests since creation */
  totalRequests: number;
  /** Requests rejected due to open circuit */
  rejectedRequests: number;
  /** Last state change timestamp */
  lastStateChange: number;
  /** Time until circuit attempts to close (if OPEN) */
  resetAt?: number;
  /** Last error message */
  lastError?: string;
}

/**
 * Events emitted by the circuit breaker.
 */
export type CircuitBreakerEvent =
  | { type: 'state.change'; from: CircuitState; to: CircuitState; reason: string }
  | { type: 'request.success'; duration: number }
  | { type: 'request.failure'; error: Error; duration: number }
  | { type: 'request.rejected'; reason: string };

export type CircuitBreakerEventListener = (event: CircuitBreakerEvent) => void;

// =============================================================================
// CIRCUIT BREAKER
// =============================================================================

/**
 * Circuit breaker for protecting against cascading failures.
 */
export class CircuitBreaker {
  private state: CircuitState = 'CLOSED';
  private failures = 0;
  private successes = 0;
  private totalRequests = 0;
  private rejectedRequests = 0;
  private lastStateChange = Date.now();
  private resetAt?: number;
  private lastError?: string;
  private halfOpenInProgress = 0;
  private listeners: CircuitBreakerEventListener[] = [];
  private config: Required<CircuitBreakerConfig>;

  constructor(config: CircuitBreakerConfig = {}) {
    this.config = {
      failureThreshold: config.failureThreshold ?? 5,
      resetTimeout: config.resetTimeout ?? 30000,
      halfOpenRequests: config.halfOpenRequests ?? 1,
      requestTimeout: config.requestTimeout ?? 0, // 0 = no timeout
      tripOnErrors: config.tripOnErrors ?? ['ALL'],
    };
  }

  /**
   * Get current state.
   */
  getState(): CircuitState {
    this.checkStateTransition();
    return this.state;
  }

  /**
   * Get current metrics.
   */
  getMetrics(): CircuitBreakerMetrics {
    this.checkStateTransition();
    return {
      state: this.state,
      failures: this.failures,
      successes: this.successes,
      totalRequests: this.totalRequests,
      rejectedRequests: this.rejectedRequests,
      lastStateChange: this.lastStateChange,
      resetAt: this.resetAt,
      lastError: this.lastError,
    };
  }

  /**
   * Check if a request can proceed.
   */
  canRequest(): boolean {
    this.checkStateTransition();

    switch (this.state) {
      case 'CLOSED':
        return true;

      case 'OPEN':
        return false;

      case 'HALF_OPEN':
        return this.halfOpenInProgress < this.config.halfOpenRequests;

      default:
        return false;
    }
  }

  /**
   * Record a successful request.
   */
  recordSuccess(): void {
    this.successes++;
    this.totalRequests++;

    if (this.state === 'HALF_OPEN') {
      this.halfOpenInProgress--;

      // All half-open requests succeeded - close circuit
      if (this.halfOpenInProgress === 0) {
        this.transitionTo('CLOSED', 'Half-open test succeeded');
      }
    } else if (this.state === 'CLOSED') {
      // Reset failure counter on success
      this.failures = 0;
    }

    this.emit({ type: 'request.success', duration: 0 });
  }

  /**
   * Record a failed request.
   */
  recordFailure(error?: Error): void {
    this.totalRequests++;
    this.failures++;
    this.lastError = error?.message;

    // Check if this error should trip the breaker
    if (!this.shouldTrip(error)) {
      this.emit({ type: 'request.failure', error: error ?? new Error('Unknown'), duration: 0 });
      return;
    }

    if (this.state === 'HALF_OPEN') {
      this.halfOpenInProgress--;
      // Half-open test failed - reopen circuit
      this.transitionTo('OPEN', 'Half-open test failed');
    } else if (this.state === 'CLOSED') {
      // Check if we should open
      if (this.failures >= this.config.failureThreshold) {
        this.transitionTo('OPEN', `Failure threshold reached (${this.failures})`);
      }
    }

    this.emit({ type: 'request.failure', error: error ?? new Error('Unknown'), duration: 0 });
  }

  /**
   * Record a rejected request (circuit was open).
   */
  recordRejection(): void {
    this.rejectedRequests++;
    this.emit({ type: 'request.rejected', reason: 'Circuit is open' });
  }

  /**
   * Manually reset the circuit breaker.
   */
  reset(): void {
    this.transitionTo('CLOSED', 'Manual reset');
    this.failures = 0;
    this.halfOpenInProgress = 0;
  }

  /**
   * Manually trip the circuit breaker.
   */
  trip(reason: string = 'Manual trip'): void {
    this.transitionTo('OPEN', reason);
  }

  /**
   * Execute a function with circuit breaker protection.
   */
  async execute<T>(fn: () => Promise<T>): Promise<T> {
    if (!this.canRequest()) {
      this.recordRejection();
      throw new ProviderError(
        `Circuit breaker is ${this.state}`,
        'circuit-breaker',
        'SERVER_ERROR'
      );
    }

    if (this.state === 'HALF_OPEN') {
      this.halfOpenInProgress++;
    }

    try {
      let result: T;

      if (this.config.requestTimeout > 0) {
        result = await Promise.race([
          fn(),
          new Promise<never>((_, reject) =>
            setTimeout(() => reject(new Error('Request timeout')), this.config.requestTimeout)
          ),
        ]);
      } else {
        result = await fn();
      }

      this.recordSuccess();
      return result;
    } catch (error) {
      const err = error instanceof Error ? error : new Error(String(error));
      this.recordFailure(err);
      throw error;
    }
  }

  /**
   * Wrap a provider with circuit breaker protection.
   */
  wrap<T extends LLMProvider>(provider: T): T {
    const breaker = this;

    // Create a proxy that intercepts chat methods
    return new Proxy(provider, {
      get(target, prop) {
        const value = target[prop as keyof T];

        if (prop === 'chat') {
          return async function (messages: Message[], options?: ChatOptions) {
            return breaker.execute(() => target.chat(messages, options));
          };
        }

        if (prop === 'chatWithTools' && 'chatWithTools' in target) {
          return async function (
            messages: (Message | MessageWithContent)[],
            options?: ChatOptionsWithTools
          ) {
            return breaker.execute(() =>
              (target as LLMProviderWithTools).chatWithTools(messages, options)
            );
          };
        }

        return value;
      },
    });
  }

  /**
   * Subscribe to events.
   */
  on(listener: CircuitBreakerEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  // ===========================================================================
  // PRIVATE METHODS
  // ===========================================================================

  private checkStateTransition(): void {
    if (this.state === 'OPEN' && this.resetAt && Date.now() >= this.resetAt) {
      this.transitionTo('HALF_OPEN', 'Reset timeout elapsed');
    }
  }

  private transitionTo(newState: CircuitState, reason: string): void {
    const oldState = this.state;
    this.state = newState;
    this.lastStateChange = Date.now();

    if (newState === 'OPEN') {
      this.resetAt = Date.now() + this.config.resetTimeout;
    } else {
      this.resetAt = undefined;
    }

    if (newState === 'CLOSED') {
      this.failures = 0;
    }

    this.emit({ type: 'state.change', from: oldState, to: newState, reason });
  }

  private shouldTrip(error?: Error): boolean {
    if (this.config.tripOnErrors.includes('ALL')) {
      return true;
    }

    if (!error) return true;

    const message = error.message.toLowerCase();

    if (this.config.tripOnErrors.includes('RATE_LIMITED')) {
      if (message.includes('rate') || message.includes('429')) return true;
    }

    if (this.config.tripOnErrors.includes('SERVER_ERROR')) {
      if (message.includes('500') || message.includes('502') || message.includes('503')) return true;
    }

    if (this.config.tripOnErrors.includes('NETWORK_ERROR')) {
      if (message.includes('network') || message.includes('connection') || message.includes('econnrefused')) return true;
    }

    if (this.config.tripOnErrors.includes('TIMEOUT')) {
      if (message.includes('timeout')) return true;
    }

    return false;
  }

  private emit(event: CircuitBreakerEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create a circuit breaker.
 */
export function createCircuitBreaker(config: CircuitBreakerConfig = {}): CircuitBreaker {
  return new CircuitBreaker(config);
}

/**
 * Create a strict circuit breaker (trips quickly).
 */
export function createStrictCircuitBreaker(): CircuitBreaker {
  return new CircuitBreaker({
    failureThreshold: 3,
    resetTimeout: 60000,
    halfOpenRequests: 1,
  });
}

/**
 * Create a lenient circuit breaker (more tolerant).
 */
export function createLenientCircuitBreaker(): CircuitBreaker {
  return new CircuitBreaker({
    failureThreshold: 10,
    resetTimeout: 15000,
    halfOpenRequests: 3,
  });
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Format circuit breaker metrics for display.
 */
export function formatCircuitBreakerMetrics(metrics: CircuitBreakerMetrics): string {
  const lines = [
    `Circuit Breaker Status: ${metrics.state}`,
    `  Failures: ${metrics.failures}`,
    `  Successes: ${metrics.successes}`,
    `  Total Requests: ${metrics.totalRequests}`,
    `  Rejected: ${metrics.rejectedRequests}`,
  ];

  if (metrics.resetAt) {
    const remaining = Math.max(0, metrics.resetAt - Date.now());
    lines.push(`  Reset in: ${(remaining / 1000).toFixed(1)}s`);
  }

  if (metrics.lastError) {
    lines.push(`  Last Error: ${metrics.lastError}`);
  }

  return lines.join('\n');
}

/**
 * Check if an error is from a tripped circuit breaker.
 */
export function isCircuitBreakerError(error: unknown): boolean {
  return (
    error instanceof ProviderError &&
    error.provider === 'circuit-breaker'
  );
}
