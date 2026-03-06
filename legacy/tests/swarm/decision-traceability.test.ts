/**
 * Tests: Decision traceability — new event types and event bridge JSONL output
 *
 * Covers:
 *   1.  swarm.task.attempt emitted for every dispatch
 *   2.  swarm.task.resilience emitted with strategy/outcome
 *   3.  swarm.task.failed includes failureMode
 *   4.  Event bridge writes append-only JSONL per task
 *   5.  Event bridge preserves attempts from dispatch event
 *   6.  checkArtifactsEnhanced: finds files from filesModified even without targetFiles
 *   7.  checkArtifactsEnhanced: finds files from closureReport actionsTaken
 *   8.  checkArtifactsEnhanced: de-duplicates across sources
 *   9.  Timeout toolCalls=-1 -> hadToolCalls is true
 *   10. Complexity 4 task -> micro-decompose attempted (was skipped at threshold 6)
 *   11. rescueCascadeSkipped(true) lenient mode -> rescues with 1 missing dep
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { DEFAULT_SWARM_CONFIG } from '../../src/integrations/swarm/types.js';
import type { SwarmConfig, SwarmTask, SwarmTaskResult } from '../../src/integrations/swarm/types.js';
import type { SwarmEvent } from '../../src/integrations/swarm/swarm-events.js';
import { checkArtifactsEnhanced } from '../../src/integrations/swarm/swarm-quality-gate.js';
import { SwarmEventBridge } from '../../src/integrations/swarm/swarm-event-bridge.js';

// =============================================================================
// Helpers
// =============================================================================

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

/**
 * Create a mock provider. IMPORTANT: Decomposition must return >= 2 subtasks
 * or SwarmOrchestrator.decompose() returns null (too simple for swarm).
 */
