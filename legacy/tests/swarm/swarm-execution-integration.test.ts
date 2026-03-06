/**
 * Integration tests for swarm execution with mocked workers.
 *
 * Covers:
 *  - Multi-wave pipeline with dependency propagation
 *  - Failure + retry within wave
 *  - Cascade skip propagation across waves
 *  - Dependency context building (merge with partial context)
 *  - Checkpoint/restore roundtrip through waves
 */

import { describe, it, expect } from 'vitest';
import { createSwarmTaskQueue } from '../../src/integrations/swarm/task-queue.js';
import { DEFAULT_SWARM_CONFIG } from '../../src/integrations/swarm/types.js';
import type {
  SmartDecompositionResult,
  SmartSubtask,
  DependencyGraph,
} from '../../src/integrations/tasks/smart-decomposer.js';
import type { SwarmConfig, SwarmTaskResult } from '../../src/integrations/swarm/types.js';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeSubtask(overrides: Partial<SmartSubtask> = {}): SmartSubtask {
  return {
    id: 'task-1',
    description: 'Test task',
    status: 'pending',
    dependencies: [],
    complexity: 3,
    type: 'implement',
    parallelizable: true,
    ...overrides,
  };
}

function makeDecomposition(subtasks: SmartSubtask[], parallelGroups: string[][]): SmartDecompositionResult {
  const dependencies = new Map<string, string[]>();
  const dependents = new Map<string, string[]>();
  for (const st of subtasks) {
    dependencies.set(st.id, st.dependencies);
    for (const dep of st.dependencies) {
      if (!dependents.has(dep)) dependents.set(dep, []);
      dependents.get(dep)!.push(st.id);
    }
  }

  const graph: DependencyGraph = {
    dependencies,
    dependents,
    executionOrder: subtasks.map(s => s.id),
    parallelGroups,
    cycles: [],
  };

  return {
    originalTask: 'Test',
    subtasks,
    dependencyGraph: graph,
    conflicts: [],
    strategy: 'parallel',
    totalComplexity: subtasks.reduce((sum, s) => sum + s.complexity, 0),
    totalEstimatedTokens: 10000,
    metadata: { decomposedAt: new Date(), codebaseAware: false, llmAssisted: false },
  };
}

const config: SwarmConfig = {
  ...DEFAULT_SWARM_CONFIG,
  orchestratorModel: 'test/model',
  workers: [],
  partialDependencyThreshold: 0.5,
};

function makeResult(overrides: Partial<SwarmTaskResult> = {}): SwarmTaskResult {
  return {
    success: true,
    output: 'Task completed',
    tokensUsed: 1000,
    costUsed: 0.01,
    durationMs: 5000,
    model: 'test/model',
    filesModified: [],
    findings: [],
    toolCalls: 5,
    ...overrides,
  };
}

// ===========================================================================
// Multi-wave pipeline integration
// ===========================================================================

