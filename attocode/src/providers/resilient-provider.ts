/**
 * Resilient Provider Factory
 *
 * Creates providers wrapped with circuit breaker and fallback chain support.
 * Provides production-grade reliability for LLM API calls.
 *
 * @example
 * ```typescript
 * // Single provider with circuit breaker
 * const provider = await getResilientProvider('anthropic');
 *
 * // Fallback chain across multiple providers
 * const chain = await createResilientFallbackChain({
 *   providers: ['anthropic', 'openrouter', 'openai'],
 *   circuitBreaker: { failureThreshold: 3, resetTimeout: 30000 },
 * });
 * ```
 */

import { getProvider, listProviders } from './provider.js';
import {
  CircuitBreaker,
  createCircuitBreaker,
  type CircuitBreakerConfig,
  type CircuitBreakerMetrics,
} from './circuit-breaker.js';
import {
  FallbackChain,
  createFallbackChain,
  type FallbackChainConfig,
  type ProviderHealth,
} from './fallback-chain.js';
import type { LLMProvider, LLMProviderWithTools } from './types.js';
import { logger } from '../integrations/utilities/logger.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Configuration for a resilient provider.
 */
export interface ResilientProviderConfig {
  /** Circuit breaker configuration (enabled by default) */
  circuitBreaker?: CircuitBreakerConfig | false;
}

/**
 * Configuration for creating a resilient fallback chain.
 */
export interface ResilientChainConfig {
  /** Provider names in priority order (lower index = higher priority) */
  providers?: string[];

  /** Circuit breaker config to wrap each provider */
  circuitBreaker?: CircuitBreakerConfig | false;

  /** Fallback chain config overrides */
  fallback?: Partial<Omit<FallbackChainConfig, 'providers'>>;

  /** Callback when falling back between providers */
  onFallback?: (from: string, to: string, error: Error) => void;

  /** Callback when provider health changes */
  onHealthChange?: (name: string, health: ProviderHealth) => void;
}

/**
 * Registry entry for circuit breakers.
 */
interface CircuitBreakerEntry {
  breaker: CircuitBreaker;
  provider: LLMProvider | LLMProviderWithTools;
}

// =============================================================================
// GLOBAL STATE
// =============================================================================

/**
 * Global registry of circuit breakers per provider.
 * Reused across calls to maintain state.
 */
const circuitBreakers = new Map<string, CircuitBreakerEntry>();

/**
 * Default circuit breaker configuration.
 */
const DEFAULT_CIRCUIT_BREAKER_CONFIG: CircuitBreakerConfig = {
  failureThreshold: 5,
  resetTimeout: 30000,
  halfOpenRequests: 1,
  tripOnErrors: ['RATE_LIMITED', 'SERVER_ERROR', 'NETWORK_ERROR', 'TIMEOUT'],
};

// =============================================================================
// RESILIENT PROVIDER
// =============================================================================

/**
 * Get a provider wrapped with a circuit breaker.
 *
 * The circuit breaker prevents cascading failures by:
 * - Tracking consecutive failures
 * - Opening the circuit after a threshold is reached
 * - Rejecting requests immediately when open
 * - Periodically testing if the service has recovered
 *
 * @example
 * ```typescript
 * const provider = await getResilientProvider('anthropic', {
 *   circuitBreaker: {
 *     failureThreshold: 3,
 *     resetTimeout: 60000,
 *   },
 * });
 *
 * // Provider will throw CircuitBreakerError when circuit is open
 * const response = await provider.chat(messages);
 * ```
 */
export async function getResilientProvider(
  preferred?: string,
  config: ResilientProviderConfig = {}
): Promise<LLMProvider | LLMProviderWithTools> {
  const provider = await getProvider(preferred);

  // Check if circuit breaker is disabled
  if (config.circuitBreaker === false) {
    return provider;
  }

  // Get or create circuit breaker for this provider
  const breakerConfig = {
    ...DEFAULT_CIRCUIT_BREAKER_CONFIG,
    ...(typeof config.circuitBreaker === 'object' ? config.circuitBreaker : {}),
  };

  let entry = circuitBreakers.get(provider.name);

  if (!entry) {
    const breaker = createCircuitBreaker(breakerConfig);
    entry = { breaker, provider };
    circuitBreakers.set(provider.name, entry);
  }

  // Wrap the provider with circuit breaker
  return entry.breaker.wrap(provider);
}

/**
 * Get the circuit breaker for a provider (if it exists).
 */
export function getCircuitBreaker(providerName: string): CircuitBreaker | null {
  return circuitBreakers.get(providerName)?.breaker ?? null;
}

/**
 * Get metrics for all circuit breakers.
 */