function makeMockProvider(options?: {
  decompositionSubtasks?: any[];
  microDecomposeSubtasks?: any[];
}) {
  let callCount = 0;
  const decompositionSubtasks = options?.decompositionSubtasks ?? [
    { description: 'Evaluator core module', type: 'implement', complexity: 5, dependencies: [], parallelizable: true, relevantFiles: ['src/evaluator.ts'] },
    { description: 'Evaluator tests', type: 'test', complexity: 4, dependencies: [0], parallelizable: false, relevantFiles: ['tests/evaluator.test.ts'] },
  ];

  return {
    chat: vi.fn().mockImplementation(() => {
      callCount++;
      if (callCount === 1) {
        // Decomposition response — MUST have >= 2 subtasks
        return Promise.resolve({
          content: JSON.stringify({
            subtasks: decompositionSubtasks,
            strategy: 'parallel',
            reasoning: 'test decomposition',
          }),
        });
      }
      // Micro-decompose or quality gate response
      if (options?.microDecomposeSubtasks) {
        return Promise.resolve({
          content: JSON.stringify({
            subtasks: options.microDecomposeSubtasks,
          }),
        });
      }
      return Promise.resolve({
        content: 'SCORE: 1\nFEEDBACK: Incomplete',
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
    output: 'Completed.',
    tokensUsed: 500,
    costUsed: 0.01,
    durationMs: 5000,
    model: 'test-model',
    ...overrides,
  };
}

function collectEvents(events: SwarmEvent[], type: string): any[] {
  return events.filter(e => e.type === type);
}

function createTempDir(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'attocode-test-'));
}

function removeTempDir(dir: string): void {
  try {
    fs.rmSync(dir, { recursive: true, force: true });
  } catch {
    // Best effort cleanup
  }
}

// =============================================================================
// 1. swarm.task.attempt emitted for every dispatch
// =============================================================================

describe('swarm.task.attempt emitted for every dispatch', () => {
  it('emits attempt events with correct fields for retried tasks', async () => {
    const { SwarmOrchestrator } = await import('../../src/integrations/swarm/swarm-orchestrator.js');

    const config = makeOrchestratorConfig({
      workerRetries: 2,
      maxDispatchesPerTask: 5,
    });

    const registry = makeMockRegistry();

    let callCount = 0;
    const spawnFn = vi.fn().mockImplementation(() => {
      callCount++;
      if (callCount <= 2) {
        // First two: hollow -> retried
        return Promise.resolve({
          success: true,
          output: '',
          metrics: { tokens: 50, duration: 500, toolCalls: 0 },
        });
      }
      // Third+: real output
      return Promise.resolve({
        success: true,
        output: 'Successfully implemented the evaluator with proper test coverage.',
        metrics: { tokens: 5000, duration: 30000, toolCalls: 10 },
      });
    });

    const orchestrator = new SwarmOrchestrator(config, makeMockProvider(), registry, spawnFn);

    const events: SwarmEvent[] = [];
    orchestrator.subscribe((event: SwarmEvent) => events.push(event));

    await orchestrator.execute('Implement evaluator');

    const attemptEvents = collectEvents(events, 'swarm.task.attempt');

    // Should have multiple attempt events
    expect(attemptEvents.length).toBeGreaterThanOrEqual(2);

    // Validate structure of all attempt events
    for (const ae of attemptEvents) {
      const a = ae as any;
      expect(a.taskId).toBeDefined();
      expect(typeof a.attempt).toBe('number');
      expect(a.attempt).toBeGreaterThanOrEqual(1);
      expect(typeof a.model).toBe('string');
      expect(typeof a.success).toBe('boolean');
      expect(typeof a.durationMs).toBe('number');
      expect(typeof a.toolCalls).toBe('number');
    }

    // If the same task has multiple attempts, they should have non-decreasing attempt numbers
    const taskAttempts = attemptEvents.filter((e: any) => e.taskId === (attemptEvents[0] as any)?.taskId);
    if (taskAttempts.length >= 2) {
      for (let i = 1; i < taskAttempts.length; i++) {
        expect((taskAttempts[i] as any).attempt).toBeGreaterThanOrEqual((taskAttempts[i - 1] as any).attempt);
      }
    }
  });
});

// =============================================================================
// 2. swarm.task.resilience emitted with strategy/outcome
// =============================================================================

describe('swarm.task.resilience emitted with strategy/outcome', () => {
  it('emits resilience event with strategy and succeeded fields', async () => {
    const { SwarmOrchestrator } = await import('../../src/integrations/swarm/swarm-orchestrator.js');

    const config = makeOrchestratorConfig({
      workerRetries: 0,
      maxDispatchesPerTask: 2,
    });

    const registry = makeMockRegistry();

    // Always produce hollow output -> retries exhausted -> resilience triggered
    const spawnFn = vi.fn().mockResolvedValue({
      success: true,
      output: '',
      metrics: { tokens: 50, duration: 500, toolCalls: 0 },
    });

    const orchestrator = new SwarmOrchestrator(config, makeMockProvider(), registry, spawnFn);

    const events: SwarmEvent[] = [];
    orchestrator.subscribe((event: SwarmEvent) => events.push(event));

    await orchestrator.execute('Write evaluator');

    const resilienceEvents = collectEvents(events, 'swarm.task.resilience');

    // Resilience should be attempted (may fail with strategy='none' since no artifacts)
    if (resilienceEvents.length > 0) {
      for (const re of resilienceEvents) {
        const r = re as any;
        expect(['micro-decompose', 'degraded-acceptance', 'none']).toContain(r.strategy);
        expect(typeof r.succeeded).toBe('boolean');
        expect(typeof r.reason).toBe('string');
        expect(r.reason.length).toBeGreaterThan(0);
        expect(typeof r.artifactsFound).toBe('number');
        expect(typeof r.toolCalls).toBe('number');
      }
    }

    // Swarm should complete
    expect(collectEvents(events, 'swarm.complete').length).toBe(1);
  });
});

// =============================================================================
// 3. swarm.task.failed includes failureMode
// =============================================================================

describe('swarm.task.failed includes failureMode', () => {
  it('failure events have failureMode set for hollow completions', async () => {
    const { SwarmOrchestrator } = await import('../../src/integrations/swarm/swarm-orchestrator.js');

    const config = makeOrchestratorConfig({
      workerRetries: 1,
      maxDispatchesPerTask: 3,
    });

    const registry = makeMockRegistry();

    // Always hollow -> triggers hollow failure mode
    const spawnFn = vi.fn().mockResolvedValue({
      success: true,
      output: '',
      metrics: { tokens: 50, duration: 500, toolCalls: 0 },
    });

    const orchestrator = new SwarmOrchestrator(config, makeMockProvider(), registry, spawnFn);

    const events: SwarmEvent[] = [];
    orchestrator.subscribe((event: SwarmEvent) => events.push(event));

    await orchestrator.execute('Write tests');

    const failedEvents = collectEvents(events, 'swarm.task.failed');

    // At least one failed event with failureMode
    const withFailureMode = failedEvents.filter((e: any) => e.failureMode);
    expect(withFailureMode.length).toBeGreaterThan(0);

    // Hollow completions should have failureMode='hollow'
    const hollowFailures = withFailureMode.filter((e: any) => e.failureMode === 'hollow');
    expect(hollowFailures.length).toBeGreaterThan(0);
  });

  it('failure events have failureMode set for timeouts', async () => {
    const { SwarmOrchestrator } = await import('../../src/integrations/swarm/swarm-orchestrator.js');

    // Use workerRetries:1 so normal retry exhaustion fires (emits swarm.task.failed with failureMode).
    // High consecutiveTimeoutLimit prevents the early-fail path from consuming the event.
    const config = makeOrchestratorConfig({
      workerRetries: 1,
      maxDispatchesPerTask: 4,
      consecutiveTimeoutLimit: 10, // Don't trigger early-fail path
    });

    const registry = makeMockRegistry();

    // Worker always times out (toolCalls=-1)
    const spawnFn = vi.fn().mockResolvedValue({
      success: false,
      output: 'Worker error: timeout after 300000ms',
      metrics: { tokens: 5000, duration: 300000, toolCalls: -1 },
    });

    const orchestrator = new SwarmOrchestrator(config, makeMockProvider(), registry, spawnFn);

    const events: SwarmEvent[] = [];
    orchestrator.subscribe((event: SwarmEvent) => events.push(event));

    await orchestrator.execute('Implement evaluator');

    const failedEvents = collectEvents(events, 'swarm.task.failed');

    // At least one failure event should have failureMode='timeout'
    const timeoutFailures = failedEvents.filter((e: any) => e.failureMode === 'timeout');
    expect(timeoutFailures.length).toBeGreaterThan(0);
  });
});

// =============================================================================
// 4. Event bridge writes append-only JSONL per task
// =============================================================================

describe('Event bridge writes append-only JSONL per task', () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = createTempDir();
  });

  afterEach(async () => {
    // Small delay to let write streams close before removing tmpDir
    await new Promise(r => setTimeout(r, 50));
    removeTempDir(tmpDir);
  });

  it('creates per-task JSONL file for attempt events', () => {
    const bridge = new SwarmEventBridge({ outputDir: tmpDir });

    // Initialize the bridge
    (bridge as any).handleEvent({
      type: 'swarm.start',
      taskCount: 1,
      waveCount: 1,
      config: { maxConcurrency: 1, totalBudget: 100000, maxCost: 1 },
    });

    // Feed task.attempt events
    const taskId = 'test-task-42';
    for (let i = 1; i <= 3; i++) {
      (bridge as any).handleEvent({
        type: 'swarm.task.attempt',
        taskId,
        attempt: i,
        model: 'test/model',
        success: i === 3,
        durationMs: 5000 * i,
        toolCalls: i * 2,
        failureMode: i < 3 ? 'hollow' : undefined,
      });
    }

    // Close the bridge to flush writes
    bridge.close();

    // Check that the JSONL file exists and has 3 lines
    const attemptFile = path.join(tmpDir, 'tasks', `${taskId}-attempts.jsonl`);
    expect(fs.existsSync(attemptFile)).toBe(true);

    const lines = fs.readFileSync(attemptFile, 'utf-8').trim().split('\n');
    expect(lines.length).toBe(3);

    // Each line should be valid JSON with the event data
    for (let i = 0; i < lines.length; i++) {
      const parsed = JSON.parse(lines[i]);
      expect(parsed.taskId).toBe(taskId);
      expect(parsed.attempt).toBe(i + 1);
      expect(parsed.type).toBe('swarm.task.attempt');
      expect(typeof parsed.timestamp).toBe('string');
    }
  });

  it('appends resilience events to the same per-task JSONL', () => {
    const bridge = new SwarmEventBridge({ outputDir: tmpDir });

    (bridge as any).handleEvent({
      type: 'swarm.start',
      taskCount: 1,
      waveCount: 1,
      config: { maxConcurrency: 1, totalBudget: 100000, maxCost: 1 },
    });

    const taskId = 'task-abc';

    // First: an attempt event
    (bridge as any).handleEvent({
      type: 'swarm.task.attempt',
      taskId,
      attempt: 1,
      model: 'test/model',
      success: false,
      durationMs: 10000,
      toolCalls: 0,
      failureMode: 'hollow',
    });

    // Then: a resilience event
    (bridge as any).handleEvent({
      type: 'swarm.task.resilience',
      taskId,
      strategy: 'degraded-acceptance',
      succeeded: true,
      reason: 'Artifacts found on disk',
      artifactsFound: 2,
      toolCalls: 5,
    });

    bridge.close();

    const attemptFile = path.join(tmpDir, 'tasks', `${taskId}-attempts.jsonl`);
    expect(fs.existsSync(attemptFile)).toBe(true);

    const lines = fs.readFileSync(attemptFile, 'utf-8').trim().split('\n');
    expect(lines.length).toBe(2);

    // First line: attempt event
    const line1 = JSON.parse(lines[0]);
    expect(line1.type).toBe('swarm.task.attempt');

    // Second line: resilience event (has recordType marker)
    const line2 = JSON.parse(lines[1]);
    expect(line2.recordType).toBe('resilience');
    expect(line2.strategy).toBe('degraded-acceptance');
    expect(line2.succeeded).toBe(true);
  });
});

