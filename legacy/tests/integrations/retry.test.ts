/**
 * Tests for the retry utility.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  withRetry,
  withRetryResult,
  DEFAULT_RETRYABLE_ERRORS,
  DEFAULT_RETRYABLE_CODES,
} from '../../src/integrations/utilities/retry.js';

describe('Retry Utility', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('withRetry', () => {
    it('should return result on first success', async () => {
      const fn = vi.fn().mockResolvedValue('success');

      const promise = withRetry(fn, { maxAttempts: 3 });
      await vi.runAllTimersAsync();
      const result = await promise;

      expect(result).toBe('success');
      expect(fn).toHaveBeenCalledTimes(1);
    });

    it('should retry on retryable error', async () => {
      const fn = vi.fn()
        .mockRejectedValueOnce(new Error('ETIMEDOUT'))
        .mockResolvedValue('success after retry');

      const promise = withRetry(fn, {
        maxAttempts: 3,
        baseDelayMs: 100,
      });
      await vi.runAllTimersAsync();
      const result = await promise;

      expect(result).toBe('success after retry');
      expect(fn).toHaveBeenCalledTimes(2);
    });

    it('should not retry on non-retryable error', async () => {
      const fn = vi.fn().mockRejectedValue(new Error('Authentication failed'));

      const promise = withRetry(fn, {
        maxAttempts: 3,
        retryableErrors: ['timeout'],
      });

      await expect(promise).rejects.toThrow('Authentication failed');
      expect(fn).toHaveBeenCalledTimes(1);
    });

    it('should respect maxAttempts limit', async () => {
      const fn = vi.fn().mockRejectedValue(new Error('ETIMEDOUT'));

      const promise = withRetry(fn, {
        maxAttempts: 3,
        baseDelayMs: 100,
      });
      const assertion = expect(promise).rejects.toThrow('ETIMEDOUT');
      await vi.runAllTimersAsync();

      await assertion;
      expect(fn).toHaveBeenCalledTimes(3);
    });

    it('should apply exponential backoff', async () => {
      const fn = vi.fn()
        .mockRejectedValueOnce(new Error('timeout'))
        .mockRejectedValueOnce(new Error('timeout'))
        .mockResolvedValue('success');

      const delays: number[] = [];
      const promise = withRetry(fn, {
        maxAttempts: 5,
        baseDelayMs: 1000,
        backoffMultiplier: 2,
        jitter: false, // Disable jitter for predictable testing
        onRetry: (_attempt, _error, delay) => {
          delays.push(delay);
        },
      });
      await vi.runAllTimersAsync();
      await promise;

      // First delay: 1000 * 2^0 = 1000
      // Second delay: 1000 * 2^1 = 2000
      expect(delays[0]).toBe(1000);
      expect(delays[1]).toBe(2000);
    });

    it('should call onRetry callback', async () => {
      const fn = vi.fn()
        .mockRejectedValueOnce(new Error('timeout'))
        .mockResolvedValue('success');

      const onRetry = vi.fn();
      const promise = withRetry(fn, {
        maxAttempts: 3,
        baseDelayMs: 100,
        jitter: false,
        onRetry,
      });
      await vi.runAllTimersAsync();
      await promise;

      expect(onRetry).toHaveBeenCalledTimes(1);
      expect(onRetry).toHaveBeenCalledWith(1, expect.any(Error), 100);
    });

    it('should call onExhausted when all attempts fail', async () => {
      const fn = vi.fn().mockRejectedValue(new Error('timeout'));
      const onExhausted = vi.fn();

      const promise = withRetry(fn, {
        maxAttempts: 2,
        baseDelayMs: 100,
        onExhausted,
      });
      const assertion = expect(promise).rejects.toThrow();
      await vi.runAllTimersAsync();

      await assertion;
      expect(onExhausted).toHaveBeenCalledWith(2, expect.any(Error));
    });

    it('should retry on error codes', async () => {
      const error = new Error('Connection reset');
      (error as NodeJS.ErrnoException).code = 'ECONNRESET';

      const fn = vi.fn()
        .mockRejectedValueOnce(error)
        .mockResolvedValue('recovered');

      const promise = withRetry(fn, {
        maxAttempts: 3,
        baseDelayMs: 100,
        retryableCodes: ['ECONNRESET'],
      });
      await vi.runAllTimersAsync();
      const result = await promise;

      expect(result).toBe('recovered');
      expect(fn).toHaveBeenCalledTimes(2);
    });

    it('should use custom isRetryable function', async () => {
      const fn = vi.fn()
        .mockRejectedValueOnce(new Error('Custom transient error'))
        .mockResolvedValue('success');

      const promise = withRetry(fn, {
        maxAttempts: 3,
        baseDelayMs: 100,
        isRetryable: (error) => error.message.includes('transient'),
      });
      await vi.runAllTimersAsync();
      const result = await promise;

      expect(result).toBe('success');
      expect(fn).toHaveBeenCalledTimes(2);
    });

    it('should respect maxDelayMs cap', async () => {
      const fn = vi.fn().mockRejectedValue(new Error('timeout'));

      const delays: number[] = [];
      const promise = withRetry(fn, {
        maxAttempts: 5,
        baseDelayMs: 1000,
        maxDelayMs: 2500, // Cap at 2500ms
        backoffMultiplier: 2,
        jitter: false,
        onRetry: (_attempt, _error, delay) => {
          delays.push(delay);
        },
      });
      const assertion = expect(promise).rejects.toThrow();
      await vi.runAllTimersAsync();
      await assertion;

      // Delays should be: 1000, 2000, 2500, 2500 (capped)
      expect(delays[0]).toBe(1000);
      expect(delays[1]).toBe(2000);
      expect(delays[2]).toBe(2500);
      expect(delays[3]).toBe(2500);
    });
  });

  describe('withRetryResult', () => {
    it('should return success result', async () => {
      const fn = vi.fn().mockResolvedValue('data');

      const promise = withRetryResult(fn, { maxAttempts: 3 });
      await vi.runAllTimersAsync();
      const result = await promise;

      expect(result.success).toBe(true);
      expect(result.value).toBe('data');
      expect(result.attempts).toBe(1);
      expect(result.totalTimeMs).toBeGreaterThanOrEqual(0);
    });

    it('should return failure result without throwing', async () => {
      const fn = vi.fn().mockRejectedValue(new Error('permanent error'));

      const promise = withRetryResult(fn, {
        maxAttempts: 2,
        baseDelayMs: 100,
        retryableErrors: [], // No retryable errors
      });
      await vi.runAllTimersAsync();
      const result = await promise;

      expect(result.success).toBe(false);
      expect(result.error?.message).toBe('permanent error');
      expect(result.attempts).toBe(1);
    });

    it('should track attempts through retries', async () => {
      const fn = vi.fn()
        .mockRejectedValueOnce(new Error('timeout'))
        .mockRejectedValueOnce(new Error('timeout'))
        .mockResolvedValue('success');

      const promise = withRetryResult(fn, {
        maxAttempts: 5,
        baseDelayMs: 100,
      });
      await vi.runAllTimersAsync();
      const result = await promise;

      expect(result.success).toBe(true);
      expect(result.attempts).toBe(3);
    });
  });

  describe('Default retryable patterns', () => {
    it('should include common timeout errors', () => {
      expect(DEFAULT_RETRYABLE_ERRORS).toContain('ETIMEDOUT');
      expect(DEFAULT_RETRYABLE_ERRORS).toContain('timeout');
    });

    it('should include network errors', () => {
      expect(DEFAULT_RETRYABLE_ERRORS).toContain('ECONNRESET');
      expect(DEFAULT_RETRYABLE_ERRORS).toContain('socket hang up');
      expect(DEFAULT_RETRYABLE_ERRORS).toContain('network error');
    });

    it('should include service unavailable', () => {
      expect(DEFAULT_RETRYABLE_ERRORS).toContain('service unavailable');
      expect(DEFAULT_RETRYABLE_ERRORS).toContain('rate limit');
    });

    it('should have retryable codes', () => {
      expect(DEFAULT_RETRYABLE_CODES).toContain('ETIMEDOUT');
      expect(DEFAULT_RETRYABLE_CODES).toContain('ECONNRESET');
      expect(DEFAULT_RETRYABLE_CODES).toContain('EBUSY');
    });
  });
});
