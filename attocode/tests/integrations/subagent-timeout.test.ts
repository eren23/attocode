/**
 * Integration tests for subagent timeout behavior.
 *
 * Replicates the exact wiring from agent.ts:4009-4053 without instantiating
 * ProductionAgent. Tests the full event flow: progress-aware timeout +
 * linked cancellation + race().
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  createProgressAwareTimeout,
  createGracefulTimeout,
  createCancellationTokenSource,
  createLinkedToken,
  race,
  CancellationError,
  type ProgressAwareTimeoutSource,
  type GracefulTimeoutSource,
  type CancellationTokenSource,
} from '../../src/integrations/budget/cancellation.js';
import { parseStructuredClosureReport } from '../../src/agent.js';

// ---------------------------------------------------------------------------
// Test harness — mirrors agent.ts:4009-4053
// ---------------------------------------------------------------------------

interface SubagentTimeoutHarness {
  progressAwareTimeout: ProgressAwareTimeoutSource;
  parentSource: CancellationTokenSource;
  effectiveSource: CancellationTokenSource;
  /** Feed an event into the progress filter (same filter as agent.ts:4030) */
  handleEvent: (event: { type: string }) => void;
  dispose: () => void;
}

function createSubagentTimeoutHarness(
  maxTimeout: number,
  idleTimeout: number,
  checkInterval = 1_000,
): SubagentTimeoutHarness {
  const progressAwareTimeout = createProgressAwareTimeout(maxTimeout, idleTimeout, checkInterval);
  const parentSource = createCancellationTokenSource();
  const effectiveSource = createLinkedToken(parentSource, progressAwareTimeout);

  // Mirror exact filter from agent.ts:4030
  const progressEvents = ['tool.start', 'tool.complete', 'llm.start', 'llm.complete'];

  function handleEvent(event: { type: string }) {
    if (progressEvents.includes(event.type)) {
      progressAwareTimeout.reportProgress();
    }
  }

  return {
    progressAwareTimeout,
    parentSource,
    effectiveSource,
    handleEvent,
    dispose() {
      progressAwareTimeout.dispose();
      effectiveSource.dispose();
    },
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Subagent Timeout Integration', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // =========================================================================
  // Normal operation
  // =========================================================================

  describe('normal operation', () => {
    it('should NOT timeout with regular event flow', async () => {
      const h = createSubagentTimeoutHarness(300_000, 10_000);

      // Simulate typical subagent cycle: llm.start → llm.complete → tool.start → tool.complete
      for (let cycle = 0; cycle < 5; cycle++) {
        h.handleEvent({ type: 'llm.start' });
        await vi.advanceTimersByTimeAsync(2_000);
        h.handleEvent({ type: 'llm.complete' });
        await vi.advanceTimersByTimeAsync(500);
        h.handleEvent({ type: 'tool.start' });
        await vi.advanceTimersByTimeAsync(3_000);
        h.handleEvent({ type: 'tool.complete' });
        await vi.advanceTimersByTimeAsync(500);
      }

      expect(h.effectiveSource.isCancellationRequested).toBe(false);

      h.dispose();
    });

    it('should resolve race when task completes during event flow', async () => {
      const h = createSubagentTimeoutHarness(300_000, 10_000);

      // Simulate a task that resolves after some events
      const taskPromise = new Promise<string>(resolve => {
        setTimeout(() => resolve('task-result'), 5_000);
      });

      const racePromise = race(taskPromise, h.effectiveSource.token);

      // Fire some events
      h.handleEvent({ type: 'llm.start' });
      await vi.advanceTimersByTimeAsync(2_000);
      h.handleEvent({ type: 'llm.complete' });
      await vi.advanceTimersByTimeAsync(3_000);

      const result = await racePromise;
      expect(result).toBe('task-result');

      h.dispose();
    });
  });

  // =========================================================================
  // THE original bug scenario
  // =========================================================================

  describe('original bug scenario', () => {
    it('should timeout when gap between events exceeds idle timeout', async () => {
      const h = createSubagentTimeoutHarness(300_000, 10_000);

      // tool.complete fires, then long gap with no events
      h.handleEvent({ type: 'tool.complete' });
      await vi.advanceTimersByTimeAsync(11_000);

      expect(h.effectiveSource.isCancellationRequested).toBe(true);
      expect(h.effectiveSource.token.cancellationReason).toMatch(/Idle timeout/);

      h.dispose();
    });

    it('should NOT timeout when event arrives just under idle threshold', async () => {
      const h = createSubagentTimeoutHarness(300_000, 10_000);

      // tool.complete, then gap just under idle timeout, then llm.start arrives
      h.handleEvent({ type: 'tool.complete' });
      await vi.advanceTimersByTimeAsync(9_000);
      expect(h.effectiveSource.isCancellationRequested).toBe(false);

      // llm.start arrives — resets idle timer
      h.handleEvent({ type: 'llm.start' });
      await vi.advanceTimersByTimeAsync(9_000);
      expect(h.effectiveSource.isCancellationRequested).toBe(false);

      h.dispose();
    });
  });

  // =========================================================================
  // Regression: old event names must NOT reset idle timer
  // =========================================================================

  describe('event name regression', () => {
    it('should NOT reset idle timer for old/invalid event names', async () => {
      const h = createSubagentTimeoutHarness(300_000, 10_000);

      // These are the OLD event names that caused the bug, plus other non-progress events.
      // They must NOT reset the idle timer.
      const nonProgressEvents = [
        'llm.response',
        'llm.tokens',
        'llm.chunk',
        'error',
        'start',
        'complete',
        'agent.thinking',
        'status',
      ];

      for (const eventName of nonProgressEvents) {
        await vi.advanceTimersByTimeAsync(5_000);
        h.handleEvent({ type: eventName });
      }

      // Total elapsed: 5000 * 8 = 40s. Since none of these reset idle,
      // the idle timer should have fired at 10s.
      expect(h.effectiveSource.isCancellationRequested).toBe(true);
      expect(h.effectiveSource.token.cancellationReason).toMatch(/Idle timeout/);

      h.dispose();
    });

    it('should ONLY reset idle timer for the 4 correct event names', async () => {
      const h = createSubagentTimeoutHarness(300_000, 10_000);
      const correctEvents = ['tool.start', 'tool.complete', 'llm.start', 'llm.complete'];

      // Send each correct event just before idle would fire
      for (const eventName of correctEvents) {
        await vi.advanceTimersByTimeAsync(9_000);
        h.handleEvent({ type: eventName });
      }

      // 36s elapsed, still alive because each event reset the timer
      expect(h.effectiveSource.isCancellationRequested).toBe(false);

      h.dispose();
    });
  });

  // =========================================================================
  // Stuck LLM
  // =========================================================================

  describe('stuck LLM', () => {
    it('should timeout when llm.start fires but llm.complete never arrives', async () => {
      const h = createSubagentTimeoutHarness(300_000, 10_000);

      h.handleEvent({ type: 'llm.start' });
      // LLM hangs — no llm.complete ever comes
      await vi.advanceTimersByTimeAsync(11_000);

      expect(h.effectiveSource.isCancellationRequested).toBe(true);
      expect(h.effectiveSource.token.cancellationReason).toMatch(/Idle timeout/);

      h.dispose();
    });
  });

  // =========================================================================
  // Long MCP tool (known limitation)
  // =========================================================================

  describe('long MCP tool', () => {
    it('should timeout when tool.start fires but tool runs longer than idle timeout', async () => {
      const h = createSubagentTimeoutHarness(300_000, 10_000);

      // tool.start fires, then tool runs for a long time with no intermediate events
      h.handleEvent({ type: 'tool.start' });
      await vi.advanceTimersByTimeAsync(11_000);

      // Known limitation: long-running tools without intermediate progress events will timeout
      expect(h.effectiveSource.isCancellationRequested).toBe(true);
      expect(h.effectiveSource.token.cancellationReason).toMatch(/Idle timeout/);

      h.dispose();
    });
  });

  // =========================================================================
  // Error reason propagation
  // =========================================================================

  describe('error reason propagation', () => {
    it('should propagate idle timeout reason through race()', async () => {
      const h = createSubagentTimeoutHarness(300_000, 10_000);

      const promise = race(new Promise<string>(() => {}), h.effectiveSource.token).catch((e: unknown) => e);
      await vi.advanceTimersByTimeAsync(11_000);

      const err = await promise;
      expect(err).toBeInstanceOf(CancellationError);
      const ce = err as CancellationError;
      expect(ce.reason).toMatch(/Idle timeout/);
      expect(ce.reason).toMatch(/\d+s/);

      h.dispose();
    });

    it('should propagate hard timeout reason through race()', async () => {
      const h = createSubagentTimeoutHarness(10_000, 60_000);

      // Keep progress alive so only hard timeout fires
      const promise = race(new Promise<string>(() => {}), h.effectiveSource.token).catch((e: unknown) => e);

      h.handleEvent({ type: 'llm.start' });
      await vi.advanceTimersByTimeAsync(5_000);
      h.handleEvent({ type: 'llm.complete' });
      await vi.advanceTimersByTimeAsync(5_000);

      const err = await promise;
      expect(err).toBeInstanceOf(CancellationError);
      const ce = err as CancellationError;
      expect(ce.reason).toMatch(/Maximum timeout exceeded/);
      expect(ce.reason).toMatch(/\d+s/);

      h.dispose();
    });
  });

  // =========================================================================
  // Parent cancellation (ESC key)
  // =========================================================================

  describe('parent cancellation', () => {
    it('should cancel race when parent is cancelled (ESC key)', async () => {
      const h = createSubagentTimeoutHarness(300_000, 60_000);

      const promise = race(new Promise<string>(() => {}), h.effectiveSource.token).catch((e: unknown) => e);

      // Simulate ESC key — parent cancels
      h.parentSource.cancel('User requested cancellation');

      const err = await promise;
      expect(err).toBeInstanceOf(CancellationError);
      expect((err as CancellationError).reason).toMatch(/User requested cancellation/);

      h.dispose();
    });

    it('should immediately cancel when parent already cancelled before harness', async () => {
      // Parent cancelled before subagent starts (edge case)
      const progressAwareTimeout = createProgressAwareTimeout(300_000, 60_000, 1_000);
      const parentSource = createCancellationTokenSource();
      parentSource.cancel('pre-cancelled');
      const effectiveSource = createLinkedToken(parentSource, progressAwareTimeout);

      expect(effectiveSource.isCancellationRequested).toBe(true);
      expect(effectiveSource.token.cancellationReason).toBe('pre-cancelled');

      progressAwareTimeout.dispose();
      effectiveSource.dispose();
    });
  });

  // =========================================================================
  // High throughput
  // =========================================================================

  describe('high throughput', () => {
    it('should handle 10 rapid tool calls without timeout', async () => {
      const h = createSubagentTimeoutHarness(300_000, 10_000);

      // 10 rapid tool calls, 100ms each
      for (let i = 0; i < 10; i++) {
        h.handleEvent({ type: 'tool.start' });
        await vi.advanceTimersByTimeAsync(50);
        h.handleEvent({ type: 'tool.complete' });
        await vi.advanceTimersByTimeAsync(50);
      }

      expect(h.effectiveSource.isCancellationRequested).toBe(false);
      // Total elapsed: ~1s — well within both timeouts
      expect(h.progressAwareTimeout.getElapsedTime()).toBeLessThan(2_000);

      h.dispose();
    });
  });
});