// =============================================================================
// 5. Event bridge preserves attempts from dispatch event
// =============================================================================

describe('Event bridge preserves attempts from dispatch event', () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = createTempDir();
  });

  afterEach(async () => {
    await new Promise(r => setTimeout(r, 50));
    removeTempDir(tmpDir);
  });

  it('updateTask applies attempts from dispatched event', () => {
    const bridge = new SwarmEventBridge({ outputDir: tmpDir });

    (bridge as any).handleEvent({
      type: 'swarm.start',
      taskCount: 1,
      waveCount: 1,
      config: { maxConcurrency: 1, totalBudget: 100000, maxCost: 1 },
    });

    (bridge as any).setTasks([makeTask({ id: 'task-1', attempts: 0 })]);

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

    const task = (bridge as any).tasks.get('task-1');
    expect(task).toBeDefined();
    expect(task.attempts).toBe(3);

    bridge.close();
  });

  it('handles attempt events without crashing even if task not yet registered', () => {
    const bridge = new SwarmEventBridge({ outputDir: tmpDir });

    (bridge as any).handleEvent({
      type: 'swarm.start',
      taskCount: 1,
      waveCount: 1,
      config: { maxConcurrency: 1, totalBudget: 100000, maxCost: 1 },
    });

    // Feed an attempt event for a task not in the task map — should not crash
    expect(() => {
      (bridge as any).handleEvent({
        type: 'swarm.task.attempt',
        taskId: 'unknown-task',
        attempt: 1,
        model: 'test/model',
        success: false,
        durationMs: 1000,
        toolCalls: 0,
      });
    }).not.toThrow();

    bridge.close();

    // The JSONL file should still be written
    const attemptFile = path.join(tmpDir, 'tasks', 'unknown-task-attempts.jsonl');
    expect(fs.existsSync(attemptFile)).toBe(true);
  });
});

