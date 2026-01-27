/**
 * Lesson 22: Fallback Chain
 *
 * Handles graceful degradation when models fail.
 * Implements retry logic and cascading fallbacks.
 */

import type {
  FallbackConfig,
  FallbackResult,
  FallbackTrigger,
  ModelAttempt,
  RouterEvent,
  RouterEventListener,
} from './types.js';

// =============================================================================
// FALLBACK CHAIN
// =============================================================================

/**
 * Manages fallback execution across multiple models.
 */
export class FallbackChain<T> {
  private config: FallbackConfig;
  private listeners: Set<RouterEventListener> = new Set();

  constructor(config: FallbackConfig) {
    this.config = config;
  }

  /**
   * Execute with fallback chain.
   */
  async execute(
    fn: (model: string) => Promise<T>,
    errorClassifier?: (error: unknown) => FallbackTrigger | null
  ): Promise<FallbackResult<T>> {
    const startTime = Date.now();
    const attempts: ModelAttempt[] = [];
    const allModels = [this.config.primary, ...this.config.fallbacks];

    for (let modelIndex = 0; modelIndex < allModels.length; modelIndex++) {
      const model = allModels[modelIndex];
      const modelAttempt = await this.attemptModel(
        model,
        fn,
        errorClassifier
      );
      attempts.push(modelAttempt);

      if (modelAttempt.success) {
        return {
          result: modelAttempt.result as T,
          successModel: model,
          attemptedModels: attempts,
          success: true,
          totalTimeMs: Date.now() - startTime,
          totalCost: attempts.reduce((sum, a) => sum + a.cost, 0),
        };
      }

      // Emit fallback event
      if (modelIndex < allModels.length - 1) {
        this.emit({
          type: 'fallback.triggered',
          trigger: modelAttempt.errorType || 'error',
          fromModel: model,
          toModel: allModels[modelIndex + 1],
        });
      }
    }

    // All models failed
    this.emit({
      type: 'fallback.exhausted',
      attempts,
    });

    return {
      attemptedModels: attempts,
      success: false,
      totalTimeMs: Date.now() - startTime,
      totalCost: attempts.reduce((sum, a) => sum + a.cost, 0),
    };
  }

  /**
   * Attempt a single model with retries.
   */
  private async attemptModel(
    model: string,
    fn: (model: string) => Promise<T>,
    errorClassifier?: (error: unknown) => FallbackTrigger | null
  ): Promise<ModelAttempt & { result?: T }> {
    const startTime = Date.now();
    let lastError: unknown = null;
    let lastErrorType: FallbackTrigger | undefined;

    for (let retry = 0; retry <= this.config.maxRetriesPerModel; retry++) {
      try {
        // Add delay between retries
        if (retry > 0) {
          const delay = this.calculateDelay(retry);
          await this.sleep(delay);
        }

        const result = await fn(model);

        return {
          model,
          success: true,
          durationMs: Date.now() - startTime,
          cost: 0, // Would be calculated from actual usage
          retries: retry,
          result,
        };
      } catch (error) {
        lastError = error;
        lastErrorType = errorClassifier
          ? errorClassifier(error) || 'error'
          : this.classifyError(error);

        // Check if error is retryable
        if (!this.isRetryable(lastErrorType)) {
          break;
        }
      }
    }

    return {
      model,
      success: false,
      error: lastError instanceof Error ? lastError.message : String(lastError),
      errorType: lastErrorType,
      durationMs: Date.now() - startTime,
      cost: 0,
      retries: this.config.maxRetriesPerModel,
    };
  }

  /**
   * Calculate retry delay.
   */
  private calculateDelay(attempt: number): number {
    if (this.config.exponentialBackoff) {
      return this.config.retryDelayMs * Math.pow(2, attempt - 1);
    }
    return this.config.retryDelayMs;
  }

  /**
   * Check if error type is retryable.
   */
  private isRetryable(errorType: FallbackTrigger): boolean {
    const retryable: FallbackTrigger[] = [
      'rate_limit',
      'timeout',
      'overload',
    ];
    return retryable.includes(errorType);
  }

