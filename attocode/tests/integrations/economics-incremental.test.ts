/**
 * Tests for incremental token accounting and graduated budget modes.
 *
 * Validates:
 * - Baseline tracking (setBaseline, updateBaseline, getBaseline)
 * - Incremental vs cumulative token accounting
 * - estimateNextCallCost
 * - Graduated BudgetMode values from checkBudget
 * - Backward compat: no baseline → cumulative counting
 * - Critical test: resumed session with deep context doesn't exhaust budget
 */

import { describe, it, expect } from 'vitest';
import { ExecutionEconomicsManager } from '../../src/integrations/budget/economics.js';

describe('Incremental token accounting', () => {
  describe('baseline tracking', () => {
    it('setBaseline establishes baseline and updates usage', () => {
      const mgr = new ExecutionEconomicsManager({ maxTokens: 200000, maxIterations: 100 });
      mgr.setBaseline(30000);
      expect(mgr.getBaseline()).toBe(30000);
      expect(mgr.getUsage().baselineContextTokens).toBe(30000);
    });

    it('updateBaseline adjusts baseline after compaction', () => {
      const mgr = new ExecutionEconomicsManager({ maxTokens: 200000, maxIterations: 100 });
      mgr.setBaseline(30000);
      mgr.updateBaseline(15000);
      expect(mgr.getBaseline()).toBe(15000);
      expect(mgr.getUsage().baselineContextTokens).toBe(15000);
    });

    it('reset clears baseline state', () => {
      const mgr = new ExecutionEconomicsManager({ maxTokens: 200000, maxIterations: 100 });
      mgr.setBaseline(30000);
      mgr.reset();
      expect(mgr.getBaseline()).toBe(0);
      expect(mgr.getUsage().baselineContextTokens).toBe(0);
    });
  });

  describe('estimateNextCallCost', () => {
    it('subtracts baseline from estimated input', () => {
      const mgr = new ExecutionEconomicsManager({ maxTokens: 200000, maxIterations: 100 });
      mgr.setBaseline(30000);
      // With 30k baseline, a 35k input call only costs 5k incrementally + output
      const cost = mgr.estimateNextCallCost(35000, 2000);
      expect(cost).toBe(5000 + 2000);
    });

    it('returns full estimate without baseline', () => {
      const mgr = new ExecutionEconomicsManager({ maxTokens: 200000, maxIterations: 100 });
      const cost = mgr.estimateNextCallCost(35000, 2000);
      expect(cost).toBe(35000 + 2000);
    });

    it('clamps to zero if estimated input is less than baseline', () => {
      const mgr = new ExecutionEconomicsManager({ maxTokens: 200000, maxIterations: 100 });
      mgr.setBaseline(30000);
      const cost = mgr.estimateNextCallCost(20000, 2000);
      expect(cost).toBe(0 + 2000); // incremental input is 0
    });
  });

  describe('recordLLMUsage with incremental accounting', () => {
    it('counts only incremental input tokens when baseline is set', () => {
      const mgr = new ExecutionEconomicsManager({ maxTokens: 200000, maxIterations: 100 });
      mgr.setBaseline(30000);

      // First call: 32k input, 2k output. Incremental = max(0, 32k - 0) = 32k
      mgr.recordLLMUsage(32000, 2000, 'test-model');
      let usage = mgr.getUsage();
      expect(usage.tokens).toBe(32000 + 2000); // 34k
      expect(usage.cumulativeInputTokens).toBe(32000);

      // Second call: 34k input (context grew by 2k from output), 1.5k output
      // Incremental = max(0, 34k - 32k) = 2k
      mgr.recordLLMUsage(34000, 1500, 'test-model');
      usage = mgr.getUsage();
      expect(usage.tokens).toBe(34000 + 2000 + 1500); // 34k + 2k + 1.5k = 37.5k
      expect(usage.cumulativeInputTokens).toBe(32000 + 34000); // 66k cumulative
    });

    it('backward compat: uses cumulative when no baseline set', () => {
      const mgr = new ExecutionEconomicsManager({ maxTokens: 200000, maxIterations: 100 });
      // No baseline set

      mgr.recordLLMUsage(32000, 2000, 'test-model');
      let usage = mgr.getUsage();
      expect(usage.tokens).toBe(32000 + 2000); // cumulative

      mgr.recordLLMUsage(34000, 1500, 'test-model');
      usage = mgr.getUsage();
      // Cumulative: 32k + 34k + 2k + 1.5k = 69.5k
      expect(usage.tokens).toBe(32000 + 2000 + 34000 + 1500);
    });

    it('subtracts cacheReadTokens from incremental input', () => {
      const mgr = new ExecutionEconomicsManager({ maxTokens: 200000, maxIterations: 100 });
      mgr.setBaseline(30000);

      // 35k input, 2k output, 3k cached
      // Incremental = max(0, 35k - 0) = 35k, effective = max(0, 35k - 3k) = 32k
      mgr.recordLLMUsage(35000, 2000, 'test-model', undefined, 3000);
      const usage = mgr.getUsage();
      expect(usage.tokens).toBe(32000 + 2000);
    });

    it('tracks cumulativeInputTokens separately for debugging', () => {
      const mgr = new ExecutionEconomicsManager({ maxTokens: 200000, maxIterations: 100 });
      mgr.setBaseline(30000);

      mgr.recordLLMUsage(32000, 2000, 'test-model');
      mgr.recordLLMUsage(34000, 1500, 'test-model');
      mgr.recordLLMUsage(36000, 1000, 'test-model');

      const usage = mgr.getUsage();
      // Cumulative input: 32k + 34k + 36k = 102k
      expect(usage.cumulativeInputTokens).toBe(102000);
      // Incremental tokens should be much less
      expect(usage.tokens).toBeLessThan(usage.cumulativeInputTokens);
    });
  });

  describe('critical scenario: resumed session with 30k context', () => {
    it('does NOT exhaust budget after 11 LLM calls with 30k context baseline', () => {
      const mgr = new ExecutionEconomicsManager({
        maxTokens: 200000,
        softTokenLimit: 150000,
        maxIterations: 100,
      });
      mgr.setBaseline(30000);

      // Simulate 11 LLM calls where each re-sends the full context
      // Without incremental: 11 * 42k = 462k tokens → WAY over budget
      // With incremental: each call adds ~2k new input + 2k output = ~4k per call
      for (let i = 0; i < 11; i++) {
        const inputTokens = 30000 + (i * 2000); // Context grows each call
        const outputTokens = 2000;
        mgr.recordLLMUsage(inputTokens, outputTokens, 'test-model');
        mgr.recordToolCall('read_file', { path: `/file${i}.ts` });
      }

      const usage = mgr.getUsage();
      const budget = mgr.getBudget();

      // With incremental accounting, we should be well under budget
      expect(usage.tokens).toBeLessThan(budget.maxTokens);
      expect(usage.tokens).toBeLessThan(100000); // Should be around 52-54k

      // But cumulative would be massive
      expect(usage.cumulativeInputTokens).toBeGreaterThan(300000);

      // Budget check should allow continuation
      const check = mgr.checkBudget();
      expect(check.canContinue).toBe(true);
      expect(check.budgetMode).not.toBe('hard');
    });
  });
});