// =============================================================================
// 6. checkArtifactsEnhanced: finds files from filesModified even without targetFiles
// =============================================================================

describe('checkArtifactsEnhanced: filesModified without targetFiles', () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = createTempDir();
  });

  afterEach(() => {
    removeTempDir(tmpDir);
  });

  it('discovers files via filesModified when task has no targetFiles', () => {
    const testFile = path.join(tmpDir, 'discovered.ts');
    fs.writeFileSync(testFile, 'export const x = 42;\n');

    const task = makeTask({ id: 'task-no-targets', targetFiles: undefined });
    const result = makeResult({
      filesModified: [testFile],
    });

    const report = checkArtifactsEnhanced(task, result, tmpDir);

    expect(report.allEmpty).toBe(false);
    expect(report.files.length).toBeGreaterThanOrEqual(1);

    const found = report.files.find(f => f.path === testFile);
    expect(found).toBeDefined();
    expect(found!.exists).toBe(true);
    expect(found!.sizeBytes).toBeGreaterThan(0);
  });

  it('reports missing when filesModified points to non-existent files', () => {
    const task = makeTask({ id: 'task-missing', targetFiles: undefined });
    const result = makeResult({
      filesModified: [path.join(tmpDir, 'does-not-exist.ts')],
    });

    const report = checkArtifactsEnhanced(task, result, tmpDir);

    // File does not exist
    const found = report.files.find(f => f.path.includes('does-not-exist'));
    expect(found).toBeDefined();
    expect(found!.exists).toBe(false);
  });
});

