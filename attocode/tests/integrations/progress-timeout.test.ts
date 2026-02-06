/**
 * Unit tests for progress-aware timeout, race(), and createLinkedToken.
 *
 * These test the cancellation primitives used by the subagent timeout system.
 * Uses fake timers for deterministic, fast execution.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  createProgressAwareTimeout,
  createCancellationTokenSource,
  createLinkedToken,
  race,
  CancellationError,
} from '../../src/integrations/cancellation.js';

describe('createProgressAwareTimeout', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('should fire idle timeout when no progress is reported', async () => {
    const timeout = createProgressAwareTimeout(300_000, 10_000, 1_000);

    // Advance past idle timeout
    await vi.advanceTimersByTimeAsync(11_000);

    expect(timeout.isCancellationRequested).toBe(true);
    expect(timeout.token.cancellationReason).toMatch(/Idle timeout/);

    timeout.dispose();
  });

  it('should NOT fire idle timeout with regular progress', async () => {
    const timeout = createProgressAwareTimeout(300_000, 10_000, 1_000);

    // Report progress every 5s for 30s
    for (let i = 0; i < 6; i++) {
      await vi.advanceTimersByTimeAsync(5_000);
      timeout.reportProgress();
    }

    expect(timeout.isCancellationRequested).toBe(false);

    timeout.dispose();
  });

  it('should fire idle timeout after progress stops', async () => {
    const timeout = createProgressAwareTimeout(300_000, 10_000, 1_000);

    // Report progress at 5s
    await vi.advanceTimersByTimeAsync(5_000);
    timeout.reportProgress();

    // Go idle for 11s
    await vi.advanceTimersByTimeAsync(11_000);

    expect(timeout.isCancellationRequested).toBe(true);
    expect(timeout.token.cancellationReason).toMatch(/Idle timeout/);

    timeout.dispose();
  });

  it('should fire hard timeout regardless of progress', async () => {
    const timeout = createProgressAwareTimeout(20_000, 10_000, 1_000);

    // Keep reporting progress every 5s
    for (let i = 0; i < 4; i++) {
      await vi.advanceTimersByTimeAsync(5_000);
      timeout.reportProgress();
    }
    // At 20s, hard timeout fires
    await vi.advanceTimersByTimeAsync(1);

    expect(timeout.isCancellationRequested).toBe(true);
    expect(timeout.token.cancellationReason).toMatch(/Maximum timeout exceeded/);

    timeout.dispose();
  });

  it('should fire hard timeout with continuous progress', async () => {
    const timeout = createProgressAwareTimeout(5_000, 3_000, 1_000);

    // Report every 1s — prevents idle, but hard timeout fires at 5s
    for (let i = 0; i < 4; i++) {
      await vi.advanceTimersByTimeAsync(1_000);
      timeout.reportProgress();
    }
    await vi.advanceTimersByTimeAsync(1_000);

    expect(timeout.isCancellationRequested).toBe(true);
    expect(timeout.token.cancellationReason).toMatch(/Maximum timeout exceeded/);

    timeout.dispose();
  });

  it('should reset idle timer on reportProgress()', async () => {
    const timeout = createProgressAwareTimeout(300_000, 10_000, 1_000);

    // Advance 9s (just under idle), report progress
    await vi.advanceTimersByTimeAsync(9_000);
    expect(timeout.isCancellationRequested).toBe(false);
    timeout.reportProgress();

    // Advance another 9s (just under idle again)
    await vi.advanceTimersByTimeAsync(9_000);
    expect(timeout.isCancellationRequested).toBe(false);

    // Advance 2 more seconds → now 11s since last progress
    await vi.advanceTimersByTimeAsync(2_000);
    expect(timeout.isCancellationRequested).toBe(true);
    expect(timeout.token.cancellationReason).toMatch(/Idle timeout/);

    timeout.dispose();
  });

  it('should return idle time via getIdleTime()', async () => {
    const timeout = createProgressAwareTimeout(300_000, 60_000, 1_000);

    await vi.advanceTimersByTimeAsync(5_000);
    expect(timeout.getIdleTime()).toBe(5_000);

    timeout.reportProgress();
    expect(timeout.getIdleTime()).toBe(0);

    await vi.advanceTimersByTimeAsync(3_000);
    expect(timeout.getIdleTime()).toBe(3_000);

    timeout.dispose();
  });

  it('should return elapsed time via getElapsedTime()', async () => {
    const timeout = createProgressAwareTimeout(300_000, 60_000, 1_000);

    await vi.advanceTimersByTimeAsync(5_000);
    expect(timeout.getElapsedTime()).toBe(5_000);

    timeout.reportProgress(); // Doesn't reset elapsed
    expect(timeout.getElapsedTime()).toBe(5_000);

    await vi.advanceTimersByTimeAsync(10_000);
    expect(timeout.getElapsedTime()).toBe(15_000);

    timeout.dispose();
  });

  it('should NOT cancel after dispose()', async () => {
    const timeout = createProgressAwareTimeout(10_000, 5_000, 1_000);

    timeout.dispose();

    // Advance past all timeouts
    await vi.advanceTimersByTimeAsync(20_000);

    // cancel() is a no-op when disposed (CancellationTokenSourceImpl.cancel checks _disposed)
    expect(timeout.isCancellationRequested).toBe(false);
  });

  it('should include seconds in idle timeout reason', async () => {
    const timeout = createProgressAwareTimeout(300_000, 10_000, 1_000);

    await vi.advanceTimersByTimeAsync(11_000);

    expect(timeout.token.cancellationReason).toMatch(/\d+s/);
    expect(timeout.token.cancellationReason).toMatch(/Idle timeout/);

    timeout.dispose();
  });

  it('should include seconds in hard timeout reason', async () => {
    const timeout = createProgressAwareTimeout(10_000, 60_000, 1_000);

    await vi.advanceTimersByTimeAsync(10_000);

    expect(timeout.token.cancellationReason).toMatch(/\d+s/);
    expect(timeout.token.cancellationReason).toMatch(/Maximum timeout exceeded/);

    timeout.dispose();
  });
});

describe('race() with ProgressAwareTimeout', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('should resolve normally if promise resolves before timeout', async () => {
    const timeout = createProgressAwareTimeout(300_000, 60_000, 1_000);

    const promise = race(
      new Promise<string>(resolve => setTimeout(() => resolve('done'), 1_000)),
      timeout.token,
    );

    await vi.advanceTimersByTimeAsync(1_000);

    const result = await promise;
    expect(result).toBe('done');

    timeout.dispose();
  });

  it('should reject with CancellationError on idle timeout', async () => {
    const timeout = createProgressAwareTimeout(300_000, 10_000, 1_000);

    const neverResolves = new Promise<string>(() => {});
    const promise = race(neverResolves, timeout.token).catch((e: unknown) => e);

    await vi.advanceTimersByTimeAsync(11_000);

    const err = await promise;
    expect(err).toBeInstanceOf(CancellationError);
    expect((err as CancellationError).reason).toMatch(/Idle timeout/);

    timeout.dispose();
  });

  it('should reject with CancellationError on hard timeout', async () => {
    const timeout = createProgressAwareTimeout(10_000, 60_000, 1_000);

    const neverResolves = new Promise<string>(() => {});
    const promise = race(neverResolves, timeout.token).catch((e: unknown) => e);

    await vi.advanceTimersByTimeAsync(10_000);

    const err = await promise;
    expect(err).toBeInstanceOf(CancellationError);
    expect((err as CancellationError).reason).toMatch(/Maximum timeout exceeded/);

    timeout.dispose();
  });

  it('should reject immediately with already-cancelled token', async () => {
    const timeout = createProgressAwareTimeout(300_000, 10_000, 1_000);

    // Cancel first
    timeout.cancel('pre-cancelled');

    const err = await race(new Promise<string>(() => {}), timeout.token).catch((e: unknown) => e);

    expect(err).toBeInstanceOf(CancellationError);
    expect((err as CancellationError).reason).toMatch(/pre-cancelled/);

    timeout.dispose();
  });
});

describe('createLinkedToken with ProgressAwareTimeout', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('should propagate parent cancel to linked token', async () => {
    const parent = createCancellationTokenSource();
    const timeout = createProgressAwareTimeout(300_000, 60_000, 1_000);
    const linked = createLinkedToken(parent, timeout);

    parent.cancel('User pressed ESC');

    expect(linked.isCancellationRequested).toBe(true);
    expect(linked.token.cancellationReason).toBe('User pressed ESC');
    // Parent is NOT affected by child timeout
    expect(parent.isCancellationRequested).toBe(true); // Only because we cancelled it

    timeout.dispose();
    linked.dispose();
  });

  it('should propagate idle timeout through linked token', async () => {
    const parent = createCancellationTokenSource();
    const timeout = createProgressAwareTimeout(300_000, 10_000, 1_000);
    const linked = createLinkedToken(parent, timeout);

    await vi.advanceTimersByTimeAsync(11_000);

    expect(linked.isCancellationRequested).toBe(true);
    expect(linked.token.cancellationReason).toMatch(/Idle timeout/);
    // Parent should NOT be cancelled by child timeout
    expect(parent.isCancellationRequested).toBe(false);

    timeout.dispose();
    linked.dispose();
  });

  it('should propagate hard timeout through linked token', async () => {
    const parent = createCancellationTokenSource();
    const timeout = createProgressAwareTimeout(10_000, 60_000, 1_000);
    const linked = createLinkedToken(parent, timeout);

    await vi.advanceTimersByTimeAsync(10_000);

    expect(linked.isCancellationRequested).toBe(true);
    expect(linked.token.cancellationReason).toMatch(/Maximum timeout exceeded/);
    expect(parent.isCancellationRequested).toBe(false);

    timeout.dispose();
    linked.dispose();
  });

  it('should immediately cancel linked if parent already cancelled', () => {
    const parent = createCancellationTokenSource();
    parent.cancel('already gone');

    const timeout = createProgressAwareTimeout(300_000, 60_000, 1_000);
    const linked = createLinkedToken(parent, timeout);

    expect(linked.isCancellationRequested).toBe(true);
    expect(linked.token.cancellationReason).toBe('already gone');

    timeout.dispose();
    linked.dispose();
  });

  it('should propagate parent cancel through race()', async () => {
    const parent = createCancellationTokenSource();
    const timeout = createProgressAwareTimeout(300_000, 60_000, 1_000);
    const linked = createLinkedToken(parent, timeout);

    const neverResolves = new Promise<string>(() => {});
    const promise = race(neverResolves, linked.token).catch((e: unknown) => e);

    // Parent cancels while racing
    parent.cancel('User pressed ESC');

    const err = await promise;
    expect(err).toBeInstanceOf(CancellationError);
    expect((err as CancellationError).reason).toMatch(/User pressed ESC/);

    timeout.dispose();
    linked.dispose();
  });
});
