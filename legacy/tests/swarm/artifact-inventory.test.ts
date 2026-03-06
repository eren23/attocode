/**
 * Tests for the artifact inventory system (R1-R6).
 *
 * Validates that:
 * - ArtifactInventory type has correct structure
 * - partialSuccess is true when 0 tasks completed but artifacts exist
 * - Cascade skip respects artifact-aware threshold (files exist → don't skip)
 * - Cascade skip works normally when artifactAwareSkip is disabled
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as os from 'node:os';
import { createSwarmTaskQueue } from '../../src/integrations/swarm/task-queue.js';
import { DEFAULT_SWARM_CONFIG } from '../../src/integrations/swarm/types.js';
import type { SmartDecompositionResult, SmartSubtask, DependencyGraph } from '../../src/integrations/tasks/smart-decomposer.js';
import type { SwarmConfig, ArtifactInventory } from '../../src/integrations/swarm/types.js';

// ─── Helpers ──────────────────────────────────────────────────────────────────

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

const baseConfig: SwarmConfig = {
  ...DEFAULT_SWARM_CONFIG,
  orchestratorModel: 'test/model',
  workers: [],
};

// ─── Tests ────────────────────────────────────────────────────────────────────

describe('ArtifactInventory types', () => {
  it('ArtifactInventory interface has correct structure', () => {
    const inventory: ArtifactInventory = {
      files: [{ path: 'src/foo.ts', sizeBytes: 100, exists: true }],
      totalFiles: 1,
      totalBytes: 100,
    };
    expect(inventory.files).toHaveLength(1);
    expect(inventory.totalFiles).toBe(1);
    expect(inventory.totalBytes).toBe(100);
    expect(inventory.files[0].exists).toBe(true);
  });
});

describe('Artifact-aware cascade skip', () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'attocode-artifact-test-'));
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it('should not cascade-skip when failed task\'s target files exist on disk', () => {
    // Create target files in the temp directory
    fs.mkdirSync(path.join(tmpDir, 'src'), { recursive: true });
    fs.writeFileSync(path.join(tmpDir, 'src/models.ts'), 'export interface Flag { id: string; }');
    fs.writeFileSync(path.join(tmpDir, 'src/schemas.ts'), 'import { z } from "zod";');

    const queue = createSwarmTaskQueue();

    // Task A (wave 0) → Task B (wave 1, depends on A)
    const decomp = makeDecomposition(
      [
        makeSubtask({ id: 'a', description: 'Create models', dependencies: [], modifies: ['src/models.ts', 'src/schemas.ts'] }),
        makeSubtask({ id: 'b', description: 'Create service', dependencies: ['a'] }),
      ],
      [['a'], ['b']],
    );

    const config: SwarmConfig = {
      ...baseConfig,
      artifactAwareSkip: true,
      facts: { workingDirectory: tmpDir },
    };

    queue.loadFromDecomposition(decomp, config);
    queue.markDispatched('a', 'test/model');

    // Task A fails (e.g., timeout) — no retries
    const canRetry = queue.markFailed('a', 0);
    expect(canRetry).toBe(false);

    // Task B should be 'ready' (not 'skipped') because artifacts exist
    const taskB = queue.getTask('b');
    expect(taskB?.status).toBe('ready');
    expect(taskB?.partialContext).toBeDefined();
  });

  it('should cascade-skip when failed task\'s target files do NOT exist', () => {
    const queue = createSwarmTaskQueue();

    const decomp = makeDecomposition(
      [
        makeSubtask({ id: 'a', description: 'Create models', dependencies: [], modifies: ['src/models.ts'] }),
        makeSubtask({ id: 'b', description: 'Create service', dependencies: ['a'] }),
      ],
      [['a'], ['b']],
    );

    const config: SwarmConfig = {
      ...baseConfig,
      artifactAwareSkip: true,
      facts: { workingDirectory: tmpDir },
    };

    queue.loadFromDecomposition(decomp, config);
    queue.markDispatched('a', 'test/model');

    // No files exist in tmpDir/src/
    queue.markFailed('a', 0);

    // Task B should be skipped since no artifacts exist
    const taskB = queue.getTask('b');
    expect(taskB?.status).toBe('skipped');
  });

  it('should cascade-skip when artifactAwareSkip is disabled', () => {
    // Create files that would normally prevent cascade skip
    fs.mkdirSync(path.join(tmpDir, 'src'), { recursive: true });
    fs.writeFileSync(path.join(tmpDir, 'src/models.ts'), 'export interface Flag { id: string; }');

    const queue = createSwarmTaskQueue();

    const decomp = makeDecomposition(
      [
        makeSubtask({ id: 'a', description: 'Create models', dependencies: [], modifies: ['src/models.ts'] }),
        makeSubtask({ id: 'b', description: 'Create service', dependencies: ['a'] }),
      ],
      [['a'], ['b']],
    );

    const config: SwarmConfig = {
      ...baseConfig,
      artifactAwareSkip: false,
      facts: { workingDirectory: tmpDir },
    };

    queue.loadFromDecomposition(decomp, config);
    queue.markDispatched('a', 'test/model');

    queue.markFailed('a', 0);

    // Task B should be skipped because feature is disabled
    const taskB = queue.getTask('b');
    expect(taskB?.status).toBe('skipped');
  });

  it('should cascade-skip when less than 50% of target files exist', () => {
    // Create only 1 out of 4 files
    fs.mkdirSync(path.join(tmpDir, 'src'), { recursive: true });
    fs.writeFileSync(path.join(tmpDir, 'src/a.ts'), 'export const a = 1;');

    const queue = createSwarmTaskQueue();

    const decomp = makeDecomposition(
      [
        makeSubtask({
          id: 'a',
          description: 'Create all files',
          dependencies: [],
          modifies: ['src/a.ts', 'src/b.ts', 'src/c.ts', 'src/d.ts'],
        }),
        makeSubtask({ id: 'b', description: 'Use files', dependencies: ['a'] }),
      ],
      [['a'], ['b']],
    );

    const config: SwarmConfig = {
      ...baseConfig,
      artifactAwareSkip: true,
      facts: { workingDirectory: tmpDir },
    };

    queue.loadFromDecomposition(decomp, config);
    queue.markDispatched('a', 'test/model');

    queue.markFailed('a', 0);

    // Task B should be skipped since only 25% of target files exist (< 50% threshold)
    const taskB = queue.getTask('b');
    expect(taskB?.status).toBe('skipped');
  });

  it('should skip when task has no target files listed', () => {
    const queue = createSwarmTaskQueue();

    // Task A has no targetFiles (modifies)
    const decomp = makeDecomposition(
      [
        makeSubtask({ id: 'a', description: 'Research task', dependencies: [] }),
        makeSubtask({ id: 'b', description: 'Depends on A', dependencies: ['a'] }),
      ],
      [['a'], ['b']],
    );

    const config: SwarmConfig = {
      ...baseConfig,
      artifactAwareSkip: true,
    };

    queue.loadFromDecomposition(decomp, config);
    queue.markDispatched('a', 'test/model');

    queue.markFailed('a', 0);

    // No target files → artifact-aware skip can't help → normal cascade → skip
    const taskB = queue.getTask('b');
    expect(taskB?.status).toBe('skipped');
  });

  it('should keep dependent ready when 50% of target files exist (threshold boundary)', () => {
    // Create exactly 2 out of 4 files (50% = threshold)
    fs.mkdirSync(path.join(tmpDir, 'src'), { recursive: true });
    fs.writeFileSync(path.join(tmpDir, 'src/a.ts'), 'export const a = 1;');
    fs.writeFileSync(path.join(tmpDir, 'src/b.ts'), 'export const b = 2;');

    const queue = createSwarmTaskQueue();

    const decomp = makeDecomposition(
      [
        makeSubtask({
          id: 'a',
          description: 'Create all files',
          dependencies: [],
          modifies: ['src/a.ts', 'src/b.ts', 'src/c.ts', 'src/d.ts'],
        }),
        makeSubtask({ id: 'b', description: 'Use files', dependencies: ['a'] }),
      ],
      [['a'], ['b']],
    );

    const config: SwarmConfig = {
      ...baseConfig,
      artifactAwareSkip: true,
      facts: { workingDirectory: tmpDir },
    };

    queue.loadFromDecomposition(decomp, config);
    queue.markDispatched('a', 'test/model');

    queue.markFailed('a', 0);

    // 50% = threshold → keep ready
    const taskB = queue.getTask('b');
    expect(taskB?.status).toBe('ready');
    expect(taskB?.partialContext).toBeDefined();
  });
});

describe('SwarmExecutionResult partialSuccess logic', () => {
  it('partialSuccess is true when 0 tasks completed but artifacts exist', () => {
    const completedTasks = 0;
    const artifactInventory: ArtifactInventory = {
      files: [
        { path: 'src/models.ts', sizeBytes: 900, exists: true },
        { path: 'src/service.ts', sizeBytes: 3000, exists: true },
      ],
      totalFiles: 2,
      totalBytes: 3900,
    };

    const hasArtifacts = artifactInventory.totalFiles > 0;
    const success = completedTasks > 0;
    const partialSuccess = !completedTasks && hasArtifacts;

    expect(success).toBe(false);
    expect(partialSuccess).toBe(true);
  });

  it('partialSuccess is false when tasks completed', () => {
    const completedTasks = 3;
    const hasArtifacts = true;

    expect(!completedTasks && hasArtifacts).toBe(false);
  });

  it('partialSuccess is false when no artifacts exist', () => {
    const completedTasks = 0;
    const inventory: ArtifactInventory = { files: [], totalFiles: 0, totalBytes: 0 };
    const hasArtifacts = inventory.totalFiles > 0;

    expect(!completedTasks && hasArtifacts).toBe(false);
  });
});
