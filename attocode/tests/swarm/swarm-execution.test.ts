/**
 * Tests for swarm execution unit functions.
 *
 * Covers:
 *  - getEffectiveThreshold (failure-mode-aware partial dependency thresholds)
 *  - hasFutureIntentLanguage (intent pattern detection)
 *  - isHollowCompletion (additional edge cases beyond hollow-completion.test.ts)
 *  - Wave scheduling: file conflict serialization, empty parallelGroups fallback
 *  - Foundation task properties through task queue
 */

import { describe, it, expect } from 'vitest';
import {
  getEffectiveThreshold,
  FAILURE_MODE_THRESHOLDS,
  createSwarmTaskQueue,
} from '../../src/integrations/swarm/task-queue.js';
import {
  hasFutureIntentLanguage,
  isHollowCompletion,
} from '../../src/integrations/swarm/swarm-helpers.js';
import { DEFAULT_SWARM_CONFIG } from '../../src/integrations/swarm/types.js';
import type { SmartDecompositionResult, SmartSubtask, DependencyGraph, ResourceConflict } from '../../src/integrations/tasks/smart-decomposer.js';
import type { SwarmTask, SwarmConfig } from '../../src/integrations/swarm/types.js';
import type { SpawnResult } from '../../src/integrations/agents/agent-registry.js';

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

