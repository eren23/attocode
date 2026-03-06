/**
 * Cancellation Token Tests
 *
 * Tests for the cancellation token system that provides graceful interruption.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  CancellationManager,
  createCancellationManager,
  createCancellationTokenSource,
  sleep,
  isCancellationError,
  CancellationError,
} from '../src/integrations/budget/cancellation.js';

describe('CancellationToken', () => {
  describe('createCancellationTokenSource', () => {
    it('should create a token source with uncancelled token', () => {
      const cts = createCancellationTokenSource();

      expect(cts.token.isCancellationRequested).toBe(false);
      expect(cts.token.cancellationReason).toBeUndefined();
    });

    it('should cancel token when cancel is called', () => {
      const cts = createCancellationTokenSource();

      cts.cancel('test reason');

      expect(cts.token.isCancellationRequested).toBe(true);
      expect(cts.token.cancellationReason).toBe('test reason');
    });

    it('should notify listeners when cancelled', () => {
      const cts = createCancellationTokenSource();
      const listener = vi.fn();

      cts.token.register(listener);
      cts.cancel('cancelled');

      expect(listener).toHaveBeenCalledWith('cancelled');
    });

    it('should call listener immediately if already cancelled', () => {
      const cts = createCancellationTokenSource();
      cts.cancel('already cancelled');

      const listener = vi.fn();
      cts.token.register(listener);

      expect(listener).toHaveBeenCalledWith('already cancelled');
    });

    it('should throw when throwIfCancellationRequested is called on cancelled token', () => {
      const cts = createCancellationTokenSource();
      cts.cancel('test');

      expect(() => cts.token.throwIfCancellationRequested()).toThrow(CancellationError);
    });

    it('should not throw when throwIfCancellationRequested is called on uncancelled token', () => {
      const cts = createCancellationTokenSource();

      expect(() => cts.token.throwIfCancellationRequested()).not.toThrow();
    });

    it('should dispose and prevent further callbacks', () => {
      const cts = createCancellationTokenSource();
      const listener = vi.fn();

      const { dispose } = cts.token.register(listener);
      dispose();
      cts.cancel('after dispose');

      // Listener was disposed before cancellation
      expect(listener).not.toHaveBeenCalled();
    });

    it('should cancel source itself', () => {
      const cts = createCancellationTokenSource();

      cts.cancel('test');

      expect(cts.isCancellationRequested).toBe(true);
    });

    it('should support cancelAfter', async () => {
      const cts = createCancellationTokenSource();
      cts.cancelAfter(50);

      expect(cts.token.isCancellationRequested).toBe(false);

      await new Promise((r) => setTimeout(r, 100));

      expect(cts.token.isCancellationRequested).toBe(true);
    });
  });

  describe('sleep', () => {
    it('should resolve after duration', async () => {
      const start = Date.now();
      await sleep(50);
      const elapsed = Date.now() - start;

      expect(elapsed).toBeGreaterThanOrEqual(45);
    });

    it('should reject if cancelled during sleep', async () => {
      const cts = createCancellationTokenSource();

      const promise = sleep(100, cts.token);
      setTimeout(() => cts.cancel('wake up'), 20);

      await expect(promise).rejects.toThrow(CancellationError);
    });
  });

  describe('isCancellationError', () => {
    it('should return true for CancellationError', () => {
      const error = new CancellationError('test');
      expect(isCancellationError(error)).toBe(true);
    });

    it('should return false for other errors', () => {
      const error = new Error('test');
      expect(isCancellationError(error)).toBe(false);
    });

    it('should return false for non-errors', () => {
      expect(isCancellationError(null)).toBe(false);
      expect(isCancellationError(undefined)).toBe(false);
      expect(isCancellationError('error')).toBe(false);
    });
  });
});

describe('CancellationManager', () => {
  let manager: CancellationManager;

  beforeEach(() => {
    manager = createCancellationManager();
  });

  afterEach(() => {
    manager.cleanup();
  });

  it('should create contexts', () => {
    const ctx1 = manager.createContext();
    const ctx2 = manager.createContext();

    expect(ctx1).toBeDefined();
    expect(ctx2).toBeDefined();
  });

  it('should expose token and isCancelled on manager', () => {
    manager.createContext();

    expect(manager.token).toBeDefined();
    expect(manager.isCancelled).toBe(false);

    manager.cancel('test');
    expect(manager.isCancelled).toBe(true);
  });

  it('should dispose context', () => {
    const ctx = manager.createContext();
    expect(ctx).toBeDefined();

    // Should not throw
    manager.disposeContext();
  });

  it('should subscribe to events', () => {
    const events: unknown[] = [];
    const unsubscribe = manager.subscribe((e) => events.push(e));

    expect(typeof unsubscribe).toBe('function');

    manager.createContext();
    manager.cancel('test');

    // Should have captured some events
    expect(events.length).toBeGreaterThanOrEqual(1);
  });

  it('should cleanup without errors', () => {
    manager.createContext();
    manager.createContext();

    expect(() => manager.cleanup()).not.toThrow();
  });
});
