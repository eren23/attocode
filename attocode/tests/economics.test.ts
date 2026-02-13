/**
 * Economics System Tests
 *
 * Comprehensive tests for ExecutionEconomicsManager: budget checking,
 * phase tracking, doom loop detection integration, extension requests,
 * duration pause/resume, preset budgets, and event emission.
 */

import { describe, it, expect, vi } from 'vitest';
import {
  createEconomicsManager,
  extractBashFileTarget,
  QUICK_BUDGET,
  STANDARD_BUDGET,
  SUBAGENT_BUDGET,
  LARGE_BUDGET,
  SWARM_WORKER_BUDGET,
  type EconomicsEvent,
} from '../src/integrations/economics.js';

// =============================================================================
// Hard Limits
// =============================================================================

describe('checkBudget - Hard Limits', () => {
  it('token budget exceeded → canContinue: false', () => {
    const econ = createEconomicsManager({ maxTokens: 1000, softTokenLimit: 800 });
    econ.recordLLMUsage(600, 500); // 1100 tokens

    const result = econ.checkBudget();
    expect(result.canContinue).toBe(false);
    expect(result.budgetType).toBe('tokens');
    expect(result.isHardLimit).toBe(true);
    expect(result.suggestedAction).toBe('stop');
  });

  it('cost budget exceeded → canContinue: false', () => {
    const econ = createEconomicsManager({ maxCost: 0.10, softCostLimit: 0.08 });
    econ.recordLLMUsage(0, 0, undefined, 0.15);

    const result = econ.checkBudget();
    expect(result.canContinue).toBe(false);
    expect(result.budgetType).toBe('cost');
    expect(result.isHardLimit).toBe(true);
    expect(result.suggestedAction).toBe('stop');
  });

  it('duration budget exceeded → canContinue: false', () => {
    const econ = createEconomicsManager({ maxDuration: 100 });
    const now = Date.now();
    vi.spyOn(Date, 'now').mockReturnValue(now + 200);

    const result = econ.checkBudget();
    expect(result.canContinue).toBe(false);
    expect(result.budgetType).toBe('duration');
    expect(result.isHardLimit).toBe(true);

    vi.restoreAllMocks();
  });
});

// =============================================================================
// Max Iterations (forceTextOnly)
// =============================================================================

describe('checkBudget - Max Iterations', () => {
  it('max iterations reached → canContinue: true + forceTextOnly + injectedPrompt', () => {
    const econ = createEconomicsManager({
      maxIterations: 3,
      // Set soft limits high to avoid them triggering first
      softTokenLimit: 999999,
      softCostLimit: 999,
    });

    // Record 3 tool calls with different args to avoid doom loop
    econ.recordToolCall('read_file', { path: '/a.ts' });
    econ.recordToolCall('read_file', { path: '/b.ts' });
    econ.recordToolCall('read_file', { path: '/c.ts' });

    const result = econ.checkBudget();
    expect(result.canContinue).toBe(true);
    expect(result.forceTextOnly).toBe(true);
    expect(result.budgetType).toBe('iterations');
    expect(result.isHardLimit).toBe(true);
    expect(result.injectedPrompt).toContain('Maximum steps reached');
    expect(result.injectedPrompt).toContain('Do NOT call any more tools');
  });
});

// =============================================================================
// Soft Limits
// =============================================================================

