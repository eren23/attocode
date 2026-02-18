/**
 * Tests for checkIterationBudget() extracted from execution-loop.ts.
 *
 * Covers: normal continue, soft limit, hard limit (iterations & tokens),
 * emergency recovery (success & failure), fallback iteration check.
 */

import { describe, it, expect, vi } from 'vitest';
import {
  checkIterationBudget,
  type BudgetCheckDeps,
} from '../../src/core/execution-loop.js';

import type { Message } from '../../src/types.js';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeDeps(overrides: Partial<BudgetCheckDeps> = {}): BudgetCheckDeps {
  return {
    economics: null,
    getTotalIterations: () => 5,
    maxIterations: 50,
    parentIterations: 0,
    state: { iteration: 5, metrics: {}, messages: [] },
    emit: vi.fn(),
    ...overrides,
  };
}

function makeEconomics(overrides: {
  canContinue?: boolean;
  forceTextOnly?: boolean;
  injectedPrompt?: string;
  allowTaskContinuation?: boolean;
  percentUsed?: number;
  budgetType?: string;
  budgetMode?: string;
  isSoftLimit?: boolean;
  suggestedAction?: string;
  reason?: string;
  enforcementMode?: string;
  tokens?: number;
  maxTokens?: number;
} = {}) {
  const {
    canContinue = true,
    forceTextOnly = false,
    injectedPrompt,
    allowTaskContinuation = true,
    percentUsed = 30,
    budgetType = 'tokens',
    budgetMode = 'standard',
    isSoftLimit = false,
    suggestedAction,
    reason,
    enforcementMode = 'strict',
    tokens = 1000,
    maxTokens = 100000,
  } = overrides;

  return {
    checkBudget: vi.fn(() => ({
      canContinue,
      forceTextOnly,
      injectedPrompt,
      allowTaskContinuation,
      percentUsed,
      budgetType,
      budgetMode,
      isSoftLimit,
      suggestedAction,
      reason,
    })),
    getBudget: vi.fn(() => ({ maxTokens, enforcementMode })),
    getUsage: vi.fn(() => ({ tokens })),
    updateBaseline: vi.fn(),
  };
}