describe('Multi-wave pipeline integration', () => {
  it('runs a 3-wave pipeline: setup → implement → integrate', () => {
    const queue = createSwarmTaskQueue();
    const subtasks = [
      makeSubtask({ id: 'setup', description: 'Project setup', type: 'design', dependencies: [] }),
      makeSubtask({ id: 'impl-a', description: 'Implement feature A', dependencies: ['setup'] }),
      makeSubtask({ id: 'impl-b', description: 'Implement feature B', dependencies: ['setup'] }),
      makeSubtask({ id: 'integrate', description: 'Integration', dependencies: ['impl-a', 'impl-b'] }),
    ];

    const decomp = makeDecomposition(subtasks, [['setup'], ['impl-a', 'impl-b'], ['integrate']]);
    queue.loadFromDecomposition(decomp, config);

    // === Wave 0: setup ===
    expect(queue.getCurrentWave()).toBe(0);
    let ready = queue.getReadyTasks();
    expect(ready.map(t => t.id)).toEqual(['setup']);

    queue.markDispatched('setup');
    queue.markCompleted('setup', makeResult({ output: 'Project scaffolded with package.json and src/' }));

    // === Wave 1: parallel impl ===
    queue.advanceWave();
    ready = queue.getReadyTasks();
    expect(ready.map(t => t.id).sort()).toEqual(['impl-a', 'impl-b']);

    queue.markDispatched('impl-a');
    queue.markDispatched('impl-b');
    queue.markCompleted('impl-a', makeResult({ output: 'Feature A implemented', filesModified: ['src/a.ts'] }));
    queue.markCompleted('impl-b', makeResult({ output: 'Feature B implemented', filesModified: ['src/b.ts'] }));

    // === Wave 2: integrate ===
    queue.advanceWave();
    ready = queue.getReadyTasks();
    expect(ready.map(t => t.id)).toEqual(['integrate']);

    // Verify dependency context is available
    const integrateTask = queue.getTask('integrate');
    expect(integrateTask).toBeDefined();
    expect(integrateTask!.dependencyContext).toBeDefined();
    expect(integrateTask!.dependencyContext).toContain('Feature A implemented');
    expect(integrateTask!.dependencyContext).toContain('Feature B implemented');

    queue.markDispatched('integrate');
    queue.markCompleted('integrate', makeResult({ output: 'All features integrated' }));

    // All done
    const stats = queue.getStats();
    expect(stats.completed).toBe(4);
    expect(stats.failed).toBe(0);
    expect(stats.skipped).toBe(0);
    expect(queue.isComplete()).toBe(true);
  });

  it('handles failure + retry within a wave', () => {
    const queue = createSwarmTaskQueue();
    const subtasks = [
      makeSubtask({ id: 'a', dependencies: [] }),
      makeSubtask({ id: 'b', dependencies: [] }),
    ];

    const decomp = makeDecomposition(subtasks, [['a', 'b']]);
    queue.loadFromDecomposition(decomp, config);

    // Dispatch and fail task a
    queue.markDispatched('a');
    queue.markFailed('a', 0); // qualityScore = 0

    // Task a should be retryable (attempts < max)
    const taskA = queue.getTask('a');
    expect(taskA!.status).toBe('failed');
    expect(taskA!.attempts).toBe(1);

    // Manually set back to ready for retry (simulating orchestrator retry logic)
    taskA!.status = 'ready';
    taskA!.retryContext = {
      previousFeedback: 'Try a different approach',
      previousScore: 0,
      attempt: 1,
    };

    // Task a should appear in ready list again
    const ready = queue.getReadyTasks();
    expect(ready.find(t => t.id === 'a')).toBeDefined();

    // Complete it on retry
    queue.markDispatched('a');
    queue.markCompleted('a', makeResult({ output: 'A done on retry' }));

    // Task b should also complete
    queue.markDispatched('b');
    queue.markCompleted('b', makeResult({ output: 'B done' }));

    expect(queue.isComplete()).toBe(true);
    expect(queue.getStats().completed).toBe(2);
  });

  it('cascade skip propagates through dependency chain', () => {
    const queue = createSwarmTaskQueue();
    const subtasks = [
      makeSubtask({ id: 'root', dependencies: [] }),
      makeSubtask({ id: 'child', dependencies: ['root'] }),
      makeSubtask({ id: 'grandchild', dependencies: ['child'] }),
    ];

    const decomp = makeDecomposition(subtasks, [['root'], ['child'], ['grandchild']]);
    // Use strict threshold so partial deps don't help
    queue.loadFromDecomposition(decomp, { ...config, partialDependencyThreshold: 1.0 });

    // Fail root
    queue.markDispatched('root');
    queue.markFailed('root', 0);
    queue.triggerCascadeSkip('root');

    // Both child and grandchild should be cascade-skipped
    const child = queue.getTask('child');
    const grandchild = queue.getTask('grandchild');
    expect(child!.status).toBe('skipped');
    expect(grandchild!.status).toBe('skipped');
  });
});

// ===========================================================================
// Merge task with partial context
// ===========================================================================

