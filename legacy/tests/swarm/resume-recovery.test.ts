/**
 * Tests for swarm resume/recovery features:
 * - CLI --resume / --swarm-resume argument parsing
 * - Task queue un-skip on dependency satisfaction
 * - Failed task reset with preserved retry budget
 * - SwarmCheckpoint.originalPrompt field
 * - addReplanTasks creates tasks with rescueContext
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { parseArgs } from '../../src/cli.js';
import { createSwarmTaskQueue } from '../../src/integrations/swarm/task-queue.js';
import { DEFAULT_SWARM_CONFIG } from '../../src/integrations/swarm/types.js';
import type { SwarmConfig, SwarmTaskResult, SwarmCheckpoint } from '../../src/integrations/swarm/types.js';
import type { SmartDecompositionResult, SmartSubtask, DependencyGraph } from '../../src/integrations/tasks/smart-decomposer.js';

// ─── Helpers ────────────────────────────────────────────────────────────────

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

const okResult: SwarmTaskResult = {
  success: true,
  output: 'Done',
  tokensUsed: 100,
  costUsed: 0.001,
  durationMs: 1000,
  model: 'test-model',
};

// ─── CLI Argument Parsing ───────────────────────────────────────────────────

describe('CLI --resume / --swarm-resume parsing', () => {
  let originalArgv: string[];

  beforeEach(() => {
    originalArgv = process.argv;
  });

  afterEach(() => {
    process.argv = originalArgv;
  });

  it('--resume with no ID sets swarmResume to "latest" and swarm to true', () => {
    process.argv = ['node', 'attocode', '--resume'];
    const args = parseArgs();
    expect(args.swarmResume).toBe('latest');
    expect(args.swarm).toBe(true);
  });

  it('--resume with an ID sets swarmResume to that ID and swarm to true', () => {
    process.argv = ['node', 'attocode', '--resume', 'abc123'];
    const args = parseArgs();
    expect(args.swarmResume).toBe('abc123');
    expect(args.swarm).toBe(true);
  });

  it('--swarm-resume with no ID sets swarmResume to "latest" and swarm to true', () => {
    process.argv = ['node', 'attocode', '--swarm-resume'];
    const args = parseArgs();
    expect(args.swarmResume).toBe('latest');
    expect(args.swarm).toBe(true);
  });

  it('--swarm-resume with an ID sets swarmResume to that ID and swarm to true', () => {
    process.argv = ['node', 'attocode', '--swarm-resume', 'abc123'];
    const args = parseArgs();
    expect(args.swarmResume).toBe('abc123');
    expect(args.swarm).toBe(true);
  });

  it('--resume does not consume a following --flag as the ID', () => {
    process.argv = ['node', 'attocode', '--resume', '--trace'];
    const args = parseArgs();
    expect(args.swarmResume).toBe('latest');
    expect(args.swarm).toBe(true);
    expect(args.trace).toBe(true);
  });

  it('--swarm-resume does not consume a following --flag as the ID', () => {
    process.argv = ['node', 'attocode', '--swarm-resume', '--debug'];
    const args = parseArgs();
    expect(args.swarmResume).toBe('latest');
    expect(args.swarm).toBe(true);
    expect(args.debug).toBe(true);
  });
});

// ─── Task Queue: Un-skip on Dependency Satisfaction ─────────────────────────

describe('Task queue unSkipDependents', () => {
  it('un-skips tasks whose dependencies are now all completed', () => {
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [
        makeSubtask({ id: 'a', description: 'Foundation' }),
        makeSubtask({ id: 'b', description: 'Depends on A', dependencies: ['a'] }),
      ],
      [['a'], ['b']],
    );

    queue.loadFromDecomposition(decomp, config);

    // Fail A so B gets cascade-skipped
    queue.markDispatched('a', 'test-model');
    queue.markFailed('a', 0);
    expect(queue.getTask('b')?.status).toBe('skipped');

    // Simulate recovery: rescue task A by marking it completed externally
    // First, directly manipulate: set A to completed via markCompleted
    // markCompleted guards against overwriting 'failed', so we use rescueTask on b + unSkipDependents
    // Instead: the orchestrator would re-dispatch A or accept its partial output.
    // For this test, we test unSkipDependents directly by setting A to completed via a new checkpoint restore.
    const checkpoint = queue.getCheckpointState();
    // Modify checkpoint: set A to completed
    const aState = checkpoint.taskStates.find(t => t.id === 'a')!;
    aState.status = 'completed';
    aState.result = okResult;
    // Set B back to skipped (it already is, but ensure consistency)
    const bState = checkpoint.taskStates.find(t => t.id === 'b')!;
    bState.status = 'skipped';

    queue.restoreFromCheckpoint(checkpoint);

    // Now call unSkipDependents for task A
    queue.unSkipDependents('a');

    expect(queue.getTask('b')?.status).toBe('ready');
  });

  it('does not un-skip tasks when some dependencies are still incomplete', () => {
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [
        makeSubtask({ id: 'a', description: 'Foundation A' }),
        makeSubtask({ id: 'b', description: 'Foundation B' }),
        makeSubtask({ id: 'c', description: 'Depends on A and B', dependencies: ['a', 'b'] }),
      ],
      [['a', 'b'], ['c']],
    );

    queue.loadFromDecomposition(decomp, config);

    // Fail both A and B so C gets cascade-skipped
    queue.markDispatched('a', 'test-model');
    queue.markFailed('a', 0);
    queue.markDispatched('b', 'test-model');
    queue.markFailed('b', 0);
    expect(queue.getTask('c')?.status).toBe('skipped');

    // Recover only A via checkpoint manipulation
    const checkpoint = queue.getCheckpointState();
    const aState = checkpoint.taskStates.find(t => t.id === 'a')!;
    aState.status = 'completed';
    aState.result = okResult;
    queue.restoreFromCheckpoint(checkpoint);

    // Un-skip dependents of A -- but B is still failed, so C should stay skipped
    queue.unSkipDependents('a');

    expect(queue.getTask('c')?.status).toBe('skipped');
  });

  it('un-skips tasks when dependency is decomposed (not just completed)', () => {
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [
        makeSubtask({ id: 'a', description: 'Foundation' }),
        makeSubtask({ id: 'b', description: 'Depends on A', dependencies: ['a'] }),
      ],
      [['a'], ['b']],
    );

    queue.loadFromDecomposition(decomp, config);

    // Fail A so B is skipped
    queue.markDispatched('a', 'test-model');
    queue.markFailed('a', 0);
    expect(queue.getTask('b')?.status).toBe('skipped');

    // Set A to 'decomposed' via checkpoint
    const checkpoint = queue.getCheckpointState();
    const aState = checkpoint.taskStates.find(t => t.id === 'a')!;
    aState.status = 'decomposed';
    queue.restoreFromCheckpoint(checkpoint);

    queue.unSkipDependents('a');

    // B should become ready because 'decomposed' counts as satisfied
    expect(queue.getTask('b')?.status).toBe('ready');
  });
});

// ─── Task Queue: Failed Task Reset with Retry Budget ────────────────────────

describe('Task queue failed task reset on restore', () => {
  it('restoreFromCheckpoint preserves attempts count for retry budget tracking', () => {
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [makeSubtask({ id: 'a', description: 'Task A' })],
      [['a']],
    );

    queue.loadFromDecomposition(decomp, config);

    // Dispatch and fail twice
    queue.markDispatched('a', 'test-model'); // attempts=1
    queue.markFailed('a', 2); // retries left, back to ready
    queue.markDispatched('a', 'test-model'); // attempts=2
    queue.markFailed('a', 2); // retries left, back to ready

    expect(queue.getTask('a')?.attempts).toBe(2);

    // Take checkpoint
    const checkpoint = queue.getCheckpointState();

    // Restore into new queue
    const queue2 = createSwarmTaskQueue();
    queue2.loadFromDecomposition(decomp, config);
    queue2.restoreFromCheckpoint(checkpoint);

    // Attempts should be preserved
    expect(queue2.getTask('a')?.attempts).toBe(2);
    expect(queue2.getTask('a')?.status).toBe('ready');
  });

  it('failed task can be reset to ready via checkpoint restore for resume', () => {
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [makeSubtask({ id: 'a', description: 'Task A' })],
      [['a']],
    );

    queue.loadFromDecomposition(decomp, config);

    // Exhaust retries
    queue.markDispatched('a', 'test-model');
    queue.markFailed('a', 0); // no retries left, goes to failed
    expect(queue.getTask('a')?.status).toBe('failed');

    // On resume, orchestrator would reset failed tasks to ready with capped attempts
    const checkpoint = queue.getCheckpointState();
    const aState = checkpoint.taskStates.find(t => t.id === 'a')!;
    aState.status = 'ready';
    // Keep attempts so retry budget is partially consumed
    expect(aState.attempts).toBe(1);

    const queue2 = createSwarmTaskQueue();
    queue2.loadFromDecomposition(decomp, config);
    queue2.restoreFromCheckpoint(checkpoint);

    expect(queue2.getTask('a')?.status).toBe('ready');
    expect(queue2.getTask('a')?.attempts).toBe(1);
  });
});

// ─── SwarmCheckpoint: originalPrompt Field ──────────────────────────────────

describe('SwarmCheckpoint originalPrompt', () => {
  it('SwarmCheckpoint type accepts originalPrompt string', () => {
    const checkpoint: SwarmCheckpoint = {
      sessionId: 'test-session',
      timestamp: Date.now(),
      phase: 'executing',
      taskStates: [],
      waves: [],
      currentWave: 0,
      stats: { totalTokens: 0, totalCost: 0, qualityRejections: 0, retries: 0 },
      modelHealth: [],
      decisions: [],
      errors: [],
      originalPrompt: 'Build a REST API with authentication',
    };

    expect(checkpoint.originalPrompt).toBe('Build a REST API with authentication');
  });

  it('SwarmCheckpoint works without originalPrompt (optional field)', () => {
    const checkpoint: SwarmCheckpoint = {
      sessionId: 'test-session',
      timestamp: Date.now(),
      phase: 'completed',
      taskStates: [],
      waves: [],
      currentWave: 0,
      stats: { totalTokens: 500, totalCost: 0.01, qualityRejections: 0, retries: 1 },
      modelHealth: [],
      decisions: [],
      errors: [],
    };

    expect(checkpoint.originalPrompt).toBeUndefined();
  });
});

// ─── addReplanTasks: rescueContext ──────────────────────────────────────────

describe('addReplanTasks creates tasks with rescueContext', () => {
  it('new re-plan tasks have rescueContext "Re-planned from stalled swarm"', () => {
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [makeSubtask({ id: 'a', description: 'Task A' })],
      [['a']],
    );

    queue.loadFromDecomposition(decomp, config);

    const newTasks = queue.addReplanTasks(
      [
        { description: 'Fix stalled auth module', type: 'implement', complexity: 5, dependencies: [] },
        { description: 'Add missing tests', type: 'test', complexity: 3, dependencies: [] },
      ],
      1,
    );

    expect(newTasks).toHaveLength(2);
    for (const task of newTasks) {
      expect(task.rescueContext).toBe('Re-planned from stalled swarm');
      expect(task.status).toBe('ready');
      expect(task.attempts).toBe(1);
      expect(task.wave).toBe(1);
      expect(task.id).toMatch(/^replan-/);
    }
  });

  it('re-plan tasks are added to the specified wave', () => {
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [makeSubtask({ id: 'a', description: 'Task A' })],
      [['a']],
    );

    queue.loadFromDecomposition(decomp, config);

    queue.addReplanTasks(
      [{ description: 'Recovery task', type: 'implement', complexity: 4, dependencies: [] }],
      2,
    );

    // The queue should now have 3 waves (0, 1 implicitly, 2)
    expect(queue.getStats().total).toBe(2); // original + 1 replan
    const allTasks = queue.getAllTasks();
    const replanTask = allTasks.find(t => t.description === 'Recovery task');
    expect(replanTask).toBeDefined();
    expect(replanTask?.wave).toBe(2);
  });

  it('re-plan tasks with relevantFiles get them as targetFiles', () => {
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [makeSubtask({ id: 'a', description: 'Task A' })],
      [['a']],
    );

    queue.loadFromDecomposition(decomp, config);

    const newTasks = queue.addReplanTasks(
      [{ description: 'Fix router', type: 'implement', complexity: 4, dependencies: [], relevantFiles: ['src/router.ts', 'src/routes/index.ts'] }],
      1,
    );

    expect(newTasks[0].targetFiles).toEqual(['src/router.ts', 'src/routes/index.ts']);
  });

  it('re-plan tasks with dependencies reference existing task IDs', () => {
    const queue = createSwarmTaskQueue();
    const decomp = makeDecomposition(
      [
        makeSubtask({ id: 'a', description: 'Task A' }),
        makeSubtask({ id: 'b', description: 'Task B' }),
      ],
      [['a', 'b']],
    );

    queue.loadFromDecomposition(decomp, config);

    const newTasks = queue.addReplanTasks(
      [{ description: 'Integrate A and B', type: 'integrate', complexity: 6, dependencies: ['a', 'b'] }],
      1,
    );

    expect(newTasks[0].dependencies).toEqual(['a', 'b']);
  });
});