export function getAllCircuitBreakerMetrics(): Record<string, CircuitBreakerMetrics> {
  const metrics: Record<string, CircuitBreakerMetrics> = {};

  for (const [name, entry] of circuitBreakers) {
    metrics[name] = entry.breaker.getMetrics();
  }

  return metrics;
}

/**
 * Reset all circuit breakers.
 */
export function resetAllCircuitBreakers(): void {
  for (const entry of circuitBreakers.values()) {
    entry.breaker.reset();
  }
}

// =============================================================================
// RESILIENT FALLBACK CHAIN
// =============================================================================

/**
 * Create a fallback chain with circuit breaker protection.
 *
 * Combines multiple providers into a resilient chain that:
 * - Tries providers in priority order
 * - Skips providers that are in cooldown
 * - Wraps each provider with a circuit breaker
 * - Tracks health and success rates
 *
 * @example
 * ```typescript
 * const chain = await createResilientFallbackChain({
 *   providers: ['anthropic', 'openrouter', 'openai'],
 *   circuitBreaker: {
 *     failureThreshold: 3,
 *     resetTimeout: 30000,
 *   },
 *   fallback: {
 *     cooldownMs: 60000,
 *     failureThreshold: 2,
 *   },
 *   onFallback: (from, to, error) => {
 *     console.log(`Falling back from ${from} to ${to}: ${error.message}`);
 *   },
 * });
 *
 * // Chain automatically handles failures and fallbacks
 * const response = await chain.chat(messages);
 * ```
 */
export async function createResilientFallbackChain(
  config: ResilientChainConfig = {}
): Promise<FallbackChain> {
  // Get available providers
  const available = listProviders().filter(p => p.configured);

  // Determine provider order
  let providerNames: string[];
  if (config.providers && config.providers.length > 0) {
    // Use specified order, but only include configured providers
    providerNames = config.providers.filter(name =>
      available.some(p => p.name === name)
    );
  } else {
    // Use default priority order
    providerNames = available.map(p => p.name);
  }

  if (providerNames.length === 0) {
    throw new Error('No configured providers available for fallback chain');
  }

  // Create wrapped providers
  const chainedProviders: Array<{
    provider: LLMProvider | LLMProviderWithTools;
    priority: number;
  }> = [];

  for (let i = 0; i < providerNames.length; i++) {
    const name = providerNames[i];

    try {
      // Get provider with circuit breaker (if enabled)
      const provider = await getResilientProvider(name, {
        circuitBreaker: config.circuitBreaker,
      });

      chainedProviders.push({
        provider,
        priority: i + 1, // Priority based on position
      });
    } catch (error) {
      // Skip providers that fail to initialize
      logger.warn('Failed to initialize resilient provider', { provider: name, error: String(error) });
    }
  }

  if (chainedProviders.length === 0) {
    throw new Error('No providers could be initialized for fallback chain');
  }

  // Create fallback chain
  return createFallbackChain({
    providers: chainedProviders,
    cooldownMs: config.fallback?.cooldownMs ?? 60000,
    failureThreshold: config.fallback?.failureThreshold ?? 3,
    onFallback: config.onFallback,
    onHealthChange: config.onHealthChange,
  });
}

/**
 * Create a fallback chain from all configured providers.
 *
 * Convenience function that creates a chain with sensible defaults.
 */
export async function createAutoFallbackChain(): Promise<FallbackChain> {
  return createResilientFallbackChain({
    // Use default provider priority
    circuitBreaker: DEFAULT_CIRCUIT_BREAKER_CONFIG,
    fallback: {
      cooldownMs: 60000,
      failureThreshold: 3,
    },
  });
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Format resilience status for display.
 */
export function formatResilienceStatus(): string {
  const metrics = getAllCircuitBreakerMetrics();
  const lines = ['Provider Resilience Status:', ''];

  if (Object.keys(metrics).length === 0) {
    lines.push('  No circuit breakers active');
    return lines.join('\n');
  }

  for (const [name, m] of Object.entries(metrics)) {
    const stateIcon = {
      CLOSED: '✓',
      OPEN: '✗',
      'HALF_OPEN': '◐',
    }[m.state] ?? '?';

    lines.push(`  ${stateIcon} ${name}: ${m.state}`);
    lines.push(`      Requests: ${m.totalRequests} (${m.rejectedRequests} rejected)`);
    lines.push(`      Failures: ${m.failures}`);

    if (m.resetAt) {
      const remaining = Math.max(0, m.resetAt - Date.now());
      lines.push(`      Reset in: ${(remaining / 1000).toFixed(1)}s`);
    }

    if (m.lastError) {
      lines.push(`      Last error: ${m.lastError}`);
    }

    lines.push('');
  }

  return lines.join('\n');
}

/**
 * Check if resilient provider features are available.
 */
export function hasResilientProviderSupport(): boolean {
  return true; // Always available now that modules are wired
}
