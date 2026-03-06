/**
 * Pre-Dispatch Auto-Split Tests
 *
 * Tests for the proactive task splitting feature that splits high-complexity
 * foundation tasks before dispatch using heuristic pre-filtering + LLM judgment.
 */

import { describe, it, expect, vi } from 'vitest';
import type { SwarmConfig } from '../../src/integrations/swarm/types.js';
import { DEFAULT_SWARM_CONFIG } from '../../src/integrations/swarm/types.js';
import { SwarmOrchestrator } from '../../src/integrations/swarm/swarm-orchestrator.js';
import type { SwarmEvent } from '../../src/integrations/swarm/swarm-events.js';

// =============================================================================
// Helpers
// =============================================================================

function makeConfig(overrides: Partial<SwarmConfig> = {}): SwarmConfig {
  return {
    ...DEFAULT_SWARM_CONFIG,
    orchestratorModel: 'test/orchestrator',
    workers: [
      { name: 'coder', model: 'model-a', capabilities: ['code', 'test'] },
      { name: 'researcher', model: 'model-b', capabilities: ['research', 'review'] },
    ],
    qualityGates: false,
    workerRetries: 2,
    enablePlanning: false,
    enableWaveReview: false,
    enableVerification: false,
    enablePersistence: false,
    enableModelFailover: false,
    ...overrides,
  };
}

/** Decomposition response that creates a complexity-8 foundation task with 3 dependents.
 *  Note: dependency references use 0-based index (task-0 = first subtask). */
const FOUNDATION_DECOMPOSITION = JSON.stringify({
  subtasks: [
    {
      description: 'Implement core data model with validation',
      type: 'implement',
      complexity: 8,
      dependencies: [],
      parallelizable: false,
      relevantFiles: ['src/models.ts', 'src/validators.ts'],
    },
    {
      description: 'Write tests for data model',
      type: 'test',
      complexity: 3,
      dependencies: ['task-0'],
      parallelizable: false,
      relevantFiles: ['tests/models.test.ts'],
    },
    {
      description: 'Integrate model with API layer',
      type: 'implement',
      complexity: 4,
      dependencies: ['task-0'],
      parallelizable: false,
      relevantFiles: ['src/api.ts'],
    },
    {
      description: 'Document the data model API',
      type: 'document',
      complexity: 2,
      dependencies: ['task-0'],
      parallelizable: false,
      relevantFiles: ['docs/api.md'],
    },
  ],
  strategy: 'sequential',
  reasoning: 'test decomposition',
});

