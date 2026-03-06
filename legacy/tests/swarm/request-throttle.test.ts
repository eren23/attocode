/**
 * Tests for SwarmThrottle and ThrottledProvider
 */
import { describe, it, expect, vi } from 'vitest';
import {
  SwarmThrottle,
  ThrottledProvider,
  createThrottledProvider,
  FREE_TIER_THROTTLE,
  PAID_TIER_THROTTLE,
} from '../../src/integrations/swarm/request-throttle.js';
import type { ThrottleConfig } from '../../src/integrations/swarm/request-throttle.js';
import type { LLMProvider, ChatResponse } from '../../src/providers/types.js';

// ─── Helpers ────────────────────────────────────────────────────────────────

function makeMockProvider(overrides: Partial<LLMProvider> = {}): LLMProvider {
  return {
    name: 'test-provider',
    defaultModel: 'test-model',
    isConfigured: () => true,
    chat: vi.fn().mockResolvedValue({
      content: 'Hello',
      stopReason: 'end_turn',
      usage: { inputTokens: 10, outputTokens: 5 },
    } satisfies ChatResponse),
    ...overrides,
  };
}

function fastThrottleConfig(overrides: Partial<ThrottleConfig> = {}): ThrottleConfig {
  return {
    maxConcurrent: 2,
    refillRatePerSecond: 100, // very fast refill for tests
    minSpacingMs: 0,          // no spacing for tests (unless explicitly set)
    ...overrides,
  };
}

// ─── SwarmThrottle Tests ────────────────────────────────────────────────────

describe('SwarmThrottle', () => {
  it('should allow immediate acquire when tokens available', async () => {
    const throttle = new SwarmThrottle(fastThrottleConfig());
    const start = Date.now();
    await throttle.acquire();
    const elapsed = Date.now() - start;
    expect(elapsed).toBeLessThan(50);
  });

  it('should respect maxConcurrent capacity', async () => {
    const throttle = new SwarmThrottle(fastThrottleConfig({
      maxConcurrent: 2,
      refillRatePerSecond: 0, // no refill — tokens don't come back
    }));

    // First two should succeed immediately
    await throttle.acquire();
    await throttle.acquire();

    // Third should block (we test by racing with a timeout)
    const result = await Promise.race([
      throttle.acquire().then(() => 'acquired'),
      new Promise<string>(resolve => setTimeout(() => resolve('timeout'), 100)),
    ]);

    expect(result).toBe('timeout');
  });

  it('should enforce minSpacing between acquisitions', async () => {
    const throttle = new SwarmThrottle(fastThrottleConfig({
      minSpacingMs: 100,
    }));

    const start = Date.now();
    await throttle.acquire();
    await throttle.acquire();
    const elapsed = Date.now() - start;

    // Second acquire should have waited ~100ms
    expect(elapsed).toBeGreaterThanOrEqual(90);
  });

  it('should refill tokens over time', async () => {
    const throttle = new SwarmThrottle(fastThrottleConfig({
      maxConcurrent: 1,
      refillRatePerSecond: 20, // 1 token every 50ms
    }));

    // Consume the one token
    await throttle.acquire();

    // Wait for refill
    await new Promise(resolve => setTimeout(resolve, 60));

    // Should be able to acquire again
    const result = await Promise.race([
      throttle.acquire().then(() => 'acquired'),
      new Promise<string>(resolve => setTimeout(() => resolve('timeout'), 100)),
    ]);

    expect(result).toBe('acquired');
  });

  it('should process waiters in FIFO order', async () => {
    const throttle = new SwarmThrottle(fastThrottleConfig({
      maxConcurrent: 1,
      refillRatePerSecond: 50, // fast enough to unblock sequentially
    }));

    // Consume the token
    await throttle.acquire();

    const order: number[] = [];

    // Queue up three waiters
    const p1 = throttle.acquire().then(() => order.push(1));
    const p2 = throttle.acquire().then(() => order.push(2));
    const p3 = throttle.acquire().then(() => order.push(3));

    // Wait for all to resolve
    await Promise.all([p1, p2, p3]);

    expect(order).toEqual([1, 2, 3]);
  });

  it('should report stats correctly', async () => {
    const throttle = new SwarmThrottle(fastThrottleConfig({ maxConcurrent: 3 }));

    const stats1 = throttle.getStats();
    expect(stats1.pendingCount).toBe(0);
    expect(stats1.totalAcquired).toBe(0);
    expect(stats1.availableTokens).toBe(3);
    expect(stats1.backoffLevel).toBe(0);
    expect(stats1.currentMaxConcurrent).toBe(3);
    expect(stats1.currentMinSpacingMs).toBe(0);

    await throttle.acquire();
    const stats2 = throttle.getStats();
    expect(stats2.totalAcquired).toBe(1);
  });

  it('should reduce capacity on backoff', () => {
    const throttle = new SwarmThrottle(fastThrottleConfig({
      maxConcurrent: 4,
      minSpacingMs: 100,
      refillRatePerSecond: 1.0,
    }));

    throttle.backoff();

    const stats = throttle.getStats();
    expect(stats.backoffLevel).toBe(1);
    expect(stats.currentMaxConcurrent).toBe(2);      // halved from 4
    expect(stats.currentMinSpacingMs).toBe(200);      // doubled from 100
  });

  it('should cap backoff at level 3', () => {
    const throttle = new SwarmThrottle(fastThrottleConfig({
      maxConcurrent: 8,
      minSpacingMs: 100,
    }));

    throttle.backoff(); // level 1: max=4, spacing=200
    throttle.backoff(); // level 2: max=2, spacing=400
    throttle.backoff(); // level 3: max=1, spacing=800
    throttle.backoff(); // should not go past 3

    expect(throttle.backoffLevel).toBe(3);
    const stats = throttle.getStats();
    expect(stats.currentMaxConcurrent).toBe(1);
  });

  it('should not recover before cooldown period', () => {
    const throttle = new SwarmThrottle(fastThrottleConfig({
      maxConcurrent: 4,
      minSpacingMs: 100,
    }));

    throttle.backoff();
    expect(throttle.backoffLevel).toBe(1);

    // Recover immediately — should not change (cooldown is 10s)
    throttle.recover();
    expect(throttle.backoffLevel).toBe(1);
  });
});