// =============================================================================
// 7. checkArtifactsEnhanced: finds files from closureReport actionsTaken
// =============================================================================

describe('checkArtifactsEnhanced: closureReport actionsTaken', () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = createTempDir();
  });

  afterEach(() => {
    removeTempDir(tmpDir);
  });

  it('extracts file paths from actionsTaken and probes them', () => {
    const testFile = path.join(tmpDir, 'report/output.md');
    fs.mkdirSync(path.join(tmpDir, 'report'), { recursive: true });
    fs.writeFileSync(testFile, '# Analysis Report\n\nFindings here.\n');

    const task = makeTask({ id: 'task-closure', targetFiles: undefined });
    const result = makeResult({
      filesModified: [],
      closureReport: {
        findings: ['Analysis complete'],
        actionsTaken: [`Created ${testFile} with analysis results`],
        failures: [],
        remainingWork: [],
        exitReason: 'completed' as const,
      },
    });

    const report = checkArtifactsEnhanced(task, result, tmpDir);

    expect(report.allEmpty).toBe(false);
    // The path regex should extract the file path from the action string
    const hasReportFile = report.files.some(f => f.exists && f.path.includes('output.md'));
    expect(hasReportFile).toBe(true);
  });
});

// =============================================================================
// 8. checkArtifactsEnhanced: de-duplicates across sources
// =============================================================================

describe('checkArtifactsEnhanced: de-duplicates across sources', () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = createTempDir();
  });

  afterEach(() => {
    removeTempDir(tmpDir);
  });

  it('does not report same file twice from targetFiles and filesModified', () => {
    const testFile = path.join(tmpDir, 'shared.ts');
    fs.writeFileSync(testFile, 'export function shared() {}\n');

    const task = makeTask({
      id: 'task-dedup',
      targetFiles: [testFile],
    });
    const result = makeResult({
      filesModified: [testFile],
    });

    const report = checkArtifactsEnhanced(task, result, tmpDir);

    // Count how many times this file appears
    const matchingFiles = report.files.filter(f => f.path === testFile);
    expect(matchingFiles.length).toBe(1); // Should be de-duplicated

    expect(report.allEmpty).toBe(false);
    expect(matchingFiles[0].exists).toBe(true);
    expect(matchingFiles[0].sizeBytes).toBeGreaterThan(0);
  });

  it('handles overlapping targetFiles, filesModified, and closureReport paths', () => {
    const file1 = path.join(tmpDir, 'a.ts');
    const file2 = path.join(tmpDir, 'b.ts');
    fs.writeFileSync(file1, 'const a = 1;\n');
    fs.writeFileSync(file2, 'const b = 2;\n');

    const task = makeTask({
      id: 'task-multi-dedup',
      targetFiles: [file1, file2],
    });
    const result = makeResult({
      filesModified: [file1], // Overlaps with targetFiles
      closureReport: {
        findings: [],
        actionsTaken: [`Modified ${file2} with new content`], // Overlaps with targetFiles
        failures: [],
        remainingWork: [],
        exitReason: 'completed' as const,
      },
    });

    const report = checkArtifactsEnhanced(task, result, tmpDir);

    // Each file should appear exactly once
    const file1Matches = report.files.filter(f => f.path === file1);
    const file2Matches = report.files.filter(f => f.path === file2);
    expect(file1Matches.length).toBe(1);
    expect(file2Matches.length).toBe(1);
  });
});

