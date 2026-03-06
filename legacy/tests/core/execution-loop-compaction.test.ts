/**
 * Tests for handleAutoCompaction() and applyContextOverflowGuard()
 * extracted from execution-loop.ts.
 *
 * Covers:
 *  handleAutoCompaction:
 *    - no compaction needed
 *    - pre-compaction prompt injection
 *    - full compaction with recovery injection
 *    - hard limit
 *    - simple compaction fallback
 *
 *  applyContextOverflowGuard:
 *    - no truncation when under budget
 *    - truncation when over budget
 *    - no-op when <= 10 results
 *    - no-op when no economics
 */

import { describe, it, expect, vi } from 'vitest';
import {
  handleAutoCompaction,
  applyContextOverflowGuard,
  type AutoCompactionDeps,
  type OverflowGuardDeps,
  type ToolResult,
} from '../../src/core/execution-loop.js';

import type { Message } from '../../src/types.js';

// ===========================================================================
// handleAutoCompaction
// ===========================================================================

function makeCompactionDeps(overrides: Partial<AutoCompactionDeps> = {}): AutoCompactionDeps {
  return {
    autoCompactionManager: null,
    economics: null,
    compactionPending: false,
    emit: vi.fn(),
    ...overrides,
  };
}

describe('handleAutoCompaction', () => {
  it('returns ok when no compaction manager and no economics', async () => {
    const deps = makeCompactionDeps();
    const messages: Message[] = [{ role: 'user', content: 'hi' }];
    const stateMessages = [...messages];

    const result = await handleAutoCompaction(deps, messages, stateMessages, vi.fn());
    expect(result).toEqual({ status: 'ok' });
  });

  describe('with autoCompactionManager', () => {
    it('returns ok when compaction check returns ok status', async () => {
      const deps = makeCompactionDeps({
        autoCompactionManager: {
          checkAndMaybeCompact: vi.fn().mockResolvedValue({ status: 'ok', ratio: 0.3 }),
        },
      });
      const messages: Message[] = [{ role: 'user', content: 'hi' }];

      const result = await handleAutoCompaction(deps, messages, [...messages], vi.fn());
      expect(result).toEqual({ status: 'ok' });
    });

    it('injects pre-compaction prompt when compaction pending is false', async () => {
      const deps = makeCompactionDeps({
        compactionPending: false,
        autoCompactionManager: {
          checkAndMaybeCompact: vi.fn().mockResolvedValue({
            status: 'compacted',
            compactedMessages: [{ role: 'user', content: 'compacted' }],
            ratio: 0.85,
          }),
        },
      });
      const messages: Message[] = [{ role: 'user', content: 'hi' }];
      const stateMessages = [...messages];
      const setPending = vi.fn();

      const result = await handleAutoCompaction(deps, messages, stateMessages, setPending);

      expect(result).toEqual({ status: 'compaction_prompt_injected' });
      expect(setPending).toHaveBeenCalledWith(true);
      // Should have pushed the pre-compaction prompt
      expect(messages[messages.length - 1].content).toContain('compaction is imminent');
      expect(stateMessages[stateMessages.length - 1].content).toContain('compaction is imminent');
    });

    it('performs full compaction when compactionPending is true', async () => {
      const compactedMessages: Message[] = [
        { role: 'system', content: 'System prompt' },
        { role: 'user', content: 'Summarized context' },
      ];
      const deps = makeCompactionDeps({
        compactionPending: true,
        autoCompactionManager: {
          checkAndMaybeCompact: vi.fn().mockResolvedValue({
            status: 'compacted',
            compactedMessages,
            ratio: 0.85,
          }),
        },
        economics: {
          getUsage: () => ({ tokens: 5000 }),
          getBudget: () => ({ maxTokens: 100000 }),
          updateBaseline: vi.fn(),
        },
      });

      const messages: Message[] = [
        { role: 'user', content: 'old message 1' },
        { role: 'assistant', content: 'old response' },
      ];
      const stateMessages = [...messages];
      const setPending = vi.fn();

      const result = await handleAutoCompaction(deps, messages, stateMessages, setPending);

      expect(result.status).toBe('compacted');
      expect(setPending).toHaveBeenCalledWith(false);
      // Messages should be replaced with compacted versions
      expect(messages[0]).toEqual(compactedMessages[0]);
      expect(messages[1]).toEqual(compactedMessages[1]);
      // Baseline should be updated
      expect(deps.economics!.updateBaseline).toHaveBeenCalled();
    });

    it('injects work log after compaction', async () => {
      const compactedMessages: Message[] = [{ role: 'user', content: 'Summary' }];
      const deps = makeCompactionDeps({
        compactionPending: true,
        autoCompactionManager: {
          checkAndMaybeCompact: vi.fn().mockResolvedValue({
            status: 'compacted',
            compactedMessages,
            ratio: 0.85,
          }),
        },
        workLog: {
          hasContent: () => true,
          toCompactString: () => '[Work Log] Steps completed',
        },
      });

      const messages: Message[] = [{ role: 'user', content: 'old' }];
      const stateMessages = [...messages];

      await handleAutoCompaction(deps, messages, stateMessages, vi.fn());

      const hasWorkLog = messages.some(m => typeof m.content === 'string' && m.content.includes('[Work Log]'));
      expect(hasWorkLog).toBe(true);
    });

    it('injects recovery context (goals, junctures, learnings) after compaction', async () => {
      const compactedMessages: Message[] = [{ role: 'user', content: 'Summary' }];
      const deps = makeCompactionDeps({
        compactionPending: true,
        autoCompactionManager: {
          checkAndMaybeCompact: vi.fn().mockResolvedValue({
            status: 'compacted',
            compactedMessages,
            ratio: 0.85,
          }),
        },
        store: {
          getGoalsSummary: () => 'Active goal: Build feature X',
          getJuncturesSummary: () => 'Decision: Chose approach A',
        },
        learningStore: {
          getLearningContext: () => 'Learned: Pattern Y works well',
        },
      });

      const messages: Message[] = [{ role: 'user', content: 'old' }];
      const stateMessages = [...messages];

      await handleAutoCompaction(deps, messages, stateMessages, vi.fn());

      const recoveryMsg = messages.find(
        m => typeof m.content === 'string' && m.content.includes('CONTEXT RECOVERY'),
      );
      expect(recoveryMsg).toBeDefined();
      expect(recoveryMsg!.content).toContain('Build feature X');
      expect(recoveryMsg!.content).toContain('Chose approach A');
      expect(recoveryMsg!.content).toContain('Pattern Y works well');
    });

    it('skips recovery for trivial goals summary', async () => {
      const compactedMessages: Message[] = [{ role: 'user', content: 'Summary' }];
      const deps = makeCompactionDeps({
        compactionPending: true,
        autoCompactionManager: {
          checkAndMaybeCompact: vi.fn().mockResolvedValue({
            status: 'compacted',
            compactedMessages,
            ratio: 0.85,
          }),
        },
        store: {
          getGoalsSummary: () => 'No active goals.',
          getJuncturesSummary: () => null,
        },
      });

      const messages: Message[] = [{ role: 'user', content: 'old' }];
      const stateMessages = [...messages];

      await handleAutoCompaction(deps, messages, stateMessages, vi.fn());

      const recoveryMsg = messages.find(
        m => typeof m.content === 'string' && m.content.includes('CONTEXT RECOVERY'),
      );
      expect(recoveryMsg).toBeUndefined();
    });

    it('emits compaction event and trace after compaction', async () => {
      const compactedMessages: Message[] = [{ role: 'user', content: 'Summary' }];
      const emit = vi.fn();
      const traceCollector = { record: vi.fn() };
      const deps = makeCompactionDeps({
        compactionPending: true,
        autoCompactionManager: {
          checkAndMaybeCompact: vi.fn().mockResolvedValue({
            status: 'compacted',
            compactedMessages,
            ratio: 0.85,
          }),
        },
        emit,
        traceCollector,
      });

      const messages: Message[] = [{ role: 'user', content: 'old' }];
      await handleAutoCompaction(deps, messages, [...messages], vi.fn());

      expect(emit).toHaveBeenCalledWith(expect.objectContaining({ type: 'context.compacted' }));
      expect(traceCollector.record).toHaveBeenCalledWith(expect.objectContaining({
        type: 'context.compacted',
      }));
    });

    it('returns hard_limit when compaction check returns hard_limit', async () => {
      const deps = makeCompactionDeps({
        autoCompactionManager: {
          checkAndMaybeCompact: vi.fn().mockResolvedValue({
            status: 'hard_limit',
            ratio: 0.98,
          }),
        },
      });
      const messages: Message[] = [{ role: 'user', content: 'hi' }];

      const result = await handleAutoCompaction(deps, messages, [...messages], vi.fn());

      expect(result.status).toBe('hard_limit');
      if (result.status === 'hard_limit') {
        expect(result.result.terminationReason).toBe('hard_context_limit');
        expect(result.result.failureReason).toContain('98%');
      }
    });
  });

  describe('simple compaction fallback (no autoCompactionManager)', () => {
    it('triggers simple compaction at >=70% usage', async () => {
      const deps = makeCompactionDeps({
        economics: {
          getUsage: () => ({ tokens: 75000 }),
          getBudget: () => ({ maxTokens: 100000 }),
          updateBaseline: vi.fn(),
        },
      });

      const messages: Message[] = [
        { role: 'user', content: 'hi' },
        {
          role: 'assistant',
          content: '',
          toolCalls: [{ id: 'tc1', name: 'read_file', arguments: { path: '/a' } }],
        },
        { role: 'tool', toolCallId: 'tc1', content: 'A'.repeat(500) },
      ];
      const stateMessages = [...messages];

      const result = await handleAutoCompaction(deps, messages, stateMessages, vi.fn());
      expect(result).toEqual({ status: 'simple_compaction_triggered' });
    });

    it('does not trigger at <70% usage', async () => {
      const deps = makeCompactionDeps({
        economics: {
          getUsage: () => ({ tokens: 50000 }),
          getBudget: () => ({ maxTokens: 100000 }),
          updateBaseline: vi.fn(),
        },
      });

      const messages: Message[] = [{ role: 'user', content: 'hi' }];
      const result = await handleAutoCompaction(deps, messages, [...messages], vi.fn());
      expect(result).toEqual({ status: 'ok' });
    });
  });
});