// ─── ThrottledProvider Tests ────────────────────────────────────────────────

describe('ThrottledProvider', () => {
  it('should delegate name, defaultModel, isConfigured', () => {
    const inner = makeMockProvider({
      name: 'my-provider',
      defaultModel: 'my-model',
    });
    const provider = createThrottledProvider(inner, fastThrottleConfig());

    expect(provider.name).toBe('my-provider');
    expect(provider.defaultModel).toBe('my-model');
    expect(provider.isConfigured()).toBe(true);
  });

  it('should call acquire before chat', async () => {
    const inner = makeMockProvider();
    const throttle = new SwarmThrottle(fastThrottleConfig());
    const acquireSpy = vi.spyOn(throttle, 'acquire');

    const provider = new ThrottledProvider(inner, throttle);
    await provider.chat([{ role: 'user', content: 'hi' }]);

    expect(acquireSpy).toHaveBeenCalledTimes(1);
    expect(inner.chat).toHaveBeenCalledTimes(1);
  });

  it('should call acquire before chatWithTools', async () => {
    const chatWithToolsMock = vi.fn().mockResolvedValue({ content: 'ok', stopReason: 'end_turn' });
    const inner = {
      ...makeMockProvider(),
      chatWithTools: chatWithToolsMock,
    };
    const throttle = new SwarmThrottle(fastThrottleConfig());
    const acquireSpy = vi.spyOn(throttle, 'acquire');

    const provider = new ThrottledProvider(inner as unknown as LLMProvider, throttle);
    await (provider as any).chatWithTools([{ role: 'user', content: 'hi' }], {});

    expect(acquireSpy).toHaveBeenCalledTimes(1);
    expect(chatWithToolsMock).toHaveBeenCalledTimes(1);
  });

  it('should throw if inner provider does not support chatWithTools', async () => {
    const inner = makeMockProvider();
    const provider = createThrottledProvider(inner, fastThrottleConfig());

    await expect(
      (provider as any).chatWithTools([{ role: 'user', content: 'hi' }])
    ).rejects.toThrow('Inner provider does not support chatWithTools');
  });

  it('should call backoff on 429 error', async () => {
    const inner = makeMockProvider({
      chat: vi.fn().mockRejectedValue(new Error('429 Too Many Requests')),
    });
    const throttle = new SwarmThrottle(fastThrottleConfig({ maxConcurrent: 4 }));
    const backoffSpy = vi.spyOn(throttle, 'backoff');

    const provider = new ThrottledProvider(inner, throttle);
    await expect(provider.chat([{ role: 'user', content: 'hi' }])).rejects.toThrow('429');

    expect(backoffSpy).toHaveBeenCalledTimes(1);
  });

  it('should call recover on successful chat', async () => {
    const inner = makeMockProvider();
    const throttle = new SwarmThrottle(fastThrottleConfig());
    const recoverSpy = vi.spyOn(throttle, 'recover');

    const provider = new ThrottledProvider(inner, throttle);
    await provider.chat([{ role: 'user', content: 'hi' }]);

    expect(recoverSpy).toHaveBeenCalledTimes(1);
  });

  it('should pass through chat arguments correctly', async () => {
    const inner = makeMockProvider();
    const provider = createThrottledProvider(inner, fastThrottleConfig());

    const messages = [{ role: 'user' as const, content: 'test message' }];
    const options = { maxTokens: 100, temperature: 0.5 };

    await provider.chat(messages, options);

    expect(inner.chat).toHaveBeenCalledWith(messages, options);
  });
});

// ─── Config Presets ─────────────────────────────────────────────────────────

describe('Config Presets', () => {
  it('FREE_TIER_THROTTLE should have conservative limits', () => {
    expect(FREE_TIER_THROTTLE.maxConcurrent).toBe(2);
    expect(FREE_TIER_THROTTLE.refillRatePerSecond).toBe(0.5);
    expect(FREE_TIER_THROTTLE.minSpacingMs).toBe(1500);
  });

  it('PAID_TIER_THROTTLE should have higher limits', () => {
    expect(PAID_TIER_THROTTLE.maxConcurrent).toBe(5);
    expect(PAID_TIER_THROTTLE.refillRatePerSecond).toBe(2.0);
    expect(PAID_TIER_THROTTLE.minSpacingMs).toBe(200);
  });
});

// ─── createThrottledProvider Factory ────────────────────────────────────────

describe('createThrottledProvider', () => {
  it('should use FREE_TIER_THROTTLE as default', () => {
    const inner = makeMockProvider();
    const provider = createThrottledProvider(inner);
    // Verify it works (default config applied)
    expect(provider).toBeInstanceOf(ThrottledProvider);
  });

  it('should accept custom config', () => {
    const inner = makeMockProvider();
    const provider = createThrottledProvider(inner, PAID_TIER_THROTTLE);
    expect(provider).toBeInstanceOf(ThrottledProvider);
  });
});
