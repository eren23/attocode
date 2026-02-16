/**
 * Tests for SwarmStateStore and task queue checkpoint/restore
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as os from 'node:os';
import { SwarmStateStore } from '../../src/integrations/swarm/swarm-state-store.js';
import { createSwarmTaskQueue } from '../../src/integrations/swarm/task-queue.js';
import { DEFAULT_SWARM_CONFIG } from '../../src/integrations/swarm/types.js';
import type { SwarmCheckpoint, SwarmConfig } from '../../src/integrations/swarm/types.js';
import type { SmartDecompositionResult, SmartSubtask, DependencyGraph } from '../../src/integrations/tasks/smart-decomposer.js';

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

let tmpDir: string;

beforeEach(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'swarm-test-'));
});

afterEach(() => {
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

describe('SwarmStateStore', () => {
  it('should save and load a checkpoint', () => {
    const store = new SwarmStateStore(tmpDir, 'test-session');

    const checkpoint: SwarmCheckpoint = {
      sessionId: 'test-session',
      timestamp: Date.now(),
      phase: 'executing',
      taskStates: [
        { id: 'a', status: 'completed', attempts: 1, wave: 0 },
        { id: 'b', status: 'ready', attempts: 0, wave: 1 },
      ],
      waves: [['a'], ['b']],
      currentWave: 1,
      stats: { totalTokens: 1000, totalCost: 0.01, qualityRejections: 0, retries: 0 },
      modelHealth: [],
      decisions: [],
      errors: [],
    };

    store.saveCheckpoint(checkpoint);

    const loaded = SwarmStateStore.loadLatest(tmpDir, 'test-session');
    expect(loaded).not.toBeNull();
    expect(loaded!.sessionId).toBe('test-session');
    expect(loaded!.taskStates.length).toBe(2);
    expect(loaded!.currentWave).toBe(1);
    expect(loaded!.stats.totalTokens).toBe(1000);
  });

  it('should return null for non-existent session', () => {
    const loaded = SwarmStateStore.loadLatest(tmpDir, 'non-existent');
    expect(loaded).toBeNull();
  });

  it('should list sessions sorted by recency', () => {
    const store1 = new SwarmStateStore(tmpDir, 'session-old');
    store1.saveCheckpoint({
      sessionId: 'session-old', timestamp: Date.now() - 1000, phase: 'completed',
      taskStates: [], waves: [], currentWave: 0,
      stats: { totalTokens: 0, totalCost: 0, qualityRejections: 0, retries: 0 },
      modelHealth: [], decisions: [], errors: [],
    });

    const store2 = new SwarmStateStore(tmpDir, 'session-new');
    store2.saveCheckpoint({
      sessionId: 'session-new', timestamp: Date.now(), phase: 'executing',
      taskStates: [], waves: [], currentWave: 0,
      stats: { totalTokens: 0, totalCost: 0, qualityRejections: 0, retries: 0 },
      modelHealth: [], decisions: [], errors: [],
    });

    const sessions = SwarmStateStore.listSessions(tmpDir);
    expect(sessions.length).toBe(2);
    expect(sessions[0].sessionId).toBe('session-new'); // Most recent first
  });

  it('should generate a session ID if not provided', () => {
    const store = new SwarmStateStore(tmpDir);
    expect(store.id).toMatch(/^swarm-/);
  });
});

describe('SwarmCheckpoint with shared state', () => {
  it('saves and loads checkpoint with sharedContext and sharedEconomics fields', () => {
    const store = new SwarmStateStore(tmpDir, 'shared-state-session');

    const checkpoint: SwarmCheckpoint = {
      sessionId: 'shared-state-session',
      timestamp: Date.now(),
      phase: 'executing',
      taskStates: [{ id: 'a', status: 'completed', attempts: 1, wave: 0 }],
      waves: [['a']],
      currentWave: 0,
      stats: { totalTokens: 5000, totalCost: 0.05, qualityRejections: 0, retries: 0 },
      modelHealth: [],
      decisions: [],
      errors: [],
      sharedContext: {
        failures: [{ id: 'f1', action: '[w1] bash', error: 'exit 1', timestamp: '2024-01-01', category: 'runtime', resolved: false, repeatCount: 0 }],
        references: [['file:/src/a.ts', { id: 'r1', type: 'file', value: '/src/a.ts', timestamp: '2024-01-01' }]],
        staticPrefix: 'You are a swarm worker agent.',
      },
      sharedEconomics: {
        fingerprints: [
          { fingerprint: 'read_file:/src/a.ts', count: 3, workers: ['w1', 'w2'] },
          { fingerprint: 'bash:npm test', count: 7, workers: ['w1', 'w2', 'w3'] },
        ],
      },
    };

    store.saveCheckpoint(checkpoint);

    const loaded = SwarmStateStore.loadLatest(tmpDir, 'shared-state-session');
    expect(loaded).not.toBeNull();
    expect(loaded!.sharedContext).toBeDefined();
    expect(loaded!.sharedContext!.failures).toHaveLength(1);
    expect(loaded!.sharedContext!.references).toHaveLength(1);
    expect(loaded!.sharedContext!.staticPrefix).toBe('You are a swarm worker agent.');
    expect(loaded!.sharedEconomics).toBeDefined();
    expect(loaded!.sharedEconomics!.fingerprints).toHaveLength(2);
    expect(loaded!.sharedEconomics!.fingerprints[0].fingerprint).toBe('read_file:/src/a.ts');
    expect(loaded!.sharedEconomics!.fingerprints[1].workers).toEqual(['w1', 'w2', 'w3']);
  });

  it('backward compatibility: old checkpoint without shared state loads correctly', () => {
    const store = new SwarmStateStore(tmpDir, 'old-session');

    // Old-style checkpoint without sharedContext or sharedEconomics
    const checkpoint: SwarmCheckpoint = {
      sessionId: 'old-session',
      timestamp: Date.now(),
      phase: 'completed',
      taskStates: [],
      waves: [],
      currentWave: 0,
      stats: { totalTokens: 0, totalCost: 0, qualityRejections: 0, retries: 0 },
      modelHealth: [],
      decisions: [],
      errors: [],
    };

    store.saveCheckpoint(checkpoint);

    const loaded = SwarmStateStore.loadLatest(tmpDir, 'old-session');
    expect(loaded).not.toBeNull();
    expect(loaded!.sharedContext).toBeUndefined();
    expect(loaded!.sharedEconomics).toBeUndefined();
  });
});

describe('TaskQueue checkpoint/restore', () => {
  it('should export and restore checkpoint state', () => {
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
    queue.markCompleted('a', {
      success: true, output: 'Done', tokensUsed: 100, costUsed: 0.001, durationMs: 1000, model: 'test',
    });
    queue.advanceWave();

    // Export checkpoint
    const checkpoint = queue.getCheckpointState();
    expect(checkpoint.currentWave).toBe(1);
    expect(checkpoint.taskStates.find(t => t.id === 'a')?.status).toBe('completed');

    // Restore into a fresh queue
    const queue2 = createSwarmTaskQueue();
    queue2.loadFromDecomposition(decomp, config);
    queue2.restoreFromCheckpoint(checkpoint);

    expect(queue2.getCurrentWave()).toBe(1);
    expect(queue2.getTask('a')?.status).toBe('completed');
  });
});