const emptyMessages: Message[] = [{ role: 'user', content: 'hello' }];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('checkIterationBudget', () => {
  describe('with economics', () => {
    it('returns continue when canContinue is true', () => {
      const econ = makeEconomics({ canContinue: true });
      const deps = makeDeps({ economics: econ });
      const result = checkIterationBudget(deps, emptyMessages);

      expect(result).toEqual({
        action: 'continue',
        forceTextOnly: false,
        budgetInjectedPrompt: undefined,
        budgetAllowsTaskContinuation: true,
      });
    });

    it('propagates forceTextOnly flag', () => {
      const econ = makeEconomics({ canContinue: true, forceTextOnly: true });
      const deps = makeDeps({ economics: econ });
      const result = checkIterationBudget(deps, emptyMessages);

      expect(result).toEqual(expect.objectContaining({
        action: 'continue',
        forceTextOnly: true,
      }));
    });

    it('propagates injectedPrompt', () => {
      const econ = makeEconomics({ canContinue: true, injectedPrompt: 'You are running low on budget.' });
      const deps = makeDeps({ economics: econ });
      const result = checkIterationBudget(deps, emptyMessages);

      expect(result).toEqual(expect.objectContaining({
        action: 'continue',
        budgetInjectedPrompt: 'You are running low on budget.',
      }));
    });

    it('propagates allowTaskContinuation', () => {
      const econ = makeEconomics({ canContinue: true, allowTaskContinuation: false });
      const deps = makeDeps({ economics: econ });
      const result = checkIterationBudget(deps, emptyMessages);

      expect(result).toEqual(expect.objectContaining({
        action: 'continue',
        budgetAllowsTaskContinuation: false,
      }));
    });

    it('records trace event', () => {
      const econ = makeEconomics({ canContinue: true, percentUsed: 42 });
      const traceCollector = { record: vi.fn() };
      const deps = makeDeps({ economics: econ, traceCollector });
      checkIterationBudget(deps, emptyMessages);

      expect(traceCollector.record).toHaveBeenCalledWith(expect.objectContaining({
        type: 'budget.check',
        data: expect.objectContaining({ percentUsed: 42 }),
      }));
    });

    it('logs soft limit approaching', () => {
      const econ = makeEconomics({
        canContinue: true,
        isSoftLimit: true,
        suggestedAction: 'request_extension',
        reason: 'Approaching token budget',
        percentUsed: 85,
      });
      const logger = { info: vi.fn(), warn: vi.fn() };
      const deps = makeDeps({ economics: econ, observability: { logger } });
      const result = checkIterationBudget(deps, emptyMessages);

      expect(result.action).toBe('continue');
      expect(logger.info).toHaveBeenCalledWith(
        'Approaching budget limit',
        expect.objectContaining({ percentUsed: 85 }),
      );
    });
  });

  describe('hard limit — iterations', () => {
    it('returns stop with max_iterations when budget type is iterations', () => {
      const econ = makeEconomics({ canContinue: false, budgetType: 'iterations', reason: 'Too many iterations' });
      const deps = makeDeps({
        economics: econ,
        state: { iteration: 50, metrics: {}, messages: [] },
        getTotalIterations: () => 50,
      });
      const result = checkIterationBudget(deps, emptyMessages);

      expect(result).toEqual({
        action: 'stop',
        result: expect.objectContaining({ terminationReason: 'max_iterations' }),
      });
    });

    it('includes parent iterations in error message', () => {
      const econ = makeEconomics({ canContinue: false, budgetType: 'iterations' });
      const deps = makeDeps({
        economics: econ,
        parentIterations: 10,
        state: { iteration: 40, metrics: {}, messages: [] },
        getTotalIterations: () => 50,
      });
      const result = checkIterationBudget(deps, emptyMessages);

      expect(result.action).toBe('stop');
      if (result.action === 'stop') {
        expect(result.result.failureReason).toContain('40 + 10 parent = 50');
      }
    });
  });

  describe('hard limit — tokens (with recovery)', () => {
    it('attempts recovery when token limit reached and succeeds if context reduced >20%', () => {
      // Create messages with enough content so compaction + truncation achieves >20% reduction
      const longMessages: Message[] = [
        { role: 'system', content: 'System prompt' },
        ...Array.from({ length: 20 }, (_, i) => ({
          role: 'user' as const,
          content: `This is message ${i} with a reasonably long body of text that adds up`.repeat(5),
        })),
      ];

      const stateMessages = [...longMessages];
      const econ = makeEconomics({
        canContinue: false,
        budgetType: 'tokens',
        reason: 'Token budget exceeded',
      });
      const deps = makeDeps({
        economics: econ,
        state: { iteration: 10, metrics: {}, messages: stateMessages },
      });
      const result = checkIterationBudget(deps, longMessages);

      expect(result.action).toBe('recovery_success');
      // Messages should have been truncated
      expect(longMessages.length).toBeLessThan(22);
    });

    it('stops if recovery does not achieve sufficient reduction', () => {
      // Very short messages — can't compact enough
      const shortMessages: Message[] = [
        { role: 'user', content: 'hi' },
        { role: 'assistant', content: 'hello' },
      ];

      const econ = makeEconomics({
        canContinue: false,
        budgetType: 'tokens',
        reason: 'Token budget exceeded',
      });
      const deps = makeDeps({
        economics: econ,
        state: { iteration: 10, metrics: {}, messages: [...shortMessages] },
      });
      const result = checkIterationBudget(deps, shortMessages);

      expect(result.action).toBe('stop');
      if (result.action === 'stop') {
        expect(result.result.terminationReason).toBe('budget_limit');
      }
    });

    it('does not attempt recovery a second time', () => {
      const longMessages: Message[] = [
        { role: 'system', content: 'System prompt' },
        ...Array.from({ length: 20 }, (_, i) => ({
          role: 'user' as const,
          content: `Message ${i} padding text`.repeat(10),
        })),
      ];

      const econ = makeEconomics({
        canContinue: false,
        budgetType: 'tokens',
        reason: 'Token budget exceeded',
      });
      const state: any = { iteration: 10, metrics: {}, messages: [...longMessages], _recoveryAttempted: true };
      const deps = makeDeps({ economics: econ, state });
      const result = checkIterationBudget(deps, longMessages);

      // Already attempted recovery → straight to stop
      expect(result.action).toBe('stop');
    });

    it('injects work log after emergency truncation', () => {
      const longMessages: Message[] = [
        { role: 'system', content: 'System prompt' },
        ...Array.from({ length: 20 }, (_, i) => ({
          role: 'user' as const,
          content: `Message ${i} padding`.repeat(10),
        })),
      ];

      const workLog = {
        hasContent: () => true,
        toCompactString: () => '[Work Log] Did things',
      };
      const econ = makeEconomics({
        canContinue: false,
        budgetType: 'tokens',
      });
      const deps = makeDeps({
        economics: econ,
        state: { iteration: 10, metrics: {}, messages: [...longMessages] },
        workLog,
      });
      const result = checkIterationBudget(deps, longMessages);

      if (result.action === 'recovery_success') {
        const hasWorkLog = longMessages.some(m => typeof m.content === 'string' && m.content.includes('[Work Log]'));
        expect(hasWorkLog).toBe(true);
      }
    });
  });

  describe('hard limit — cost budget', () => {
    it('returns stop with budget_limit for cost budget type', () => {
      const econ = makeEconomics({
        canContinue: false,
        budgetType: 'cost',
        reason: 'Cost limit exceeded',
      });
      // Short messages so recovery fails
      const deps = makeDeps({
        economics: econ,
        state: { iteration: 5, metrics: {}, messages: [{ role: 'user', content: 'x' }] },
      });
      const result = checkIterationBudget(deps, [{ role: 'user', content: 'x' }]);

      expect(result.action).toBe('stop');
      if (result.action === 'stop') {
        expect(result.result.terminationReason).toBe('budget_limit');
      }
    });
  });

  describe('without economics (fallback)', () => {
    it('returns continue when under max iterations', () => {
      const deps = makeDeps({ economics: null, getTotalIterations: () => 10, maxIterations: 50 });
      const result = checkIterationBudget(deps, emptyMessages);

      expect(result).toEqual({
        action: 'continue',
        forceTextOnly: false,
        budgetAllowsTaskContinuation: true,
      });
    });

    it('returns stop when at max iterations', () => {
      const deps = makeDeps({ economics: null, getTotalIterations: () => 50, maxIterations: 50 });
      const result = checkIterationBudget(deps, emptyMessages);

      expect(result).toEqual({
        action: 'stop',
        result: expect.objectContaining({
          terminationReason: 'max_iterations',
        }),
      });
    });

    it('emits error event on max iterations', () => {
      const emit = vi.fn();
      const deps = makeDeps({ economics: null, getTotalIterations: () => 50, maxIterations: 50, emit });
      checkIterationBudget(deps, emptyMessages);

      expect(emit).toHaveBeenCalledWith(expect.objectContaining({ type: 'error' }));
    });
  });
});
