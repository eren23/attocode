/**
 * Tests for the cascade-skip timing fix in SwarmTaskQueue.
 *
 * Key methods under test:
 * - markFailedWithoutCascade()  — marks failed WITHOUT triggering cascade skip
 * - triggerCascadeSkip()        — manually triggers cascade skip after recovery fails
 * - unSkipDependents()          — restores skipped tasks when deps are now satisfied
 * - addReplanTasks()            — adds new tasks from mid-swarm re-planning
 */

import { describe, it, expect } from 'vitest';
import { SwarmTaskQueue, createSwarmTaskQueue } from '../../src/integrations/swarm/task-queue.js';
import { DEFAULT_SWARM_CONFIG } from '../../src/integrations/swarm/types.js';
import type { SwarmTask, SwarmConfig } from '../../src/integrations/swarm/types.js';
import type { SmartDecompositionResult } from '../../src/integrations/tasks/smart-decomposer.js';

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

/**
 * Build a minimal SmartDecompositionResult suitable for loadFromDecomposition.
 * Creates subtasks with specified IDs, descriptions, and dependency edges.
 */
function makeDecomposition(
  subtasks: Array<{ id: string; description?: string; type?: string; complexity?: number; dependencies: string[]; modifies?: string[] }>,
  parallelGroups?: string[][],
): SmartDecompositionResult {
  const builtSubtasks = subtasks.map(s => ({
    id: s.id,
    description: s.description ?? `Task ${s.id}`,
    type: (s.type ?? 'implement') as any,
    complexity: s.complexity ?? 5,
    dependencies: s.dependencies,
    modifies: s.modifies ?? [],
    reads: [],
  }));

  // Auto-compute parallelGroups from dependencies if not provided
  const groups = parallelGroups ?? computeParallelGroups(subtasks);

  return {
    subtasks: builtSubtasks,
    dependencyGraph: {
      nodes: builtSubtasks.map(s => s.id),
      edges: builtSubtasks.flatMap(s => s.dependencies.map(d => ({ from: d, to: s.id }))),
      parallelGroups: groups,
    },
    conflicts: [],
    reasoning: 'test decomposition',
  } as SmartDecompositionResult;
}

/**
 * Simple topological grouping: tasks with no unresolved deps go in the earliest possible wave.
 */
function computeParallelGroups(subtasks: Array<{ id: string; dependencies: string[] }>): string[][] {
  const assigned = new Map<string, number>();
  const waves: string[][] = [];

  function assignWave(id: string): number {
    if (assigned.has(id)) return assigned.get(id)!;
    const subtask = subtasks.find(s => s.id === id);
    if (!subtask) return 0;
    const depWave = subtask.dependencies.length === 0
      ? -1
      : Math.max(...subtask.dependencies.map(d => assignWave(d)));
    const wave = depWave + 1;
    assigned.set(id, wave);
    while (waves.length <= wave) waves.push([]);
    waves[wave].push(id);
    return wave;
  }

  for (const s of subtasks) assignWave(s.id);
  return waves;
}

// =============================================================================
// markFailedWithoutCascade — does NOT trigger cascade skip
// =============================================================================