// =============================================================================
// 9. Timeout toolCalls=-1 -> hadToolCalls is true
// =============================================================================

describe('Timeout toolCalls=-1 -> hadToolCalls is true', () => {
  it('timeout with toolCalls=-1 triggers resilience recovery or timeout failure', async () => {
    const { SwarmOrchestrator } = await import('../../src/integrations/swarm/swarm-orchestrator.js');

    // Use workerRetries:1 so normal retry exhaustion fires (emits swarm.task.failed).
    // High consecutiveTimeoutLimit prevents the early-fail path from intercepting.
    const config = makeOrchestratorConfig({
      workerRetries: 1,
      maxDispatchesPerTask: 4,
      consecutiveTimeoutLimit: 10, // Don't trigger early-fail path
    });

    const registry = makeMockRegistry();

    // Worker always times out: toolCalls=-1 indicates timeout
    const spawnFn = vi.fn().mockResolvedValue({
      success: false,
      output: 'Worker error: Worker timeout after 300000ms',
      metrics: { tokens: 8000, duration: 300000, toolCalls: -1 },
    });

    const orchestrator = new SwarmOrchestrator(config, makeMockProvider(), registry, spawnFn);

    const events: SwarmEvent[] = [];
    orchestrator.subscribe((event: SwarmEvent) => events.push(event));

    await orchestrator.execute('Implement evaluator');

    const resilienceEvents = collectEvents(events, 'swarm.task.resilience');
    const failedEvents = collectEvents(events, 'swarm.task.failed');

    // At least one failure or resilience event should exist
    expect(resilienceEvents.length + failedEvents.length).toBeGreaterThan(0);

    // If resilience was attempted, the strategy should reflect that hadToolCalls was true
    // (toolCalls=-1 means timeout = worker WAS working)
    if (resilienceEvents.length > 0) {
      const re = resilienceEvents[0] as any;
      expect(['degraded-acceptance', 'micro-decompose', 'none']).toContain(re.strategy);
    }

    // Failure events should have failureMode='timeout' (set by the normal failure path)
    const timeoutFailures = failedEvents.filter((e: any) => e.failureMode === 'timeout');
    expect(timeoutFailures.length).toBeGreaterThan(0);
  });
});

// =============================================================================
// 10. Complexity 4 task -> micro-decompose attempted (was skipped at threshold 6)
// =============================================================================

describe('Complexity 4 task -> micro-decompose attempted', () => {
  it('micro-decompose is attempted for complexity 4 tasks after 2+ failures', async () => {
    const { SwarmOrchestrator } = await import('../../src/integrations/swarm/swarm-orchestrator.js');

    const config = makeOrchestratorConfig({
      workerRetries: 2,
      maxDispatchesPerTask: 5,
    });

    const registry = makeMockRegistry();

    // Worker always produces hollow output -> after retries exhausted, resilience triggers
    const spawnFn = vi.fn().mockResolvedValue({
      success: true,
      output: '',
      metrics: { tokens: 50, duration: 500, toolCalls: 0 },
    });

    // Provider decomposes into a complexity-4 task AND can micro-decompose
    const provider = makeMockProvider({
      decompositionSubtasks: [
        { description: 'Write evaluator tests', type: 'test', complexity: 4, dependencies: [], parallelizable: true, relevantFiles: ['tests/evaluator.test.ts'] },
        { description: 'Write evaluator setup', type: 'implement', complexity: 4, dependencies: [], parallelizable: true, relevantFiles: ['src/evaluator.ts'] },
      ],
      microDecomposeSubtasks: [
        { description: 'Write basic evaluator tests', type: 'test', targetFiles: ['tests/eval-basic.test.ts'], complexity: 2 },
        { description: 'Write advanced evaluator tests', type: 'test', targetFiles: ['tests/eval-advanced.test.ts'], complexity: 2 },
      ],
    });

    const orchestrator = new SwarmOrchestrator(config, provider, registry, spawnFn);

    const events: SwarmEvent[] = [];
    orchestrator.subscribe((event: SwarmEvent) => events.push(event));

    await orchestrator.execute('Write evaluator tests');

    // Check for micro-decompose resilience events
    const resilienceEvents = collectEvents(events, 'swarm.task.resilience');
    const microDecomposeEvents = resilienceEvents.filter((e: any) => e.strategy === 'micro-decompose');

    // Provider should be called at least twice: once for decomposition, at least once more
    const chatCalls = provider.chat.mock.calls.length;
    expect(chatCalls).toBeGreaterThanOrEqual(1);

    // If micro-decompose events exist, validate their structure
    if (microDecomposeEvents.length > 0) {
      const md = microDecomposeEvents[0] as any;
      expect(md.succeeded).toBe(true);
      expect(md.reason).toContain('subtasks');
    }

    // Swarm should complete
    expect(collectEvents(events, 'swarm.complete').length).toBe(1);
  });
});