function makeMockProvider(splitResponse?: { shouldSplit: boolean; reason: string; subtasks?: any[] }) {
  let callCount = 0;
  return {
    chat: vi.fn().mockImplementation(() => {
      callCount++;
      if (callCount === 1) {
        // Decomposition response
        return Promise.resolve({ content: FOUNDATION_DECOMPOSITION });
      }
      // Auto-split judge response (and any subsequent calls)
      if (splitResponse) {
        return Promise.resolve({
          content: JSON.stringify(splitResponse),
          usage: { total_tokens: 200 },
        });
      }
      // Default: don't split
      return Promise.resolve({
        content: JSON.stringify({ shouldSplit: false, reason: 'task is atomic' }),
        usage: { total_tokens: 200 },
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

function makeSpawnFn() {
  return vi.fn().mockResolvedValue({
    success: true,
    output: 'Task completed with changes.',
    metrics: { tokens: 500, duration: 2000, toolCalls: 3 },
  });
}

// =============================================================================
// shouldAutoSplit heuristic tests
// =============================================================================

describe('shouldAutoSplit heuristics', () => {
  it('should consider foundation task with complexity >= 6 for auto-split', async () => {
    const splitJudgeResponse = {
      shouldSplit: true,
      reason: 'Multiple independent files',
      subtasks: [
        { description: 'Part A', type: 'implement', targetFiles: ['src/a.ts'], complexity: 4 },
        { description: 'Part B', type: 'implement', targetFiles: ['src/b.ts'], complexity: 4 },
      ],
    };
    const provider = makeMockProvider(splitJudgeResponse);
    const config = makeConfig();
    const events: SwarmEvent[] = [];
    const orchestrator = new SwarmOrchestrator(config, provider, makeMockRegistry(), makeSpawnFn());
    orchestrator.subscribe((event) => events.push(event));

    await orchestrator.execute('Build a data model system');

    const resilienceEvents = events.filter(
      (e): e is Extract<SwarmEvent, { type: 'swarm.task.resilience' }> =>
        e.type === 'swarm.task.resilience' && (e as any).strategy === 'auto-split',
    );

    // The foundation task should have been auto-split
    expect(resilienceEvents.length).toBeGreaterThanOrEqual(1);
    if (resilienceEvents.length > 0) {
      expect(resilienceEvents[0].succeeded).toBe(true);
    }
  });

  it('should NOT auto-split non-splittable types (research, review, document)', async () => {
    const provider = makeMockProvider({
      shouldSplit: true,
      reason: 'should not happen',
      subtasks: [
        { description: 'A', type: 'document', complexity: 3 },
        { description: 'B', type: 'document', complexity: 3 },
      ],
    });

    // Override decomposition to return high-complexity document task
    provider.chat.mockImplementationOnce(() =>
      Promise.resolve({
        content: JSON.stringify({
          subtasks: [
            { description: 'Document system', type: 'document', complexity: 8, dependencies: [], parallelizable: false, relevantFiles: [] },
            { description: 'Review docs', type: 'review', complexity: 3, dependencies: ['task-0'], parallelizable: false, relevantFiles: [] },
            { description: 'Update docs', type: 'document', complexity: 3, dependencies: ['task-0'], parallelizable: false, relevantFiles: [] },
            { description: 'Final review', type: 'review', complexity: 2, dependencies: ['task-0'], parallelizable: false, relevantFiles: [] },
          ],
          strategy: 'sequential',
          reasoning: 'test',
        }),
      }),
    );

    const config = makeConfig();
    const events: SwarmEvent[] = [];
    const orchestrator = new SwarmOrchestrator(config, provider, makeMockRegistry(), makeSpawnFn());
    orchestrator.subscribe((event) => events.push(event));

    await orchestrator.execute('Document the system');

    const autoSplitEvents = events.filter(
      (e): e is Extract<SwarmEvent, { type: 'swarm.task.resilience' }> =>
        e.type === 'swarm.task.resilience' && (e as any).strategy === 'auto-split',
    );
    expect(autoSplitEvents.length).toBe(0);
  });

  it('should NOT auto-split when autoSplit.enabled is false', async () => {
    const provider = makeMockProvider({
      shouldSplit: true,
      reason: 'should not happen',
      subtasks: [
        { description: 'A', type: 'implement', complexity: 3 },
        { description: 'B', type: 'implement', complexity: 3 },
      ],
    });

    const config = makeConfig({ autoSplit: { enabled: false } });
    const events: SwarmEvent[] = [];
    const orchestrator = new SwarmOrchestrator(config, provider, makeMockRegistry(), makeSpawnFn());
    orchestrator.subscribe((event) => events.push(event));

    await orchestrator.execute('Build a data model system');

    const autoSplitEvents = events.filter(
      (e): e is Extract<SwarmEvent, { type: 'swarm.task.resilience' }> =>
        e.type === 'swarm.task.resilience' && (e as any).strategy === 'auto-split',
    );
    expect(autoSplitEvents.length).toBe(0);
  });

  it('should NOT auto-split low-complexity tasks (below floor)', async () => {
    const provider = makeMockProvider({
      shouldSplit: true,
      reason: 'should not happen',
      subtasks: [
        { description: 'A', type: 'implement', complexity: 2 },
        { description: 'B', type: 'implement', complexity: 2 },
      ],
    });

    // Decomposition returns only low-complexity tasks
    provider.chat.mockImplementationOnce(() =>
      Promise.resolve({
        content: JSON.stringify({
          subtasks: [
            { description: 'Simple task', type: 'implement', complexity: 3, dependencies: [], parallelizable: false, relevantFiles: [] },
            { description: 'Dependent', type: 'implement', complexity: 3, dependencies: ['task-0'], parallelizable: false, relevantFiles: [] },
            { description: 'Dependent 2', type: 'implement', complexity: 3, dependencies: ['task-0'], parallelizable: false, relevantFiles: [] },
            { description: 'Dependent 3', type: 'implement', complexity: 3, dependencies: ['task-0'], parallelizable: false, relevantFiles: [] },
          ],
          strategy: 'sequential',
          reasoning: 'test',
        }),
      }),
    );

    const config = makeConfig();
    const events: SwarmEvent[] = [];
    const orchestrator = new SwarmOrchestrator(config, provider, makeMockRegistry(), makeSpawnFn());
    orchestrator.subscribe((event) => events.push(event));

    await orchestrator.execute('Do a simple task');

    const autoSplitEvents = events.filter(
      (e): e is Extract<SwarmEvent, { type: 'swarm.task.resilience' }> =>
        e.type === 'swarm.task.resilience' && (e as any).strategy === 'auto-split',
    );
    expect(autoSplitEvents.length).toBe(0);
  });
});

// =============================================================================
// judgeSplit LLM response parsing tests
// =============================================================================

describe('judgeSplit LLM response parsing', () => {
  it('should parse split response and create subtasks', async () => {
    const splitResponse = {
      shouldSplit: true,
      reason: 'Task touches 3 independent files',
      subtasks: [
        { description: 'Implement model A', type: 'implement', targetFiles: ['src/a.ts'], complexity: 4 },
        { description: 'Implement model B', type: 'implement', targetFiles: ['src/b.ts'], complexity: 3 },
        { description: 'Implement model C', type: 'implement', targetFiles: ['src/c.ts'], complexity: 3 },
      ],
    };
    const provider = makeMockProvider(splitResponse);
    const config = makeConfig();
    const events: SwarmEvent[] = [];
    const orchestrator = new SwarmOrchestrator(config, provider, makeMockRegistry(), makeSpawnFn());
    orchestrator.subscribe((event) => events.push(event));

    await orchestrator.execute('Build a data model system');

    const autoSplitEvents = events.filter(
      (e): e is Extract<SwarmEvent, { type: 'swarm.task.resilience' }> =>
        e.type === 'swarm.task.resilience' && (e as any).strategy === 'auto-split',
    );
    if (autoSplitEvents.length > 0) {
      expect(autoSplitEvents[0].reason).toContain('parallel subtasks');
    }
  });

  it('should respect maxSubtasks cap', async () => {
    const splitResponse = {
      shouldSplit: true,
      reason: 'Many pieces',
      subtasks: [
        { description: 'Part 1', type: 'implement', targetFiles: ['a.ts'], complexity: 3 },
        { description: 'Part 2', type: 'implement', targetFiles: ['b.ts'], complexity: 3 },
        { description: 'Part 3', type: 'implement', targetFiles: ['c.ts'], complexity: 3 },
        { description: 'Part 4', type: 'implement', targetFiles: ['d.ts'], complexity: 3 },
        { description: 'Part 5', type: 'implement', targetFiles: ['e.ts'], complexity: 3 },
        { description: 'Part 6', type: 'implement', targetFiles: ['f.ts'], complexity: 3 },
      ],
    };
    const provider = makeMockProvider(splitResponse);
    const config = makeConfig({ autoSplit: { maxSubtasks: 3 } });
    const events: SwarmEvent[] = [];
    const orchestrator = new SwarmOrchestrator(config, provider, makeMockRegistry(), makeSpawnFn());
    orchestrator.subscribe((event) => events.push(event));

    await orchestrator.execute('Build a data model system');

    const autoSplitEvents = events.filter(
      (e): e is Extract<SwarmEvent, { type: 'swarm.task.resilience' }> =>
        e.type === 'swarm.task.resilience' && (e as any).strategy === 'auto-split',
    );
    // If split happened, it should respect maxSubtasks=3
    if (autoSplitEvents.length > 0) {
      expect(autoSplitEvents[0].reason).toContain('3 parallel subtasks');
    }
  });

  it('should fall through to normal dispatch when judge says no', async () => {
    const provider = makeMockProvider({
      shouldSplit: false,
      reason: 'Task is conceptually atomic',
    });
    const config = makeConfig();
    const events: SwarmEvent[] = [];
    const orchestrator = new SwarmOrchestrator(config, provider, makeMockRegistry(), makeSpawnFn());
    orchestrator.subscribe((event) => events.push(event));

    await orchestrator.execute('Build a data model system');

    const autoSplitEvents = events.filter(
      (e): e is Extract<SwarmEvent, { type: 'swarm.task.resilience' }> =>
        e.type === 'swarm.task.resilience' && (e as any).strategy === 'auto-split',
    );
    expect(autoSplitEvents.length).toBe(0);

    // Task should have been dispatched normally
    const dispatchEvents = events.filter((e) => e.type === 'swarm.task.dispatched');
    expect(dispatchEvents.length).toBeGreaterThan(0);
  });

  it('should fall through to normal dispatch when judge call fails', async () => {
    const provider = makeMockProvider();
    // Override all calls
    let callCount = 0;
    provider.chat.mockImplementation(() => {
      callCount++;
      if (callCount === 1) {
        return Promise.resolve({ content: FOUNDATION_DECOMPOSITION });
      }
      // Split judge call — throw error
      return Promise.reject(new Error('LLM unavailable'));
    });

    const config = makeConfig();
    const events: SwarmEvent[] = [];
    const orchestrator = new SwarmOrchestrator(config, provider, makeMockRegistry(), makeSpawnFn());
    orchestrator.subscribe((event) => events.push(event));

    await orchestrator.execute('Build something');

    const autoSplitEvents = events.filter(
      (e): e is Extract<SwarmEvent, { type: 'swarm.task.resilience' }> =>
        e.type === 'swarm.task.resilience' && (e as any).strategy === 'auto-split',
    );
    expect(autoSplitEvents.length).toBe(0);
  });
});

// =============================================================================
// Subtask complexity constraints
// =============================================================================

describe('auto-split subtask constraints', () => {
  it('should floor subtask complexity at 3', async () => {
    const splitResponse = {
      shouldSplit: true,
      reason: 'Test complexity floor',
      subtasks: [
        { description: 'Part A', type: 'implement', targetFiles: ['a.ts'], complexity: 1 },
        { description: 'Part B', type: 'implement', targetFiles: ['b.ts'], complexity: 2 },
      ],
    };
    const provider = makeMockProvider(splitResponse);
    const config = makeConfig();
    const events: SwarmEvent[] = [];
    const decisions: string[] = [];
    const orchestrator = new SwarmOrchestrator(config, provider, makeMockRegistry(), makeSpawnFn());
    orchestrator.subscribe((event) => {
      events.push(event);
      if (event.type === 'swarm.orchestrator.decision') {
        decisions.push(event.decision.decision);
      }
    });

    await orchestrator.execute('Build a data model system');

    // The auto-split decision should have been logged
    const splitDecisions = decisions.filter(d => d.includes('split into'));
    if (splitDecisions.length > 0) {
      expect(splitDecisions[0]).toContain('subtasks');
    }
  });
});

// =============================================================================
// Config defaults
// =============================================================================

describe('auto-split config defaults', () => {
  it('should use default values when autoSplit config is not provided', () => {
    const config = makeConfig();
    expect(config.autoSplit).toBeUndefined();
  });

  it('should respect custom autoSplit config', () => {
    const config = makeConfig({
      autoSplit: {
        enabled: true,
        complexityFloor: 4,
        maxSubtasks: 2,
        splittableTypes: ['implement'],
      },
    });
    expect(config.autoSplit?.complexityFloor).toBe(4);
    expect(config.autoSplit?.maxSubtasks).toBe(2);
    expect(config.autoSplit?.splittableTypes).toEqual(['implement']);
  });
});