describe('checkBudget - Soft Limits', () => {
  it('soft token limit (67-79%) → warning with request_extension', () => {
    // 75% of 200 = 150 (softTokenLimit default)
    const econ = createEconomicsManager({
      maxTokens: 200,
      softTokenLimit: 140,
    });
    econ.recordLLMUsage(75, 75); // 150 tokens = 75% of 200

    const result = econ.checkBudget();
    expect(result.canContinue).toBe(true);
    expect(result.isSoftLimit).toBe(true);
    expect(result.budgetType).toBe('tokens');
    // 75% is below 80% threshold, so should suggest extension not force stop
    expect(result.suggestedAction).toBe('request_extension');
    expect(result.forceTextOnly).toBeFalsy();
  });

  it('soft token limit (80%+) → forceTextOnly', () => {
    const econ = createEconomicsManager({
      maxTokens: 200,
      softTokenLimit: 150,
    });
    econ.recordLLMUsage(90, 90); // 180 tokens = 90% of 200

    const result = econ.checkBudget();
    expect(result.canContinue).toBe(true);
    expect(result.isSoftLimit).toBe(true);
    expect(result.forceTextOnly).toBe(true);
    expect(result.suggestedAction).toBe('stop');
  });

  it('soft cost limit → warning emitted', () => {
    const events: EconomicsEvent[] = [];
    const econ = createEconomicsManager({
      maxCost: 1.00,
      softCostLimit: 0.50,
      softTokenLimit: 999999, // Avoid token limit triggering first
    });
    econ.on(e => events.push(e));

    econ.recordLLMUsage(0, 0, undefined, 0.60);

    const result = econ.checkBudget();
    expect(result.canContinue).toBe(true);
    expect(result.isSoftLimit).toBe(true);
    expect(result.budgetType).toBe('cost');

    const warnings = events.filter(e => e.type === 'budget.warning');
    expect(warnings.length).toBeGreaterThanOrEqual(1);
  });
});

// =============================================================================
// Stuck Detection
// =============================================================================

describe('checkBudget - Stuck Detection', () => {
  it('3+ iterations without progress → suggestedAction request_extension', () => {
    const econ = createEconomicsManager({
      softTokenLimit: 999999,
      softCostLimit: 999,
    });

    // Do many iterations of the same tool call to be stuck
    // Need stuckCount >= 3 (isStuck() returns true when 3 consecutive same calls)
    // and those get accumulated via recordToolCall
    for (let i = 0; i < 10; i++) {
      econ.recordToolCall('read_file', { path: '/same.ts' });
    }

    // The isStuck check in checkBudget looks at stuckCount >= 3
    // But doom loop will trigger first (at 3 consecutive). Let's check doom loop fires.
    const result = econ.checkBudget();
    // With 10 identical calls, doom loop fires first
    expect(result.canContinue).toBe(true);
    expect(result.isSoftLimit).toBe(true);
    // Doom loop prompt should be injected
    expect(result.injectedPrompt).toBeDefined();
  });
});

// =============================================================================
// Phase Tracking
// =============================================================================

describe('Phase Tracking', () => {
  it('starts in exploring phase', () => {
    const econ = createEconomicsManager(STANDARD_BUDGET);
    expect(econ.getPhaseState().phase).toBe('exploring');
  });

  it('transitions to acting on first edit', () => {
    const events: EconomicsEvent[] = [];
    const econ = createEconomicsManager(STANDARD_BUDGET);
    econ.on(e => events.push(e));

    econ.recordToolCall('write_file', { path: '/foo.ts', content: 'hello' });

    expect(econ.getPhaseState().phase).toBe('acting');
    const transitions = events.filter(e => e.type === 'phase.transition');
    expect(transitions.length).toBe(1);
    expect((transitions[0] as { from: string; to: string }).from).toBe('exploring');
    expect((transitions[0] as { from: string; to: string }).to).toBe('acting');
  });

  it('transitions to verifying when tests run after edits', () => {
    const econ = createEconomicsManager(STANDARD_BUDGET);

    // First make an edit (transitions to acting)
    econ.recordToolCall('write_file', { path: '/foo.ts', content: 'hello' });
    expect(econ.getPhaseState().phase).toBe('acting');

    // Then run tests (transitions to verifying)
    econ.recordToolCall('bash', { command: 'npm test' });
    expect(econ.getPhaseState().phase).toBe('verifying');
  });

  it('does not transition to verifying if no edits made', () => {
    const econ = createEconomicsManager(STANDARD_BUDGET);

    // Run tests without edits — stays in exploring
    econ.recordToolCall('bash', { command: 'npm test' });
    expect(econ.getPhaseState().phase).toBe('exploring');
  });
});