  /**
   * Classify an error into a trigger type.
   */
  private classifyError(error: unknown): FallbackTrigger {
    if (!(error instanceof Error)) return 'error';

    const message = error.message.toLowerCase();

    if (message.includes('rate limit') || message.includes('429')) {
      return 'rate_limit';
    }
    if (message.includes('timeout') || message.includes('timed out')) {
      return 'timeout';
    }
    if (message.includes('overload') || message.includes('503')) {
      return 'overload';
    }
    if (message.includes('unavailable') || message.includes('not found')) {
      return 'unavailable';
    }
    if (message.includes('context') || message.includes('token')) {
      return 'context_too_long';
    }
    if (message.includes('cost') || message.includes('budget')) {
      return 'cost_exceeded';
    }

    return 'error';
  }

  /**
   * Sleep helper.
   */
  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  /**
   * Subscribe to events.
   */
  on(listener: RouterEventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /**
   * Emit an event.
   */
  private emit(event: RouterEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch (err) {
        console.error('Fallback chain listener error:', err);
      }
    }
  }
}

// =============================================================================
// FALLBACK BUILDER
// =============================================================================

/**
 * Fluent builder for fallback configuration.
 */
export class FallbackBuilder {
  private config: Partial<FallbackConfig> = {
    fallbacks: [],
    triggers: ['rate_limit', 'timeout', 'error', 'overload', 'unavailable'],
    maxRetriesPerModel: 2,
    retryDelayMs: 1000,
    exponentialBackoff: true,
  };

  /**
   * Set primary model.
   */
  primary(model: string): FallbackBuilder {
    this.config.primary = model;
    return this;
  }

  /**
   * Add fallback model.
   */
  fallbackTo(model: string): FallbackBuilder {
    this.config.fallbacks!.push(model);
    return this;
  }

  /**
   * Set fallback models.
   */
  fallbacks(models: string[]): FallbackBuilder {
    this.config.fallbacks = models;
    return this;
  }

  /**
   * Set triggers.
   */
  onTriggers(triggers: FallbackTrigger[]): FallbackBuilder {
    this.config.triggers = triggers;
    return this;
  }

  /**
   * Set max retries per model.
   */
  maxRetries(n: number): FallbackBuilder {
    this.config.maxRetriesPerModel = n;
    return this;
  }

  /**
   * Set retry delay.
   */
  retryDelay(ms: number): FallbackBuilder {
    this.config.retryDelayMs = ms;
    return this;
  }

  /**
   * Enable/disable exponential backoff.
   */
  exponentialBackoff(enabled: boolean): FallbackBuilder {
    this.config.exponentialBackoff = enabled;
    return this;
  }

  /**
   * Build the configuration.
   */
  build(): FallbackConfig {
    if (!this.config.primary) {
      throw new Error('Primary model is required');
    }

    return this.config as FallbackConfig;
  }

  /**
   * Build and create chain.
   */
  createChain<T>(): FallbackChain<T> {
    return new FallbackChain<T>(this.build());
  }
}

// =============================================================================
// CIRCUIT BREAKER
// =============================================================================

/**
 * Circuit breaker state.
 */
type CircuitState = 'closed' | 'open' | 'half-open';

/**
 * Circuit breaker for preventing cascade failures.
 */
export class CircuitBreaker {
  private state: CircuitState = 'closed';
  private failures = 0;
  private successes = 0;
  private lastFailureTime = 0;
  private listeners: Set<RouterEventListener> = new Set();

  constructor(
    private model: string,
    private failureThreshold: number = 5,
    private successThreshold: number = 3,
    private resetTimeoutMs: number = 30000
  ) {}

  /**
   * Check if the circuit allows requests.
   */
  canRequest(): boolean {
    if (this.state === 'closed') return true;

    if (this.state === 'open') {
      // Check if we should try half-open
      if (Date.now() - this.lastFailureTime > this.resetTimeoutMs) {
        this.state = 'half-open';
        return true;
      }
      return false;
    }

    // Half-open: allow limited requests
    return true;
  }

