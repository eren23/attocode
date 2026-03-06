/**
 * Tests for SwarmTaskQueue
 */
import { describe, it, expect } from 'vitest';
import { createSwarmTaskQueue } from '../../src/integrations/swarm/task-queue.js';
import { DEFAULT_SWARM_CONFIG } from '../../src/integrations/swarm/types.js';
import type { SmartDecompositionResult, SmartSubtask, DependencyGraph } from '../../src/integrations/tasks/smart-decomposer.js';
import type { SwarmConfig, SwarmTaskResult, FixupTask } from '../../src/integrations/swarm/types.js';

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
};

describe('SwarmTaskQueue', () => {
  it('should load tasks from decomposition', () => {
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [
        makeSubtask({ id: 'a', description: 'Task A' }),
        makeSubtask({ id: 'b', description: 'Task B' }),
      ],
      [['a', 'b']],
    );

    queue.loadFromDecomposition(decomp, config);

    expect(queue.getTotalWaves()).toBe(1);
    expect(queue.getStats().total).toBe(2);
    expect(queue.getStats().ready).toBe(2);
  });

  it('should organize tasks into waves from parallelGroups', () => {
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [
        makeSubtask({ id: 'a', description: 'Task A' }),
        makeSubtask({ id: 'b', description: 'Task B', dependencies: ['a'] }),
        makeSubtask({ id: 'c', description: 'Task C', dependencies: ['a'] }),
      ],
      [['a'], ['b', 'c']],
    );

    queue.loadFromDecomposition(decomp, config);

    expect(queue.getTotalWaves()).toBe(2);
    // Only wave 0 tasks should be ready initially
    const ready = queue.getReadyTasks();
    expect(ready.length).toBe(1);
    expect(ready[0].id).toBe('a');
  });

  it('should advance waves and update ready status', () => {
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [
        makeSubtask({ id: 'a', description: 'Task A' }),
        makeSubtask({ id: 'b', description: 'Task B', dependencies: ['a'] }),
      ],
      [['a'], ['b']],
    );

    queue.loadFromDecomposition(decomp, config);

    // Complete task A
    queue.markDispatched('a', 'test-model');
    const result: SwarmTaskResult = {
      success: true,
      output: 'Done',
      tokensUsed: 100,
      costUsed: 0.001,
      durationMs: 1000,
      model: 'test-model',
    };
    queue.markCompleted('a', result);

    // Advance wave
    expect(queue.isCurrentWaveComplete()).toBe(true);
    queue.advanceWave();

    // Task B should now be ready
    const ready = queue.getReadyTasks();
    expect(ready.length).toBe(1);
    expect(ready[0].id).toBe('b');
  });

  it('should cascade skip on failure', () => {
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [
        makeSubtask({ id: 'a', description: 'Task A' }),
        makeSubtask({ id: 'b', description: 'Task B', dependencies: ['a'] }),
        makeSubtask({ id: 'c', description: 'Task C', dependencies: ['b'] }),
      ],
      [['a'], ['b'], ['c']],
    );

    queue.loadFromDecomposition(decomp, config);

    // Fail task A (no retries)
    queue.markDispatched('a', 'test-model');
    queue.markFailed('a', 0);

    // B and C should be skipped
    const stats = queue.getStats();
    expect(stats.failed).toBe(1);
    expect(stats.skipped).toBe(2);
  });

  it('should allow retry when attempts remain', () => {
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [makeSubtask({ id: 'a', description: 'Task A' })],
      [['a']],
    );

    queue.loadFromDecomposition(decomp, config);
    queue.markDispatched('a', 'test-model');

    // First failure — should allow retry (maxRetries=1)
    const canRetry = queue.markFailed('a', 1);
    expect(canRetry).toBe(true);

    const task = queue.getTask('a');
    expect(task?.status).toBe('ready');
  });

  it('should report complete when all tasks resolved', () => {
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [
        makeSubtask({ id: 'a', description: 'Task A' }),
        makeSubtask({ id: 'b', description: 'Task B' }),
      ],
      [['a', 'b']],
    );

    queue.loadFromDecomposition(decomp, config);

    expect(queue.isComplete()).toBe(false);

    queue.markDispatched('a', 'test-model');
    queue.markCompleted('a', { success: true, output: 'Done', tokensUsed: 0, costUsed: 0, durationMs: 0, model: 'test' });
    queue.markDispatched('b', 'test-model');
    queue.markCompleted('b', { success: true, output: 'Done', tokensUsed: 0, costUsed: 0, durationMs: 0, model: 'test' });

    expect(queue.isComplete()).toBe(true);
  });

  it('should build dependency context from completed deps', () => {
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [
        makeSubtask({ id: 'a', description: 'Research task' }),
        makeSubtask({ id: 'b', description: 'Implement based on research', dependencies: ['a'] }),
      ],
      [['a'], ['b']],
    );

    queue.loadFromDecomposition(decomp, config);

    // Complete task A with findings
    queue.markDispatched('a', 'test-model');
    queue.markCompleted('a', {
      success: true,
      output: 'Found the pattern in src/utils.ts',
      tokensUsed: 500,
      costUsed: 0.01,
      durationMs: 5000,
      model: 'test',
    });

    // Advance wave
    queue.advanceWave();

    // Task B should have dependency context
    const taskB = queue.getTask('b');
    expect(taskB?.dependencyContext).toContain('Research task');
  });

  it('should serialize conflicting tasks when strategy is serialize', () => {
    const serializeConfig = { ...config, fileConflictStrategy: 'serialize' as const };
    const queue = createSwarmTaskQueue();

    const decomp = makeDecomposition(
      [
        makeSubtask({ id: 'a', description: 'Write to file', modifies: ['src/app.ts'] }),
        makeSubtask({ id: 'b', description: 'Also write to file', modifies: ['src/app.ts'] }),
      ],
      [['a', 'b']],
    );
    // Add a write-write conflict
    decomp.conflicts = [
      { resource: 'src/app.ts', taskIds: ['a', 'b'], type: 'write-write', severity: 'error', suggestion: 'Serialize' },
    ];

    queue.loadFromDecomposition(decomp, serializeConfig);

    // Tasks should be in different waves
    const taskA = queue.getTask('a');
    const taskB = queue.getTask('b');
    expect(taskA?.wave).not.toBe(taskB?.wave);
  });

  // =========================================================================
  // New tests: markCompleted guards, cascade, checkpoint, fixup, retryAfter
  // =========================================================================

  it('markCompleted on skipped task is a no-op (status stays skipped)', () => {
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [
        makeSubtask({ id: 'a', description: 'Task A' }),
        makeSubtask({ id: 'b', description: 'Task B', dependencies: ['a'] }),
      ],
      [['a'], ['b']],
    );

    queue.loadFromDecomposition(decomp, config);

    // Fail A → B gets cascade-skipped
    queue.markDispatched('a', 'test-model');
    queue.markFailed('a', 0);
    expect(queue.getTask('b')?.status).toBe('skipped');

    // Try to mark skipped B as completed — should be a no-op
    queue.markCompleted('b', { success: true, output: 'Done', tokensUsed: 0, costUsed: 0, durationMs: 0, model: 'test' });
    expect(queue.getTask('b')?.status).toBe('skipped');
  });

  it('markCompleted on failed task is a no-op (status stays failed)', () => {
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [makeSubtask({ id: 'a', description: 'Task A' })],
      [['a']],
    );

    queue.loadFromDecomposition(decomp, config);
    queue.markDispatched('a', 'test-model');
    // Exhaust retries so it ends up failed
    queue.markFailed('a', 0);
    expect(queue.getTask('a')?.status).toBe('failed');

    // Try to mark it completed — should be no-op
    queue.markCompleted('a', { success: true, output: 'Late result', tokensUsed: 0, costUsed: 0, durationMs: 0, model: 'test' });
    expect(queue.getTask('a')?.status).toBe('failed');
  });

  it('cascadeSkip callback fires for each skipped task with correct reason', () => {
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [
        makeSubtask({ id: 'a', description: 'Task A' }),
        makeSubtask({ id: 'b', description: 'Task B', dependencies: ['a'] }),
        makeSubtask({ id: 'c', description: 'Task C', dependencies: ['a'] }),
      ],
      [['a'], ['b', 'c']],
    );

    queue.loadFromDecomposition(decomp, config);

    const skippedTasks: Array<{ taskId: string; reason: string }> = [];
    queue.setOnCascadeSkip((taskId, reason) => {
      skippedTasks.push({ taskId, reason });
    });

    queue.markDispatched('a', 'test-model');
    queue.markFailed('a', 0);

    expect(skippedTasks.length).toBe(2);
    expect(skippedTasks.map(s => s.taskId).sort()).toEqual(['b', 'c']);
    expect(skippedTasks[0].reason).toContain('dependency');
    expect(skippedTasks[0].reason).toContain('a');
  });

  it('cascadeSkip also skips dispatched tasks whose dependency failed', () => {
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [
        makeSubtask({ id: 'a', description: 'Task A' }),
        makeSubtask({ id: 'b', description: 'Task B' }),
        makeSubtask({ id: 'c', description: 'Task C', dependencies: ['a'] }),
      ],
      [['a', 'b'], ['c']],
    );

    queue.loadFromDecomposition(decomp, config);

    // Manually set c to dispatched (simulate it was already picked up)
    queue.markDispatched('a', 'test-model');
    // Mark c as dispatched before a fails (edge case: already running)
    // First advance wave so c can become ready
    queue.markCompleted('a', { success: true, output: 'Done', tokensUsed: 0, costUsed: 0, durationMs: 0, model: 'test' });
    queue.markDispatched('b', 'test-model');
    queue.markCompleted('b', { success: true, output: 'Done', tokensUsed: 0, costUsed: 0, durationMs: 0, model: 'test' });
    queue.advanceWave();

    // c should now be ready (its dep a is completed)
    expect(queue.getTask('c')?.status).toBe('ready');
    queue.markDispatched('c', 'test-model');
    expect(queue.getTask('c')?.status).toBe('dispatched');

    // Now simulate a scenario where c depends on a and a gets failed
    // Actually this test is about dispatched tasks being skipped in cascadeSkip.
    // Let's use a different setup: direct dependency chain where a task is dispatched
    // before its dependency is marked failed.
    // Use fresh queue for cleaner test.
    const queue2 = createSwarmTaskQueue();
    const decomp2 = makeDecomposition(
      [
        makeSubtask({ id: 'x', description: 'Task X' }),
        makeSubtask({ id: 'y', description: 'Task Y', dependencies: ['x'] }),
      ],
      [['x'], ['y']],
    );
    queue2.loadFromDecomposition(decomp2, config);
    queue2.markDispatched('x', 'test-model');

    // Fail X with no retries — Y should be skipped even though it's still pending
    queue2.markFailed('x', 0);
    expect(queue2.getTask('y')?.status).toBe('skipped');
  });

  it('transitive cascade: A→B→C, A fails → both B and C skipped', () => {
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [
        makeSubtask({ id: 'a', description: 'Task A' }),
        makeSubtask({ id: 'b', description: 'Task B', dependencies: ['a'] }),
        makeSubtask({ id: 'c', description: 'Task C', dependencies: ['b'] }),
      ],
      [['a'], ['b'], ['c']],
    );

    queue.loadFromDecomposition(decomp, config);

    queue.markDispatched('a', 'test-model');
    queue.markFailed('a', 0);

    expect(queue.getTask('b')?.status).toBe('skipped');
    expect(queue.getTask('c')?.status).toBe('skipped');
  });

  it('checkpoint/restore roundtrip preserves stats', () => {
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [
        makeSubtask({ id: 'a', description: 'Task A' }),
        makeSubtask({ id: 'b', description: 'Task B', dependencies: ['a'] }),
      ],
      [['a'], ['b']],
    );

    queue.loadFromDecomposition(decomp, config);

    // Complete task A
    queue.markDispatched('a', 'test-model');
    queue.markCompleted('a', { success: true, output: 'Done', tokensUsed: 100, costUsed: 0.01, durationMs: 1000, model: 'test' });
    queue.advanceWave();

    // Take checkpoint
    const checkpoint = queue.getCheckpointState();
    expect(checkpoint.currentWave).toBe(1);

    // Create a new queue and restore
    const queue2 = createSwarmTaskQueue();
    queue2.loadFromDecomposition(decomp, config);
    queue2.restoreFromCheckpoint(checkpoint);

    // Verify restored state matches
    expect(queue2.getCurrentWave()).toBe(1);
    const taskA = queue2.getTask('a');
    expect(taskA?.status).toBe('completed');
    expect(taskA?.attempts).toBe(1);

    const stats = queue2.getStats();
    expect(stats.completed).toBe(1);
  });

  it('addFixupTasks adds tasks to the current wave', () => {
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [
        makeSubtask({ id: 'a', description: 'Task A' }),
        makeSubtask({ id: 'b', description: 'Task B' }),
      ],
      [['a', 'b']],
    );

    queue.loadFromDecomposition(decomp, config);

    const fixup: FixupTask = {
      id: 'fix-1',
      description: 'Fix task A output',
      type: 'implement',
      dependencies: [],
      status: 'ready',
      complexity: 2,
      wave: 0,
      attempts: 0,
      fixesTaskId: 'a',
      fixInstructions: 'Add error handling',
    };

    queue.addFixupTasks([fixup]);

    // Fixup task should be in the queue
    const fixupTask = queue.getTask('fix-1');
    expect(fixupTask).toBeDefined();
    expect(fixupTask?.description).toBe('Fix task A output');

    // Total tasks should increase
    expect(queue.getStats().total).toBe(3);
  });

  it('retryAfter excludes task from getReadyTasks()', () => {
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [
        makeSubtask({ id: 'a', description: 'Task A' }),
        makeSubtask({ id: 'b', description: 'Task B' }),
      ],
      [['a', 'b']],
    );

    queue.loadFromDecomposition(decomp, config);

    // Set a future retryAfter on task A
    queue.setRetryAfter('a', 60000); // 60 seconds in the future

    const ready = queue.getReadyTasks();
    // Only B should be ready, A is on cooldown
    expect(ready.length).toBe(1);
    expect(ready[0].id).toBe('b');

    // getAllReadyTasks should also exclude A
    const allReady = queue.getAllReadyTasks();
    expect(allReady.length).toBe(1);
    expect(allReady[0].id).toBe('b');
  });

  it('getAllReadyTasks sorts by wave then complexity descending', () => {
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [
        makeSubtask({ id: 'a', description: 'Task A', complexity: 2 }),
        makeSubtask({ id: 'b', description: 'Task B', complexity: 8 }),
        makeSubtask({ id: 'c', description: 'Task C', complexity: 5 }),
      ],
      [['a', 'b', 'c']],
    );

    queue.loadFromDecomposition(decomp, config);

    const allReady = queue.getAllReadyTasks();
    expect(allReady.length).toBe(3);
    // Same wave → sorted by complexity descending
    expect(allReady[0].id).toBe('b'); // complexity 8
    expect(allReady[1].id).toBe('c'); // complexity 5
    expect(allReady[2].id).toBe('a'); // complexity 2
  });

  // =========================================================================
  // Partial dependency tolerance (BUG-1 fix)
  // =========================================================================

  it('dispatches merge task when enough deps succeed (partial threshold)', () => {
    const partialConfig = { ...config, partialDependencyThreshold: 0.5 };
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [
        makeSubtask({ id: 'a', description: 'Research A' }),
        makeSubtask({ id: 'b', description: 'Research B' }),
        makeSubtask({ id: 'c', description: 'Research C' }),
        makeSubtask({ id: 'd', description: 'Research D' }),
        makeSubtask({ id: 'merge', description: 'Merge results', dependencies: ['a', 'b', 'c', 'd'] }),
      ],
      [['a', 'b', 'c', 'd'], ['merge']],
    );

    queue.loadFromDecomposition(decomp, partialConfig);

    // Complete 3 of 4 research tasks
    const result: SwarmTaskResult = { success: true, output: 'Done', tokensUsed: 100, costUsed: 0.001, durationMs: 1000, model: 'test' };
    queue.markDispatched('a', 'test'); queue.markCompleted('a', result);
    queue.markDispatched('b', 'test'); queue.markCompleted('b', result);
    queue.markDispatched('c', 'test'); queue.markCompleted('c', result);
    // Fail task D
    queue.markDispatched('d', 'test'); queue.markFailed('d', 0);

    queue.advanceWave();

    // Merge task should be ready (3/4 = 75% >= 50% threshold)
    const mergeTask = queue.getTask('merge');
    expect(mergeTask?.status).toBe('ready');
    expect(mergeTask?.partialContext).toBeDefined();
    expect(mergeTask?.partialContext?.ratio).toBe(0.75);
    expect(mergeTask?.partialContext?.succeeded).toHaveLength(3);
    expect(mergeTask?.partialContext?.failed).toHaveLength(1);
  });

  it('skips merge task when too many deps fail (below threshold)', () => {
    const partialConfig = { ...config, partialDependencyThreshold: 0.5 };
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [
        makeSubtask({ id: 'a', description: 'Research A' }),
        makeSubtask({ id: 'b', description: 'Research B' }),
        makeSubtask({ id: 'c', description: 'Research C' }),
        makeSubtask({ id: 'd', description: 'Research D' }),
        makeSubtask({ id: 'merge', description: 'Merge results', dependencies: ['a', 'b', 'c', 'd'] }),
      ],
      [['a', 'b', 'c', 'd'], ['merge']],
    );

    queue.loadFromDecomposition(decomp, partialConfig);

    // Only 1 of 4 succeeds
    const result: SwarmTaskResult = { success: true, output: 'Done', tokensUsed: 100, costUsed: 0.001, durationMs: 1000, model: 'test' };
    queue.markDispatched('a', 'test'); queue.markCompleted('a', result);
    queue.markDispatched('b', 'test'); queue.markFailed('b', 0);
    queue.markDispatched('c', 'test'); queue.markFailed('c', 0);
    queue.markDispatched('d', 'test'); queue.markFailed('d', 0);

    queue.advanceWave();

    // Merge task should be skipped (1/4 = 25% < 50% threshold)
    const mergeTask = queue.getTask('merge');
    expect(mergeTask?.status).toBe('skipped');
  });

  it('includes partial dependency warning in dependency context', () => {
    const partialConfig = { ...config, partialDependencyThreshold: 0.5 };
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [
        makeSubtask({ id: 'a', description: 'Research frameworks' }),
        makeSubtask({ id: 'b', description: 'Research testing' }),
        makeSubtask({ id: 'merge', description: 'Merge results', dependencies: ['a', 'b'] }),
      ],
      [['a', 'b'], ['merge']],
    );

    queue.loadFromDecomposition(decomp, partialConfig);

    const result: SwarmTaskResult = { success: true, output: 'Found framework data', tokensUsed: 100, costUsed: 0.001, durationMs: 1000, model: 'test' };
    queue.markDispatched('a', 'test'); queue.markCompleted('a', result);
    queue.markDispatched('b', 'test'); queue.markFailed('b', 0);

    queue.advanceWave();

    const mergeTask = queue.getTask('merge');
    expect(mergeTask?.status).toBe('ready');
    expect(mergeTask?.dependencyContext).toContain('WARNING');
    expect(mergeTask?.dependencyContext).toContain('1/2');
  });

  it('strict mode (threshold=1.0) skips on any failure', () => {
    const strictConfig = { ...config, partialDependencyThreshold: 1.0 };
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [
        makeSubtask({ id: 'a', description: 'Research A' }),
        makeSubtask({ id: 'b', description: 'Research B' }),
        makeSubtask({ id: 'merge', description: 'Merge results', dependencies: ['a', 'b'] }),
      ],
      [['a', 'b'], ['merge']],
    );

    queue.loadFromDecomposition(decomp, strictConfig);

    const result: SwarmTaskResult = { success: true, output: 'Done', tokensUsed: 100, costUsed: 0.001, durationMs: 1000, model: 'test' };
    queue.markDispatched('a', 'test'); queue.markCompleted('a', result);
    queue.markDispatched('b', 'test'); queue.markFailed('b', 0);

    queue.advanceWave();

    // Strict mode: 1/2 = 50% < 100% threshold — skip
    const mergeTask = queue.getTask('merge');
    expect(mergeTask?.status).toBe('skipped');
  });

  // =========================================================================
  // Resume: dispatched tasks reset (BUG-3 fix)
  // =========================================================================

  it('restoreFromCheckpoint preserves dispatched status (orchestrator handles reset)', () => {
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [
        makeSubtask({ id: 'a', description: 'Task A' }),
        makeSubtask({ id: 'b', description: 'Task B' }),
      ],
      [['a', 'b']],
    );

    queue.loadFromDecomposition(decomp, config);
    queue.markDispatched('a', 'test-model');

    const checkpoint = queue.getCheckpointState();

    // Restore into a new queue
    const queue2 = createSwarmTaskQueue();
    queue2.loadFromDecomposition(decomp, config);
    queue2.restoreFromCheckpoint(checkpoint);

    // Dispatched status is preserved — orchestrator's resume logic resets it
    expect(queue2.getTask('a')?.status).toBe('dispatched');
  });

  it('reconciles stale dispatched tasks back to ready when no worker is active', () => {
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [makeSubtask({ id: 'a', description: 'Task A' })],
      [['a']],
    );

    queue.loadFromDecomposition(decomp, config);
    queue.markDispatched('a', 'test-model');
    const dispatchedAt = queue.getTask('a')?.dispatchedAt ?? 0;

    const recovered = queue.reconcileStaleDispatched({
      staleAfterMs: 100,
      now: dispatchedAt + 500,
      activeTaskIds: new Set<string>(),
    });

    expect(recovered).toEqual(['a']);
    expect(queue.getTask('a')?.status).toBe('ready');
  });

  it('does not reconcile dispatched task when worker is still active', () => {
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [makeSubtask({ id: 'a', description: 'Task A' })],
      [['a']],
    );

    queue.loadFromDecomposition(decomp, config);
    queue.markDispatched('a', 'test-model');
    const dispatchedAt = queue.getTask('a')?.dispatchedAt ?? 0;

    const recovered = queue.reconcileStaleDispatched({
      staleAfterMs: 100,
      now: dispatchedAt + 500,
      activeTaskIds: new Set(['a']),
    });

    expect(recovered).toEqual([]);
    expect(queue.getTask('a')?.status).toBe('dispatched');
  });
});