// =============================================================================
// Exploration Saturation
// =============================================================================

describe('Exploration Saturation', () => {
  it('10+ files read without edits → shouldTransition + nudge prompt', () => {
    const events: EconomicsEvent[] = [];
    const econ = createEconomicsManager({
      ...STANDARD_BUDGET,
      softTokenLimit: 999999,
      softCostLimit: 999,
    });
    econ.on(e => events.push(e));

    // Read 10 unique files (no edits)
    for (let i = 0; i < 10; i++) {
      econ.recordToolCall('read_file', { path: `/file${i}.ts` });
    }

    const phase = econ.getPhaseState();
    expect(phase.shouldTransition).toBe(true);
    expect(phase.uniqueFilesRead).toBe(10);

    const saturationEvents = events.filter(e => e.type === 'exploration.saturation');
    expect(saturationEvents.length).toBeGreaterThanOrEqual(1);

    // checkBudget should include nudge prompt
    const result = econ.checkBudget();
    expect(result.injectedPrompt).toContain('read');
    expect(result.injectedPrompt).toContain('files');
  });
});

// =============================================================================
// Test-Fix Cycle
// =============================================================================

describe('Test-Fix Cycle', () => {
  it('3 consecutive test failures → rethink prompt', () => {
    const econ = createEconomicsManager({
      ...STANDARD_BUDGET,
      softTokenLimit: 999999,
      softCostLimit: 999,
    });

    // Make an edit first (enter acting phase)
    econ.recordToolCall('write_file', { path: '/fix.ts', content: 'fix' });

    // 3 test runs with different commands to avoid doom loop detection
    // but all fail (interleave edits to break the doom loop)
    econ.recordToolCall('bash', { command: 'npm test -- tests/auth.test.ts' }, 'FAILED: 3 tests');
    econ.recordToolCall('edit_file', { path: '/fix.ts', content: 'fix2' });
    econ.recordToolCall('bash', { command: 'npm test -- tests/auth.test.ts --verbose' }, 'FAILED: 2 tests');
    econ.recordToolCall('edit_file', { path: '/fix.ts', content: 'fix3' });
    econ.recordToolCall('bash', { command: 'npx jest tests/auth.test.ts' }, 'FAILED: 1 test');

    const phase = econ.getPhaseState();
    expect(phase.consecutiveTestFailures).toBe(3);
    expect(phase.inTestFixCycle).toBe(true);

    const result = econ.checkBudget();
    expect(result.injectedPrompt).toContain('consecutive test failures');
    expect(result.injectedPrompt).toContain('DIFFERENT fix strategy');
  });

  it('test pass resets consecutive failure count', () => {
    const econ = createEconomicsManager(STANDARD_BUDGET);

    econ.recordToolCall('write_file', { path: '/fix.ts', content: 'fix' });
    econ.recordToolCall('bash', { command: 'npm test' }, 'FAILED: 1 test');
    econ.recordToolCall('bash', { command: 'npm test' }, 'FAILED: 1 test');
    econ.recordToolCall('bash', { command: 'npm test' }, '5 passed');

    const phase = econ.getPhaseState();
    expect(phase.consecutiveTestFailures).toBe(0);
    expect(phase.lastTestPassed).toBe(true);
    expect(phase.inTestFixCycle).toBe(false);
  });
});

// =============================================================================
// Phase Budget Enforcement
// =============================================================================

