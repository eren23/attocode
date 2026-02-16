/**
 * Tests for WorkerBudgetTracker (Phase 3.2)
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { WorkerBudgetTracker, createWorkerBudgetTracker } from '../../src/shared/budget-tracker.js';
import { SharedEconomicsState } from '../../src/shared/shared-economics-state.js';

describe('WorkerBudgetTracker', () => {
  let tracker: WorkerBudgetTracker;

  beforeEach(() => {
    tracker = new WorkerBudgetTracker({
      workerId: 'worker-1',
      maxTokens: 10000,
      maxIterations: 10,
      doomLoopThreshold: 3,
    });
  });

  // ─── Token Budget ─────────────────────────────────────────────────────

  describe('token budget', () => {
    it('allows continuation within token budget', () => {
      tracker.recordLLMUsage(3000, 1000);
      const result = tracker.checkBudget();
      expect(result.canContinue).toBe(true);
    });

    it('blocks when token budget exhausted', () => {
      tracker.recordLLMUsage(8000, 3000);
      const result = tracker.checkBudget();
      expect(result.canContinue).toBe(false);
      expect(result.budgetType).toBe('tokens');
      expect(result.reason).toContain('Token budget exhausted');
    });

    it('accumulates tokens across multiple calls', () => {
      tracker.recordLLMUsage(3000, 1000);
      tracker.recordLLMUsage(3000, 1000);
      tracker.recordLLMUsage(3000, 1000); // total = 12000 > 10000
      const result = tracker.checkBudget();
      expect(result.canContinue).toBe(false);
      expect(result.budgetType).toBe('tokens');
    });
  });

  // ─── Iteration Budget ─────────────────────────────────────────────────

  describe('iteration budget', () => {
    it('allows continuation within iteration budget', () => {
      for (let i = 0; i < 5; i++) tracker.recordIteration();
      const result = tracker.checkBudget();
      expect(result.canContinue).toBe(true);
    });

    it('blocks when iteration budget exhausted', () => {
      for (let i = 0; i < 10; i++) tracker.recordIteration();
      const result = tracker.checkBudget();
      expect(result.canContinue).toBe(false);
      expect(result.budgetType).toBe('iterations');
      expect(result.reason).toContain('Iteration budget exhausted');
    });
  });

  // ─── Local Doom Loop Detection ────────────────────────────────────────

  describe('local doom loop detection', () => {
    it('allows diverse tool calls', () => {
      tracker.recordToolCall('read_file', '{"path": "a.ts"}');
      tracker.recordToolCall('read_file', '{"path": "b.ts"}');
      tracker.recordToolCall('read_file', '{"path": "c.ts"}');
      const result = tracker.checkBudget();
      expect(result.canContinue).toBe(true);
    });

    it('detects doom loop with identical consecutive calls', () => {
      tracker.recordToolCall('read_file', '{"path": "a.ts"}');
      tracker.recordToolCall('read_file', '{"path": "a.ts"}');
      tracker.recordToolCall('read_file', '{"path": "a.ts"}');
      const result = tracker.checkBudget();
      expect(result.canContinue).toBe(false);
      expect(result.budgetType).toBe('doom_loop');
      expect(result.reason).toContain('Doom loop detected');
    });

    it('does not trigger doom loop if recent calls differ', () => {
      tracker.recordToolCall('read_file', '{"path": "a.ts"}');
      tracker.recordToolCall('read_file', '{"path": "a.ts"}');
      tracker.recordToolCall('read_file', '{"path": "b.ts"}');
      const result = tracker.checkBudget();
      expect(result.canContinue).toBe(true);
    });

    it('respects custom doom loop threshold', () => {
      const lenient = new WorkerBudgetTracker({
        workerId: 'w2',
        maxTokens: 100000,
        maxIterations: 100,
        doomLoopThreshold: 5,
      });
      for (let i = 0; i < 4; i++) lenient.recordToolCall('bash', '{"cmd": "ls"}');
      expect(lenient.checkBudget().canContinue).toBe(true);
      lenient.recordToolCall('bash', '{"cmd": "ls"}');
      expect(lenient.checkBudget().canContinue).toBe(false);
    });
  });

  // ─── Cross-Worker Doom Loop Detection ─────────────────────────────────

  describe('cross-worker doom loop detection', () => {
    it('detects global doom loop via SharedEconomicsState', () => {
      const shared = new SharedEconomicsState({ globalDoomLoopThreshold: 5 });
      // Use higher local threshold so local doom loop doesn't fire first
      const t1 = new WorkerBudgetTracker({
        workerId: 'w1',
        maxTokens: 100000,
        maxIterations: 100,
        doomLoopThreshold: 10,
      }, shared);
      const t2 = new WorkerBudgetTracker({
        workerId: 'w2',
        maxTokens: 100000,
        maxIterations: 100,
        doomLoopThreshold: 10,
      }, shared);

      // Each worker makes 3 identical calls = 6 total > global threshold of 5
      for (let i = 0; i < 3; i++) {
        t1.recordToolCall('read_file', '{"path": "same.ts"}');
        t2.recordToolCall('read_file', '{"path": "same.ts"}');
      }

      // The last worker to call should detect the global loop
      const result = t2.checkBudget();
      expect(result.canContinue).toBe(false);
      expect(result.budgetType).toBe('doom_loop');
      expect(result.reason).toContain('Global doom loop');
    });

    it('does not trigger global loop below threshold', () => {
      const shared = new SharedEconomicsState({ globalDoomLoopThreshold: 10 });
      const t1 = new WorkerBudgetTracker({
        workerId: 'w1',
        maxTokens: 100000,
        maxIterations: 100,
      }, shared);

      for (let i = 0; i < 2; i++) {
        t1.recordToolCall('read_file', '{"path": "same.ts"}');
      }
      expect(t1.checkBudget().canContinue).toBe(true);
    });
  });

  // ─── Usage & Utilization ──────────────────────────────────────────────

  describe('getUsage', () => {
    it('returns correct usage stats', () => {
      tracker.recordLLMUsage(1000, 500);
      tracker.recordIteration();
      tracker.recordIteration();
      tracker.recordToolCall('bash', '{"cmd": "ls"}');

      const usage = tracker.getUsage();
      expect(usage.inputTokens).toBe(1000);
      expect(usage.outputTokens).toBe(500);
      expect(usage.totalTokens).toBe(1500);
      expect(usage.iterations).toBe(2);
      expect(usage.toolCalls).toBe(1);
    });
  });

  describe('getUtilization', () => {
    it('returns correct percentages', () => {
      tracker.recordLLMUsage(5000, 0); // 50% of 10000
      for (let i = 0; i < 3; i++) tracker.recordIteration(); // 30% of 10

      const util = tracker.getUtilization();
      expect(util.tokenPercent).toBe(50);
      expect(util.iterationPercent).toBe(30);
    });

    it('handles zero max values gracefully', () => {
      const zeroTracker = new WorkerBudgetTracker({
        workerId: 'z',
        maxTokens: 0,
        maxIterations: 0,
      });
      const util = zeroTracker.getUtilization();
      expect(util.tokenPercent).toBe(0);
      expect(util.iterationPercent).toBe(0);
    });
  });

  // ─── Factory Function ─────────────────────────────────────────────────

  describe('createWorkerBudgetTracker', () => {
    it('creates a tracker via factory', () => {
      const t = createWorkerBudgetTracker({
        workerId: 'factory-test',
        maxTokens: 5000,
        maxIterations: 5,
      });
      expect(t).toBeInstanceOf(WorkerBudgetTracker);
      expect(t.checkBudget().canContinue).toBe(true);
    });

    it('accepts optional SharedEconomicsState', () => {
      const shared = new SharedEconomicsState();
      const t = createWorkerBudgetTracker({
        workerId: 'factory-shared',
        maxTokens: 5000,
        maxIterations: 5,
      }, shared);
      expect(t).toBeInstanceOf(WorkerBudgetTracker);
    });
  });

  // ─── Priority: token check before iteration before doom loop ──────────

  describe('budget check priority', () => {
    it('reports token exhaustion even when doom loop present', () => {
      tracker.recordLLMUsage(11000, 0);
      tracker.recordToolCall('bash', '{"cmd": "ls"}');
      tracker.recordToolCall('bash', '{"cmd": "ls"}');
      tracker.recordToolCall('bash', '{"cmd": "ls"}');
      const result = tracker.checkBudget();
      expect(result.budgetType).toBe('tokens');
    });

    it('reports iteration exhaustion before doom loop', () => {
      for (let i = 0; i < 10; i++) tracker.recordIteration();
      tracker.recordToolCall('bash', '{"cmd": "ls"}');
      tracker.recordToolCall('bash', '{"cmd": "ls"}');
      tracker.recordToolCall('bash', '{"cmd": "ls"}');
      const result = tracker.checkBudget();
      expect(result.budgetType).toBe('iterations');
    });
  });

  // ─── Orchestrator-Side Integration (dispatch → complete → utilization) ──

  describe('orchestrator-side lifecycle', () => {
    it('dispatch creates tracker, completion populates it, utilization is correct', () => {
      // Simulate: orchestrator creates a tracker at dispatch time
      const workerTracker = createWorkerBudgetTracker({
        workerId: 'task-42',
        maxTokens: 50_000,
        maxIterations: 15,
        doomLoopThreshold: 3,
      });

      // Worker runs — orchestrator records post-completion usage from SpawnResult
      const totalTokens = 30_000;
      workerTracker.recordLLMUsage(
        Math.floor(totalTokens * 0.6),  // 18000 input
        Math.floor(totalTokens * 0.4),  // 12000 output
      );

      // Check utilization
      const util = workerTracker.getUtilization();
      expect(util.tokenPercent).toBe(60); // 30000 / 50000 = 60%
      expect(util.iterationPercent).toBe(0); // No iterations tracked at orchestrator level
    });

    it('utilization reflects actual token consumption', () => {
      const workerTracker = createWorkerBudgetTracker({
        workerId: 'task-99',
        maxTokens: 100_000,
        maxIterations: 20,
      });

      // Simulate worker used 45000 tokens
      workerTracker.recordLLMUsage(27000, 18000);

      const util = workerTracker.getUtilization();
      expect(util.tokenPercent).toBe(45); // 45000 / 100000 = 45%
    });

    it('zero-token worker shows 0% utilization', () => {
      const workerTracker = createWorkerBudgetTracker({
        workerId: 'task-empty',
        maxTokens: 50_000,
        maxIterations: 10,
      });

      // Worker error with 0 tokens
      workerTracker.recordLLMUsage(0, 0);

      const util = workerTracker.getUtilization();
      expect(util.tokenPercent).toBe(0);
      expect(util.iterationPercent).toBe(0);
    });
  });
});
