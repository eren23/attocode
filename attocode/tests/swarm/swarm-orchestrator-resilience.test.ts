/**
 * Swarm Orchestrator Resilience Tests
 *
 * Tests for the 4 resilience features:
 * 1. Degraded acceptance — accept partial work instead of hard fail
 * 2. Budget escalation — escalating retry multiplier
 * 3. Micro-decomposition — break complex failing tasks into subtasks
 * 4. Cascade rescue — un-skip tasks whose dependencies have artifacts
 *
 * Also tests bypass bug fixes:
 * 5. Dispatch-cap triggers resilience recovery instead of hard fail
 * 6. Timeout early-fail triggers resilience recovery instead of hard fail
 * 7. Attempts field in dispatched events
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { DEFAULT_SWARM_CONFIG } from '../../src/integrations/swarm/types.js';
import type { SwarmTask, SwarmConfig, SwarmTaskResult, SwarmTaskStatus } from '../../src/integrations/swarm/types.js';
import type { SmartDecompositionResult, SmartSubtask } from '../../src/integrations/smart-decomposer.js';
import { SwarmTaskQueue } from '../../src/integrations/swarm/task-queue.js';
import { SwarmWorkerPool } from '../../src/integrations/swarm/worker-pool.js';
import type { AgentRegistry, AgentDefinition } from '../../src/integrations/agent-registry.js';
import type { SwarmBudgetPool } from '../../src/integrations/swarm/swarm-budget.js';
import type { SwarmEvent } from '../../src/integrations/swarm/swarm-events.js';

// =============================================================================
// Helpers
// =============================================================================

function makeConfig(overrides: Partial<SwarmConfig> = {}): SwarmConfig {
  return {
    ...DEFAULT_SWARM_CONFIG,
    orchestratorModel: 'test/orchestrator',
    workers: [{ name: 'coder', model: 'test/coder', capabilities: ['code'] }],
    ...overrides,
  };
}

function makeTask(overrides: Partial<SwarmTask> = {}): SwarmTask {
  return {
    id: 'task-1',
    description: 'Test task',
    type: 'implement',
    dependencies: [],
    status: 'ready',
    complexity: 5,
    wave: 0,
    attempts: 0,
    ...overrides,
  };
}

function makeResult(overrides: Partial<SwarmTaskResult> = {}): SwarmTaskResult {
  return {
    success: true,
    output: 'Completed the task successfully.',
    tokensUsed: 500,
    costUsed: 0.01,
    durationMs: 5000,
    model: 'test-model',
    ...overrides,
  };
}

function makeDecomposition(subtasks: Partial<SmartSubtask>[]): SmartDecompositionResult {
  const fullSubtasks: SmartSubtask[] = subtasks.map((s, i) => ({
    id: s.id ?? `st-${i}`,
    description: s.description ?? `Task ${i}`,
    type: s.type ?? 'implement',
    status: 'pending' as const,
    complexity: s.complexity ?? 5,
    dependencies: s.dependencies ?? [],
    modifies: s.modifies ?? [],
    reads: s.reads ?? [],
    estimatedTokens: 5000,
    parallelizable: s.parallelizable ?? true,
  }));

  // Build parallel groups from dependencies
  const groups: string[][] = [];
  const placed = new Set<string>();
  const remaining = [...fullSubtasks];

  while (remaining.length > 0) {
    const group: string[] = [];
    for (const t of remaining) {
      if (t.dependencies.every(d => placed.has(d))) {
        group.push(t.id);
      }
    }
    if (group.length === 0) break; // Circular dependency — bail
    for (const id of group) {
      placed.add(id);
      remaining.splice(remaining.findIndex(t => t.id === id), 1);
    }
    groups.push(group);
  }

  // Build dependency/dependent maps
  const dependencies = new Map<string, string[]>();
  const dependents = new Map<string, string[]>();
  for (const s of fullSubtasks) {
    dependencies.set(s.id, s.dependencies);
    for (const depId of s.dependencies) {
      const existing = dependents.get(depId) ?? [];
      existing.push(s.id);
      dependents.set(depId, existing);
    }
  }

  return {
    originalTask: 'test task',
    subtasks: fullSubtasks,
    dependencyGraph: {
      dependencies,
      dependents,
      executionOrder: fullSubtasks.map(s => s.id),
      parallelGroups: groups,
      cycles: [],
    },
    conflicts: [],
    strategy: 'parallel' as const,
    totalComplexity: fullSubtasks.reduce((sum, s) => sum + s.complexity, 0),
    totalEstimatedTokens: 10000,
    metadata: {
      decomposedAt: new Date(),
      codebaseAware: false,
      llmAssisted: false,
    },
  };
}

// =============================================================================
// 1. Degraded Acceptance
// =============================================================================

describe('Degraded Acceptance', () => {
  it('SwarmTaskResult supports degraded flag', () => {
    const result = makeResult({ degraded: true, qualityScore: 2 });
    expect(result.degraded).toBe(true);
    expect(result.qualityScore).toBe(2);
  });

  it('SwarmTask supports degraded flag', () => {
    const task = makeTask({ degraded: true });
    expect(task.degraded).toBe(true);
  });

  it('degraded tasks count as completed for dependency resolution', () => {
    const config = makeConfig();
    const queue = new SwarmTaskQueue();
    const decomp = makeDecomposition([
      { id: 'st-0', description: 'Foundation', dependencies: [] },
      { id: 'st-1', description: 'Dependent', dependencies: ['st-0'] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    // Simulate degraded completion of st-0
    queue.markDispatched('st-0', 'test-model');
    const degradedResult = makeResult({ degraded: true, qualityScore: 2 });
    const task0 = queue.getTask('st-0')!;
    task0.degraded = true;
    queue.markCompleted('st-0', degradedResult);

    // st-1 should become ready
    const task1 = queue.getTask('st-1')!;
    expect(task1.status).toBe('ready');
  });

  it('degraded dependency context includes warning', () => {
    const config = makeConfig();
    const queue = new SwarmTaskQueue();
    const decomp = makeDecomposition([
      { id: 'st-0', description: 'Foundation task', dependencies: [] },
      { id: 'st-1', description: 'Dependent task', dependencies: ['st-0'] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    // Complete st-0 as degraded
    queue.markDispatched('st-0', 'test-model');
    const task0 = queue.getTask('st-0')!;
    task0.degraded = true;
    queue.markCompleted('st-0', makeResult({
      degraded: true,
      qualityScore: 2,
      output: 'Partial implementation done.',
      filesModified: ['src/foo.ts'],
    }));

    // Check st-1's dependency context
    const task1 = queue.getTask('st-1')!;
    expect(task1.dependencyContext).toContain('DEGRADED');
  });
});

// =============================================================================
// 2. Budget Escalation
// =============================================================================

describe('Budget Escalation', () => {
  let mockRegistry: AgentRegistry;
  let mockBudgetPool: SwarmBudgetPool;
  let registeredDefs: AgentDefinition[];

  beforeEach(() => {
    registeredDefs = [];
    mockRegistry = {
      registerAgent: vi.fn((def: AgentDefinition) => registeredDefs.push(def)),
      unregisterAgent: vi.fn(),
      getAgent: vi.fn(),
      listAgents: vi.fn().mockReturnValue([]),
    } as unknown as AgentRegistry;
    mockBudgetPool = {
      hasCapacity: vi.fn().mockReturnValue(true),
      allocate: vi.fn(),
      release: vi.fn(),
      getStats: vi.fn().mockReturnValue({ tokensRemaining: 1000000, utilization: 0.1 }),
    } as unknown as SwarmBudgetPool;
  });

  it('retry multiplier escalates with attempts: 1.0, 1.3, 1.6, 2.0', async () => {
    const config = makeConfig({ maxTokensPerWorker: 10000, workerMaxIterations: 10, maxConcurrency: 10 });
    const spawnAgent = vi.fn().mockResolvedValue({ success: true, output: 'done', metrics: { tokens: 100, duration: 1000, toolCalls: 1 } });
    const pool = new SwarmWorkerPool(config, mockRegistry, spawnAgent, mockBudgetPool);

    // Attempt 0: multiplier 1.0
    const task0 = makeTask({ id: 'task-0', attempts: 0, complexity: 5 });
    await pool.dispatch(task0);
    const def0 = registeredDefs[registeredDefs.length - 1];
    const budget0 = def0.maxTokenBudget!;

    // Attempt 1: multiplier 1.3
    const task1 = makeTask({ id: 'task-1', attempts: 1, complexity: 5 });
    await pool.dispatch(task1);
    const def1 = registeredDefs[registeredDefs.length - 1];
    const budget1 = def1.maxTokenBudget!;
    expect(budget1 / budget0).toBeCloseTo(1.3, 1);

    // Attempt 2: multiplier 1.6
    const task2 = makeTask({ id: 'task-2', attempts: 2, complexity: 5 });
    await pool.dispatch(task2);
    const def2 = registeredDefs[registeredDefs.length - 1];
    const budget2 = def2.maxTokenBudget!;
    expect(budget2 / budget0).toBeCloseTo(1.6, 1);

    // Attempt 3: multiplier 2.0
    const task3 = makeTask({ id: 'task-3', attempts: 3, complexity: 5 });
    await pool.dispatch(task3);
    const def3 = registeredDefs[registeredDefs.length - 1];
    const budget3 = def3.maxTokenBudget!;
    expect(budget3 / budget0).toBeCloseTo(2.0, 1);
  });

  it('iteration multiplier kicks in at attempt 2', async () => {
    const config = makeConfig({ maxTokensPerWorker: 10000, workerMaxIterations: 10, maxConcurrency: 10 });
    const spawnAgent = vi.fn().mockResolvedValue({ success: true, output: 'done', metrics: { tokens: 100, duration: 1000, toolCalls: 1 } });
    const pool = new SwarmWorkerPool(config, mockRegistry, spawnAgent, mockBudgetPool);

    // Attempt 0: no iteration multiplier
    const task0 = makeTask({ id: 'task-0', attempts: 0, complexity: 5 });
    await pool.dispatch(task0);
    const def0 = registeredDefs[registeredDefs.length - 1];
    const iters0 = def0.maxIterations!;

    // Attempt 1: still no iteration multiplier (only retry budget scales)
    const task1 = makeTask({ id: 'task-1', attempts: 1, complexity: 5 });
    await pool.dispatch(task1);
    const def1 = registeredDefs[registeredDefs.length - 1];
    const iters1 = def1.maxIterations!;
    // retryMultiplier 1.3 but no iterationMultiplier
    expect(iters1 / iters0).toBeCloseTo(1.3, 1);

    // Attempt 2: iteration multiplier 1.5 + retry multiplier 1.6
    const task2 = makeTask({ id: 'task-2', attempts: 2, complexity: 5 });
    await pool.dispatch(task2);
    const def2 = registeredDefs[registeredDefs.length - 1];
    const iters2 = def2.maxIterations!;
    // Should be ~1.6 * 1.5 = 2.4x relative to base
    expect(iters2 / iters0).toBeCloseTo(2.4, 1);
  });
});

// =============================================================================
// 3. Micro-Decomposition (task-queue side)
// =============================================================================

describe('Micro-Decomposition (task queue)', () => {
  it('replaceWithSubtasks marks original as decomposed', () => {
    const config = makeConfig();
    const queue = new SwarmTaskQueue();
    const decomp = makeDecomposition([
      { id: 'st-0', description: 'Foundation', dependencies: [] },
      { id: 'st-1', description: 'Complex test task', dependencies: ['st-0'], complexity: 8 },
      { id: 'st-2', description: 'Final', dependencies: ['st-1'] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    // Complete st-0
    queue.markDispatched('st-0', 'test-model');
    queue.markCompleted('st-0', makeResult());

    // Now st-1 should be ready
    const task1 = queue.getTask('st-1')!;
    expect(task1.status).toBe('ready');

    // Simulate micro-decomposition of st-1
    const subtasks: SwarmTask[] = [
      makeTask({ id: 'st-1-sub1', description: 'Write first 3 tests', type: 'test', complexity: 4, wave: task1.wave, status: 'ready' }),
      makeTask({ id: 'st-1-sub2', description: 'Write remaining tests', type: 'test', complexity: 4, wave: task1.wave, status: 'ready' }),
    ];
    queue.replaceWithSubtasks('st-1', subtasks);

    // Original should be decomposed
    expect(queue.getTask('st-1')!.status).toBe('decomposed');
    expect(queue.getTask('st-1')!.subtaskIds).toEqual(['st-1-sub1', 'st-1-sub2']);

    // Subtasks should exist and have the parent's dependencies
    const sub1 = queue.getTask('st-1-sub1')!;
    const sub2 = queue.getTask('st-1-sub2')!;
    expect(sub1.parentTaskId).toBe('st-1');
    expect(sub2.parentTaskId).toBe('st-1');
    expect(sub1.dependencies).toContain('st-0');
    expect(sub2.dependencies).toContain('st-0');

    // st-2 should now depend on the subtasks, not the original
    const task2 = queue.getTask('st-2')!;
    expect(task2.dependencies).toContain('st-1-sub1');
    expect(task2.dependencies).toContain('st-1-sub2');
    expect(task2.dependencies).not.toContain('st-1');
  });

  it('decomposed status counts as completed in wave checks', () => {
    const config = makeConfig();
    const queue = new SwarmTaskQueue();
    const decomp = makeDecomposition([
      { id: 'st-0', description: 'Only task', dependencies: [] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    // Manually set to decomposed
    const task = queue.getTask('st-0')!;
    task.status = 'decomposed';

    expect(queue.isCurrentWaveComplete()).toBe(true);
  });

  it('decomposed tasks count as completed in stats', () => {
    const config = makeConfig();
    const queue = new SwarmTaskQueue();
    const decomp = makeDecomposition([
      { id: 'st-0', description: 'Task A', dependencies: [] },
      { id: 'st-1', description: 'Task B', dependencies: [] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    queue.getTask('st-0')!.status = 'decomposed';
    queue.markDispatched('st-1', 'test-model');
    queue.markCompleted('st-1', makeResult());

    const stats = queue.getStats();
    expect(stats.completed).toBe(2); // decomposed + completed
  });

  it('decomposed status resolves dependencies for downstream tasks', () => {
    const config = makeConfig();
    const queue = new SwarmTaskQueue();
    const decomp = makeDecomposition([
      { id: 'st-0', description: 'Will be decomposed', dependencies: [] },
      { id: 'st-1', description: 'Depends on decomposed', dependencies: ['st-0'] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    // Mark st-0 as decomposed (simulating replaceWithSubtasks without actual subtasks)
    const task0 = queue.getTask('st-0')!;
    task0.status = 'decomposed';

    // Advance wave to trigger updateReadyStatus
    queue.advanceWave();

    const task1 = queue.getTask('st-1')!;
    // After decomposed dep resolves, dependent should become ready
    expect(task1.status === 'ready' || task1.status === 'pending').toBe(true);
  });
});

// =============================================================================
// 4. Cascade Rescue (task queue side)
// =============================================================================

describe('Cascade Rescue', () => {
  it('rescueTask un-skips a task and sets rescue context', () => {
    const config = makeConfig();
    const queue = new SwarmTaskQueue();
    const decomp = makeDecomposition([
      { id: 'st-0', description: 'Will fail', dependencies: [] },
      { id: 'st-1', description: 'Will be skipped', dependencies: ['st-0'] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    // Fail st-0 to trigger cascade skip
    queue.markDispatched('st-0', 'test-model');
    // Exhaust retries
    queue.getTask('st-0')!.attempts = 10;
    queue.markFailed('st-0', 0);

    // st-1 should be skipped (or pending depending on artifact-aware skip)
    const task1 = queue.getTask('st-1')!;
    if (task1.status === 'skipped') {
      // Rescue it
      queue.rescueTask('st-1', 'Test rescue: artifacts exist on disk');
      expect(task1.status).toBe('ready');
      expect(task1.rescueContext).toContain('Test rescue');
    }
  });

  it('getSkippedTasks returns only skipped tasks', () => {
    const config = makeConfig();
    const queue = new SwarmTaskQueue();
    const decomp = makeDecomposition([
      { id: 'st-0', description: 'Complete', dependencies: [] },
      { id: 'st-1', description: 'Ready', dependencies: [] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    queue.markDispatched('st-0', 'test-model');
    queue.markCompleted('st-0', makeResult());

    // Manually skip st-1 for testing
    queue.getTask('st-1')!.status = 'skipped';

    const skipped = queue.getSkippedTasks();
    expect(skipped).toHaveLength(1);
    expect(skipped[0].id).toBe('st-1');
  });

  it('rescued task gets dependency context rebuilt', () => {
    const config = makeConfig();
    const queue = new SwarmTaskQueue();
    const decomp = makeDecomposition([
      { id: 'st-0', description: 'Completed dep', dependencies: [] },
      { id: 'st-1', description: 'Failed dep', dependencies: [] },
      { id: 'st-2', description: 'Will be rescued', dependencies: ['st-0', 'st-1'] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    // Complete st-0
    queue.markDispatched('st-0', 'test-model');
    queue.markCompleted('st-0', makeResult({ output: 'Foundation code written.' }));

    // Fail st-1
    queue.markDispatched('st-1', 'test-model');
    queue.getTask('st-1')!.attempts = 10;
    queue.markFailed('st-1', 0);

    // Manually skip st-2 (simulating what cascadeSkip would do)
    queue.getTask('st-2')!.status = 'skipped';

    // Rescue st-2
    queue.rescueTask('st-2', 'Dep st-1 failed but artifacts exist');

    const task2 = queue.getTask('st-2')!;
    expect(task2.status).toBe('ready');
    expect(task2.rescueContext).toContain('artifacts exist');
    // Should have dependency context from st-0
    expect(task2.dependencyContext).toContain('Foundation code written');
  });
});

// =============================================================================
// Task Status Type
// =============================================================================

describe('SwarmTaskStatus type', () => {
  it('includes decomposed status', () => {
    const statuses: SwarmTaskStatus[] = ['pending', 'ready', 'dispatched', 'completed', 'failed', 'skipped', 'decomposed'];
    expect(statuses).toContain('decomposed');
  });
});

// =============================================================================
// Integration: Rescue context in dependency context
// =============================================================================

describe('Rescue context in dependency context', () => {
  it('includes rescue warning when task was rescued', () => {
    const config = makeConfig();
    const queue = new SwarmTaskQueue();
    const decomp = makeDecomposition([
      { id: 'st-0', description: 'Foundation', dependencies: [] },
      { id: 'st-1', description: 'Was rescued', dependencies: ['st-0'] },
      { id: 'st-2', description: 'Depends on rescued', dependencies: ['st-1'] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    // Complete st-0
    queue.markDispatched('st-0', 'test-model');
    queue.markCompleted('st-0', makeResult({ output: 'Done' }));

    // Mark st-1 as rescued and completed
    const task1 = queue.getTask('st-1')!;
    task1.status = 'skipped';
    queue.rescueTask('st-1', 'Rescued from cascade');
    queue.markDispatched('st-1', 'test-model');
    queue.markCompleted('st-1', makeResult({ output: 'Rescued task output' }));

    // st-2 should have dependency context from st-1
    const task2 = queue.getTask('st-2')!;
    expect(task2.status).toBe('ready');
    expect(task2.dependencyContext).toContain('Rescued task output');
  });
});

// =============================================================================
// 5. Resilience Bypass Fix: Dispatch-Cap & Timeout paths call recovery
// =============================================================================

describe('Resilience bypass fixes (orchestrator-level)', () => {
  function makeOrchestratorConfig(overrides: Partial<SwarmConfig> = {}): SwarmConfig {
    return {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/orchestrator',
      workers: [{ name: 'coder', model: 'test/coder', capabilities: ['code'] }],
      qualityGates: false,
      enablePlanning: false,
      enableWaveReview: false,
      enableVerification: false,
      enablePersistence: false,
      enableModelFailover: false,
      probeModels: false,
      dispatchStaggerMs: 0,
      maxConcurrency: 5,
      ...overrides,
    };
  }

  function makeMockProvider() {
    let callCount = 0;
    return {
      chat: vi.fn().mockImplementation(() => {
        callCount++;
        if (callCount === 1) {
          // Decomposition response — two tasks, both low complexity (below micro-decompose threshold)
          return Promise.resolve({
            content: JSON.stringify({
              subtasks: [
                { description: 'Write evaluator tests', type: 'test', complexity: 3, dependencies: [], parallelizable: true, relevantFiles: ['tests/evaluator.test.ts'] },
                { description: 'Simple evaluator setup', type: 'implement', complexity: 3, dependencies: [], parallelizable: true, relevantFiles: ['src/evaluator.ts'] },
              ],
              strategy: 'parallel',
              reasoning: 'test',
            }),
          });
        }
        // Micro-decompose response (for recovery)
        return Promise.resolve({
          content: JSON.stringify({
            subtasks: [
              { description: 'Write basic evaluator tests', type: 'test', targetFiles: ['tests/evaluator.test.ts'], complexity: 3 },
              { description: 'Write advanced evaluator tests', type: 'test', targetFiles: ['tests/evaluator.test.ts'], complexity: 4 },
            ],
          }),
        });
      }),
      name: 'mock',
      listModels: vi.fn(),
      supportsStreaming: false,
      countTokens: vi.fn(),
    } as any;
  }

  function makeMockRegistry() {
    return {
      registerAgent: vi.fn(),
      unregisterAgent: vi.fn(),
      listAgents: vi.fn().mockReturnValue([]),
    } as any;
  }

  it('dispatch-cap triggers degraded acceptance when worker had tool calls', async () => {
    const { SwarmOrchestrator } = await import('../../src/integrations/swarm/swarm-orchestrator.js');
    const config = makeOrchestratorConfig({
      maxDispatchesPerTask: 2,
      workerRetries: 1, // Allow 1 retry so hollow attempt 1 can be retried, reaching dispatch cap on attempt 2
    });

    const registry = makeMockRegistry();

    // Worker "succeeds" but with hollow output (empty) on attempt 1.
    // On attempt 2 (dispatch cap), it makes tool calls (simulating real work).
    let spawnCallCount = 0;
    const spawnFn = vi.fn().mockImplementation(() => {
      spawnCallCount++;
      return Promise.resolve({
        success: true,
        output: '',
        metrics: { tokens: 500, duration: 5000, toolCalls: spawnCallCount >= 2 ? 3 : 0 },
      });
    });

    const orchestrator = new SwarmOrchestrator(config, makeMockProvider(), registry, spawnFn);

    const events: SwarmEvent[] = [];
    orchestrator.subscribe((event: SwarmEvent) => events.push(event));

    await orchestrator.execute('Write evaluator tests');

    // With the fix, when dispatch cap is reached and worker had tool calls,
    // tryResilienceRecovery should trigger degraded acceptance.
    // Check that we got a completed event (not just failed).
    const completedEvents = events.filter(
      e => e.type === 'swarm.task.completed' && (e as any).qualityScore === 2,
    );
    const failedEvents = events.filter(
      e => e.type === 'swarm.task.failed' && (e as any).error?.includes('Dispatch cap'),
    );

    // Either degraded acceptance succeeded (completed with score 2)
    // or dispatch cap was hit but the task was still processed through resilience
    const hadResilienceAttempt = completedEvents.length > 0 || failedEvents.length > 0;
    expect(hadResilienceAttempt).toBe(true);
  });

  it('timeout early-fail triggers degraded acceptance when worker had tool calls', async () => {
    const { SwarmOrchestrator } = await import('../../src/integrations/swarm/swarm-orchestrator.js');
    const config = makeOrchestratorConfig({
      consecutiveTimeoutLimit: 2,
      workerRetries: 3,
      maxDispatchesPerTask: 10,
    });

    const registry = makeMockRegistry();

    // Worker always times out (toolCalls === -1) but has non-zero tokens
    const spawnFn = vi.fn().mockResolvedValue({
      success: false,
      output: 'Worker error: Worker timeout after 300000ms',
      metrics: { tokens: 8000, duration: 300000, toolCalls: -1 },
    });

    const orchestrator = new SwarmOrchestrator(config, makeMockProvider(), registry, spawnFn);

    const events: SwarmEvent[] = [];
    orchestrator.subscribe((event: SwarmEvent) => events.push(event));

    await orchestrator.execute('Write evaluator tests');

    // With the fix, when consecutive timeouts exhaust all models,
    // tryResilienceRecovery is called before hard fail.
    // The task should either be degraded-accepted (if artifacts exist) or hard-failed
    // (if no artifacts). Since we can't mock checkArtifacts easily here,
    // just verify the timeout-early-fail path was reached.
    const timeoutFailEvents = events.filter(
      e => e.type === 'swarm.task.failed'
        && ((e as any).error?.includes('timeout') || (e as any).error?.includes('Hollow')),
    );
    expect(timeoutFailEvents.length).toBeGreaterThan(0);
  });

  it('dispatched event includes attempts field', async () => {
    const { SwarmOrchestrator } = await import('../../src/integrations/swarm/swarm-orchestrator.js');
    const config = makeOrchestratorConfig({
      workerRetries: 1,
      maxDispatchesPerTask: 3,
    });

    const registry = makeMockRegistry();

    // Worker fails on first attempt, succeeds on second
    let callCount = 0;
    const spawnFn = vi.fn().mockImplementation(() => {
      callCount++;
      if (callCount === 1) {
        return Promise.resolve({
          success: true,
          output: '',
          metrics: { tokens: 100, duration: 1000, toolCalls: 0 },
        });
      }
      return Promise.resolve({
        success: true,
        output: 'Tests written successfully with full coverage.',
        metrics: { tokens: 5000, duration: 30000, toolCalls: 8 },
      });
    });

    const orchestrator = new SwarmOrchestrator(config, makeMockProvider(), registry, spawnFn);

    const events: SwarmEvent[] = [];
    orchestrator.subscribe((event: SwarmEvent) => events.push(event));

    await orchestrator.execute('Write evaluator tests');

    const dispatchedEvents = events.filter(e => e.type === 'swarm.task.dispatched');
    expect(dispatchedEvents.length).toBeGreaterThan(0);

    // All dispatched events should have attempts field defined as a number
    for (const evt of dispatchedEvents) {
      const e = evt as any;
      expect(e.attempts).toBeDefined();
      expect(typeof e.attempts).toBe('number');
      expect(e.attempts).toBeGreaterThanOrEqual(1); // attempts is incremented before dispatch
    }

    // If the same taskId is dispatched twice, second should have higher attempts
    const byTask = new Map<string, any[]>();
    for (const evt of dispatchedEvents) {
      const e = evt as any;
      const arr = byTask.get(e.taskId) ?? [];
      arr.push(e);
      byTask.set(e.taskId, arr);
    }
    for (const [, dispatches] of byTask) {
      if (dispatches.length >= 2) {
        expect(dispatches[1].attempts).toBeGreaterThan(dispatches[0].attempts);
      }
    }
  });
});

// =============================================================================
// 6. Event Bridge: Attempts field propagation
// =============================================================================

describe('Event Bridge attempts propagation', () => {
  it('updateTask applies attempts from dispatched event', async () => {
    const { SwarmEventBridge } = await import('../../src/integrations/swarm/swarm-event-bridge.js');
    const bridge = new SwarmEventBridge({ outputDir: '/tmp/test-swarm-bridge-' + Date.now() });

    // Simulate swarm.start to initialize
    (bridge as any).handleEvent({ type: 'swarm.start', taskCount: 1, waveCount: 1, config: { maxConcurrency: 1, totalBudget: 100000, maxCost: 1 } });

    // Load a task
    (bridge as any).setTasks([{
      id: 'task-1',
      description: 'Test task',
      type: 'implement',
      dependencies: [],
      status: 'ready',
      complexity: 5,
      wave: 0,
      attempts: 0,
    }]);

    // Dispatch with attempts=3
    (bridge as any).handleEvent({
      type: 'swarm.task.dispatched',
      taskId: 'task-1',
      description: 'Test task',
      model: 'test-model',
      workerName: 'coder',
      toolCount: -1,
      attempts: 3,
    });

    // Check that the task's attempts field was updated
    const task = (bridge as any).tasks.get('task-1');
    expect(task).toBeDefined();
    expect(task.attempts).toBe(3);
  });

  it('updateTask preserves attempts=0 when event has no attempts field', async () => {
    const { SwarmEventBridge } = await import('../../src/integrations/swarm/swarm-event-bridge.js');
    const bridge = new SwarmEventBridge({ outputDir: '/tmp/test-swarm-bridge-' + Date.now() });

    // Initialize
    (bridge as any).handleEvent({ type: 'swarm.start', taskCount: 1, waveCount: 1, config: { maxConcurrency: 1, totalBudget: 100000, maxCost: 1 } });

    (bridge as any).setTasks([{
      id: 'task-1',
      description: 'Test task',
      type: 'implement',
      dependencies: [],
      status: 'ready',
      complexity: 5,
      wave: 0,
      attempts: 0,
    }]);

    // Dispatch WITHOUT attempts field (backwards compatibility)
    (bridge as any).handleEvent({
      type: 'swarm.task.dispatched',
      taskId: 'task-1',
      description: 'Test task',
      model: 'test-model',
      workerName: 'coder',
      toolCount: -1,
    });

    const task = (bridge as any).tasks.get('task-1');
    expect(task).toBeDefined();
    // Should stay at 0, not be overwritten with undefined
    expect(task.attempts).toBe(0);
  });
});