describe('Merge task with partial dependency context', () => {
  it('merge task receives combined context from successful dependencies', () => {
    const queue = createSwarmTaskQueue();
    const subtasks = [
      makeSubtask({ id: 'a', dependencies: [] }),
      makeSubtask({ id: 'b', dependencies: [] }),
      makeSubtask({ id: 'c', dependencies: [] }),
      makeSubtask({ id: 'merge', dependencies: ['a', 'b', 'c'] }),
    ];

    const decomp = makeDecomposition(subtasks, [['a', 'b', 'c'], ['merge']]);
    queue.loadFromDecomposition(decomp, { ...config, partialDependencyThreshold: 0.5 });

    // Complete a and b, fail c
    queue.markDispatched('a');
    queue.markCompleted('a', makeResult({ output: 'Module A created' }));
    queue.markDispatched('b');
    queue.markCompleted('b', makeResult({ output: 'Module B created' }));
    queue.markDispatched('c');
    queue.markFailed('c', 0);
    queue.triggerCascadeSkip('c');

    queue.advanceWave();

    // 2/3 = 0.67 >= 0.5 → merge should be ready with partial context
    const ready = queue.getReadyTasks();
    const merge = ready.find(t => t.id === 'merge');
    expect(merge).toBeDefined();

    // Partial context should indicate which succeeded and which failed (by description)
    expect(merge!.partialContext).toBeDefined();
    expect(merge!.partialContext!.succeeded.length).toBe(2);
    expect(merge!.partialContext!.failed.length).toBe(1);
    expect(merge!.partialContext!.ratio).toBeCloseTo(2 / 3, 1);

    // Dependency context should include outputs from a and b
    expect(merge!.dependencyContext).toContain('Module A created');
    expect(merge!.dependencyContext).toContain('Module B created');
  });

  it('dependency context includes warnings about failed dependencies', () => {
    const queue = createSwarmTaskQueue();
    const subtasks = [
      makeSubtask({ id: 'a', dependencies: [] }),
      makeSubtask({ id: 'b', dependencies: [] }),
      makeSubtask({ id: 'merge', dependencies: ['a', 'b'] }),
    ];

    const decomp = makeDecomposition(subtasks, [['a', 'b'], ['merge']]);
    queue.loadFromDecomposition(decomp, { ...config, partialDependencyThreshold: 0.5 });

    queue.markDispatched('a');
    queue.markCompleted('a', makeResult({ output: 'A done' }));
    queue.markDispatched('b');
    queue.markFailed('b', 0);
    queue.triggerCascadeSkip('b');

    queue.advanceWave();

    const ready = queue.getReadyTasks();
    const merge = ready.find(t => t.id === 'merge');
    expect(merge).toBeDefined();
    // Context should include a warning about degraded input
    expect(merge!.dependencyContext).toMatch(/partial|degraded|warning|failed/i);
  });
});

// ===========================================================================
// Checkpoint/restore through waves
// ===========================================================================

describe('Checkpoint/restore through wave execution', () => {
  it('roundtrip preserves task states across waves', () => {
    const queue = createSwarmTaskQueue();
    const subtasks = [
      makeSubtask({ id: 'a', dependencies: [] }),
      makeSubtask({ id: 'b', dependencies: ['a'] }),
    ];

    const decomp = makeDecomposition(subtasks, [['a'], ['b']]);
    queue.loadFromDecomposition(decomp, config);

    // Complete wave 0
    queue.markDispatched('a');
    queue.markCompleted('a', makeResult({ output: 'A output' }));
    queue.advanceWave();

    // Save checkpoint
    const checkpoint = queue.getCheckpointState();
    expect(checkpoint).toBeDefined();

    // Create new queue and restore
    const queue2 = createSwarmTaskQueue();
    queue2.restoreFromCheckpoint(checkpoint);

    // Wave state should be preserved
    expect(queue2.getCurrentWave()).toBe(1);

    // Task a should be completed
    const taskA = queue2.getTask('a');
    expect(taskA!.status).toBe('completed');

    // Task b should be ready
    const ready = queue2.getReadyTasks();
    expect(ready.map(t => t.id)).toContain('b');
  });

  it('checkpoint preserves stats correctly', () => {
    const queue = createSwarmTaskQueue();
    const subtasks = [
      makeSubtask({ id: 'a', dependencies: [] }),
      makeSubtask({ id: 'b', dependencies: [] }),
      makeSubtask({ id: 'c', dependencies: ['a', 'b'] }),
    ];

    const decomp = makeDecomposition(subtasks, [['a', 'b'], ['c']]);
    queue.loadFromDecomposition(decomp, { ...config, partialDependencyThreshold: 1.0 });

    // Complete a, fail b, cascade skip c
    queue.markDispatched('a');
    queue.markCompleted('a', makeResult({ output: 'A done' }));
    queue.markDispatched('b');
    queue.markFailed('b', 0);
    queue.triggerCascadeSkip('b');

    const checkpoint = queue.getCheckpointState();

    const queue2 = createSwarmTaskQueue();
    queue2.restoreFromCheckpoint(checkpoint);

    const stats = queue2.getStats();
    expect(stats.completed).toBe(1);
    expect(stats.failed).toBe(1);
    expect(stats.skipped).toBeGreaterThanOrEqual(1);
  });
});