  /**
   * Record a successful request.
   */
  recordSuccess(): void {
    if (this.state === 'half-open') {
      this.successes++;
      if (this.successes >= this.successThreshold) {
        this.state = 'closed';
        this.failures = 0;
        this.successes = 0;
        this.emit({
          type: 'model.recovered',
          model: this.model,
        });
      }
    } else {
      this.failures = 0;
    }
  }

  /**
   * Record a failed request.
   */
  recordFailure(): void {
    this.failures++;
    this.lastFailureTime = Date.now();

    if (this.state === 'half-open') {
      // Back to open on any failure
      this.state = 'open';
      this.successes = 0;
      this.emit({
        type: 'model.unavailable',
        model: this.model,
        reason: 'Circuit breaker opened (half-open failure)',
      });
    } else if (this.failures >= this.failureThreshold) {
      this.state = 'open';
      this.emit({
        type: 'model.unavailable',
        model: this.model,
        reason: `Circuit breaker opened after ${this.failures} failures`,
      });
    }
  }

  /**
   * Get current state.
   */
  getState(): CircuitState {
    return this.state;
  }

  /**
   * Force circuit to close.
   */
  reset(): void {
    this.state = 'closed';
    this.failures = 0;
    this.successes = 0;
  }

  /**
   * Subscribe to events.
   */
  on(listener: RouterEventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit(event: RouterEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch (err) {
        console.error('Circuit breaker listener error:', err);
      }
    }
  }
}

// =============================================================================
// CIRCUIT BREAKER REGISTRY
// =============================================================================

/**
 * Manages circuit breakers for multiple models.
 */
export class CircuitBreakerRegistry {
  private breakers: Map<string, CircuitBreaker> = new Map();

  constructor(
    private failureThreshold: number = 5,
    private successThreshold: number = 3,
    private resetTimeoutMs: number = 30000
  ) {}

  /**
   * Get or create breaker for a model.
   */
  getBreaker(model: string): CircuitBreaker {
    let breaker = this.breakers.get(model);
    if (!breaker) {
      breaker = new CircuitBreaker(
        model,
        this.failureThreshold,
        this.successThreshold,
        this.resetTimeoutMs
      );
      this.breakers.set(model, breaker);
    }
    return breaker;
  }

  /**
   * Check if a model can receive requests.
   */
  canRequest(model: string): boolean {
    return this.getBreaker(model).canRequest();
  }

  /**
   * Record success for a model.
   */
  recordSuccess(model: string): void {
    this.getBreaker(model).recordSuccess();
  }

  /**
   * Record failure for a model.
   */
  recordFailure(model: string): void {
    this.getBreaker(model).recordFailure();
  }

  /**
   * Get available models from a list.
   */
  filterAvailable(models: string[]): string[] {
    return models.filter((m) => this.canRequest(m));
  }

  /**
   * Get all breaker states.
   */
  getAllStates(): Record<string, CircuitState> {
    const states: Record<string, CircuitState> = {};
    for (const [model, breaker] of this.breakers) {
      states[model] = breaker.getState();
    }
    return states;
  }

  /**
   * Reset all breakers.
   */
  resetAll(): void {
    for (const breaker of this.breakers.values()) {
      breaker.reset();
    }
  }
}

// =============================================================================
// EXPORTS
// =============================================================================

export function createFallbackChain<T>(config: FallbackConfig): FallbackChain<T> {
  return new FallbackChain<T>(config);
}

export function createFallbackBuilder(): FallbackBuilder {
  return new FallbackBuilder();
}

export function createCircuitBreaker(
  model: string,
  options?: {
    failureThreshold?: number;
    successThreshold?: number;
    resetTimeoutMs?: number;
  }
): CircuitBreaker {
  return new CircuitBreaker(
    model,
    options?.failureThreshold,
    options?.successThreshold,
    options?.resetTimeoutMs
  );
}

export function createCircuitBreakerRegistry(
  options?: {
    failureThreshold?: number;
    successThreshold?: number;
    resetTimeoutMs?: number;
  }
): CircuitBreakerRegistry {
  return new CircuitBreakerRegistry(
    options?.failureThreshold,
    options?.successThreshold,
    options?.resetTimeoutMs
  );
}
