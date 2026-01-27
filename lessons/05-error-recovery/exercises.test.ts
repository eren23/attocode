/**
 * Exercise Tests: Lesson 5 - Retry with Backoff
 *
 * Run with: npm run test:lesson:5:exercise
 */

import { describe, it, expect, vi } from 'vitest';

// Import from answers for testing
import {
  retryWithBackoff,
  isRetryableError,
  calculateBackoff,
  type RetryOptions,
  type RetryableError,
} from './exercises/answers/exercise-1.js';

// =============================================================================
// HELPER: Create errors with properties
// =============================================================================

function createError(props: Partial<RetryableError>): RetryableError {
  const error = new Error(props.message || 'Test error') as RetryableError;
  Object.assign(error, props);
  return error;
}

// =============================================================================
// TESTS: isRetryableError
// =============================================================================

describe('isRetryableError', () => {
  describe('explicit retryable flag', () => {
    it('should return true when retryable=true', () => {
      const error = createError({ retryable: true });
      expect(isRetryableError(error)).toBe(true);
    });

    it('should return false when retryable=false', () => {
      const error = createError({ retryable: false });
      expect(isRetryableError(error)).toBe(false);
    });
  });

  describe('network error codes', () => {
    it.each(['ECONNRESET', 'ETIMEDOUT', 'ECONNREFUSED', 'EPIPE'])(
      'should retry on %s',
      (code) => {
        const error = createError({ code });
        expect(isRetryableError(error)).toBe(true);
      }
    );
  });

  describe('HTTP status codes', () => {
    it.each([429, 500, 502, 503, 504])(
      'should retry on status %d',
      (status) => {
        const error = createError({ status });
        expect(isRetryableError(error)).toBe(true);
      }
    );

    it.each([400, 401, 403, 404, 422])(
      'should not retry on status %d',
      (status) => {
        const error = createError({ status });
        expect(isRetryableError(error)).toBe(false);
      }
    );
  });

  describe('message patterns', () => {
    it('should retry on timeout message', () => {
      const error = createError({ message: 'Request timeout' });
      expect(isRetryableError(error)).toBe(true);
    });

    it('should retry on network message', () => {
      const error = createError({ message: 'Network error occurred' });
      expect(isRetryableError(error)).toBe(true);
    });
  });

  describe('non-Error values', () => {
    it('should return false for non-Error', () => {
      expect(isRetryableError('string error')).toBe(false);
      expect(isRetryableError({ message: 'object' })).toBe(false);
      expect(isRetryableError(null)).toBe(false);
    });
  });
});

// =============================================================================
// TESTS: calculateBackoff
// =============================================================================

describe('calculateBackoff', () => {
  const options: RetryOptions = {
    maxRetries: 3,
    initialDelayMs: 100,
    maxDelayMs: 5000,
  };

  it('should calculate exponential backoff', () => {
    expect(calculateBackoff(0, options)).toBe(100);  // 100 * 2^0
    expect(calculateBackoff(1, options)).toBe(200);  // 100 * 2^1
    expect(calculateBackoff(2, options)).toBe(400);  // 100 * 2^2
    expect(calculateBackoff(3, options)).toBe(800);  // 100 * 2^3
  });

  it('should cap at maxDelayMs', () => {
    expect(calculateBackoff(10, options)).toBe(5000); // Would be 102400, capped at 5000
  });

  it('should use retryAfter when provided', () => {
    const error = createError({ retryAfter: 2000 });
    expect(calculateBackoff(0, options, error)).toBe(2000);
  });

  it('should cap retryAfter at maxDelayMs', () => {
    const error = createError({ retryAfter: 10000 });
    expect(calculateBackoff(0, options, error)).toBe(5000);
  });
});

// =============================================================================
// TESTS: retryWithBackoff
// =============================================================================

describe('retryWithBackoff', () => {
  const options: RetryOptions = {
    maxRetries: 3,
    initialDelayMs: 10, // Short delays for tests
    maxDelayMs: 100,
  };

  it('should return result on immediate success', async () => {
    const fn = vi.fn().mockResolvedValue('success');

    const result = await retryWithBackoff(fn, options);

    expect(result).toBe('success');
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('should retry on retryable errors', async () => {
    const fn = vi.fn()
      .mockRejectedValueOnce(createError({ status: 500 }))
      .mockRejectedValueOnce(createError({ status: 503 }))
      .mockResolvedValue('success');

    const result = await retryWithBackoff(fn, options);

    expect(result).toBe('success');
    expect(fn).toHaveBeenCalledTimes(3);
  });

  it('should throw immediately on non-retryable error', async () => {
    const error = createError({ status: 404, message: 'Not found' });
    const fn = vi.fn().mockRejectedValue(error);

    await expect(retryWithBackoff(fn, options)).rejects.toThrow('Not found');
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('should throw after max retries exhausted', async () => {
    const error = createError({ status: 500, message: 'Server error' });
    const fn = vi.fn().mockRejectedValue(error);

    await expect(retryWithBackoff(fn, options)).rejects.toThrow('Server error');
    expect(fn).toHaveBeenCalledTimes(4); // Initial + 3 retries
  });

  it('should call onRetry callback', async () => {
    const onRetry = vi.fn();
    const optionsWithCallback = { ...options, onRetry };

    const fn = vi.fn()
      .mockRejectedValueOnce(createError({ status: 500 }))
      .mockResolvedValue('success');

    await retryWithBackoff(fn, optionsWithCallback);

    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(onRetry).toHaveBeenCalledWith(1, expect.any(Error), expect.any(Number));
  });

  it('should apply increasing delays', async () => {
    const delays: number[] = [];
    const onRetry = (_attempt: number, _error: Error, delayMs: number) => {
      delays.push(delayMs);
    };

    const fn = vi.fn()
      .mockRejectedValueOnce(createError({ status: 500 }))
      .mockRejectedValueOnce(createError({ status: 500 }))
      .mockResolvedValue('success');

    await retryWithBackoff(fn, { ...options, onRetry });

    expect(delays[0]).toBeLessThan(delays[1]); // Exponential increase
  });
});
