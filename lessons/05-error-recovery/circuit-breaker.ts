/**
 * Lesson 5: Circuit Breaker
 * 
 * Prevents cascading failures by stopping requests when a service is down.
 */

import type {
  CircuitBreakerConfig,
  CircuitBreakerState,
  CircuitState,
  RecoveryEvent,
  RecoveryEventHandler,
} from './types.js';
import { DEFAULT_CIRCUIT_CONFIG } from './types.js';

// =============================================================================
// CIRCUIT BREAKER
// =============================================================================

export class CircuitBreaker {
  private config: CircuitBreakerConfig;
  private state: CircuitState = 'closed';
  private failures: number[] = []; // Timestamps of failures
  private consecutiveSuccesses = 0;
  private lastFailure?: Date;
  private lastSuccess?: Date;
  private stateChangedAt: Date = new Date();
  private eventHandler?: RecoveryEventHandler;

  constructor(config: Partial<CircuitBreakerConfig> = {}) {
    this.config = { ...DEFAULT_CIRCUIT_CONFIG, ...config };
  }

  /**
   * Set event handler for state changes.
   */
  onEvent(handler: RecoveryEventHandler): void {
    this.eventHandler = handler;
  }

  /**
   * Execute an operation through the circuit breaker.
   */
  async execute<T>(operation: () => Promise<T>): Promise<T> {
    // Clean up old failures
    this.cleanupOldFailures();

    // Check circuit state
    if (this.state === 'open') {
      if (this.shouldTransitionToHalfOpen()) {
        this.transitionTo('half-open');
      } else {
        this.emit({ type: 'circuit_rejected' });
        throw new CircuitOpenError('Circuit breaker is open');
      }
    }

    try {
      const result = await operation();
      this.recordSuccess();
      return result;
    } catch (error) {
      this.recordFailure();
      throw error;
    }
  }

  /**
   * Check if a request can pass through.
   */
  canExecute(): boolean {
    this.cleanupOldFailures();

    if (this.state === 'closed') {
      return true;
    }

    if (this.state === 'half-open') {
      return true;
    }

    // State is 'open'
    return this.shouldTransitionToHalfOpen();
  }

  /**
   * Record a successful operation.
   */
  private recordSuccess(): void {
    this.lastSuccess = new Date();
    this.consecutiveSuccesses++;

    if (this.state === 'half-open') {
      if (this.consecutiveSuccesses >= this.config.successThreshold) {
        this.transitionTo('closed');
      }
    }
  }

  /**
   * Record a failed operation.
   */
  private recordFailure(): void {
    this.lastFailure = new Date();
    this.failures.push(Date.now());
    this.consecutiveSuccesses = 0;

    if (this.state === 'half-open') {
      // Any failure in half-open state opens the circuit
      this.transitionTo('open');
    } else if (this.state === 'closed') {
      // Check if we should open the circuit
      if (this.failures.length >= this.config.failureThreshold) {
        this.transitionTo('open');
      }
    }
  }

  /**
   * Check if we should transition from open to half-open.
   */
  private shouldTransitionToHalfOpen(): boolean {
    const elapsed = Date.now() - this.stateChangedAt.getTime();
    return elapsed >= this.config.resetTimeout;
  }

  /**
   * Transition to a new state.
   */
  private transitionTo(newState: CircuitState): void {
    if (this.state === newState) return;

    const oldState = this.state;
    this.state = newState;
    this.stateChangedAt = new Date();

    // Reset counters on state change
    if (newState === 'closed') {
      this.failures = [];
      this.consecutiveSuccesses = 0;
      this.emit({ type: 'circuit_closed' });
    } else if (newState === 'half-open') {
      this.consecutiveSuccesses = 0;
      this.emit({ type: 'circuit_half_opened' });
    } else if (newState === 'open') {
      this.emit({ type: 'circuit_opened', failures: this.failures.length });
    }
  }

  /**
   * Remove failures outside the time window.
   */
  private cleanupOldFailures(): void {
    const cutoff = Date.now() - this.config.windowDuration;
    this.failures = this.failures.filter(ts => ts > cutoff);
  }

  /**
   * Emit an event.
   */
  private emit(event: RecoveryEvent): void {
    if (this.eventHandler) {
      try {
        this.eventHandler(event);
      } catch {
        // Ignore handler errors
      }
    }
  }

  /**
   * Get current state snapshot.
   */
  getState(): CircuitBreakerState {
    this.cleanupOldFailures();
    
    return {
      state: this.state,
      failures: this.failures.length,
      successes: this.consecutiveSuccesses,
      lastFailure: this.lastFailure,
      lastSuccess: this.lastSuccess,
      nextRetry: this.state === 'open' 
        ? new Date(this.stateChangedAt.getTime() + this.config.resetTimeout)
        : undefined,
    };
  }

  /**
   * Manually reset the circuit breaker.
   */
  reset(): void {
    this.failures = [];
    this.consecutiveSuccesses = 0;
    this.lastFailure = undefined;
    this.lastSuccess = undefined;
    this.transitionTo('closed');
  }

  /**
   * Force the circuit open (for testing or manual intervention).
   */
  forceOpen(): void {
    this.transitionTo('open');
  }
}

// =============================================================================
// ERROR
// =============================================================================

/**
 * Error thrown when circuit is open.
 */
export class CircuitOpenError extends Error {
  readonly name = 'CircuitOpenError';
  
  constructor(message: string) {
    super(message);
  }
}

// =============================================================================
// FACTORY
// =============================================================================

/**
 * Create a circuit breaker for a named service.
 */
const circuitBreakers = new Map<string, CircuitBreaker>();

export function getCircuitBreaker(
  name: string,
  config?: Partial<CircuitBreakerConfig>
): CircuitBreaker {
  let breaker = circuitBreakers.get(name);
  
  if (!breaker) {
    breaker = new CircuitBreaker(config);
    circuitBreakers.set(name, breaker);
  }
  
  return breaker;
}

/**
 * Reset all circuit breakers.
 */
export function resetAllCircuitBreakers(): void {
  for (const breaker of circuitBreakers.values()) {
    breaker.reset();
  }
}