// ===========================================================================
// GRACEFUL TIMEOUT TESTS
// ===========================================================================

describe('Graceful Timeout (createGracefulTimeout)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('should fire wrapup callback before hard cancel on max timeout', async () => {
    const wrapupFired = vi.fn();
    // 60s max, 30s idle, 10s wrapup window
    const timeout = createGracefulTimeout(60_000, 30_000, 10_000);
    timeout.onWrapupWarning(wrapupFired);

    // Keep progress alive so only max timeout fires
    // Wrapup fires at 60s - 10s = 50s
    for (let i = 0; i < 9; i++) {
      await vi.advanceTimersByTimeAsync(5_000);
      timeout.reportProgress();
    }
    // At 45s, progress reported. Now wait for wrapup at 50s
    await vi.advanceTimersByTimeAsync(5_000);

    expect(wrapupFired).toHaveBeenCalledTimes(1);
    expect(timeout.isInWrapupPhase()).toBe(true);
    // NOT cancelled yet — still in wrapup window
    expect(timeout.isCancellationRequested).toBe(false);

    // Hard kill at 60s (10s after wrapup)
    await vi.advanceTimersByTimeAsync(10_000);
    expect(timeout.isCancellationRequested).toBe(true);

    timeout.dispose();
  });

  it('should fire wrapup callback before hard cancel on idle timeout', async () => {
    const wrapupFired = vi.fn();
    // 300s max, 10s idle, 5s wrapup window
    const timeout = createGracefulTimeout(300_000, 10_000, 5_000, 1_000);
    timeout.onWrapupWarning(wrapupFired);

    // No progress — idle timeout fires at 10s, which triggers wrapup
    await vi.advanceTimersByTimeAsync(10_000);

    expect(wrapupFired).toHaveBeenCalledTimes(1);
    expect(timeout.isInWrapupPhase()).toBe(true);
    expect(timeout.isCancellationRequested).toBe(false);

    // Hard kill 5s later
    await vi.advanceTimersByTimeAsync(5_000);
    expect(timeout.isCancellationRequested).toBe(true);

    timeout.dispose();
  });

  it('should NOT extend deadline during wrapup phase', async () => {
    const wrapupFired = vi.fn();
    // 60s max, 10s idle, 5s wrapup window
    const timeout = createGracefulTimeout(60_000, 10_000, 5_000, 1_000);
    timeout.onWrapupWarning(wrapupFired);

    // Trigger idle timeout → wrapup
    await vi.advanceTimersByTimeAsync(10_000);
    expect(timeout.isInWrapupPhase()).toBe(true);

    // Report progress during wrapup — should NOT extend
    timeout.reportProgress();
    await vi.advanceTimersByTimeAsync(5_000);

    // Should still be cancelled despite progress report
    expect(timeout.isCancellationRequested).toBe(true);

    timeout.dispose();
  });

  it('should work with race() and createLinkedToken', async () => {
    const wrapupFired = vi.fn();
    const timeout = createGracefulTimeout(60_000, 10_000, 5_000, 1_000);
    timeout.onWrapupWarning(wrapupFired);

    const parentSource = createCancellationTokenSource();
    const effectiveSource = createLinkedToken(parentSource, timeout);

    const promise = race(new Promise<string>(() => {}), effectiveSource.token)
      .catch((e: unknown) => e);

    // Idle timeout → wrapup
    await vi.advanceTimersByTimeAsync(10_000);
    expect(wrapupFired).toHaveBeenCalled();
    expect(effectiveSource.isCancellationRequested).toBe(false);

    // Hard kill
    await vi.advanceTimersByTimeAsync(5_000);
    const err = await promise;
    expect(err).toBeInstanceOf(CancellationError);

    timeout.dispose();
    effectiveSource.dispose();
  });

  it('should fire wrapup callback immediately if registered during wrapup phase', async () => {
    const timeout = createGracefulTimeout(60_000, 10_000, 5_000, 1_000);

    // Trigger idle timeout → wrapup
    await vi.advanceTimersByTimeAsync(10_000);
    expect(timeout.isInWrapupPhase()).toBe(true);

    // Register callback AFTER wrapup started — should fire immediately
    const lateFn = vi.fn();
    timeout.onWrapupWarning(lateFn);
    expect(lateFn).toHaveBeenCalledTimes(1);

    timeout.dispose();
  });

  it('should not fire wrapup if task completes before timeout', async () => {
    const wrapupFired = vi.fn();
    const timeout = createGracefulTimeout(60_000, 30_000, 10_000, 1_000);
    timeout.onWrapupWarning(wrapupFired);

    // Simulate task completing quickly
    timeout.reportProgress();
    await vi.advanceTimersByTimeAsync(5_000);
    timeout.dispose();

    expect(wrapupFired).not.toHaveBeenCalled();
    expect(timeout.isInWrapupPhase()).toBe(false);
  });
});