// ===========================================================================
// applyContextOverflowGuard
// ===========================================================================

function makeOverflowDeps(overrides: Partial<OverflowGuardDeps> = {}): OverflowGuardDeps {
  return {
    economics: { getBudget: () => ({ maxTokens: 100000 }) },
    emit: vi.fn(),
    ...overrides,
  };
}

describe('applyContextOverflowGuard', () => {
  it('returns 0 when no economics', () => {
    const deps = makeOverflowDeps({ economics: null });
    const results: ToolResult[] = Array.from({ length: 15 }, (_, i) => ({
      callId: `tc${i}`,
      result: 'short result',
    }));

    const skipped = applyContextOverflowGuard(deps, [], results);
    expect(skipped).toBe(0);
  });

  it('returns 0 when 10 or fewer results', () => {
    const deps = makeOverflowDeps();
    const results: ToolResult[] = Array.from({ length: 10 }, (_, i) => ({
      callId: `tc${i}`,
      result: 'some result text',
    }));

    const skipped = applyContextOverflowGuard(deps, [], results);
    expect(skipped).toBe(0);
  });

  it('returns 0 when results fit within budget', () => {
    const deps = makeOverflowDeps({
      economics: { getBudget: () => ({ maxTokens: 1000000 }) }, // Very large budget
    });
    const results: ToolResult[] = Array.from({ length: 15 }, (_, i) => ({
      callId: `tc${i}`,
      result: 'small',
    }));

    const skipped = applyContextOverflowGuard(deps, [], results);
    expect(skipped).toBe(0);
  });

  it('truncates results that exceed available context', () => {
    // Use a small maxTokens so results won't fit
    const deps = makeOverflowDeps({
      economics: { getBudget: () => ({ maxTokens: 500 }) },
    });

    // 15 results with decent-sized content
    const results: ToolResult[] = Array.from({ length: 15 }, (_, i) => ({
      callId: `tc${i}`,
      result: 'A'.repeat(200), // Each ~57 tokens
    }));

    const messages: Message[] = []; // No pre-existing context
    const skipped = applyContextOverflowGuard(deps, messages, results);

    expect(skipped).toBeGreaterThan(0);
    // Verify skipped results have the overflow message
    const lastResult = results[results.length - 1];
    expect(lastResult.result).toContain('context overflow guard');
  });

  it('emits safeguard event when truncating', () => {
    const emit = vi.fn();
    const deps = makeOverflowDeps({
      economics: { getBudget: () => ({ maxTokens: 500 }) },
      emit,
    });

    const results: ToolResult[] = Array.from({ length: 15 }, (_, i) => ({
      callId: `tc${i}`,
      result: 'A'.repeat(200),
    }));

    applyContextOverflowGuard(deps, [], results);

    expect(emit).toHaveBeenCalledWith(expect.objectContaining({
      type: 'safeguard.context_overflow_guard',
    }));
  });

  it('preserves callId on truncated results', () => {
    const deps = makeOverflowDeps({
      economics: { getBudget: () => ({ maxTokens: 500 }) },
    });

    const results: ToolResult[] = Array.from({ length: 15 }, (_, i) => ({
      callId: `tc${i}`,
      result: 'A'.repeat(200),
    }));

    applyContextOverflowGuard(deps, [], results);

    // All results should still have their original callIds
    results.forEach((r, i) => {
      expect(r.callId).toBe(`tc${i}`);
    });
  });

  it('does not modify results within budget', () => {
    const deps = makeOverflowDeps({
      economics: { getBudget: () => ({ maxTokens: 500 }) },
    });

    const results: ToolResult[] = Array.from({ length: 15 }, (_, i) => ({
      callId: `tc${i}`,
      result: 'A'.repeat(200),
    }));

    const skipped = applyContextOverflowGuard(deps, [], results);

    // Results before the cutoff should be untouched
    const keptCount = results.length - skipped;
    for (let i = 0; i < keptCount; i++) {
      expect(results[i].result).toBe('A'.repeat(200));
    }
  });
});