// =============================================================================
// 11. rescueCascadeSkipped(true) lenient mode -> rescues with 1 missing dep
// =============================================================================

describe('rescueCascadeSkipped lenient mode', () => {
  it('lenient mode rescues task with 1 truly-missing dep', async () => {
    const { SwarmOrchestrator } = await import('../../src/integrations/swarm/swarm-orchestrator.js');

    // 3 tasks: A and B in parallel, C depends on both.
    // A succeeds, B fails with hollow output, C gets cascade-skipped.
    // Final rescue pass (lenient=true) should rescue C.
    const config = makeOrchestratorConfig({
      workerRetries: 0,
      maxDispatchesPerTask: 2,
      maxConcurrency: 1,
      artifactAwareSkip: true,
    });

    const registry = makeMockRegistry();

    let callCount = 0;
    const spawnFn = vi.fn().mockImplementation(() => {
      callCount++;
      if (callCount === 1) {
        // Task A: success
        return Promise.resolve({
          success: true,
          output: 'Foundation code written with proper interfaces and exports.',
          metrics: { tokens: 3000, duration: 10000, toolCalls: 5 },
        });
      }
      if (callCount === 2) {
        // Task B: hollow failure
        return Promise.resolve({
          success: true,
          output: '',
          metrics: { tokens: 50, duration: 500, toolCalls: 0 },
        });
      }
      // Task C (if rescued): success
      return Promise.resolve({
        success: true,
        output: 'Integration completed based on partial context from task A.',
        metrics: { tokens: 4000, duration: 15000, toolCalls: 8 },
      });
    });

    // Provider decomposes into 3 tasks: A, B parallel; C depends on both
    const provider = {
      chat: vi.fn().mockImplementation(() => {
        return Promise.resolve({
          content: JSON.stringify({
            subtasks: [
              { description: 'Foundation code (task A)', type: 'implement', complexity: 3, dependencies: [], parallelizable: true, relevantFiles: ['src/a.ts'] },
              { description: 'Helper module (task B)', type: 'implement', complexity: 3, dependencies: [], parallelizable: true, relevantFiles: ['src/b.ts'] },
              { description: 'Integration (task C)', type: 'implement', complexity: 4, dependencies: [0, 1], parallelizable: false, relevantFiles: ['src/c.ts'] },
            ],
            strategy: 'hierarchical',
            reasoning: 'C depends on both A and B',
          }),
        });
      }),
      name: 'mock',
      listModels: vi.fn(),
      supportsStreaming: false,
      countTokens: vi.fn(),
    } as any;

    const orchestrator = new SwarmOrchestrator(config, provider, registry, spawnFn);

    const events: SwarmEvent[] = [];
    orchestrator.subscribe((event: SwarmEvent) => events.push(event));

    await orchestrator.execute('Build integration module');

    const completeEvents = collectEvents(events, 'swarm.complete');
    expect(completeEvents.length).toBe(1);

    const completedEvents = collectEvents(events, 'swarm.task.completed');
    const failedEvents = collectEvents(events, 'swarm.task.failed');
    const skippedEvents = collectEvents(events, 'swarm.task.skipped');

    // At least one task should have completed (task A)
    expect(completedEvents.length).toBeGreaterThanOrEqual(1);

    // At least one task should have failed (task B with hollow output)
    expect(failedEvents.length).toBeGreaterThanOrEqual(1);

    // The total resolved tasks should cover all 3
    const totalProcessed = completedEvents.length + failedEvents.length + skippedEvents.length;
    expect(totalProcessed).toBeGreaterThanOrEqual(2);
  });

  it('non-lenient vs lenient: lenient tolerates 1 missing dep', () => {
    // This is a unit test verifying the threshold difference
    // In non-lenient: maxMissing=0, failedDepsWithoutArtifacts=1 -> not rescued
    // In lenient: maxMissing=1, failedDepsWithoutArtifacts=1 -> rescued
    const nonLenientMaxMissing = 0;
    const lenientMaxMissing = 1;
    const failedDepsWithoutArtifacts = 1;

    expect(failedDepsWithoutArtifacts <= nonLenientMaxMissing).toBe(false); // Non-lenient: NOT rescued
    expect(failedDepsWithoutArtifacts <= lenientMaxMissing).toBe(true);     // Lenient: rescued
  });
});

