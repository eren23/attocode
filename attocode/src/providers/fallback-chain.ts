/**
 * Provider Fallback Chain
 *
 * Wraps multiple LLM providers with automatic failover.
 * When the primary provider fails, requests are routed to secondary providers.
 *
 * Features:
 * - Priority-based provider ordering
 * - Cooldown period for failed providers
 * - Circuit breaker integration (optional)
 * - Health tracking and metrics
 *
 * @example
 * ```typescript
 * const chain = createFallbackChain({
 *   providers: [
 *     { provider: anthropicProvider, priority: 1 },
 *     { provider: openRouterProvider, priority: 2 },
 *     { provider: openAIProvider, priority: 3 },
 *   ],
 *   cooldownMs: 60000,  // 1 minute cooldown after failure
 * });
 *
 * // Uses first available provider, fails over automatically
 * const response = await chain.chat(messages);
 * ```
 */

import type {
  LLMProvider,
  LLMProviderWithTools,
  Message,
  MessageWithContent,
  ChatOptions,
  ChatOptionsWithTools,
  ChatResponse,
  ChatResponseWithTools,
  ProviderErrorCode,
} from './types.js';
import { ProviderError } from './types.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * A provider entry in the fallback chain.
 */
export interface ChainedProvider {
  /** The LLM provider instance */
  provider: LLMProvider | LLMProviderWithTools;
  /** Priority (lower = tried first) */
  priority: number;
  /** Optional weight for load balancing (future use) */
  weight?: number;
}

/**
 * Health status of a provider.
 */
export interface ProviderHealth {
  /** Provider name */
  name: string;
  /** Whether provider is currently healthy */
  healthy: boolean;
  /** Number of consecutive failures */
  consecutiveFailures: number;
  /** Timestamp of last failure */
  lastFailureAt?: number;
  /** Timestamp when cooldown ends */
  cooldownUntil?: number;
  /** Last error message */
  lastError?: string;
  /** Total requests made */
  totalRequests: number;
  /** Total failures */
  totalFailures: number;
  /** Success rate (0-1) */
  successRate: number;
}

/**
 * Configuration for the fallback chain.
 */
export interface FallbackChainConfig {
  /** Providers in the chain */
  providers: ChainedProvider[];
  /** Cooldown period after failure in ms (default: 60000) */
  cooldownMs?: number;
  /** Number of failures before cooldown (default: 3) */
  failureThreshold?: number;
  /** Whether to skip providers that aren't configured (default: true) */
  skipUnconfigured?: boolean;
  /** Callback when falling back to next provider */
  onFallback?: (from: string, to: string, error: Error) => void;
  /** Callback when provider health changes */
  onHealthChange?: (name: string, health: ProviderHealth) => void;
}

/**
 * Events emitted by the fallback chain.
 */
export type FallbackChainEvent =
  | { type: 'provider.success'; provider: string; duration: number }
  | { type: 'provider.failure'; provider: string; error: Error; willRetry: boolean }
  | { type: 'provider.fallback'; from: string; to: string; error: Error }
  | { type: 'provider.cooldown.start'; provider: string; until: number }
  | { type: 'provider.cooldown.end'; provider: string }
  | { type: 'chain.exhausted'; errors: Array<{ provider: string; error: Error }> };

export type FallbackChainEventListener = (event: FallbackChainEvent) => void;

// =============================================================================
// FALLBACK CHAIN
// =============================================================================

/**
 * Provider fallback chain with automatic failover.
 */
export class FallbackChain implements LLMProviderWithTools {
  readonly name = 'fallback-chain';
  readonly defaultModel: string;

  private config: Required<Omit<FallbackChainConfig, 'onFallback' | 'onHealthChange'>> & {
    onFallback?: FallbackChainConfig['onFallback'];
    onHealthChange?: FallbackChainConfig['onHealthChange'];
  };
  private healthMap: Map<string, ProviderHealth> = new Map();
  private listeners: FallbackChainEventListener[] = [];

  constructor(config: FallbackChainConfig) {
    // Sort providers by priority
    const sortedProviders = [...config.providers].sort((a, b) => a.priority - b.priority);

    this.config = {
      providers: sortedProviders,
      cooldownMs: config.cooldownMs ?? 60000,
      failureThreshold: config.failureThreshold ?? 3,
      skipUnconfigured: config.skipUnconfigured ?? true,
      onFallback: config.onFallback,
      onHealthChange: config.onHealthChange,
    };

    // Use first provider's default model
    this.defaultModel = sortedProviders[0]?.provider.defaultModel ?? 'unknown';

    // Initialize health tracking
    for (const { provider } of sortedProviders) {
      this.healthMap.set(provider.name, {
        name: provider.name,
        healthy: true,
        consecutiveFailures: 0,
        totalRequests: 0,
        totalFailures: 0,
        successRate: 1,
      });
    }
  }

  /**
   * Check if any provider in the chain is configured.
   */
  isConfigured(): boolean {
    return this.config.providers.some(({ provider }) => provider.isConfigured());
  }