// ===========================================================================
// STRUCTURED CLOSURE REPORT PARSING TESTS
// ===========================================================================

describe('parseStructuredClosureReport', () => {
  it('should parse valid JSON from wrapup response', () => {
    const text = `Here is my summary:
{
  "findings": ["Found bug in tool-registry.ts:245"],
  "actionsTaken": ["Read 8 files", "Ran grep across src/"],
  "failures": ["Couldn't analyze dependency chain"],
  "remainingWork": ["Trace the call from registry.ts:245"],
  "suggestedNextSteps": ["Spawn debugger on tool-registry.ts:245"]
}`;
    const result = parseStructuredClosureReport(text, 'timeout_graceful');
    expect(result).toBeDefined();
    expect(result!.findings).toEqual(['Found bug in tool-registry.ts:245']);
    expect(result!.actionsTaken).toEqual(['Read 8 files', 'Ran grep across src/']);
    expect(result!.failures).toEqual(["Couldn't analyze dependency chain"]);
    expect(result!.remainingWork).toEqual(['Trace the call from registry.ts:245']);
    expect(result!.exitReason).toBe('timeout_graceful');
    expect(result!.suggestedNextSteps).toEqual(['Spawn debugger on tool-registry.ts:245']);
  });

  it('should handle JSON without suggestedNextSteps', () => {
    const text = '{"findings": ["found it"], "actionsTaken": [], "failures": [], "remainingWork": []}';
    const result = parseStructuredClosureReport(text, 'completed');
    expect(result).toBeDefined();
    expect(result!.findings).toEqual(['found it']);
    expect(result!.suggestedNextSteps).toBeUndefined();
    expect(result!.exitReason).toBe('completed');
  });

  it('should return fallback for invalid JSON with timeout exit reason', () => {
    const text = 'I was working on analyzing the code but ran out of time...';
    const result = parseStructuredClosureReport(text, 'timeout_graceful', 'Find the bug');
    expect(result).toBeDefined();
    expect(result!.findings[0]).toContain('I was working on');
    expect(result!.failures).toContain('Did not produce structured JSON summary');
    expect(result!.remainingWork).toEqual(['Find the bug']);
    expect(result!.exitReason).toBe('timeout_hard');
  });

  it('should return undefined for completed agents without JSON', () => {
    const text = 'I found the answer: the issue is in line 42.';
    const result = parseStructuredClosureReport(text, 'completed');
    expect(result).toBeUndefined();
  });

  it('should return timeout_hard fallback for empty text with fallback task', () => {
    const result = parseStructuredClosureReport('', 'timeout_graceful', 'Analyze codebase');
    expect(result).toBeDefined();
    expect(result!.findings).toEqual([]);
    expect(result!.failures).toEqual(['Timeout before producing structured summary']);
    expect(result!.remainingWork).toEqual(['Analyze codebase']);
    expect(result!.exitReason).toBe('timeout_hard');
  });

  it('should return undefined for empty text without fallback task', () => {
    const result = parseStructuredClosureReport('', 'completed');
    expect(result).toBeUndefined();
  });

  it('should handle JSON embedded in markdown', () => {
    const text = `## Summary
\`\`\`json
{"findings": ["A", "B"], "actionsTaken": ["C"], "failures": [], "remainingWork": ["D"]}
\`\`\`
`;
    const result = parseStructuredClosureReport(text, 'timeout_graceful');
    expect(result).toBeDefined();
    expect(result!.findings).toEqual(['A', 'B']);
    expect(result!.actionsTaken).toEqual(['C']);
    expect(result!.remainingWork).toEqual(['D']);
  });

  it('should handle non-array fields gracefully', () => {
    const text = '{"findings": "single finding", "actionsTaken": null, "failures": 42, "remainingWork": []}';
    const result = parseStructuredClosureReport(text, 'timeout_graceful');
    expect(result).toBeDefined();
    expect(result!.findings).toEqual([]);
    expect(result!.actionsTaken).toEqual([]);
    expect(result!.failures).toEqual([]);
    expect(result!.remainingWork).toEqual([]);
  });

  it('should ignore JSON that does not look like a closure report', () => {
    const text = 'The config is: {"port": 3000, "host": "localhost"}';
    const result = parseStructuredClosureReport(text, 'timeout_graceful', 'Find config');
    // This JSON has none of the expected fields, so it falls through to fallback
    expect(result).toBeDefined();
    expect(result!.exitReason).toBe('timeout_hard');
    expect(result!.findings[0]).toContain('The config is');
  });
});