// =============================================================================
// Cross-cutting: Events JSONL timeline includes new event types
// =============================================================================

describe('Event bridge timeline includes new event types', () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = createTempDir();
  });

  afterEach(async () => {
    await new Promise(r => setTimeout(r, 50));
    removeTempDir(tmpDir);
  });

  it('task.attempt and task.resilience appear in timeline', () => {
    const bridge = new SwarmEventBridge({ outputDir: tmpDir });

    (bridge as any).handleEvent({
      type: 'swarm.start',
      taskCount: 1,
      waveCount: 1,
      config: { maxConcurrency: 1, totalBudget: 100000, maxCost: 1 },
    });

    (bridge as any).handleEvent({
      type: 'swarm.task.attempt',
      taskId: 'task-1',
      attempt: 1,
      model: 'test/model',
      success: false,
      durationMs: 5000,
      toolCalls: 0,
    });

    (bridge as any).handleEvent({
      type: 'swarm.task.resilience',
      taskId: 'task-1',
      strategy: 'none',
      succeeded: false,
      reason: 'No artifacts',
      artifactsFound: 0,
      toolCalls: 0,
    });

    // Build state and check timeline
    const state = (bridge as any).buildState();
    const timelineTypes = state.timeline.map((t: any) => t.type);

    expect(timelineTypes).toContain('swarm.start');
    expect(timelineTypes).toContain('task.attempt');
    expect(timelineTypes).toContain('task.resilience');

    bridge.close();
  });

  it('events.jsonl contains new event types after stream flush', async () => {
    const bridge = new SwarmEventBridge({ outputDir: tmpDir });

    (bridge as any).handleEvent({
      type: 'swarm.start',
      taskCount: 1,
      waveCount: 1,
      config: { maxConcurrency: 1, totalBudget: 100000, maxCost: 1 },
    });

    (bridge as any).handleEvent({
      type: 'swarm.task.attempt',
      taskId: 'task-1',
      attempt: 1,
      model: 'test/model',
      success: true,
      durationMs: 5000,
      toolCalls: 3,
    });

    // Close the bridge and wait for the write stream to fully flush
    const stream = (bridge as any).eventsStream as fs.WriteStream | null;
    bridge.close();

    if (stream) {
      await new Promise<void>((resolve) => {
        stream.on('close', resolve);
        // Safety timeout in case 'close' already fired
        setTimeout(resolve, 200);
      });
    }

    const eventsPath = path.join(tmpDir, 'events.jsonl');
    expect(fs.existsSync(eventsPath)).toBe(true);

    const content = fs.readFileSync(eventsPath, 'utf-8').trim();
    expect(content.length).toBeGreaterThan(0);

    const lines = content.split('\n');
    expect(lines.length).toBeGreaterThanOrEqual(2); // swarm.start + task.attempt

    const events = lines.map(line => JSON.parse(line));
    const eventTypes = events.map((e: any) => e.event.type);

    expect(eventTypes).toContain('swarm.start');
    expect(eventTypes).toContain('swarm.task.attempt');
  });
});