  /**
   * Send a chat request, falling back through providers on failure.
   */
  async chat(messages: Message[], options?: ChatOptions): Promise<ChatResponse> {
    return this.executeWithFallback(
      (provider) => provider.chat(messages, options),
      'chat'
    );
  }

  /**
   * Send a chat request with tools, falling back through providers on failure.
   */
  async chatWithTools(
    messages: (Message | MessageWithContent)[],
    options?: ChatOptionsWithTools
  ): Promise<ChatResponseWithTools> {
    return this.executeWithFallback(
      (provider) => {
        if (this.supportsTools(provider)) {
          return provider.chatWithTools(messages, options);
        }
        // Fall back to regular chat if provider doesn't support tools
        const simpleMessages = messages.map(m => ({
          role: m.role as 'user' | 'assistant' | 'system',
          content: typeof m.content === 'string' ? m.content : '[complex content]',
        }));
        return provider.chat(simpleMessages, options);
      },
      'chatWithTools'
    );
  }

  /**
   * Get health status of all providers.
   */
  getHealth(): ProviderHealth[] {
    return Array.from(this.healthMap.values());
  }

  /**
   * Get health status of a specific provider.
   */
  getProviderHealth(name: string): ProviderHealth | undefined {
    return this.healthMap.get(name);
  }

  /**
   * Manually mark a provider as healthy (e.g., after fixing an issue).
   */
  markHealthy(name: string): void {
    const health = this.healthMap.get(name);
    if (health) {
      health.healthy = true;
      health.consecutiveFailures = 0;
      health.cooldownUntil = undefined;
      this.emit({ type: 'provider.cooldown.end', provider: name });
      this.config.onHealthChange?.(name, health);
    }
  }

  /**
   * Manually mark a provider as unhealthy (e.g., for maintenance).
   */
  markUnhealthy(name: string, duration?: number): void {
    const health = this.healthMap.get(name);
    if (health) {
      health.healthy = false;
      health.cooldownUntil = Date.now() + (duration ?? this.config.cooldownMs);
      this.emit({ type: 'provider.cooldown.start', provider: name, until: health.cooldownUntil });
      this.config.onHealthChange?.(name, health);
    }
  }