describe('markFailedWithoutCascade', () => {
  it('does NOT cascade-skip dependents when task fails beyond max retries', () => {
    const queue = createSwarmTaskQueue();
    const config = makeConfig({ partialDependencyThreshold: 1.0 }); // strict: all deps must pass

    // st-0 (wave 0, no deps) -> st-1 (wave 1, depends on st-0)
    const decomp = makeDecomposition([
      { id: 'st-0', dependencies: [] },
      { id: 'st-1', dependencies: ['st-0'] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    // Dispatch st-0 and then fail it without cascade
    queue.markDispatched('st-0', 'test-model');
    // attempts is now 1, maxRetries=0 → should NOT be retryable
    const canRetry = queue.markFailedWithoutCascade('st-0', 0);

    expect(canRetry).toBe(false);
    expect(queue.getTask('st-0')!.status).toBe('failed');

    // The critical assertion: st-1 should still be pending (not skipped)
    const st1 = queue.getTask('st-1')!;
    expect(st1.status).not.toBe('skipped');
    // It should be 'pending' since its dependency is not completed
    expect(st1.status).toBe('pending');
  });

  it('returns true for retry when attempts <= maxRetries', () => {
    const queue = createSwarmTaskQueue();
    const config = makeConfig();

    const decomp = makeDecomposition([
      { id: 'st-0', dependencies: [] },
      { id: 'st-1', dependencies: ['st-0'] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    // Dispatch (attempts becomes 1)
    queue.markDispatched('st-0', 'test-model');

    // maxRetries=2, attempts=1 → 1 <= 2 → can retry
    const canRetry = queue.markFailedWithoutCascade('st-0', 2);

    expect(canRetry).toBe(true);
    expect(queue.getTask('st-0')!.status).toBe('ready');
    // st-1 should still be pending — no cascade
    expect(queue.getTask('st-1')!.status).toBe('pending');
  });

  it('returns false when attempts exceed maxRetries', () => {
    const queue = createSwarmTaskQueue();
    const config = makeConfig();

    const decomp = makeDecomposition([
      { id: 'st-0', dependencies: [] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    // Dispatch three times (attempts becomes 3)
    queue.markDispatched('st-0', 'test-model');
    queue.markFailedWithoutCascade('st-0', 3); // attempts=1 <= 3 → retry
    queue.markDispatched('st-0', 'test-model');
    queue.markFailedWithoutCascade('st-0', 3); // attempts=2 <= 3 → retry
    queue.markDispatched('st-0', 'test-model');
    queue.markFailedWithoutCascade('st-0', 3); // attempts=3 <= 3 → retry
    queue.markDispatched('st-0', 'test-model');
    const canRetry = queue.markFailedWithoutCascade('st-0', 3); // attempts=4 > 3 → no retry

    expect(canRetry).toBe(false);
    expect(queue.getTask('st-0')!.status).toBe('failed');
  });
});

// =============================================================================
// triggerCascadeSkip — manually triggers cascade on dependents
// =============================================================================

describe('triggerCascadeSkip', () => {
  it('manually triggers cascade skip on dependents after recovery fails', () => {
    const queue = createSwarmTaskQueue();
    const config = makeConfig({ partialDependencyThreshold: 1.0 });

    const decomp = makeDecomposition([
      { id: 'st-0', dependencies: [] },
      { id: 'st-1', dependencies: ['st-0'] },
      { id: 'st-2', dependencies: ['st-0'] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    // Dispatch and fail st-0 WITHOUT cascade
    queue.markDispatched('st-0', 'test-model');
    queue.markFailedWithoutCascade('st-0', 0);

    // Dependents should still NOT be skipped
    expect(queue.getTask('st-1')!.status).toBe('pending');
    expect(queue.getTask('st-2')!.status).toBe('pending');

    // Now recovery failed — trigger cascade manually
    queue.triggerCascadeSkip('st-0');

    // NOW dependents should be skipped
    expect(queue.getTask('st-1')!.status).toBe('skipped');
    expect(queue.getTask('st-2')!.status).toBe('skipped');
  });

  it('contrast: markFailed (standard) DOES trigger cascade immediately', () => {
    const queue = createSwarmTaskQueue();
    const config = makeConfig({ partialDependencyThreshold: 1.0 });

    const decomp = makeDecomposition([
      { id: 'st-0', dependencies: [] },
      { id: 'st-1', dependencies: ['st-0'] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    queue.markDispatched('st-0', 'test-model');
    queue.markFailed('st-0', 0); // standard markFailed

    // Standard markFailed should cascade-skip the dependent
    expect(queue.getTask('st-0')!.status).toBe('failed');
    expect(queue.getTask('st-1')!.status).toBe('skipped');
  });
});

// =============================================================================
// Recovery sequence: markFailedWithoutCascade -> recovery -> dependents stay ready
// =============================================================================

describe('Recovery sequence: fail -> recover -> dependents ready', () => {
  it('dependents stay ready when failed task is recovered via retry and completion', () => {
    const queue = createSwarmTaskQueue();
    const config = makeConfig();

    const decomp = makeDecomposition([
      { id: 'st-0', dependencies: [] },
      { id: 'st-1', dependencies: ['st-0'] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    // First attempt: dispatch, then fail without cascade (retryable)
    queue.markDispatched('st-0', 'test-model');
    const canRetry = queue.markFailedWithoutCascade('st-0', 2);
    expect(canRetry).toBe(true);
    expect(queue.getTask('st-0')!.status).toBe('ready');

    // Second attempt: dispatch and this time succeed
    queue.markDispatched('st-0', 'test-model');
    queue.markCompleted('st-0', {
      success: true,
      output: 'Recovery succeeded!',
      tokensUsed: 500,
      costUsed: 0.01,
      durationMs: 5000,
      model: 'test-model',
    });

    expect(queue.getTask('st-0')!.status).toBe('completed');

    // st-1 should now be ready (dependency satisfied)
    // Need to advance wave for st-1 to become ready
    queue.advanceWave();
    expect(queue.getTask('st-1')!.status).toBe('ready');
  });

  it('dependents are NOT skipped during the recovery window', () => {
    const queue = createSwarmTaskQueue();
    const config = makeConfig({ partialDependencyThreshold: 1.0 });

    // Chain: st-0 -> st-1 -> st-2
    const decomp = makeDecomposition([
      { id: 'st-0', dependencies: [] },
      { id: 'st-1', dependencies: ['st-0'] },
      { id: 'st-2', dependencies: ['st-1'] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    // Fail st-0 without cascade
    queue.markDispatched('st-0', 'test-model');
    queue.markFailedWithoutCascade('st-0', 0); // no retries left

    // st-0 is failed, but neither st-1 nor st-2 should be skipped
    expect(queue.getTask('st-0')!.status).toBe('failed');
    expect(queue.getTask('st-1')!.status).toBe('pending');
    expect(queue.getTask('st-2')!.status).toBe('pending');

    // Stats should show no skipped tasks
    const stats = queue.getStats();
    expect(stats.skipped).toBe(0);
    expect(queue.getSkippedTasks()).toHaveLength(0);
  });
});

// =============================================================================
// unSkipDependents — restores skipped tasks when deps are now satisfied
// =============================================================================

describe('unSkipDependents', () => {
  it('restores skipped tasks when all deps are completed', () => {
    const queue = createSwarmTaskQueue();
    const config = makeConfig({ partialDependencyThreshold: 1.0 });

    const decomp = makeDecomposition([
      { id: 'st-0', dependencies: [] },
      { id: 'st-1', dependencies: ['st-0'] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    // Fail st-0 with cascade (standard) so st-1 gets skipped
    queue.markDispatched('st-0', 'test-model');
    queue.markFailed('st-0', 0);

    expect(queue.getTask('st-1')!.status).toBe('skipped');

    // Now "recover" st-0: manually set it to completed
    // (Simulates external recovery like resilience handler fixing the task)
    const st0 = queue.getTask('st-0')!;
    st0.status = 'completed';
    st0.result = {
      success: true,
      output: 'Recovered externally',
      tokensUsed: 100,
      costUsed: 0.001,
      durationMs: 1000,
      model: 'test-model',
    };

    // Now unskip dependents
    queue.unSkipDependents('st-0');

    expect(queue.getTask('st-1')!.status).toBe('ready');
  });

  it('restores skipped tasks when all deps are decomposed', () => {
    const queue = createSwarmTaskQueue();
    const config = makeConfig({ partialDependencyThreshold: 1.0 });

    const decomp = makeDecomposition([
      { id: 'st-0', dependencies: [] },
      { id: 'st-1', dependencies: ['st-0'] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    // Fail and cascade
    queue.markDispatched('st-0', 'test-model');
    queue.markFailed('st-0', 0);
    expect(queue.getTask('st-1')!.status).toBe('skipped');

    // Simulate recovery by marking st-0 as decomposed
    const st0 = queue.getTask('st-0')!;
    st0.status = 'decomposed';

    queue.unSkipDependents('st-0');
    expect(queue.getTask('st-1')!.status).toBe('ready');
  });

  it('does NOT restore tasks whose deps are NOT all satisfied', () => {
    const queue = createSwarmTaskQueue();
    const config = makeConfig({ partialDependencyThreshold: 1.0 });

    // st-2 depends on both st-0 and st-1
    const decomp = makeDecomposition([
      { id: 'st-0', dependencies: [] },
      { id: 'st-1', dependencies: [] },
      { id: 'st-2', dependencies: ['st-0', 'st-1'] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    // Fail both st-0 and st-1 with cascade
    queue.markDispatched('st-0', 'test-model');
    queue.markFailed('st-0', 0);
    queue.markDispatched('st-1', 'test-model');
    queue.markFailed('st-1', 0);

    expect(queue.getTask('st-2')!.status).toBe('skipped');

    // Recover only st-0 but NOT st-1
    const st0 = queue.getTask('st-0')!;
    st0.status = 'completed';
    st0.result = {
      success: true,
      output: 'Recovered',
      tokensUsed: 100,
      costUsed: 0.001,
      durationMs: 1000,
      model: 'test-model',
    };

    // st-1 is still failed → st-2 should remain skipped
    queue.unSkipDependents('st-0');

    expect(queue.getTask('st-2')!.status).toBe('skipped');
  });

  it('restores task when last unsatisfied dep is finally satisfied', () => {
    const queue = createSwarmTaskQueue();
    const config = makeConfig({ partialDependencyThreshold: 1.0 });

    const decomp = makeDecomposition([
      { id: 'st-0', dependencies: [] },
      { id: 'st-1', dependencies: [] },
      { id: 'st-2', dependencies: ['st-0', 'st-1'] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    // Fail both and cascade
    queue.markDispatched('st-0', 'test-model');
    queue.markFailed('st-0', 0);
    queue.markDispatched('st-1', 'test-model');
    queue.markFailed('st-1', 0);

    expect(queue.getTask('st-2')!.status).toBe('skipped');

    // Recover st-0
    const st0 = queue.getTask('st-0')!;
    st0.status = 'completed';
    st0.result = { success: true, output: 'ok', tokensUsed: 100, costUsed: 0.001, durationMs: 1000, model: 'test-model' };
    queue.unSkipDependents('st-0');
    expect(queue.getTask('st-2')!.status).toBe('skipped'); // still missing st-1

    // Now recover st-1 too
    const st1 = queue.getTask('st-1')!;
    st1.status = 'completed';
    st1.result = { success: true, output: 'ok', tokensUsed: 100, costUsed: 0.001, durationMs: 1000, model: 'test-model' };
    queue.unSkipDependents('st-1');

    // Now both deps are satisfied → st-2 should be ready
    expect(queue.getTask('st-2')!.status).toBe('ready');
  });

  it('only affects tasks that depend on the given taskId', () => {
    const queue = createSwarmTaskQueue();
    const config = makeConfig({ partialDependencyThreshold: 1.0 });

    const decomp = makeDecomposition([
      { id: 'st-0', dependencies: [] },
      { id: 'st-1', dependencies: [] },
      { id: 'st-2', dependencies: ['st-0'] },
      { id: 'st-3', dependencies: ['st-1'] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    // Fail both
    queue.markDispatched('st-0', 'test-model');
    queue.markFailed('st-0', 0);
    queue.markDispatched('st-1', 'test-model');
    queue.markFailed('st-1', 0);

    expect(queue.getTask('st-2')!.status).toBe('skipped');
    expect(queue.getTask('st-3')!.status).toBe('skipped');

    // Recover st-0 only
    const st0 = queue.getTask('st-0')!;
    st0.status = 'completed';
    st0.result = { success: true, output: 'ok', tokensUsed: 100, costUsed: 0.001, durationMs: 1000, model: 'test-model' };
    queue.unSkipDependents('st-0');

    // st-2 (depends on st-0) should be restored
    expect(queue.getTask('st-2')!.status).toBe('ready');
    // st-3 (depends on st-1, still failed) should stay skipped
    expect(queue.getTask('st-3')!.status).toBe('skipped');
  });
});

// =============================================================================
// addReplanTasks — adds new tasks from mid-swarm re-planning
// =============================================================================

describe('addReplanTasks', () => {
  it('creates new tasks in the specified wave with ready status', () => {
    const queue = createSwarmTaskQueue();
    const config = makeConfig();

    const decomp = makeDecomposition([
      { id: 'st-0', dependencies: [] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    const newTasks = queue.addReplanTasks([
      { description: 'Fix the parser', type: 'implement', complexity: 4, dependencies: [] },
      { description: 'Add tests for parser', type: 'test', complexity: 3, dependencies: [] },
    ], 1);

    expect(newTasks).toHaveLength(2);

    // All new tasks should have 'ready' status
    for (const task of newTasks) {
      expect(task.status).toBe('ready');
    }

    // All tasks should be in wave 1
    for (const task of newTasks) {
      expect(task.wave).toBe(1);
    }

    // Tasks should be retrievable from the queue
    for (const task of newTasks) {
      const retrieved = queue.getTask(task.id);
      expect(retrieved).toBeDefined();
      expect(retrieved!.status).toBe('ready');
      expect(retrieved!.wave).toBe(1);
    }

    // Queue stats should include the new tasks
    const stats = queue.getStats();
    // st-0 is ready + 2 new replan tasks ready = 3 ready
    expect(stats.ready).toBe(3);
    expect(stats.total).toBe(3);
  });

  it('assigns unique IDs to replan tasks', () => {
    const queue = createSwarmTaskQueue();
    const config = makeConfig();

    const decomp = makeDecomposition([
      { id: 'st-0', dependencies: [] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    const tasks1 = queue.addReplanTasks([
      { description: 'Task A', type: 'implement', complexity: 3, dependencies: [] },
    ], 0);
    const tasks2 = queue.addReplanTasks([
      { description: 'Task B', type: 'implement', complexity: 3, dependencies: [] },
    ], 0);

    expect(tasks1[0].id).not.toBe(tasks2[0].id);
    expect(tasks1[0].id).toMatch(/^replan-/);
    expect(tasks2[0].id).toMatch(/^replan-/);
  });

  it('respects dependencies in replan tasks', () => {
    const queue = createSwarmTaskQueue();
    const config = makeConfig();

    const decomp = makeDecomposition([
      { id: 'st-0', dependencies: [] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    const newTasks = queue.addReplanTasks([
      { description: 'Depends on st-0', type: 'implement', complexity: 5, dependencies: ['st-0'] },
    ], 1);

    expect(newTasks[0].dependencies).toEqual(['st-0']);
  });

  it('populates relevantFiles as targetFiles', () => {
    const queue = createSwarmTaskQueue();
    const config = makeConfig();

    const decomp = makeDecomposition([
      { id: 'st-0', dependencies: [] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    const newTasks = queue.addReplanTasks([
      { description: 'Fix files', type: 'implement', complexity: 3, dependencies: [], relevantFiles: ['src/foo.ts', 'src/bar.ts'] },
    ], 0);

    expect(newTasks[0].targetFiles).toEqual(['src/foo.ts', 'src/bar.ts']);
  });

  it('sets rescueContext on replan tasks', () => {
    const queue = createSwarmTaskQueue();
    const config = makeConfig();

    const decomp = makeDecomposition([
      { id: 'st-0', dependencies: [] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    const newTasks = queue.addReplanTasks([
      { description: 'Re-planned task', type: 'implement', complexity: 5, dependencies: [] },
    ], 0);

    expect(newTasks[0].rescueContext).toBe('Re-planned from stalled swarm');
  });
});

// =============================================================================
// Integration: full lifecycle with cascade timing
// =============================================================================

describe('Full lifecycle: cascade timing integration', () => {
  it('markFailedWithoutCascade -> triggerCascadeSkip after recovery fails', () => {
    const queue = createSwarmTaskQueue();
    const config = makeConfig({ partialDependencyThreshold: 1.0 });

    // Diamond: st-0 -> st-1, st-0 -> st-2, st-1+st-2 -> st-3
    const decomp = makeDecomposition([
      { id: 'st-0', dependencies: [] },
      { id: 'st-1', dependencies: ['st-0'] },
      { id: 'st-2', dependencies: ['st-0'] },
      { id: 'st-3', dependencies: ['st-1', 'st-2'] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    // Step 1: st-0 fails without cascade
    queue.markDispatched('st-0', 'test-model');
    queue.markFailedWithoutCascade('st-0', 0);

    // Nothing should be skipped yet
    expect(queue.getSkippedTasks()).toHaveLength(0);

    // Step 2: Recovery attempted but fails — trigger cascade
    queue.triggerCascadeSkip('st-0');

    // st-1 and st-2 should now be skipped (direct dependents)
    expect(queue.getTask('st-1')!.status).toBe('skipped');
    expect(queue.getTask('st-2')!.status).toBe('skipped');

    // st-3 depends on st-1 and st-2, which both depend on st-0.
    // The cascadeSkip implementation uses dependsOn() which checks transitive deps,
    // so st-3 is also cascade-skipped since it transitively depends on st-0.
    expect(queue.getTask('st-3')!.status).toBe('skipped');
  });

  it('markFailedWithoutCascade -> recovery succeeds -> full chain completes', () => {
    const queue = createSwarmTaskQueue();
    const config = makeConfig();

    const decomp = makeDecomposition([
      { id: 'st-0', dependencies: [] },
      { id: 'st-1', dependencies: ['st-0'] },
      { id: 'st-2', dependencies: ['st-1'] },
    ]);
    queue.loadFromDecomposition(decomp, config);

    // st-0 fails on first attempt, retryable
    queue.markDispatched('st-0', 'test-model');
    const canRetry = queue.markFailedWithoutCascade('st-0', 1);
    expect(canRetry).toBe(true);

    // No cascade — st-1 and st-2 are safe
    expect(queue.getSkippedTasks()).toHaveLength(0);

    // st-0 succeeds on retry
    queue.markDispatched('st-0', 'test-model');
    queue.markCompleted('st-0', {
      success: true,
      output: 'Done on second try',
      tokensUsed: 500,
      costUsed: 0.01,
      durationMs: 3000,
      model: 'test-model',
    });

    // Advance wave — st-1 should become ready
    queue.advanceWave();
    expect(queue.getTask('st-1')!.status).toBe('ready');

    // Complete st-1
    queue.markDispatched('st-1', 'test-model');
    queue.markCompleted('st-1', {
      success: true,
      output: 'st-1 done',
      tokensUsed: 400,
      costUsed: 0.008,
      durationMs: 2000,
      model: 'test-model',
    });

    // Advance wave — st-2 should become ready
    queue.advanceWave();
    expect(queue.getTask('st-2')!.status).toBe('ready');

    // Complete st-2
    queue.markDispatched('st-2', 'test-model');
    queue.markCompleted('st-2', {
      success: true,
      output: 'st-2 done',
      tokensUsed: 300,
      costUsed: 0.006,
      durationMs: 1500,
      model: 'test-model',
    });

    // All tasks completed, no skipped tasks
    expect(queue.getSkippedTasks()).toHaveLength(0);
    const stats = queue.getStats();
    expect(stats.completed).toBe(3);
    expect(stats.failed).toBe(0);
    expect(stats.skipped).toBe(0);
  });
});