function makeDecomposition(
  subtasks: SmartSubtask[],
  parallelGroups: string[][],
  conflicts: ResourceConflict[] = [],
): SmartDecompositionResult {
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
    conflicts,
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

function makeSpawnResult(overrides: Partial<SpawnResult> = {}): SpawnResult {
  return {
    success: true,
    output: 'Task completed successfully',
    metrics: {
      tokens: 1000,
      duration: 5000,
      toolCalls: 5,
    },
    ...overrides,
  };
}

function makeFailedSwarmTask(overrides: Partial<SwarmTask> = {}): SwarmTask {
  return {
    id: 'dep-1',
    description: 'Failed dependency',
    type: 'implement',
    dependencies: [],
    status: 'failed',
    complexity: 3,
    wave: 0,
    attempts: 1,
    ...overrides,
  } as SwarmTask;
}

// ===========================================================================
// getEffectiveThreshold
// ===========================================================================

describe('getEffectiveThreshold', () => {
  it('returns configured threshold when no failed deps', () => {
    expect(getEffectiveThreshold([], 0.5)).toBe(0.5);
  });

  it('returns configured threshold when failed deps have no failureMode', () => {
    const deps = [makeFailedSwarmTask({ failureMode: undefined })];
    expect(getEffectiveThreshold(deps, 0.5)).toBe(0.5);
  });

  it('uses timeout threshold (0.3) when dependency timed out', () => {
    const deps = [makeFailedSwarmTask({ failureMode: 'timeout' })];
    expect(getEffectiveThreshold(deps, 0.5)).toBe(0.3);
  });

  it('uses rate-limit threshold (0.3) when dependency was rate-limited', () => {
    const deps = [makeFailedSwarmTask({ failureMode: 'rate-limit' })];
    expect(getEffectiveThreshold(deps, 0.5)).toBe(0.3);
  });

  it('uses quality threshold (0.7) — stricter than default', () => {
    const deps = [makeFailedSwarmTask({ failureMode: 'quality' })];
    // 0.7 > 0.5, so configured (0.5) wins
    expect(getEffectiveThreshold(deps, 0.5)).toBe(0.5);
  });

  it('quality threshold wins when configured is higher', () => {
    const deps = [makeFailedSwarmTask({ failureMode: 'quality' })];
    expect(getEffectiveThreshold(deps, 0.9)).toBe(0.7);
  });

  it('takes most lenient threshold across multiple failed deps', () => {
    const deps = [
      makeFailedSwarmTask({ id: 'a', failureMode: 'quality' }),  // 0.7
      makeFailedSwarmTask({ id: 'b', failureMode: 'timeout' }),  // 0.3
      makeFailedSwarmTask({ id: 'c', failureMode: 'error' }),    // 0.5
    ];
    expect(getEffectiveThreshold(deps, 0.8)).toBe(0.3);
  });

  it('cascade failure mode uses 0.8', () => {
    const deps = [makeFailedSwarmTask({ failureMode: 'cascade' })];
    expect(getEffectiveThreshold(deps, 0.9)).toBe(0.8);
  });

  it('hollow failure mode uses 0.7', () => {
    const deps = [makeFailedSwarmTask({ failureMode: 'hollow' })];
    expect(getEffectiveThreshold(deps, 0.9)).toBe(0.7);
  });

  it('all failure modes are defined', () => {
    const modes = ['timeout', 'rate-limit', 'error', 'quality', 'hollow', 'cascade'] as const;
    for (const mode of modes) {
      expect(FAILURE_MODE_THRESHOLDS[mode]).toBeGreaterThan(0);
      expect(FAILURE_MODE_THRESHOLDS[mode]).toBeLessThanOrEqual(1);
    }
  });
});

// ===========================================================================
// hasFutureIntentLanguage
// ===========================================================================

describe('hasFutureIntentLanguage', () => {
  it('returns false for empty string', () => {
    expect(hasFutureIntentLanguage('')).toBe(false);
  });

  it('returns false for completed language', () => {
    expect(hasFutureIntentLanguage('I created the file successfully')).toBe(false);
    expect(hasFutureIntentLanguage('Done. All tests pass.')).toBe(false);
    expect(hasFutureIntentLanguage('I implemented the feature and it works')).toBe(false);
    expect(hasFutureIntentLanguage('Updated the configuration file')).toBe(false);
  });

  it('detects "I will" patterns', () => {
    expect(hasFutureIntentLanguage('I will create the configuration file next')).toBe(true);
    expect(hasFutureIntentLanguage("I'll write the tests now")).toBe(true);
  });

  it('detects "let me" patterns', () => {
    expect(hasFutureIntentLanguage('Let me create the file structure')).toBe(true);
    expect(hasFutureIntentLanguage('let me fix the import error')).toBe(true);
  });

  it('detects "I need to" patterns', () => {
    expect(hasFutureIntentLanguage('I need to update the configuration')).toBe(true);
    expect(hasFutureIntentLanguage('I should implement the error handler')).toBe(true);
  });

  it('detects "next step" and "remaining work" patterns', () => {
    expect(hasFutureIntentLanguage('The next step is to wire the component')).toBe(true);
    expect(hasFutureIntentLanguage('There is remaining work on this feature')).toBe(true);
  });

  it('detects "I am going to" patterns', () => {
    expect(hasFutureIntentLanguage('I am going to implement this feature')).toBe(true);
    expect(hasFutureIntentLanguage("I'm going to fix the tests")).toBe(true);
  });

  it('does not flag completed language mixed with future intent', () => {
    // Completion signals take priority
    expect(hasFutureIntentLanguage('Done. I will also note that...')).toBe(false);
    expect(hasFutureIntentLanguage('Finished implementing. Next step would be...')).toBe(false);
  });
});

// ===========================================================================
// isHollowCompletion — edge cases
// ===========================================================================

describe('isHollowCompletion edge cases', () => {
  it('timeout (toolCalls === -1) is never hollow', () => {
    const result = makeSpawnResult({
      success: false,
      output: '',
      metrics: { tokens: 0, duration: 60000, toolCalls: -1 },
    });
    expect(isHollowCompletion(result)).toBe(false);
  });

  it('zero tools + output below threshold = hollow', () => {
    const result = makeSpawnResult({
      success: true,
      output: 'ok',
      metrics: { tokens: 100, duration: 1000, toolCalls: 0 },
    });
    expect(isHollowCompletion(result)).toBe(true);
  });

  it('zero tools + output above threshold = not hollow', () => {
    const result = makeSpawnResult({
      success: true,
      output: 'A'.repeat(200), // > 120 default threshold
      metrics: { tokens: 500, duration: 5000, toolCalls: 0 },
    });
    expect(isHollowCompletion(result)).toBe(false);
  });

  it('success with failure admission language = hollow', () => {
    const result = makeSpawnResult({
      success: true,
      output: 'The task was attempted but I was unable to complete the work due to limitations.',
      metrics: { tokens: 500, duration: 10000, toolCalls: 3 },
    });
    expect(isHollowCompletion(result)).toBe(true);
  });

  it('success=false with failure language is not hollow', () => {
    const result = makeSpawnResult({
      success: false,
      output: 'Unable to complete the task.',
      metrics: { tokens: 500, duration: 10000, toolCalls: 3 },
    });
    // Not hollow because success is false — it's genuinely failed, not hollow
    expect(isHollowCompletion(result)).toBe(false);
  });

  it('boilerplate response with zero tools = hollow', () => {
    const result = makeSpawnResult({
      success: true,
      output: 'Task completed successfully.',
      metrics: { tokens: 100, duration: 1000, toolCalls: 0 },
    });
    expect(isHollowCompletion(result)).toBe(true);
  });

  it('custom hollow threshold from config', () => {
    const result = makeSpawnResult({
      success: true,
      output: 'x', // 1 char — below custom threshold of 5
      metrics: { tokens: 100, duration: 1000, toolCalls: 0 },
    });
    const swarmConfig = { ...config, hollowOutputThreshold: 5 };
    // 1 char < 5 threshold AND toolCalls === 0 → hollow
    expect(isHollowCompletion(result, undefined, swarmConfig)).toBe(true);
  });

  it('non-zero tools with substantive output = not hollow', () => {
    const result = makeSpawnResult({
      success: true,
      output: 'Created file src/utils.ts with utility functions. Tests pass.',
      metrics: { tokens: 2000, duration: 15000, toolCalls: 8 },
    });
    expect(isHollowCompletion(result)).toBe(false);
  });
});

// ===========================================================================
// Wave scheduling — file conflict serialization
// ===========================================================================

describe('Wave scheduling — file conflict serialization', () => {
  it('serializes write-write conflicts to different waves', () => {
    const queue = createSwarmTaskQueue();
    const subtasks = [
      makeSubtask({ id: 'a', description: 'Write to shared.ts' }),
      makeSubtask({ id: 'b', description: 'Also writes to shared.ts' }),
      makeSubtask({ id: 'c', description: 'Independent task' }),
    ];

    const conflicts: ResourceConflict[] = [
      { type: 'write-write', resource: 'shared.ts', taskIds: ['a', 'b'], severity: 'warning', suggestion: 'Serialize' },
    ];

    const decomp = makeDecomposition(subtasks, [['a', 'b', 'c']], conflicts);
    queue.loadFromDecomposition(decomp, {
      ...config,
      fileConflictStrategy: 'serialize',
    });

    // a and c should be in wave 0, b should be pushed to wave 1
    expect(queue.getTotalWaves()).toBe(2);
    const readyTasks = queue.getReadyTasks();
    const readyIds = readyTasks.map(t => t.id);
    expect(readyIds).toContain('a');
    expect(readyIds).toContain('c');
    expect(readyIds).not.toContain('b'); // b is in wave 1, not ready yet
  });

  it('does not serialize when strategy is not serialize', () => {
    const queue = createSwarmTaskQueue();
    const subtasks = [
      makeSubtask({ id: 'a' }),
      makeSubtask({ id: 'b' }),
    ];

    const conflicts: ResourceConflict[] = [
      { type: 'write-write', resource: 'shared.ts', taskIds: ['a', 'b'], severity: 'warning', suggestion: 'Serialize' },
    ];

    const decomp = makeDecomposition(subtasks, [['a', 'b']], conflicts);
    queue.loadFromDecomposition(decomp, config); // no fileConflictStrategy

    // Both should be in wave 0
    expect(queue.getTotalWaves()).toBe(1);
    expect(queue.getReadyTasks().length).toBe(2);
  });

  it('chains multiple conflicting tasks across waves', () => {
    const queue = createSwarmTaskQueue();
    const subtasks = [
      makeSubtask({ id: 'a' }),
      makeSubtask({ id: 'b' }),
      makeSubtask({ id: 'c' }),
    ];

    const conflicts: ResourceConflict[] = [
      { type: 'write-write', resource: 'shared.ts', taskIds: ['a', 'b', 'c'], severity: 'warning', suggestion: 'Serialize' },
    ];

    const decomp = makeDecomposition(subtasks, [['a', 'b', 'c']], conflicts);
    queue.loadFromDecomposition(decomp, {
      ...config,
      fileConflictStrategy: 'serialize',
    });

    // a → wave 0, b → wave 1, c → wave 2
    expect(queue.getTotalWaves()).toBe(3);
  });
});

// ===========================================================================
// Wave scheduling — empty parallelGroups fallback
// ===========================================================================

describe('Wave scheduling — empty parallelGroups fallback', () => {
  it('falls back to single wave when parallelGroups is empty', () => {
    const queue = createSwarmTaskQueue();
    const subtasks = [
      makeSubtask({ id: 'a' }),
      makeSubtask({ id: 'b' }),
    ];

    const decomp = makeDecomposition(subtasks, []); // empty parallelGroups
    queue.loadFromDecomposition(decomp, config);

    expect(queue.getTotalWaves()).toBe(1);
    expect(queue.getReadyTasks().length).toBe(2);
  });
});

// ===========================================================================
// Wave scheduling — multi-wave DAG
// ===========================================================================

describe('Wave scheduling — multi-wave dependency DAG', () => {
  it('respects 3-wave dependency chain: A → B → C', () => {
    const queue = createSwarmTaskQueue();
    const subtasks = [
      makeSubtask({ id: 'a', dependencies: [] }),
      makeSubtask({ id: 'b', dependencies: ['a'] }),
      makeSubtask({ id: 'c', dependencies: ['b'] }),
    ];

    const decomp = makeDecomposition(subtasks, [['a'], ['b'], ['c']]);
    queue.loadFromDecomposition(decomp, config);

    expect(queue.getTotalWaves()).toBe(3);

    // Wave 0: only a is ready
    const wave0Ready = queue.getReadyTasks();
    expect(wave0Ready.map(t => t.id)).toEqual(['a']);

    // Complete a → b becomes ready in wave 1
    queue.markDispatched('a');
    queue.markCompleted('a', { success: true, output: 'Done A' } as any);
    queue.advanceWave();

    const wave1Ready = queue.getReadyTasks();
    expect(wave1Ready.map(t => t.id)).toEqual(['b']);

    // Complete b → c becomes ready in wave 2
    queue.markDispatched('b');
    queue.markCompleted('b', { success: true, output: 'Done B' } as any);
    queue.advanceWave();

    const wave2Ready = queue.getReadyTasks();
    expect(wave2Ready.map(t => t.id)).toEqual(['c']);
  });

  it('parallel tasks in same wave both become ready', () => {
    const queue = createSwarmTaskQueue();
    const subtasks = [
      makeSubtask({ id: 'root', dependencies: [] }),
      makeSubtask({ id: 'left', dependencies: ['root'] }),
      makeSubtask({ id: 'right', dependencies: ['root'] }),
      makeSubtask({ id: 'merge', dependencies: ['left', 'right'] }),
    ];

    const decomp = makeDecomposition(subtasks, [['root'], ['left', 'right'], ['merge']]);
    queue.loadFromDecomposition(decomp, config);

    expect(queue.getTotalWaves()).toBe(3);

    // Complete root
    queue.markDispatched('root');
    queue.markCompleted('root', { success: true, output: 'Root done' } as any);
    queue.advanceWave();

    // Both left and right should be ready
    const wave1Ready = queue.getReadyTasks();
    const readyIds = wave1Ready.map(t => t.id).sort();
    expect(readyIds).toEqual(['left', 'right']);
  });

  it('merge task waits for all dependencies', () => {
    const queue = createSwarmTaskQueue();
    const subtasks = [
      makeSubtask({ id: 'a', dependencies: [] }),
      makeSubtask({ id: 'b', dependencies: [] }),
      makeSubtask({ id: 'merge', dependencies: ['a', 'b'] }),
    ];

    const decomp = makeDecomposition(subtasks, [['a', 'b'], ['merge']]);
    queue.loadFromDecomposition(decomp, config);

    // Complete only a
    queue.markDispatched('a');
    queue.markCompleted('a', { success: true, output: 'A done' } as any);

    // merge should NOT be ready yet (b not done)
    queue.advanceWave();
    const ready = queue.getReadyTasks();
    expect(ready.map(t => t.id)).not.toContain('merge');

    // Complete b → merge becomes ready
    queue.markDispatched('b');
    queue.markCompleted('b', { success: true, output: 'B done' } as any);

    // Now merge should be ready
    const readyAfter = queue.getReadyTasks();
    expect(readyAfter.map(t => t.id)).toContain('merge');
  });

  it('getAllReadyTasks returns cross-wave ready tasks sorted by wave then complexity', () => {
    const queue = createSwarmTaskQueue();
    const subtasks = [
      makeSubtask({ id: 'a', complexity: 5, dependencies: [] }),
      makeSubtask({ id: 'b', complexity: 8, dependencies: [] }),
      makeSubtask({ id: 'c', complexity: 3, dependencies: ['a'] }),
    ];

    const decomp = makeDecomposition(subtasks, [['a', 'b'], ['c']]);
    queue.loadFromDecomposition(decomp, config);

    // Complete a so c becomes ready
    queue.markDispatched('a');
    queue.markCompleted('a', { success: true, output: 'A done' } as any);

    // getAllReadyTasks should include both b (wave 0) and c (wave 1)
    const allReady = queue.getAllReadyTasks();
    const ids = allReady.map(t => t.id);
    expect(ids).toContain('b');
    expect(ids).toContain('c');

    // b (wave 0, complexity 8) should come before c (wave 1, complexity 3)
    expect(ids.indexOf('b')).toBeLessThan(ids.indexOf('c'));
  });
});

// ===========================================================================
// Partial dependency threshold via task queue
// ===========================================================================

describe('Partial dependency threshold behavior', () => {
  it('merge task runs with partial context when threshold met', () => {
    const queue = createSwarmTaskQueue();
    const subtasks = [
      makeSubtask({ id: 'a', dependencies: [] }),
      makeSubtask({ id: 'b', dependencies: [] }),
      makeSubtask({ id: 'merge', dependencies: ['a', 'b'] }),
    ];

    const decomp = makeDecomposition(subtasks, [['a', 'b'], ['merge']]);
    queue.loadFromDecomposition(decomp, {
      ...config,
      partialDependencyThreshold: 0.5,
    });

    // Complete a, fail b
    queue.markDispatched('a');
    queue.markCompleted('a', { success: true, output: 'A done' } as any);
    queue.markDispatched('b');
    queue.markFailed('b', 0);
    queue.triggerCascadeSkip('b');

    queue.advanceWave();

    // With threshold 0.5, 1/2 = 0.5 >= 0.5 → merge should be ready
    const ready = queue.getReadyTasks();
    const mergeTask = ready.find(t => t.id === 'merge');
    expect(mergeTask).toBeDefined();
    // Should have partial context info
    expect(mergeTask!.partialContext).toBeDefined();
  });

  it('merge task skipped when below threshold', () => {
    const queue = createSwarmTaskQueue();
    const subtasks = [
      makeSubtask({ id: 'a', dependencies: [] }),
      makeSubtask({ id: 'b', dependencies: [] }),
      makeSubtask({ id: 'c', dependencies: [] }),
      makeSubtask({ id: 'merge', dependencies: ['a', 'b', 'c'] }),
    ];

    const decomp = makeDecomposition(subtasks, [['a', 'b', 'c'], ['merge']]);
    queue.loadFromDecomposition(decomp, {
      ...config,
      partialDependencyThreshold: 0.5,
    });

    // Complete a, fail b and c
    queue.markDispatched('a');
    queue.markCompleted('a', { success: true, output: 'A done' } as any);
    queue.markDispatched('b');
    queue.markFailed('b', 0);
    queue.triggerCascadeSkip('b');
    queue.markDispatched('c');
    queue.markFailed('c', 0);
    queue.triggerCascadeSkip('c');

    queue.advanceWave();

    // 1/3 = 0.33 < 0.5 → merge should be skipped
    const ready = queue.getReadyTasks();
    expect(ready.find(t => t.id === 'merge')).toBeUndefined();

    const stats = queue.getStats();
    expect(stats.skipped).toBeGreaterThanOrEqual(1);
  });

  it('strict mode (threshold=1.0) skips merge on any failure', () => {
    const queue = createSwarmTaskQueue();
    const subtasks = [
      makeSubtask({ id: 'a', dependencies: [] }),
      makeSubtask({ id: 'b', dependencies: [] }),
      makeSubtask({ id: 'merge', dependencies: ['a', 'b'] }),
    ];

    const decomp = makeDecomposition(subtasks, [['a', 'b'], ['merge']]);
    queue.loadFromDecomposition(decomp, {
      ...config,
      partialDependencyThreshold: 1.0,
    });

    queue.markDispatched('a');
    queue.markCompleted('a', { success: true, output: 'A done' } as any);
    queue.markDispatched('b');
    queue.markFailed('b', 0);
    queue.triggerCascadeSkip('b');

    queue.advanceWave();

    // 1/2 = 0.5 < 1.0 → merge should be skipped
    const ready = queue.getReadyTasks();
    expect(ready.find(t => t.id === 'merge')).toBeUndefined();
  });
});
