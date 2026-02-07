/**
 * Tests for SwarmTaskQueue
 */
import { describe, it, expect } from 'vitest';
import { createSwarmTaskQueue } from '../../src/integrations/swarm/task-queue.js';
import { DEFAULT_SWARM_CONFIG } from '../../src/integrations/swarm/types.js';
import type { SmartDecompositionResult, SmartSubtask, DependencyGraph } from '../../src/integrations/smart-decomposer.js';
import type { SwarmConfig, SwarmTaskResult } from '../../src/integrations/swarm/types.js';

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
});