  /**
   * Subscribe to events.
   */
  on(listener: FallbackChainEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  // ===========================================================================
  // PRIVATE METHODS
  // ===========================================================================

  private async executeWithFallback<T>(
    operation: (provider: LLMProvider | LLMProviderWithTools) => Promise<T>,
    operationName: string
  ): Promise<T> {
    const errors: Array<{ provider: string; error: Error }> = [];
    const availableProviders = this.getAvailableProviders();

    if (availableProviders.length === 0) {
      throw new ProviderError(
        'No providers available in fallback chain (all in cooldown or unconfigured)',
        this.name,
        'NOT_CONFIGURED'
      );
    }

    for (let i = 0; i < availableProviders.length; i++) {
      const { provider } = availableProviders[i];
      const health = this.healthMap.get(provider.name)!;

      health.totalRequests++;
      const startTime = Date.now();

      try {
        const result = await operation(provider);

        // Success - update health
        this.recordSuccess(provider.name, Date.now() - startTime);

        return result;
      } catch (error) {
        const err = error instanceof Error ? error : new Error(String(error));
        errors.push({ provider: provider.name, error: err });

        // Record failure
        this.recordFailure(provider.name, err);

        // Check if we should fall back
        const nextProvider = availableProviders[i + 1];
        if (nextProvider) {
          this.emit({
            type: 'provider.fallback',
            from: provider.name,
            to: nextProvider.provider.name,
            error: err,
          });

          this.config.onFallback?.(provider.name, nextProvider.provider.name, err);
        }
      }
    }

    // All providers failed
    this.emit({ type: 'chain.exhausted', errors });

    throw new ProviderError(
      `All providers in fallback chain failed for ${operationName}. ` +
        `Errors: ${errors.map(e => `${e.provider}: ${e.error.message}`).join('; ')}`,
      this.name,
      this.determineErrorCode(errors)
    );
  }

  private getAvailableProviders(): ChainedProvider[] {
    const now = Date.now();

    return this.config.providers.filter(({ provider }) => {
      // Check if configured
      if (this.config.skipUnconfigured && !provider.isConfigured()) {
        return false;
      }

      // Check health/cooldown
      const health = this.healthMap.get(provider.name);
      if (!health) return true;

      // Check if in cooldown
      if (health.cooldownUntil && health.cooldownUntil > now) {
        return false;
      }

      // Cooldown expired - reset health
      if (health.cooldownUntil && health.cooldownUntil <= now) {
        health.healthy = true;
        health.cooldownUntil = undefined;
        this.emit({ type: 'provider.cooldown.end', provider: provider.name });
      }

      return health.healthy;
    });
  }

  private recordSuccess(name: string, duration: number): void {
    const health = this.healthMap.get(name);
    if (!health) return;

    health.consecutiveFailures = 0;
    health.healthy = true;
    health.successRate = this.calculateSuccessRate(health);

    this.emit({ type: 'provider.success', provider: name, duration });
    this.config.onHealthChange?.(name, health);
  }

  private recordFailure(name: string, error: Error): void {
    const health = this.healthMap.get(name);
    if (!health) return;

    health.consecutiveFailures++;
    health.totalFailures++;
    health.lastFailureAt = Date.now();
    health.lastError = error.message;
    health.successRate = this.calculateSuccessRate(health);

    const willRetry = health.consecutiveFailures < this.config.failureThreshold;

    this.emit({
      type: 'provider.failure',
      provider: name,
      error,
      willRetry,
    });

    // Check if we should trigger cooldown
    if (health.consecutiveFailures >= this.config.failureThreshold) {
      health.healthy = false;
      health.cooldownUntil = Date.now() + this.config.cooldownMs;

      this.emit({
        type: 'provider.cooldown.start',
        provider: name,
        until: health.cooldownUntil,
      });
    }

    this.config.onHealthChange?.(name, health);
  }

  private calculateSuccessRate(health: ProviderHealth): number {
    if (health.totalRequests === 0) return 1;
    return (health.totalRequests - health.totalFailures) / health.totalRequests;
  }

  private supportsTools(provider: LLMProvider): provider is LLMProviderWithTools {
    return 'chatWithTools' in provider && typeof provider.chatWithTools === 'function';
  }

  private determineErrorCode(errors: Array<{ provider: string; error: Error }>): ProviderErrorCode {
    // Check for specific error patterns
    for (const { error } of errors) {
      if (error instanceof ProviderError) {
        // Propagate specific codes (prioritize rate limits and auth)
        if (error.code === 'RATE_LIMITED') return 'RATE_LIMITED';
        if (error.code === 'AUTHENTICATION_FAILED') return 'AUTHENTICATION_FAILED';
      }
    }

    // Check if all errors are network-related
    const allNetwork = errors.every(({ error }) =>
      error.message.toLowerCase().includes('network') ||
      error.message.toLowerCase().includes('timeout') ||
      error.message.toLowerCase().includes('connection')
    );
    if (allNetwork) return 'NETWORK_ERROR';

    return 'UNKNOWN';
  }

  private emit(event: FallbackChainEvent): void {
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
 * Create a fallback chain from providers.
 *
 * @example
 * ```typescript
 * const chain = createFallbackChain({
 *   providers: [
 *     { provider: anthropicProvider, priority: 1 },
 *     { provider: openRouterProvider, priority: 2 },
 *   ],
 *   cooldownMs: 60000,
 *   onFallback: (from, to, error) => {
 *     console.log(`Falling back from ${from} to ${to}: ${error.message}`);
 *   },
 * });
 * ```
 */
export function createFallbackChain(config: FallbackChainConfig): FallbackChain {
  return new FallbackChain(config);
}

/**
 * Create a fallback chain from the provider registry.
 * Automatically includes all configured providers sorted by priority.
 */
export async function createFallbackChainFromRegistry(
  overrides?: Partial<Omit<FallbackChainConfig, 'providers'>>
): Promise<FallbackChain> {
  // Dynamic import to avoid circular dependency
  const { listProviders, getProvider } = await import('./provider.js');

  const available = listProviders().filter(p => p.configured);
  const chainedProviders: ChainedProvider[] = [];

  for (const { name, priority } of available) {
    try {
      const provider = await getProvider(name);
      chainedProviders.push({ provider, priority });
    } catch {
      // Skip providers that fail to initialize
    }
  }

  if (chainedProviders.length === 0) {
    throw new ProviderError(
      'No providers could be initialized for fallback chain',
      'fallback-chain',
      'NOT_CONFIGURED'
    );
  }

  return createFallbackChain({
    providers: chainedProviders,
    ...overrides,
  });
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Format health status for display.
 */
export function formatHealthStatus(health: ProviderHealth[]): string {
  const lines = ['Provider Health Status:', ''];

  for (const h of health) {
    const status = h.healthy ? '✓' : '✗';
    const rate = `${(h.successRate * 100).toFixed(1)}%`;
    const cooldown = h.cooldownUntil
      ? ` (cooldown until ${new Date(h.cooldownUntil).toLocaleTimeString()})`
      : '';

    lines.push(`  ${status} ${h.name}: ${rate} success, ${h.totalRequests} requests${cooldown}`);

    if (h.lastError) {
      lines.push(`      Last error: ${h.lastError}`);
    }
  }

  return lines.join('\n');
}

/**
 * Check if an error is from an exhausted fallback chain.
 */
export function isChainExhaustedError(error: unknown): boolean {
  return (
    error instanceof ProviderError &&
    error.provider === 'fallback-chain' &&
    error.message.includes('All providers in fallback chain failed')
  );
}