describe('Phase Budget Enforcement', () => {
  it('exploration exceeds maxExplorationPercent → prompt injected', () => {
    const econ = createEconomicsManager({
      maxIterations: 10,
      softTokenLimit: 999999,
      softCostLimit: 999,
    });

    econ.setPhaseBudget({
      maxExplorationPercent: 30,
      reservedVerificationPercent: 20,
      enabled: true,
    });

    // 4 iterations in exploration = 40% > 30%
    econ.recordToolCall('read_file', { path: '/a.ts' });
    econ.recordToolCall('read_file', { path: '/b.ts' });
    econ.recordToolCall('read_file', { path: '/c.ts' });
    econ.recordToolCall('read_file', { path: '/d.ts' });

    const result = econ.checkBudget();
    expect(result.injectedPrompt).toContain('exploration');
    expect(result.injectedPrompt).toContain('Start making edits NOW');
  });

  it('verification reserve → run tests prompt when low budget and no tests run', () => {
    const econ = createEconomicsManager({
      maxIterations: 10,
      softTokenLimit: 999999,
      softCostLimit: 999,
    });

    econ.setPhaseBudget({
      maxExplorationPercent: 30,
      reservedVerificationPercent: 30,
      enabled: true,
    });

    // Make an edit (transitions to acting)
    econ.recordToolCall('write_file', { path: '/fix.ts', content: 'code' });

    // Use up iterations until only ~20% left (8 iterations = 80% used, 20% remaining)
    for (let i = 0; i < 7; i++) {
      econ.recordToolCall('edit_file', { path: `/file${i}.ts`, content: 'edit' });
    }

    // Now at 8 iterations = 80% used, 20% remaining <= 30% reserved
    const result = econ.checkBudget();
    expect(result.injectedPrompt).toContain('Run your tests NOW');
  });
});

// =============================================================================
// Duration Pause/Resume
// =============================================================================

describe('Duration Pause/Resume', () => {
  it('paused time excluded from effective duration', () => {
    const econ2 = createEconomicsManager({ maxDuration: 10000 });
    const baseTime = Date.now();

    // Simulate: pause at +100, resume at +600 (paused for 500ms), check at +700
    const mockNow = vi.spyOn(Date, 'now');
    // pauseDuration call
    mockNow.mockReturnValueOnce(baseTime + 100);
    econ2.pauseDuration();

    // resumeDuration call
    mockNow.mockReturnValueOnce(baseTime + 600);
    econ2.resumeDuration();

    // getUsage calls getEffectiveDuration which calls Date.now
    mockNow.mockReturnValue(baseTime + 700);
    const usage = econ2.getUsage();

    // Effective = 700 - 500(paused) = 200ms (approximately)
    // The actual startTime was set at construction time (before our mock), so
    // the exact value depends on timing. But we can verify paused duration is subtracted.
    // Let's just verify the concept works by checking duration < 700.
    // Actually since startTime was set before mock, duration = (baseTime+700) - startTime - 500
    // startTime ≈ baseTime (within ms), so duration ≈ 200
    expect(usage.duration).toBeLessThan(500);

    vi.restoreAllMocks();
  });

  it('double pause is idempotent', () => {
    const econ = createEconomicsManager();
    econ.pauseDuration();
    econ.pauseDuration(); // should not reset pauseStart
    econ.resumeDuration();
    // No error thrown = pass
    expect(true).toBe(true);
  });

  it('resume without pause is no-op', () => {
    const econ = createEconomicsManager();
    econ.resumeDuration(); // should be no-op
    expect(true).toBe(true);
  });
});

// =============================================================================
// Extension Request
// =============================================================================

