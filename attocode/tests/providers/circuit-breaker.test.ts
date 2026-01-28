/**
 * Circuit Breaker Tests
 *
 * Tests for the circuit breaker pattern implementation.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  CircuitBreaker,
  createCircuitBreaker,
  createStrictCircuitBreaker,
  createLenientCircuitBreaker,
  formatCircuitBreakerMetrics,
  isCircuitBreakerError,
  type CircuitBreakerConfig,
  type CircuitBreakerEvent,
} from '../../src/providers/circuit-breaker.js';
import type { LLMProvider, Message, ChatResponse } from '../../src/providers/types.js';
import { ProviderError } from '../../src/providers/types.js';

// =============================================================================
// TEST HELPERS
// =============================================================================

function createMockProvider(name: string, options: { failCount?: number } = {}): LLMProvider {
  const { failCount = 0 } = options;
  let failures = 0;

  return {
    name,
    defaultModel: `${name}-model`,
    isConfigured: () => true,

    chat: vi.fn(async (_messages: Message[]): Promise<ChatResponse> => {
      if (failures < failCount) {
        failures++;
        throw new Error(`${name} failed`);
      }

      return {
        content: `Response from ${name}`,
        stopReason: 'end_turn',
        usage: { inputTokens: 10, outputTokens: 20 },
      };
    }),
  };
}

// =============================================================================
// TESTS
// =============================================================================

describe('CircuitBreaker', () => {
  let config: CircuitBreakerConfig;

  beforeEach(() => {
    config = {
      failureThreshold: 3,
      resetTimeout: 100, // Short for testing
      halfOpenRequests: 1,
    };
  });

  describe('initialization', () => {
    it('should start in CLOSED state', () => {
      const breaker = createCircuitBreaker(config);

      expect(breaker.getState()).toBe('CLOSED');
    });

    it('should allow requests in CLOSED state', () => {
      const breaker = createCircuitBreaker(config);

      expect(breaker.canRequest()).toBe(true);
    });

    it('should initialize with zero metrics', () => {
      const breaker = createCircuitBreaker(config);
      const metrics = breaker.getMetrics();

      expect(metrics.failures).toBe(0);
      expect(metrics.successes).toBe(0);
      expect(metrics.totalRequests).toBe(0);
      expect(metrics.rejectedRequests).toBe(0);
    });
  });

  describe('state transitions', () => {
    it('should stay CLOSED after successes', () => {
      const breaker = createCircuitBreaker(config);

      breaker.recordSuccess();
      breaker.recordSuccess();
      breaker.recordSuccess();

      expect(breaker.getState()).toBe('CLOSED');
    });

    it('should transition to OPEN after failure threshold', () => {
      const breaker = createCircuitBreaker({ ...config, failureThreshold: 3 });

      breaker.recordFailure();
      expect(breaker.getState()).toBe('CLOSED');

      breaker.recordFailure();
      expect(breaker.getState()).toBe('CLOSED');

      breaker.recordFailure();
      expect(breaker.getState()).toBe('OPEN');
    });

    it('should reject requests in OPEN state', () => {
      const breaker = createCircuitBreaker({ ...config, failureThreshold: 2 });

      breaker.recordFailure();
      breaker.recordFailure();

      expect(breaker.getState()).toBe('OPEN');
      expect(breaker.canRequest()).toBe(false);
    });

    it('should transition to HALF_OPEN after reset timeout', async () => {
      const breaker = createCircuitBreaker({
        ...config,
        failureThreshold: 2,
        resetTimeout: 50,
      });

      breaker.recordFailure();
      breaker.recordFailure();

      expect(breaker.getState()).toBe('OPEN');

      await new Promise((resolve) => setTimeout(resolve, 60));

      expect(breaker.getState()).toBe('HALF_OPEN');
    });

    it('should allow limited requests in HALF_OPEN state', async () => {
      const breaker = createCircuitBreaker({
        ...config,
        failureThreshold: 2,
        resetTimeout: 50,
        halfOpenRequests: 1,
      });

      // Trip the breaker
      breaker.recordFailure();
      breaker.recordFailure();

      // Wait for reset
      await new Promise((resolve) => setTimeout(resolve, 60));

      expect(breaker.getState()).toBe('HALF_OPEN');
      expect(breaker.canRequest()).toBe(true);
    });

    it('should transition to CLOSED on success in HALF_OPEN', async () => {
      const breaker = createCircuitBreaker({
        ...config,
        failureThreshold: 2,
        resetTimeout: 50,
        halfOpenRequests: 1,
      });

      // Trip and reset
      breaker.recordFailure();
      breaker.recordFailure();
      await new Promise((resolve) => setTimeout(resolve, 60));

      expect(breaker.getState()).toBe('HALF_OPEN');

      // Use execute() which properly tracks halfOpenInProgress
      await breaker.execute(() => Promise.resolve('success'));

      expect(breaker.getState()).toBe('CLOSED');
    });

    it('should transition back to OPEN on failure in HALF_OPEN', async () => {
      const breaker = createCircuitBreaker({
        ...config,
        failureThreshold: 2,
        resetTimeout: 50,
        halfOpenRequests: 1,
      });

      // Trip and reset
      breaker.recordFailure();
      breaker.recordFailure();
      await new Promise((resolve) => setTimeout(resolve, 60));

      expect(breaker.getState()).toBe('HALF_OPEN');

      breaker.recordFailure();

      expect(breaker.getState()).toBe('OPEN');
    });
  });

  describe('execute', () => {
    it('should execute function when CLOSED', async () => {
      const breaker = createCircuitBreaker(config);
      const fn = vi.fn().mockResolvedValue('result');

      const result = await breaker.execute(fn);

      expect(result).toBe('result');
      expect(fn).toHaveBeenCalledTimes(1);
    });

    it('should throw when OPEN', async () => {
      const breaker = createCircuitBreaker({ ...config, failureThreshold: 2 });

      breaker.recordFailure();
      breaker.recordFailure();

      const fn = vi.fn().mockResolvedValue('result');

      await expect(breaker.execute(fn)).rejects.toThrow('Circuit breaker is OPEN');
      expect(fn).not.toHaveBeenCalled();
    });

    it('should record success on successful execution', async () => {
      const breaker = createCircuitBreaker(config);
      const fn = vi.fn().mockResolvedValue('result');

      await breaker.execute(fn);

      const metrics = breaker.getMetrics();
      expect(metrics.successes).toBe(1);
      expect(metrics.failures).toBe(0);
    });

    it('should record failure on failed execution', async () => {
      const breaker = createCircuitBreaker(config);
      const fn = vi.fn().mockRejectedValue(new Error('Failed'));

      await expect(breaker.execute(fn)).rejects.toThrow('Failed');

      const metrics = breaker.getMetrics();
      expect(metrics.failures).toBe(1);
    });

    it('should track rejected requests', async () => {
      const breaker = createCircuitBreaker({ ...config, failureThreshold: 2 });

      breaker.recordFailure();
      breaker.recordFailure();

      try {
        await breaker.execute(() => Promise.resolve('result'));
      } catch {
        // Expected
      }

      const metrics = breaker.getMetrics();
      expect(metrics.rejectedRequests).toBe(1);
    });
  });

  describe('wrap', () => {
    it('should wrap provider with circuit breaker', async () => {
      const breaker = createCircuitBreaker(config);
      const provider = createMockProvider('test');

      const wrapped = breaker.wrap(provider);
      const messages: Message[] = [{ role: 'user', content: 'Hello' }];

      const response = await wrapped.chat(messages);

      expect(response.content).toBe('Response from test');
      expect(breaker.getMetrics().successes).toBe(1);
    });

    it('should trip breaker on wrapped provider failures', async () => {
      const breaker = createCircuitBreaker({ ...config, failureThreshold: 2 });
      const provider = createMockProvider('test', { failCount: 10 });

      const wrapped = breaker.wrap(provider);
      const messages: Message[] = [{ role: 'user', content: 'Hello' }];

      await expect(wrapped.chat(messages)).rejects.toThrow();
      await expect(wrapped.chat(messages)).rejects.toThrow();

      expect(breaker.getState()).toBe('OPEN');

      // Next request should be rejected immediately
      await expect(wrapped.chat(messages)).rejects.toThrow('Circuit breaker is OPEN');
    });

    it('should preserve provider properties', () => {
      const breaker = createCircuitBreaker(config);
      const provider = createMockProvider('test');

      const wrapped = breaker.wrap(provider);

      expect(wrapped.name).toBe('test');
      expect(wrapped.defaultModel).toBe('test-model');
      expect(wrapped.isConfigured()).toBe(true);
    });
  });

  describe('manual control', () => {
    it('should reset circuit manually', () => {
      const breaker = createCircuitBreaker({ ...config, failureThreshold: 2 });

      breaker.recordFailure();
      breaker.recordFailure();

      expect(breaker.getState()).toBe('OPEN');

      breaker.reset();

      expect(breaker.getState()).toBe('CLOSED');
      expect(breaker.getMetrics().failures).toBe(0);
    });

    it('should trip circuit manually', () => {
      const breaker = createCircuitBreaker(config);

      expect(breaker.getState()).toBe('CLOSED');

      breaker.trip('Manual trip for maintenance');

      expect(breaker.getState()).toBe('OPEN');
    });
  });

  describe('events', () => {
    it('should emit state change events', () => {
      const events: CircuitBreakerEvent[] = [];
      const breaker = createCircuitBreaker({ ...config, failureThreshold: 2 });

      breaker.on((event) => events.push(event));

      breaker.recordFailure();
      breaker.recordFailure();

      const stateChange = events.find((e) => e.type === 'state.change');
      expect(stateChange).toBeDefined();

      if (stateChange?.type === 'state.change') {
        expect(stateChange.from).toBe('CLOSED');
        expect(stateChange.to).toBe('OPEN');
      }
    });

    it('should emit success events', async () => {
      const events: CircuitBreakerEvent[] = [];
      const breaker = createCircuitBreaker(config);

      breaker.on((event) => events.push(event));

      await breaker.execute(() => Promise.resolve('result'));

      expect(events.some((e) => e.type === 'request.success')).toBe(true);
    });

    it('should emit failure events', async () => {
      const events: CircuitBreakerEvent[] = [];
      const breaker = createCircuitBreaker(config);

      breaker.on((event) => events.push(event));

      try {
        await breaker.execute(() => Promise.reject(new Error('Failed')));
      } catch {
        // Expected
      }

      expect(events.some((e) => e.type === 'request.failure')).toBe(true);
    });

    it('should emit rejected events', async () => {
      const events: CircuitBreakerEvent[] = [];
      const breaker = createCircuitBreaker({ ...config, failureThreshold: 2 });

      breaker.on((event) => events.push(event));

      breaker.recordFailure();
      breaker.recordFailure();

      try {
        await breaker.execute(() => Promise.resolve('result'));
      } catch {
        // Expected
      }

      expect(events.some((e) => e.type === 'request.rejected')).toBe(true);
    });

    it('should allow unsubscribing', () => {
      const events: CircuitBreakerEvent[] = [];
      const breaker = createCircuitBreaker(config);

      const unsubscribe = breaker.on((event) => events.push(event));

      breaker.recordSuccess();
      expect(events.length).toBeGreaterThan(0);

      events.length = 0;
      unsubscribe();

      breaker.recordSuccess();
      expect(events.length).toBe(0);
    });
  });

  describe('tripOnErrors filtering', () => {
    it('should only trip on specified error types', () => {
      const breaker = createCircuitBreaker({
        ...config,
        failureThreshold: 2,
        tripOnErrors: ['RATE_LIMITED'],
      });

      // Non-matching error
      breaker.recordFailure(new Error('Some random error'));
      breaker.recordFailure(new Error('Another error'));

      // Should still be CLOSED because errors don't match filter
      expect(breaker.getState()).toBe('CLOSED');

      // Matching error
      breaker.recordFailure(new Error('rate limit exceeded'));
      breaker.recordFailure(new Error('429 too many requests'));

      expect(breaker.getState()).toBe('OPEN');
    });
  });
});

describe('factory functions', () => {
  it('createStrictCircuitBreaker should have low thresholds', () => {
    const breaker = createStrictCircuitBreaker();

    // Trip with just 3 failures
    breaker.recordFailure();
    breaker.recordFailure();
    breaker.recordFailure();

    expect(breaker.getState()).toBe('OPEN');
  });

  it('createLenientCircuitBreaker should have high thresholds', () => {
    const breaker = createLenientCircuitBreaker();

    // Should not trip with 5 failures
    for (let i = 0; i < 5; i++) {
      breaker.recordFailure();
    }

    expect(breaker.getState()).toBe('CLOSED');
  });
});

describe('formatCircuitBreakerMetrics', () => {
  it('should format metrics for display', () => {
    const metrics = {
      state: 'OPEN' as const,
      failures: 5,
      successes: 10,
      totalRequests: 20,
      rejectedRequests: 5,
      lastStateChange: Date.now(),
      resetAt: Date.now() + 30000,
      lastError: 'Connection timeout',
    };

    const formatted = formatCircuitBreakerMetrics(metrics);

    expect(formatted).toContain('OPEN');
    expect(formatted).toContain('Failures: 5');
    expect(formatted).toContain('Successes: 10');
    expect(formatted).toContain('Reset in');
    expect(formatted).toContain('Connection timeout');
  });
});

describe('isCircuitBreakerError', () => {
  it('should identify circuit breaker errors', () => {
    const error = new ProviderError(
      'Circuit breaker is OPEN',
      'circuit-breaker',
      'SERVER_ERROR'
    );

    expect(isCircuitBreakerError(error)).toBe(true);
  });

  it('should not identify other errors', () => {
    const error = new Error('Some error');
    expect(isCircuitBreakerError(error)).toBe(false);

    const providerError = new ProviderError('Auth failed', 'anthropic', 'AUTHENTICATION_FAILED');
    expect(isCircuitBreakerError(providerError)).toBe(false);
  });
});
