/**
 * Fallback Chain Tests
 *
 * Tests for the provider fallback chain functionality.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  FallbackChain,
  createFallbackChain,
  formatHealthStatus,
  isChainExhaustedError,
  type ChainedProvider,
  type FallbackChainConfig,
  type FallbackChainEvent,
} from '../../src/providers/fallback-chain.js';
import type { LLMProvider, Message, ChatResponse } from '../../src/providers/types.js';
import { ProviderError } from '../../src/providers/types.js';

// =============================================================================
// TEST HELPERS
// =============================================================================

function createMockProvider(
  name: string,
  options: {
    configured?: boolean;
    failCount?: number;
    response?: string;
    delay?: number;
  } = {}
): LLMProvider {
  const { configured = true, failCount = 0, response = 'Mock response', delay = 0 } = options;
  let failures = 0;

  return {
    name,
    defaultModel: `${name}-model`,

    isConfigured: () => configured,

    chat: vi.fn(async (_messages: Message[]): Promise<ChatResponse> => {
      if (delay > 0) {
        await new Promise((resolve) => setTimeout(resolve, delay));
      }

      if (failures < failCount) {
        failures++;
        throw new ProviderError(`${name} failed`, name, 'SERVER_ERROR');
      }

      return {
        content: `${response} from ${name}`,
        stopReason: 'end_turn',
        usage: { inputTokens: 10, outputTokens: 20 },
      };
    }),
  };
}

// =============================================================================
// TESTS
// =============================================================================

describe('FallbackChain', () => {
  let primaryProvider: LLMProvider;
  let secondaryProvider: LLMProvider;
  let tertiaryProvider: LLMProvider;
  let config: FallbackChainConfig;

  beforeEach(() => {
    primaryProvider = createMockProvider('primary');
    secondaryProvider = createMockProvider('secondary');
    tertiaryProvider = createMockProvider('tertiary');

    config = {
      providers: [
        { provider: primaryProvider, priority: 1 },
        { provider: secondaryProvider, priority: 2 },
        { provider: tertiaryProvider, priority: 3 },
      ],
      cooldownMs: 1000,
      failureThreshold: 2,
    };
  });

  describe('initialization', () => {
    it('should create chain with providers', () => {
      const chain = createFallbackChain(config);

      expect(chain.name).toBe('fallback-chain');
      expect(chain.isConfigured()).toBe(true);
    });

    it('should sort providers by priority', () => {
      const chain = createFallbackChain({
        providers: [
          { provider: tertiaryProvider, priority: 3 },
          { provider: primaryProvider, priority: 1 },
          { provider: secondaryProvider, priority: 2 },
        ],
      });

      // Use default model from highest priority provider
      expect(chain.defaultModel).toBe('primary-model');
    });

    it('should initialize health tracking for all providers', () => {
      const chain = createFallbackChain(config);
      const health = chain.getHealth();

      expect(health.length).toBe(3);
      expect(health.every((h) => h.healthy)).toBe(true);
      expect(health.every((h) => h.consecutiveFailures === 0)).toBe(true);
    });

    it('should return false for isConfigured when no providers configured', () => {
      const unconfiguredProvider = createMockProvider('unconfigured', { configured: false });
      const chain = createFallbackChain({
        providers: [{ provider: unconfiguredProvider, priority: 1 }],
      });

      expect(chain.isConfigured()).toBe(false);
    });
  });

  describe('chat', () => {
    it('should use primary provider when healthy', async () => {
      const chain = createFallbackChain(config);
      const messages: Message[] = [{ role: 'user', content: 'Hello' }];

      const response = await chain.chat(messages);

      expect(response.content).toBe('Mock response from primary');
      expect(primaryProvider.chat).toHaveBeenCalledTimes(1);
      expect(secondaryProvider.chat).not.toHaveBeenCalled();
    });

    it('should fallback to secondary when primary fails', async () => {
      primaryProvider = createMockProvider('primary', { failCount: 10 });

      const chain = createFallbackChain({
        ...config,
        providers: [
          { provider: primaryProvider, priority: 1 },
          { provider: secondaryProvider, priority: 2 },
        ],
      });

      const messages: Message[] = [{ role: 'user', content: 'Hello' }];
      const response = await chain.chat(messages);

      expect(response.content).toBe('Mock response from secondary');
      expect(primaryProvider.chat).toHaveBeenCalledTimes(1);
      expect(secondaryProvider.chat).toHaveBeenCalledTimes(1);
    });

    it('should try all providers before throwing', async () => {
      primaryProvider = createMockProvider('primary', { failCount: 10 });
      secondaryProvider = createMockProvider('secondary', { failCount: 10 });
      tertiaryProvider = createMockProvider('tertiary', { failCount: 10 });

      const chain = createFallbackChain({
        providers: [
          { provider: primaryProvider, priority: 1 },
          { provider: secondaryProvider, priority: 2 },
          { provider: tertiaryProvider, priority: 3 },
        ],
      });

      const messages: Message[] = [{ role: 'user', content: 'Hello' }];

      await expect(chain.chat(messages)).rejects.toThrow('All providers in fallback chain failed');

      expect(primaryProvider.chat).toHaveBeenCalledTimes(1);
      expect(secondaryProvider.chat).toHaveBeenCalledTimes(1);
      expect(tertiaryProvider.chat).toHaveBeenCalledTimes(1);
    });

    it('should skip unconfigured providers', async () => {
      primaryProvider = createMockProvider('primary', { configured: false });

      const chain = createFallbackChain({
        ...config,
        providers: [
          { provider: primaryProvider, priority: 1 },
          { provider: secondaryProvider, priority: 2 },
        ],
        skipUnconfigured: true,
      });

      const messages: Message[] = [{ role: 'user', content: 'Hello' }];
      const response = await chain.chat(messages);

      expect(response.content).toBe('Mock response from secondary');
      expect(primaryProvider.chat).not.toHaveBeenCalled();
    });
  });

  describe('health tracking', () => {
    it('should record successes', async () => {
      const chain = createFallbackChain(config);
      const messages: Message[] = [{ role: 'user', content: 'Hello' }];

      await chain.chat(messages);
      await chain.chat(messages);

      const health = chain.getProviderHealth('primary');
      expect(health?.totalRequests).toBe(2);
      expect(health?.totalFailures).toBe(0);
      expect(health?.successRate).toBe(1);
    });

    it('should record failures', async () => {
      primaryProvider = createMockProvider('primary', { failCount: 10 });

      const chain = createFallbackChain({
        providers: [
          { provider: primaryProvider, priority: 1 },
          { provider: secondaryProvider, priority: 2 },
        ],
        failureThreshold: 5, // High threshold to prevent cooldown
      });

      const messages: Message[] = [{ role: 'user', content: 'Hello' }];
      await chain.chat(messages);

      const health = chain.getProviderHealth('primary');
      expect(health?.totalFailures).toBe(1);
      expect(health?.consecutiveFailures).toBe(1);
    });

    it('should trigger cooldown after failure threshold', async () => {
      primaryProvider = createMockProvider('primary', { failCount: 10 });

      const chain = createFallbackChain({
        providers: [
          { provider: primaryProvider, priority: 1 },
          { provider: secondaryProvider, priority: 2 },
        ],
        failureThreshold: 2,
        cooldownMs: 1000,
      });

      const messages: Message[] = [{ role: 'user', content: 'Hello' }];

      // First two requests trigger cooldown
      await chain.chat(messages);
      await chain.chat(messages);

      const health = chain.getProviderHealth('primary');
      expect(health?.healthy).toBe(false);
      expect(health?.cooldownUntil).toBeDefined();

      // Third request should not try primary (it's in cooldown)
      (primaryProvider.chat as ReturnType<typeof vi.fn>).mockClear();
      await chain.chat(messages);

      expect(primaryProvider.chat).not.toHaveBeenCalled();
    });

    it('should reset failures on success', async () => {
      // Fails first, then succeeds
      primaryProvider = createMockProvider('primary', { failCount: 1 });

      const chain = createFallbackChain({
        providers: [
          { provider: primaryProvider, priority: 1 },
          { provider: secondaryProvider, priority: 2 },
        ],
        failureThreshold: 3, // High enough to not trigger cooldown
      });

      const messages: Message[] = [{ role: 'user', content: 'Hello' }];

      // First call fails, falls back to secondary
      await chain.chat(messages);

      let health = chain.getProviderHealth('primary');
      expect(health?.consecutiveFailures).toBe(1);

      // Second call succeeds on primary (failCount exhausted)
      await chain.chat(messages);

      health = chain.getProviderHealth('primary');
      expect(health?.consecutiveFailures).toBe(0);
    });
  });

  describe('manual health control', () => {
    it('should allow manual health marking', async () => {
      const chain = createFallbackChain(config);

      chain.markUnhealthy('primary');

      const health = chain.getProviderHealth('primary');
      expect(health?.healthy).toBe(false);

      // Should use secondary
      const messages: Message[] = [{ role: 'user', content: 'Hello' }];
      await chain.chat(messages);

      expect(primaryProvider.chat).not.toHaveBeenCalled();
      expect(secondaryProvider.chat).toHaveBeenCalled();
    });

    it('should allow manual health recovery', async () => {
      const chain = createFallbackChain(config);

      chain.markUnhealthy('primary');
      chain.markHealthy('primary');

      const health = chain.getProviderHealth('primary');
      expect(health?.healthy).toBe(true);
      expect(health?.cooldownUntil).toBeUndefined();
    });
  });

  describe('events', () => {
    it('should emit success events', async () => {
      const events: FallbackChainEvent[] = [];
      const chain = createFallbackChain(config);

      chain.on((event) => events.push(event));

      const messages: Message[] = [{ role: 'user', content: 'Hello' }];
      await chain.chat(messages);

      expect(events.some((e) => e.type === 'provider.success')).toBe(true);
    });

    it('should emit fallback events', async () => {
      primaryProvider = createMockProvider('primary', { failCount: 10 });

      const events: FallbackChainEvent[] = [];
      const chain = createFallbackChain({
        providers: [
          { provider: primaryProvider, priority: 1 },
          { provider: secondaryProvider, priority: 2 },
        ],
      });

      chain.on((event) => events.push(event));

      const messages: Message[] = [{ role: 'user', content: 'Hello' }];
      await chain.chat(messages);

      const fallbackEvent = events.find((e) => e.type === 'provider.fallback');
      expect(fallbackEvent).toBeDefined();
      if (fallbackEvent?.type === 'provider.fallback') {
        expect(fallbackEvent.from).toBe('primary');
        expect(fallbackEvent.to).toBe('secondary');
      }
    });

    it('should emit cooldown events', async () => {
      primaryProvider = createMockProvider('primary', { failCount: 10 });

      const events: FallbackChainEvent[] = [];
      const chain = createFallbackChain({
        providers: [
          { provider: primaryProvider, priority: 1 },
          { provider: secondaryProvider, priority: 2 },
        ],
        failureThreshold: 2,
      });

      chain.on((event) => events.push(event));

      const messages: Message[] = [{ role: 'user', content: 'Hello' }];
      await chain.chat(messages);
      await chain.chat(messages);

      const cooldownEvent = events.find((e) => e.type === 'provider.cooldown.start');
      expect(cooldownEvent).toBeDefined();
    });

    it('should emit chain.exhausted when all providers fail', async () => {
      primaryProvider = createMockProvider('primary', { failCount: 10 });
      secondaryProvider = createMockProvider('secondary', { failCount: 10 });

      const events: FallbackChainEvent[] = [];
      const chain = createFallbackChain({
        providers: [
          { provider: primaryProvider, priority: 1 },
          { provider: secondaryProvider, priority: 2 },
        ],
      });

      chain.on((event) => events.push(event));

      const messages: Message[] = [{ role: 'user', content: 'Hello' }];

      try {
        await chain.chat(messages);
      } catch {
        // Expected
      }

      const exhaustedEvent = events.find((e) => e.type === 'chain.exhausted');
      expect(exhaustedEvent).toBeDefined();
    });

    it('should allow unsubscribing from events', async () => {
      const events: FallbackChainEvent[] = [];
      const chain = createFallbackChain(config);

      const unsubscribe = chain.on((event) => events.push(event));

      const messages: Message[] = [{ role: 'user', content: 'Hello' }];
      await chain.chat(messages);

      expect(events.length).toBeGreaterThan(0);

      events.length = 0;
      unsubscribe();

      await chain.chat(messages);
      expect(events.length).toBe(0);
    });
  });

  describe('callbacks', () => {
    it('should call onFallback when falling back', async () => {
      const onFallback = vi.fn();
      primaryProvider = createMockProvider('primary', { failCount: 10 });

      const chain = createFallbackChain({
        providers: [
          { provider: primaryProvider, priority: 1 },
          { provider: secondaryProvider, priority: 2 },
        ],
        onFallback,
      });

      const messages: Message[] = [{ role: 'user', content: 'Hello' }];
      await chain.chat(messages);

      expect(onFallback).toHaveBeenCalledWith('primary', 'secondary', expect.any(Error));
    });

    it('should call onHealthChange on health updates', async () => {
      const onHealthChange = vi.fn();

      const chain = createFallbackChain({
        ...config,
        onHealthChange,
      });

      const messages: Message[] = [{ role: 'user', content: 'Hello' }];
      await chain.chat(messages);

      expect(onHealthChange).toHaveBeenCalled();
    });
  });
});

describe('formatHealthStatus', () => {
  it('should format health status for display', () => {
    const health = [
      {
        name: 'primary',
        healthy: true,
        consecutiveFailures: 0,
        totalRequests: 100,
        totalFailures: 5,
        successRate: 0.95,
      },
      {
        name: 'secondary',
        healthy: false,
        consecutiveFailures: 3,
        totalRequests: 50,
        totalFailures: 10,
        successRate: 0.8,
        cooldownUntil: Date.now() + 30000,
        lastError: 'Connection refused',
      },
    ];

    const formatted = formatHealthStatus(health);

    expect(formatted).toContain('Provider Health Status');
    expect(formatted).toContain('primary');
    expect(formatted).toContain('secondary');
    expect(formatted).toContain('95.0%');
    expect(formatted).toContain('Connection refused');
  });
});

describe('isChainExhaustedError', () => {
  it('should identify chain exhausted errors', () => {
    const error = new ProviderError(
      'All providers in fallback chain failed for chat',
      'fallback-chain',
      'UNKNOWN'
    );

    expect(isChainExhaustedError(error)).toBe(true);
  });

  it('should not identify other errors', () => {
    const error = new Error('Some other error');
    expect(isChainExhaustedError(error)).toBe(false);

    const providerError = new ProviderError('Auth failed', 'anthropic', 'AUTHENTICATION_FAILED');
    expect(isChainExhaustedError(providerError)).toBe(false);
  });
});
