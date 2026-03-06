/**
 * Shared base types for common configuration patterns.
 *
 * These types capture recurring shapes found across 20+ config interfaces.
 * New configs should compose from these bases where appropriate.
 * Existing interfaces get `@see` annotations pointing here — no breaking changes.
 */

/**
 * Retry behavior configuration.
 * @see ToolRetryConfig in tools/types.ts
 * @see RetryConfig in integrations/retry.ts
 * @see CircuitBreakerConfig in providers/circuit-breaker.ts
 */
export interface RetryConfig {
  maxAttempts?: number;
  baseDelayMs?: number;
  maxDelayMs?: number;
}

/**
 * Budget / capacity limits configuration.
 * @see ResourceConfig in types.ts
 * @see SemanticCacheAgentConfig in types.ts
 */
export interface BudgetConfig {
  maxEntries?: number;
  /** Warning threshold as a 0-1 ratio. */
  warnThreshold?: number;
}

/**
 * Timeout and grace period configuration.
 * @see CancellationConfig in types.ts
 * @see SubagentConfig in types.ts
 */
export interface TimeoutConfig {
  timeoutMs?: number;
  gracePeriodMs?: number;
}

/**
 * Model selection configuration.
 */
export interface ModelSelectionConfig {
  model?: string;
  maxTokens?: number;
}
