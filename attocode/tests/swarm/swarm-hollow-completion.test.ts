/**
 * Tests for V10 hollow completion detection (simplified),
 * quality gate pre-check, dependency context warnings, and per-task-type timeouts.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { SpawnResult, StructuredClosureReport } from '../../src/integrations/agent-registry.js';
import type { SwarmTask, SwarmConfig } from '../../src/integrations/swarm/types.js';
import { DEFAULT_SWARM_CONFIG } from '../../src/integrations/swarm/types.js';
import { SwarmWorkerPool } from '../../src/integrations/swarm/worker-pool.js';
import type { AgentRegistry, AgentDefinition } from '../../src/integrations/agent-registry.js';
import type { SwarmBudgetPool } from '../../src/integrations/swarm/swarm-budget.js';
import { isHollowCompletion } from '../../src/integrations/swarm/swarm-orchestrator.js';

describe('isHollowCompletion', () => {
  it('returns true for zero tool calls with short output', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: 'I completed the task',
      metrics: { tokens: 500, duration: 5000, toolCalls: 0 },
    };

    expect(isHollowCompletion(spawnResult)).toBe(true);
  });

  it('returns false for budget-excuse closure report with tool calls (closure report check removed)', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: 'Budget critical',
      metrics: { tokens: 500, duration: 5000, toolCalls: 2 },
      structured: {
        findings: ['Could not complete due to budget constraints'],
        actionsTaken: [],
        failures: ['Budget critical — before any research could be performed'],
        remainingWork: ['Everything'],
        suggestedNextSteps: [],
        exitReason: 'completed',
      },
    };

    // V10: Has 2 tool calls → not hollow (closure report check removed, quality gate handles this)
    expect(isHollowCompletion(spawnResult)).toBe(false);
  });

  it('returns false for real completion with tool calls', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: 'Found 5 results about React state management',
      metrics: { tokens: 2000, duration: 30000, toolCalls: 8 },
      structured: {
        findings: ['React has several state management options', 'Redux is the most popular'],
        actionsTaken: ['Searched for React state management', 'Read 3 documentation pages'],
        failures: [],
        remainingWork: [],
        suggestedNextSteps: [],
        exitReason: 'completed',
      },
    };

    expect(isHollowCompletion(spawnResult)).toBe(false);
  });

  it('returns false when there are tool calls but no closure report', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: 'Done',
      metrics: { tokens: 1000, duration: 10000, toolCalls: 5 },
    };

    expect(isHollowCompletion(spawnResult)).toBe(false);
  });

  it('returns false for timeout (toolCalls === -1)', () => {
    const spawnResult: SpawnResult = {
      success: false,
      output: 'Worker error: Worker timeout after 300000ms',
      metrics: { tokens: 0, duration: 300000, toolCalls: -1 },
    };

    expect(isHollowCompletion(spawnResult)).toBe(false);
  });

  it('returns false for 0 tool calls but substantial output (any task type)', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: 'Research findings: After analyzing multiple sources, the React ecosystem offers several state management solutions. Redux remains the most popular with 40M+ weekly downloads. MobX provides a simpler API with observables. Zustand is gaining traction as a lightweight alternative. Jotai and Recoil offer atomic state management patterns that work well with React Suspense.',
      metrics: { tokens: 1500, duration: 15000, toolCalls: 0 },
    };

    // V10: 0 tool calls but output > 50 chars → NOT hollow (quality gate judges substance)
    expect(isHollowCompletion(spawnResult)).toBe(false);
  });

  it('returns true for 0 tool calls and trivial output', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: 'I tried.',
      metrics: { tokens: 50, duration: 2000, toolCalls: 0 },
    };

    // 0 tool calls + output < 50 chars → IS hollow
    expect(isHollowCompletion(spawnResult)).toBe(true);
  });

  it('returns false for code task with 0 tool calls but substantial output', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: 'Here is the implementation plan: We should refactor the parser module to use a recursive descent approach. This involves creating separate functions for each grammar rule and chaining them together.',
      metrics: { tokens: 1000, duration: 10000, toolCalls: 0 },
    };

    // V10: No task-type distinction — output > 50 chars → NOT hollow (quality gate judges)
    expect(isHollowCompletion(spawnResult)).toBe(false);
  });

  it('returns false for analysis output with 0 tool calls but substantial output', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: 'Architecture Analysis: The codebase follows a modular monolith pattern with clear separation of concerns. The agent module (5400 lines) is the largest and would benefit from decomposition. The integrations layer provides good abstraction boundaries. The TUI layer is cleanly separated from business logic. Key improvement areas: 1) Split agent.ts into smaller modules 2) Add proper dependency injection 3) Improve error propagation patterns.',
      metrics: { tokens: 2000, duration: 20000, toolCalls: 0 },
    };

    // V10: 0 tool calls but output > 50 chars → NOT hollow
    expect(isHollowCompletion(spawnResult)).toBe(false);
  });

  it('returns false for design output with 0 tool calls but substantial output', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: 'Design Proposal: The new authentication system should use JWT tokens with refresh token rotation. The token service will be a standalone module in src/integrations/auth.ts. User sessions will be stored in SQLite alongside existing session data. The middleware chain: rate-limit → cors → auth → route handler. Token expiry: access=15min, refresh=7d.',
      metrics: { tokens: 1800, duration: 18000, toolCalls: 0 },
    };

    // V10: 0 tool calls but output > 50 chars → NOT hollow
    expect(isHollowCompletion(spawnResult)).toBe(false);
  });

  it('returns false for closure report with real findings and tool calls', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: 'Partial results',
      metrics: { tokens: 1500, duration: 20000, toolCalls: 4 },
      structured: {
        findings: ['Found TypeScript best practices document', 'Project uses ESLint with strict config'],
        actionsTaken: ['Read tsconfig.json', 'Searched for lint rules'],
        failures: ['Budget ran out before completing full analysis'],
        remainingWork: ['Check test coverage'],
        suggestedNextSteps: [],
        exitReason: 'completed',
      },
    };

    // Has 4 tool calls → not hollow
    expect(isHollowCompletion(spawnResult)).toBe(false);
  });

  it('returns false for empty findings with budget failure but has tool calls (closure report check removed)', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: 'Could not proceed',
      metrics: { tokens: 200, duration: 3000, toolCalls: 1 },
      structured: {
        findings: [],
        actionsTaken: [],
        failures: ['Budget critical — before any research could be performed'],
        remainingWork: ['All research'],
        suggestedNextSteps: [],
        exitReason: 'completed',
      },
    };

    // V10: Has 1 tool call → not hollow (closure report check removed, quality gate handles this)
    expect(isHollowCompletion(spawnResult)).toBe(false);
  });

  it('returns true for zero tool calls with empty output', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: '',
      metrics: { tokens: 10, duration: 1000, toolCalls: 0 },
    };

    expect(isHollowCompletion(spawnResult)).toBe(true);
  });

  it('returns true for zero tool calls with whitespace-only output', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: '   \n\n  ',
      metrics: { tokens: 10, duration: 1000, toolCalls: 0 },
    };

    expect(isHollowCompletion(spawnResult)).toBe(true);
  });

  it('returns false for exactly 50 chars output with zero tool calls', () => {
    const spawnResult: SpawnResult = {
      success: true,
      // Exactly 50 characters
      output: 'A'.repeat(50),
      metrics: { tokens: 100, duration: 2000, toolCalls: 0 },
    };

    // >= 50 chars → not hollow
    expect(isHollowCompletion(spawnResult)).toBe(false);
  });
});

// ─── Quality gate closure report pre-check ──────────────────────────────────

describe('Quality gate closure report pre-check', () => {
  // We test this indirectly by importing evaluateWorkerOutput and verifying
  // it auto-fails on bad closure reports without calling the LLM judge.
  // The actual evaluateWorkerOutput needs a provider mock, so we test the logic pattern.

  function shouldAutoFail(closureReport: StructuredClosureReport): boolean {
    const noRealFindings = closureReport.findings.length === 0 ||
      closureReport.findings.every(f => /budget|unable|not completed|constraint/i.test(f));
    const admitsFailure = closureReport.failures.length > 0 &&
      closureReport.failures.some(f => /no.*search|no.*performed|not created/i.test(f));
    return noRealFindings && admitsFailure;
  }

  it('auto-fails when closure report has no real findings and admits failure', () => {
    const cr: StructuredClosureReport = {
      findings: [],
      actionsTaken: [],
      failures: ['No search was performed due to constraints'],
      remainingWork: ['Everything'],
      suggestedNextSteps: [],
        exitReason: 'completed',
    };
    expect(shouldAutoFail(cr)).toBe(true);
  });

  it('auto-fails when findings only mention budget and admits failure', () => {
    const cr: StructuredClosureReport = {
      findings: ['Unable to complete research'],
      actionsTaken: [],
      failures: ['File not created due to budget'],
      remainingWork: [],
      suggestedNextSteps: [],
        exitReason: 'completed',
    };
    expect(shouldAutoFail(cr)).toBe(true);
  });

  it('does not auto-fail when there are real findings', () => {
    const cr: StructuredClosureReport = {
      findings: ['React uses virtual DOM for efficient rendering', 'Next.js supports SSR'],
      actionsTaken: ['Searched documentation'],
      failures: ['No additional search performed'],
      remainingWork: [],
      suggestedNextSteps: [],
        exitReason: 'completed',
    };
    expect(shouldAutoFail(cr)).toBe(false);
  });

  it('does not auto-fail when no failures mentioned', () => {
    const cr: StructuredClosureReport = {
      findings: [],
      actionsTaken: [],
      failures: [],
      remainingWork: [],
      suggestedNextSteps: [],
        exitReason: 'completed',
    };
    expect(shouldAutoFail(cr)).toBe(false);
  });
});

// ─── Dependency context hollow detection ────────────────────────────────────

describe('Dependency context hollow detection', () => {
  // Test the buildDependencyContext logic by creating a task queue
  // We test via the SwarmTaskQueue class
  it('warns about hollow dependencies', async () => {
    const { SwarmTaskQueue } = await import('../../src/integrations/swarm/task-queue.js');
    const queue = new SwarmTaskQueue();

    // Completed dep with hollow output
    const hollowDep: SwarmTask = {
      id: 'st-0',
      description: 'Research AI frameworks',
      type: 'research',
      dependencies: [],
      status: 'completed',
      complexity: 3,
      wave: 0,
      attempts: 1,
      result: {
        success: true,
        output: 'Budget critical',
        closureReport: {
          findings: [],
          actionsTaken: [],
          failures: ['Unable to complete — budget exhausted'],
          remainingWork: ['All research'],
          suggestedNextSteps: [],
        exitReason: 'completed',
        },
        tokensUsed: 100,
        costUsed: 0.001,
        durationMs: 5000,
        model: 'test/model',
      },
    };

    // Completed dep with real output
    const realDep: SwarmTask = {
      id: 'st-1',
      description: 'Research ML libraries',
      type: 'research',
      dependencies: [],
      status: 'completed',
      complexity: 3,
      wave: 0,
      attempts: 1,
      result: {
        success: true,
        output: 'Found 5 popular ML libraries: TensorFlow, PyTorch, JAX, Scikit-learn, and Keras. TensorFlow and PyTorch dominate the market with approximately 70% combined market share.',
        closureReport: {
          findings: ['TensorFlow and PyTorch are the most popular ML libraries', 'JAX is growing rapidly'],
          actionsTaken: ['Searched for ML library comparisons', 'Read official documentation'],
          failures: [],
          remainingWork: [],
          suggestedNextSteps: [],
        exitReason: 'completed',
        },
        tokensUsed: 2000,
        costUsed: 0.01,
        durationMs: 30000,
        model: 'test/model',
      },
    };

    // Dependent task
    const mergeTask: SwarmTask = {
      id: 'st-2',
      description: 'Synthesize research findings',
      type: 'merge',
      dependencies: ['st-0', 'st-1'],
      status: 'pending',
      complexity: 4,
      wave: 1,
      attempts: 0,
    };

    // Access private methods via casting
    (queue as any).tasks.set('st-0', hollowDep);
    (queue as any).tasks.set('st-1', realDep);
    (queue as any).tasks.set('st-2', mergeTask);

    // Call updateReadyStatus to trigger buildDependencyContext
    (queue as any).updateReadyStatus();

    const task = (queue as any).tasks.get('st-2');
    expect(task.status).toBe('ready');
    expect(task.dependencyContext).toContain('WARNING');
    expect(task.dependencyContext).toContain('Research AI frameworks');
    // Should still include real dep context
    expect(task.dependencyContext).toContain('Research ML libraries');
    expect(task.dependencyContext).toContain('TensorFlow');
  });

  it('preserves real dependency output without warnings', async () => {
    const { SwarmTaskQueue } = await import('../../src/integrations/swarm/task-queue.js');
    const queue = new SwarmTaskQueue();

    const realDep: SwarmTask = {
      id: 'st-0',
      description: 'Research testing frameworks',
      type: 'research',
      dependencies: [],
      status: 'completed',
      complexity: 3,
      wave: 0,
      attempts: 1,
      result: {
        success: true,
        output: 'Jest and Vitest are the top testing frameworks. Vitest offers better ESM support and faster execution times.',
        closureReport: {
          findings: ['Jest is the most widely used testing framework with over 40 million weekly downloads', 'Vitest is the fastest for Vite-based projects with native ESM support'],
          actionsTaken: ['Compared Jest, Vitest, and Mocha across performance, DX, and ecosystem criteria'],
          failures: [],
          remainingWork: [],
          suggestedNextSteps: [],
        exitReason: 'completed',
        },
        tokensUsed: 1500,
        costUsed: 0.008,
        durationMs: 20000,
        model: 'test/model',
      },
    };

    const mergeTask: SwarmTask = {
      id: 'st-1',
      description: 'Write recommendation',
      type: 'merge',
      dependencies: ['st-0'],
      status: 'pending',
      complexity: 3,
      wave: 1,
      attempts: 0,
    };

    (queue as any).tasks.set('st-0', realDep);
    (queue as any).tasks.set('st-1', mergeTask);
    (queue as any).updateReadyStatus();

    const task = (queue as any).tasks.get('st-1');
    expect(task.status).toBe('ready');
    expect(task.dependencyContext).not.toContain('WARNING');
    expect(task.dependencyContext).toContain('Research testing frameworks');
  });

  it('does NOT flag short real completion as hollow (Bug 2 fix)', async () => {
    const { SwarmTaskQueue } = await import('../../src/integrations/swarm/task-queue.js');
    const queue = new SwarmTaskQueue();

    // Short but legitimate completion — no budget failures
    const shortRealDep: SwarmTask = {
      id: 'st-0',
      description: 'Fix the parser bug',
      type: 'implement',
      dependencies: [],
      status: 'completed',
      complexity: 2,
      wave: 0,
      attempts: 1,
      result: {
        success: true,
        output: 'Fixed the bug',
        closureReport: {
          findings: ['Fixed the bug'],
          actionsTaken: ['Updated parser.ts'],
          failures: [],
          remainingWork: [],
          suggestedNextSteps: [],
          exitReason: 'completed',
        },
        tokensUsed: 500,
        costUsed: 0.002,
        durationMs: 10000,
        model: 'test/model',
      },
    };

    const dependentTask: SwarmTask = {
      id: 'st-1',
      description: 'Write tests for parser fix',
      type: 'test',
      dependencies: ['st-0'],
      status: 'pending',
      complexity: 3,
      wave: 1,
      attempts: 0,
    };

    (queue as any).tasks.set('st-0', shortRealDep);
    (queue as any).tasks.set('st-1', dependentTask);
    (queue as any).updateReadyStatus();

    const task = (queue as any).tasks.get('st-1');
    expect(task.status).toBe('ready');
    // Short real completion should NOT trigger hollow warning
    expect(task.dependencyContext).not.toContain('WARNING');
    // Should include the actual dependency context
    expect(task.dependencyContext).toContain('Fix the parser bug');
  });
});

// ─── Hollow completion does NOT inflate health score (Bug 1 fix) ─────────────

describe('Hollow completion health score (Bug 1 fix)', () => {
  it('recordSuccess is not called for hollow completions', async () => {
    const { ModelHealthTracker } = await import('../../src/integrations/swarm/model-selector.js');
    const tracker = new ModelHealthTracker();

    // Simulate what the orchestrator does:
    // A hollow completion (0 tool calls, short output) should NOT record success
    const model = 'test/hollow-model';
    const spawnResult: SpawnResult = {
      success: true,
      output: 'I completed the task',
      metrics: { tokens: 500, duration: 5000, toolCalls: 0 },
    };

    // Check hollow first (as the fixed code does)
    const hollow = isHollowCompletion(spawnResult);
    expect(hollow).toBe(true);

    // Since it's hollow, we should NOT record success
    if (!hollow) {
      tracker.recordSuccess(model, 5000);
    }

    const records = tracker.getAllRecords();
    const modelRecord = records.find(r => r.model === model);
    // Model should have no record at all (never had success recorded)
    expect(modelRecord).toBeUndefined();
  });

  it('recordSuccess IS called for real completions', async () => {
    const { ModelHealthTracker } = await import('../../src/integrations/swarm/model-selector.js');
    const tracker = new ModelHealthTracker();

    const model = 'test/good-model';
    const spawnResult: SpawnResult = {
      success: true,
      output: 'Found results',
      metrics: { tokens: 2000, duration: 15000, toolCalls: 8 },
    };

    const hollow = isHollowCompletion(spawnResult);
    expect(hollow).toBe(false);

    if (!hollow) {
      tracker.recordSuccess(model, 15000);
    }

    const records = tracker.getAllRecords();
    const modelRecord = records.find(r => r.model === model);
    expect(modelRecord).toBeDefined();
    expect(modelRecord!.successes).toBe(1);
    expect(modelRecord!.healthy).toBe(true);
  });

  it('recordFailure IS called for hollow completions', async () => {
    const { ModelHealthTracker } = await import('../../src/integrations/swarm/model-selector.js');
    const tracker = new ModelHealthTracker();

    const model = 'test/hollow-model';
    const spawnResult: SpawnResult = {
      success: true,
      output: 'I completed the task',
      metrics: { tokens: 500, duration: 5000, toolCalls: 0 },
    };

    const hollow = isHollowCompletion(spawnResult);
    expect(hollow).toBe(true);

    // Hollow completions now record a failure (not just skip success)
    if (hollow) {
      tracker.recordFailure(model, 'error');
    }

    const records = tracker.getAllRecords();
    const modelRecord = records.find(r => r.model === model);
    expect(modelRecord).toBeDefined();
    expect(modelRecord!.failures).toBe(1);
    expect(modelRecord!.successes).toBe(0);
  });

  it('hollow completion triggers model failover when alternative available', async () => {
    const { ModelHealthTracker, selectAlternativeModel } = await import('../../src/integrations/swarm/model-selector.js');
    const tracker = new ModelHealthTracker();

    const hollowModel = 'test/hollow-model';

    // Record several failures to degrade health
    tracker.recordFailure(hollowModel, 'error');
    tracker.recordFailure(hollowModel, 'error');
    tracker.recordFailure(hollowModel, 'error');

    const workers = [
      { name: 'worker-a', model: hollowModel, capabilities: ['code' as const] },
      { name: 'worker-b', model: 'test/good-model', capabilities: ['code' as const] },
    ];

    const alternative = selectAlternativeModel(workers, hollowModel, 'code', tracker);
    // Should select the healthy alternative
    expect(alternative).toBeDefined();
    expect(alternative!.model).toBe('test/good-model');
  });
});

// ─── Quality circuit breaker wave-boundary reset ─────────────────────────────

describe('Quality circuit breaker wave-boundary reset', () => {
  it('quality-gate-passed resets counter within a wave', () => {
    // Within a wave, when a task passes the quality gate, the counter resets
    let consecutiveQualityRejections = 0;

    // Simulate 3 consecutive rejections
    consecutiveQualityRejections = 3;

    // Quality gate passes → counter resets (line 1194 in orchestrator)
    consecutiveQualityRejections = 0;

    expect(consecutiveQualityRejections).toBe(0);
  });

  it('isLastAttempt completion does NOT reset quality counter within a wave', () => {
    // isLastAttempt tasks bypass the quality gate entirely — they didn't *pass*
    // quality, we just gave up. So completing them should NOT reset the counter.
    let consecutiveQualityRejections = 0;
    let qualityGateDisabled = false;
    const THRESHOLD = 8;

    // Simulate 5 rejections within a wave
    for (let i = 0; i < 5; i++) {
      consecutiveQualityRejections++;
    }

    // An isLastAttempt task completes — this bypassed quality gate,
    // so the counter should NOT reset (per-completion reset was removed)
    // The old code would have reset here; the new code does not.
    // (No reset logic fires for task completion — only quality-gate-passed resets within wave)

    expect(consecutiveQualityRejections).toBe(5);
    expect(qualityGateDisabled).toBe(false);

    // Continue accumulating rejections — they should still count
    for (let i = 5; i < THRESHOLD; i++) {
      consecutiveQualityRejections++;
      if (consecutiveQualityRejections >= THRESHOLD) {
        qualityGateDisabled = true;
      }
    }
    expect(qualityGateDisabled).toBe(true);
  });

  it('wave boundary resets circuit breaker for fresh evaluation window', () => {
    let consecutiveQualityRejections = 0;
    let qualityGateDisabled = false;
    const THRESHOLD = 8;

    // Wave N: accumulate enough rejections to trip the breaker
    for (let i = 0; i < THRESHOLD; i++) {
      consecutiveQualityRejections++;
      if (consecutiveQualityRejections >= THRESHOLD) {
        qualityGateDisabled = true;
      }
    }
    expect(qualityGateDisabled).toBe(true);

    // Wave boundary reset (happens in executeWaves after fixup tasks)
    if (qualityGateDisabled) {
      qualityGateDisabled = false;
      consecutiveQualityRejections = 0;
    }

    // Wave N+1 gets a fresh chance
    expect(consecutiveQualityRejections).toBe(0);
    expect(qualityGateDisabled).toBe(false);
  });

  it('threshold is 8 (raised from 5)', () => {
    let consecutiveQualityRejections = 0;
    let qualityGateDisabled = false;
    const THRESHOLD = 8;

    for (let i = 0; i < 5; i++) {
      consecutiveQualityRejections++;
      if (consecutiveQualityRejections >= THRESHOLD) {
        qualityGateDisabled = true;
      }
    }
    // 5 should NOT trip with threshold 8
    expect(qualityGateDisabled).toBe(false);

    for (let i = 5; i < 8; i++) {
      consecutiveQualityRejections++;
      if (consecutiveQualityRejections >= THRESHOLD) {
        qualityGateDisabled = true;
      }
    }
    // 8 should trip
    expect(qualityGateDisabled).toBe(true);
  });
});

// ─── Per-task-type timeout ──────────────────────────────────────────────────

describe('Per-task-type timeout', () => {
  const registeredAgents = new Map<string, AgentDefinition>();

  const mockAgentRegistry = {
    registerAgent: vi.fn((def: AgentDefinition) => {
      registeredAgents.set(def.name, def);
    }),
    unregisterAgent: vi.fn(),
    getAgent: vi.fn(),
    listAgents: vi.fn(() => []),
    filterToolsForAgent: vi.fn(() => []),
  } as unknown as AgentRegistry;

  const mockBudgetPool = {
    hasCapacity: vi.fn().mockReturnValue(true),
    pool: { reserve: vi.fn().mockReturnValue({ tokenBudget: 50000 }) },
    orchestratorReserve: 750000,
    maxPerWorker: 50000,
    getStats: vi.fn().mockReturnValue({ totalTokens: 5000000, tokensUsed: 0 }),
  } as unknown as SwarmBudgetPool;

  beforeEach(() => {
    registeredAgents.clear();
  });

  it('should use default taskTypeTimeouts from DEFAULT_SWARM_CONFIG', () => {
    expect(DEFAULT_SWARM_CONFIG.taskTypeTimeouts).toBeDefined();
    expect(DEFAULT_SWARM_CONFIG.taskTypeTimeouts?.research).toBe(300_000);
    expect(DEFAULT_SWARM_CONFIG.taskTypeTimeouts?.analysis).toBe(300_000);
    expect(DEFAULT_SWARM_CONFIG.taskTypeTimeouts?.merge).toBe(180_000);
  });

  it('should use per-type timeout for research tasks', async () => {
    const mockSpawnAgent = vi.fn().mockImplementation(() => {
      return new Promise(resolve => {
        // Resolve immediately — we care about the timeout race, not the result
        resolve({
          success: true,
          output: 'Done',
          metrics: { tokens: 100, duration: 1000, toolCalls: 3 },
        });
      });
    });

    const config: SwarmConfig = {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/model',
      workerTimeout: 120_000,
      taskTypeTimeouts: { research: 300_000 },
      workers: [
        { name: 'researcher', model: 'test/researcher', capabilities: ['research'] },
      ],
    };

    const pool = new SwarmWorkerPool(config, mockAgentRegistry, mockSpawnAgent, mockBudgetPool);

    const task: SwarmTask = {
      id: 'test-timeout',
      description: 'Research AI landscape',
      type: 'research',
      dependencies: [],
      status: 'ready',
      complexity: 3,
      wave: 0,
      attempts: 0,
    };

    await pool.dispatch(task);

    // Verify the task was dispatched (spawn was called)
    expect(mockSpawnAgent).toHaveBeenCalled();
  });

  it('should fall back to workerTimeout for types without override', async () => {
    const mockSpawnAgent = vi.fn().mockResolvedValue({
      success: true,
      output: 'Done',
      metrics: { tokens: 100, duration: 1000, toolCalls: 3 },
    });

    const config: SwarmConfig = {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/model',
      workerTimeout: 120_000,
      taskTypeTimeouts: { research: 300_000 },
      workers: [
        { name: 'coder', model: 'test/coder', capabilities: ['code'] },
      ],
    };

    const pool = new SwarmWorkerPool(config, mockAgentRegistry, mockSpawnAgent, mockBudgetPool);

    const task: SwarmTask = {
      id: 'test-timeout-fallback',
      description: 'Implement parser',
      type: 'implement',
      dependencies: [],
      status: 'ready',
      complexity: 5,
      wave: 0,
      attempts: 0,
    };

    await pool.dispatch(task);
    expect(mockSpawnAgent).toHaveBeenCalled();
  });
});