describe('Graduated budget modes', () => {
  it('returns budgetMode=none when all is well', () => {
    const mgr = new ExecutionEconomicsManager({
      maxTokens: 200000,
      maxIterations: 100,
    });
    const check = mgr.checkBudget();
    expect(check.budgetMode).toBe('none');
    expect(check.allowTaskContinuation).toBe(true);
  });

  it('returns budgetMode=warn for soft token limit (67-79%)', () => {
    const mgr = new ExecutionEconomicsManager({
      maxTokens: 200000,
      softTokenLimit: 140000,
      maxIterations: 100,
    });
    // Push tokens to 70% (140k)
    mgr.recordLLMUsage(140000, 1000, 'test-model');
    const check = mgr.checkBudget();
    expect(check.budgetMode).toBe('warn');
    expect(check.allowTaskContinuation).toBe(true);
  });

  it('returns budgetMode=restricted for 80%+ tokens with task continuation allowed', () => {
    const mgr = new ExecutionEconomicsManager({
      maxTokens: 200000,
      softTokenLimit: 140000,
      maxIterations: 100,
    });
    // Push tokens to 82% (164k)
    mgr.recordLLMUsage(163000, 1000, 'test-model');
    const check = mgr.checkBudget();
    expect(check.budgetMode).toBe('restricted');
    expect(check.forceTextOnly).toBe(true);
    expect(check.allowTaskContinuation).toBe(true); // Key: can switch tasks
  });

  it('returns budgetMode=hard for max iterations', () => {
    const mgr = new ExecutionEconomicsManager({
      maxTokens: 200000,
      maxIterations: 5,
    });
    // Exhaust iterations
    for (let i = 0; i < 5; i++) {
      mgr.recordToolCall('read_file', { path: `/file${i}.ts` });
    }
    const check = mgr.checkBudget();
    expect(check.budgetMode).toBe('hard');
    expect(check.allowTaskContinuation).toBe(false);
    expect(check.forceTextOnly).toBe(true);
  });

  it('returns budgetMode=hard for token budget exceeded (strict enforcement)', () => {
    const mgr = new ExecutionEconomicsManager({
      maxTokens: 50000,
      maxIterations: 100,
      enforcementMode: 'strict',
    });
    mgr.recordLLMUsage(50001, 1000, 'test-model');
    const check = mgr.checkBudget();
    expect(check.budgetMode).toBe('hard');
    expect(check.allowTaskContinuation).toBe(false);
    expect(check.canContinue).toBe(false);
  });

  it('returns budgetMode=warn for doom loop with task continuation allowed', () => {
    const mgr = new ExecutionEconomicsManager({
      maxTokens: 200000,
      maxIterations: 100,
    });
    // Trigger doom loop: same tool+args 3 times
    for (let i = 0; i < 3; i++) {
      mgr.recordToolCall('read_file', { path: '/same/file.ts' });
    }
    const check = mgr.checkBudget();
    expect(check.budgetMode).toBe('warn');
    expect(check.allowTaskContinuation).toBe(true);
    expect(check.reason).toContain('Doom loop');
  });

  it('returns budgetMode=warn for doomloop_only enforcement mode even when over budget', () => {
    const mgr = new ExecutionEconomicsManager({
      maxTokens: 50000,
      maxIterations: 100,
      enforcementMode: 'doomloop_only',
    });
    mgr.recordLLMUsage(50001, 1000, 'test-model');
    const check = mgr.checkBudget();
    expect(check.budgetMode).toBe('warn');
    expect(check.allowTaskContinuation).toBe(true);
    expect(check.canContinue).toBe(true);
  });
});