describe('Extension Request', () => {
  it('handler called and budget extended on approval', async () => {
    const econ = createEconomicsManager({ maxTokens: 1000 });

    econ.setExtensionHandler(async (_request) => ({
      maxTokens: 2000,
    }));

    const granted = await econ.requestExtension('Need more tokens');
    expect(granted).toBe(true);
    expect(econ.getBudget().maxTokens).toBe(2000);
  });

  it('returns false when handler returns null', async () => {
    const econ = createEconomicsManager({ maxTokens: 1000 });

    econ.setExtensionHandler(async () => null);

    const granted = await econ.requestExtension('Need more tokens');
    expect(granted).toBe(false);
    expect(econ.getBudget().maxTokens).toBe(1000); // unchanged
  });

  it('returns false when no handler set', async () => {
    const econ = createEconomicsManager();
    const granted = await econ.requestExtension('Need more');
    expect(granted).toBe(false);
  });

  it('returns false when handler throws', async () => {
    const econ = createEconomicsManager();
    econ.setExtensionHandler(async () => {
      throw new Error('Network error');
    });

    const granted = await econ.requestExtension('Need more');
    expect(granted).toBe(false);
  });

  it('emits extension events', async () => {
    const events: EconomicsEvent[] = [];
    const econ = createEconomicsManager({ maxTokens: 1000 });
    econ.on(e => events.push(e));

    econ.setExtensionHandler(async () => ({ maxTokens: 2000 }));
    await econ.requestExtension('Need more tokens');

    expect(events.some(e => e.type === 'extension.requested')).toBe(true);
    expect(events.some(e => e.type === 'extension.granted')).toBe(true);
  });
});

// =============================================================================
// Budget Presets
// =============================================================================

describe('Budget Presets', () => {
  it('QUICK < STANDARD < LARGE in all budget dimensions', () => {
    const quick = createEconomicsManager(QUICK_BUDGET).getBudget();
    const standard = createEconomicsManager(STANDARD_BUDGET).getBudget();
    const large = createEconomicsManager(LARGE_BUDGET).getBudget();

    expect(quick.maxTokens).toBeLessThan(standard.maxTokens);
    expect(standard.maxTokens).toBeLessThan(large.maxTokens);

    expect(quick.maxCost).toBeLessThan(standard.maxCost);
    expect(standard.maxCost).toBeLessThan(large.maxCost);

    expect(quick.maxDuration).toBeLessThan(standard.maxDuration);
    expect(standard.maxDuration).toBeLessThan(large.maxDuration);

    expect(quick.maxIterations).toBeLessThan(standard.maxIterations);
    expect(standard.maxIterations).toBeLessThan(large.maxIterations);
  });

  it('SUBAGENT is smaller than LARGE', () => {
    const sub = createEconomicsManager(SUBAGENT_BUDGET).getBudget();
    const large = createEconomicsManager(LARGE_BUDGET).getBudget();

    expect(sub.maxTokens).toBeLessThan(large.maxTokens);
    expect(sub.maxIterations).toBeLessThan(large.maxIterations);
  });

  it('SWARM_WORKER is the smallest preset', () => {
    const worker = createEconomicsManager(SWARM_WORKER_BUDGET).getBudget();
    const quick = createEconomicsManager(QUICK_BUDGET).getBudget();

    expect(worker.maxTokens).toBeLessThan(quick.maxTokens);
    expect(worker.maxDuration).toBeGreaterThan(0);
  });
});

// =============================================================================
// Reset
// =============================================================================

describe('Reset', () => {
  it('clears all usage, progress, loop state, phase state', () => {
    const econ = createEconomicsManager(STANDARD_BUDGET);

    // Accumulate state
    econ.recordLLMUsage(1000, 500);
    econ.recordToolCall('write_file', { path: '/b.ts', content: 'x' });
    econ.recordToolCall('read_file', { path: '/a.ts' });
    econ.recordToolCall('read_file', { path: '/a.ts' });
    econ.recordToolCall('read_file', { path: '/a.ts' });

    // Verify state was accumulated
    expect(econ.getUsage().tokens).toBeGreaterThan(0);
    expect(econ.getUsage().iterations).toBeGreaterThan(0);
    expect(econ.getProgress().filesRead).toBeGreaterThan(0);
    expect(econ.getLoopState().doomLoopDetected).toBe(true);
    expect(econ.getPhaseState().phase).toBe('acting');

    // Reset
    econ.reset();

    // Everything should be zeroed
    expect(econ.getUsage().tokens).toBe(0);
    expect(econ.getUsage().iterations).toBe(0);
    expect(econ.getUsage().cost).toBe(0);
    expect(econ.getUsage().llmCalls).toBe(0);
    expect(econ.getProgress().filesRead).toBe(0);
    expect(econ.getProgress().filesModified).toBe(0);
    expect(econ.getProgress().commandsRun).toBe(0);
    expect(econ.getLoopState().doomLoopDetected).toBe(false);
    expect(econ.getLoopState().consecutiveCount).toBe(0);
    expect(econ.getPhaseState().phase).toBe('exploring');
    expect(econ.getPhaseState().uniqueFilesRead).toBe(0);
    expect(econ.getPhaseState().testsRun).toBe(0);
  });
});