// ===========================================================================
// UnSkip + rescue behavior
// ===========================================================================

describe('Cascade rescue behavior', () => {
  it('unSkipDependents re-enables skipped tasks after dependency completes on retry', () => {
    const queue = createSwarmTaskQueue();
    const subtasks = [
      makeSubtask({ id: 'a', dependencies: [] }),
      makeSubtask({ id: 'b', dependencies: ['a'] }),
    ];

    const decomp = makeDecomposition(subtasks, [['a'], ['b']]);
    queue.loadFromDecomposition(decomp, { ...config, partialDependencyThreshold: 1.0 });

    // Fail a → cascade skip b
    queue.markDispatched('a');
    queue.markFailed('a', 0);
    queue.triggerCascadeSkip('a');

    expect(queue.getTask('b')!.status).toBe('skipped');

    // Simulate retry: manually set a back to ready and complete it
    const taskA = queue.getTask('a')!;
    taskA.status = 'ready';
    queue.markDispatched('a');
    queue.markCompleted('a', makeResult({ output: 'A done on retry' }));

    // Un-skip dependents of a
    queue.unSkipDependents('a');

    // b should now be ready (its dependency a is completed)
    queue.advanceWave();
    const ready = queue.getReadyTasks();
    expect(ready.find(t => t.id === 'b')).toBeDefined();
  });
});

// ===========================================================================
// Fixup tasks injection
// ===========================================================================

describe('Fixup tasks injection', () => {
  it('addFixupTasks inserts new tasks into the current wave', () => {
    const queue = createSwarmTaskQueue();
    const subtasks = [
      makeSubtask({ id: 'a', dependencies: [] }),
    ];

    const decomp = makeDecomposition(subtasks, [['a']]);
    queue.loadFromDecomposition(decomp, config);

    queue.markDispatched('a');
    queue.markCompleted('a', makeResult({ output: 'A done with issues' }));

    // Inject fixup task
    queue.addFixupTasks([{
      id: 'fixup-1',
      description: 'Fix issues from task A',
      type: 'implement',
      complexity: 2,
      dependencies: ['a'],
      status: 'ready',
      wave: 0,
      attempts: 0,
      fixesTaskId: 'a',
      fixInstructions: 'Fix the compilation errors in src/a.ts',
    }]);

    const fixup = queue.getTask('fixup-1');
    expect(fixup).toBeDefined();
    expect(fixup!.status).toBe('ready'); // a is completed, so fixup is ready
  });
});

// ===========================================================================
// Stale dispatch reconciliation
// ===========================================================================

describe('Stale dispatch reconciliation', () => {
  it('recovers tasks stuck in dispatched state when no worker is active', () => {
    const queue = createSwarmTaskQueue();
    const subtasks = [
      makeSubtask({ id: 'a', dependencies: [] }),
    ];

    const decomp = makeDecomposition(subtasks, [['a']]);
    queue.loadFromDecomposition(decomp, config);

    queue.markDispatched('a');

    // Simulate passage of time (dispatched 10 minutes ago, stale after 5)
    const recovered = queue.reconcileStaleDispatched({
      staleAfterMs: 5 * 60 * 1000,
      now: Date.now() + 10 * 60 * 1000,
      activeTaskIds: new Set(), // no active workers
    });

    expect(recovered).toContain('a');
    expect(queue.getTask('a')!.status).toBe('ready');
  });

  it('does not recover task if worker is still active', () => {
    const queue = createSwarmTaskQueue();
    const subtasks = [
      makeSubtask({ id: 'a', dependencies: [] }),
    ];

    const decomp = makeDecomposition(subtasks, [['a']]);
    queue.loadFromDecomposition(decomp, config);

    queue.markDispatched('a');

    const recovered = queue.reconcileStaleDispatched({
      staleAfterMs: 5 * 60 * 1000,
      now: Date.now() + 10 * 60 * 1000,
      activeTaskIds: new Set(['a']), // worker still active
    });

    expect(recovered).not.toContain('a');
    expect(queue.getTask('a')!.status).toBe('dispatched');
  });
});