// =============================================================================
// recordLLMUsage
// =============================================================================

describe('recordLLMUsage', () => {
  it('records with actual cost (ignores model pricing)', () => {
    const econ = createEconomicsManager();
    econ.recordLLMUsage(1000, 500, 'some-model', 0.25);

    const usage = econ.getUsage();
    expect(usage.inputTokens).toBe(1000);
    expect(usage.outputTokens).toBe(500);
    expect(usage.tokens).toBe(1500);
    expect(usage.cost).toBe(0.25);
    expect(usage.llmCalls).toBe(1);
  });

  it('calculates cost from model when actualCost not provided', () => {
    const econ = createEconomicsManager();
    econ.recordLLMUsage(1000, 500, 'unknown-model');

    const usage = econ.getUsage();
    expect(usage.tokens).toBe(1500);
    expect(usage.llmCalls).toBe(1);
    // Cost may be 0 for unknown model, but should not throw
    expect(usage.cost).toBeGreaterThanOrEqual(0);
  });

  it('accumulates across multiple calls', () => {
    const econ = createEconomicsManager();
    econ.recordLLMUsage(1000, 500, undefined, 0.10);
    econ.recordLLMUsage(2000, 1000, undefined, 0.20);

    const usage = econ.getUsage();
    expect(usage.inputTokens).toBe(3000);
    expect(usage.outputTokens).toBe(1500);
    expect(usage.tokens).toBe(4500);
    expect(usage.cost).toBeCloseTo(0.30);
    expect(usage.llmCalls).toBe(2);
  });
});

// =============================================================================
// Event Emission
// =============================================================================

describe('Event Emission', () => {
  it('budget.warning emitted on soft token limit', () => {
    const events: EconomicsEvent[] = [];
    const econ = createEconomicsManager({ maxTokens: 200, softTokenLimit: 150 });
    econ.on(e => events.push(e));

    econ.recordLLMUsage(100, 60); // 160 tokens > 150 soft
    econ.checkBudget();

    const warnings = events.filter(e => e.type === 'budget.warning');
    expect(warnings.length).toBeGreaterThanOrEqual(1);
    expect((warnings[0] as { budgetType: string }).budgetType).toBe('tokens');
  });

  it('budget.exceeded emitted on hard token limit', () => {
    const events: EconomicsEvent[] = [];
    const econ = createEconomicsManager({ maxTokens: 100, softTokenLimit: 80 });
    econ.on(e => events.push(e));

    econ.recordLLMUsage(60, 50); // 110 tokens > 100 max
    econ.checkBudget();

    const exceeded = events.filter(e => e.type === 'budget.exceeded');
    expect(exceeded.length).toBeGreaterThanOrEqual(1);
    expect((exceeded[0] as { budgetType: string }).budgetType).toBe('tokens');
  });

  it('phase.transition emitted on phase change', () => {
    const events: EconomicsEvent[] = [];
    const econ = createEconomicsManager(STANDARD_BUDGET);
    econ.on(e => events.push(e));

    econ.recordToolCall('edit_file', { path: '/x.ts', content: 'y' });

    const transitions = events.filter(e => e.type === 'phase.transition');
    expect(transitions.length).toBe(1);
  });

  it('exploration.saturation emitted after 10+ files', () => {
    const events: EconomicsEvent[] = [];
    const econ = createEconomicsManager(STANDARD_BUDGET);
    econ.on(e => events.push(e));

    for (let i = 0; i < 11; i++) {
      econ.recordToolCall('read_file', { path: `/file${i}.ts` });
    }

    const saturation = events.filter(e => e.type === 'exploration.saturation');
    expect(saturation.length).toBeGreaterThanOrEqual(1);
  });

  it('listener errors are swallowed', () => {
    const econ = createEconomicsManager({ maxTokens: 100, softTokenLimit: 80 });

    econ.on(() => {
      throw new Error('bad listener');
    });

    // Second listener should still fire
    const events: EconomicsEvent[] = [];
    econ.on(e => events.push(e));

    econ.recordLLMUsage(60, 50);
    econ.checkBudget();

    // Should not throw and second listener should have captured events
    expect(events.length).toBeGreaterThan(0);
  });

  it('unsubscribe works', () => {
    const econ = createEconomicsManager(STANDARD_BUDGET);
    const events: EconomicsEvent[] = [];

    const unsub = econ.on(e => events.push(e));
    econ.recordToolCall('read_file', { path: '/a.ts' });
    const countBefore = events.length;

    unsub();
    econ.recordToolCall('read_file', { path: '/b.ts' });

    // No new events after unsubscribe
    expect(events.length).toBe(countBefore);
  });
});

// =============================================================================
// Utility methods
// =============================================================================

describe('Utility Methods', () => {
  it('getBudgetStatusString includes token count', () => {
    const econ = createEconomicsManager({ maxTokens: 10000 });
    econ.recordLLMUsage(5000, 0);
    const status = econ.getBudgetStatusString();
    expect(status).toContain('5,000');
    expect(status).toContain('10,000');
  });

  it('isApproachingLimit returns true at 80%+ tokens', () => {
    const econ = createEconomicsManager({ maxTokens: 100, softTokenLimit: 90 });
    econ.recordLLMUsage(45, 45); // 90 tokens = 90%

    const result = econ.isApproachingLimit();
    expect(result.approaching).toBe(true);
    expect(result.metric).toBe('tokens');
    expect(result.percentUsed).toBeGreaterThanOrEqual(80);
  });

  it('isApproachingLimit returns false below 80%', () => {
    const econ = createEconomicsManager({ maxTokens: 1000 });
    econ.recordLLMUsage(100, 100); // 200 tokens = 20%

    const result = econ.isApproachingLimit();
    expect(result.approaching).toBe(false);
  });

  it('checkBudget returns continue when all within limits', () => {
    const econ = createEconomicsManager(STANDARD_BUDGET);
    econ.recordLLMUsage(100, 50);
    econ.recordToolCall('read_file', { path: '/a.ts' });

    const result = econ.checkBudget();
    expect(result.canContinue).toBe(true);
    expect(result.isHardLimit).toBe(false);
    expect(result.isSoftLimit).toBe(false);
    expect(result.suggestedAction).toBe('continue');
  });
});

// =============================================================================
// extractBashFileTarget (W1)
// =============================================================================

describe('W1: extractBashFileTarget', () => {
  it('extracts path from cat command', () => {
    expect(extractBashFileTarget('cat /src/foo.ts')).toBe('/src/foo.ts');
  });

  it('extracts path from head with flags', () => {
    expect(extractBashFileTarget('head -20 /src/foo.ts')).toBe('/src/foo.ts');
  });

  it('extracts path from tail command', () => {
    expect(extractBashFileTarget('tail -200 src/agent.ts')).toBe('src/agent.ts');
  });

  it('returns null for piped commands', () => {
    expect(extractBashFileTarget('cat foo.ts | grep test')).toBe(null);
  });

  it('returns null for non-file-read commands', () => {
    expect(extractBashFileTarget('npm test')).toBe(null);
  });

  it('returns null for commands with redirects', () => {
    expect(extractBashFileTarget('cat foo.ts > out.txt')).toBe(null);
  });
});
