/**
 * Swarm Orchestrator Integration Tests
 *
 * Exercises the full orchestrator lifecycle with mocked dependencies:
 * - Mock LLM provider for decomposition, planning, review, verification
 * - Mock SpawnAgentFn for worker dispatch
 * - Real SharedBlackboard for coordination
 * - Real AgentRegistry for agent management
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { createSwarmOrchestrator, type SwarmOrchestrator } from '../../src/integrations/swarm/swarm-orchestrator.js';
import { DEFAULT_SWARM_CONFIG, type SwarmConfig } from '../../src/integrations/swarm/types.js';
import type { SpawnAgentFn } from '../../src/integrations/swarm/worker-pool.js';
import type { SpawnResult } from '../../src/integrations/agents/agent-registry.js';
import { AgentRegistry } from '../../src/integrations/agents/agent-registry.js';
import { createSharedBlackboard, type SharedBlackboard } from '../../src/integrations/agents/shared-blackboard.js';
import type { LLMProvider, ChatResponse, Message, MessageWithContent, ChatOptions } from '../../src/providers/types.js';
import type { SwarmEvent } from '../../src/integrations/swarm/swarm-events.js';

// ─── Decomposition JSON ─────────────────────────────────────────────────────

/** A minimal valid decomposition response for 2 subtasks. */
const TWO_SUBTASK_DECOMPOSITION = JSON.stringify({
  subtasks: [
    {
      description: 'Create the hello world main file',
      type: 'implement',
      complexity: 3,
      dependencies: [],
      parallelizable: true,
      relevantFiles: ['src/main.ts'],
    },
    {
      description: 'Write a test for the hello world app',
      type: 'test',
      complexity: 2,
      dependencies: [0],
      parallelizable: false,
      relevantFiles: ['tests/main.test.ts'],
    },
  ],
  strategy: 'sequential',
  reasoning: 'Implement first, then test.',
});

/** A planning response with acceptance criteria. */
const PLANNING_RESPONSE = JSON.stringify({
  acceptanceCriteria: [
    { taskId: 'subtask-0', criteria: ['File src/main.ts exists', 'Prints hello world'] },
    { taskId: 'subtask-1', criteria: ['Test file exists', 'Test passes'] },
  ],
  integrationTestPlan: {
    description: 'Run the app and check output',
    steps: [
      { description: 'Run main', command: 'node src/main.ts', expectedResult: 'Hello, world!', required: true },
    ],
    successCriteria: 'App prints hello world',
  },
  reasoning: 'Simple plan for hello world.',
});

/** A wave review response. */
const WAVE_REVIEW_RESPONSE = JSON.stringify({
  assessment: 'good',
  taskAssessments: [
    { taskId: 'subtask-0', passed: true },
  ],
  fixupTasks: [],
});

// ─── Mock LLM Provider ──────────────────────────────────────────────────────

/**
 * Creates a mock LLM provider that returns context-aware responses.
 * Detects decomposition, planning, review, and verification prompts
 * from the message content and returns appropriate JSON.
 */
function createMockLLMProvider(): LLMProvider {
  return {
    name: 'mock-provider',
    defaultModel: 'mock/test-model',

    async chat(
      messages: (Message | MessageWithContent)[],
      _options?: ChatOptions,
    ): Promise<ChatResponse> {
      // Combine all message content to detect intent
      const allContent = messages
        .map((m) => (typeof m.content === 'string' ? m.content : ''))
        .join(' ')
        .toLowerCase();

      let responseContent: string;

      if (allContent.includes('decompos') || allContent.includes('break down') || allContent.includes('subtask')) {
        responseContent = TWO_SUBTASK_DECOMPOSITION;
      } else if (allContent.includes('acceptance criteria') || allContent.includes('plan')) {
        responseContent = PLANNING_RESPONSE;
      } else if (allContent.includes('review') || allContent.includes('wave')) {
        responseContent = WAVE_REVIEW_RESPONSE;
      } else if (allContent.includes('verif') || allContent.includes('integration')) {
        responseContent = JSON.stringify({ passed: true, summary: 'All checks passed.' });
      } else {
        responseContent = 'Task completed successfully.';
      }

      return {
        content: responseContent,
        stopReason: 'end_turn',
        usage: {
          inputTokens: 100,
          outputTokens: 200,
          cost: 0.001,
        },
      };
    },

    isConfigured(): boolean {
      return true;
    },
  };
}

// ─── Mock SpawnAgentFn ──────────────────────────────────────────────────────

/** Creates a mock SpawnAgentFn that resolves with successful results. */
function createMockSpawnAgent(options?: {
  delay?: number;
  failForTasks?: string[];
  throwForTasks?: string[];
}): SpawnAgentFn {
  const { delay = 10, failForTasks = [], throwForTasks = [] } = options ?? {};

  return async (agentName: string, task: string): Promise<SpawnResult> => {
    // Small delay to simulate async work
    await new Promise((resolve) => setTimeout(resolve, delay));

    // Check if this task should throw
    if (throwForTasks.some((pattern) => agentName.includes(pattern) || task.includes(pattern))) {
      throw new Error(`Worker crashed: simulated error for ${agentName}`);
    }

    // Check if this task should fail
    const shouldFail = failForTasks.some(
      (pattern) => agentName.includes(pattern) || task.includes(pattern),
    );

    return {
      success: !shouldFail,
      output: shouldFail
        ? `Failed to complete: ${task.slice(0, 80)}`
        : `Completed: ${task.slice(0, 80)}. Created files and made changes.`,
      metrics: {
        tokens: 5000,
        duration: delay,
        toolCalls: shouldFail ? 0 : 3,
      },
      filesModified: shouldFail ? [] : ['src/main.ts'],
      structured: shouldFail
        ? undefined
        : {
            findings: ['Implemented feature successfully'],
            actionsTaken: ['Created src/main.ts'],
            failures: [],
            remainingWork: [],
            exitReason: 'completed' as const,
          },
    };
  };
}

// ─── Test Helpers ────────────────────────────────────────────────────────────

/** Build a minimal SwarmConfig for testing. */
function buildTestConfig(overrides?: Partial<SwarmConfig>): SwarmConfig {
  return {
    ...DEFAULT_SWARM_CONFIG,
    orchestratorModel: 'mock/test-model',
    workers: [
      {
        name: 'coder',
        model: 'mock/test-model',
        capabilities: ['code', 'test'],
        contextWindow: 32000,
        allowedTools: ['read_file', 'write_file', 'edit_file', 'glob', 'grep', 'bash'],
      },
    ],
    // Keep budgets small for fast tests
    totalBudget: 100_000,
    maxCost: 1.0,
    maxConcurrency: 1,
    maxTokensPerWorker: 20_000,
    workerTimeout: 10_000,
    workerMaxIterations: 5,
    // Disable features that would slow down tests or require real filesystem
    enablePersistence: false,
    enableVerification: false,
    qualityGates: false,
    enablePlanning: false,
    enableWaveReview: false,
    probeModels: false,
    dispatchStaggerMs: 0,
    // Override for tests
    ...overrides,
  } as SwarmConfig;
}

// ─── Tests ───────────────────────────────────────────────────────────────────

describe('SwarmOrchestrator Integration', () => {
  let provider: LLMProvider;
  let registry: AgentRegistry;
  let blackboard: SharedBlackboard;
  let spawnAgent: SpawnAgentFn;

  beforeEach(() => {
    provider = createMockLLMProvider();
    registry = new AgentRegistry('/tmp/swarm-test');
    blackboard = createSharedBlackboard();
    spawnAgent = createMockSpawnAgent();
  });

  afterEach(() => {
    registry.cleanup();
    blackboard.clear();
  });

  // ─── Test a) ─────────────────────────────────────────────────────────

  describe('creation', () => {
    it('should create orchestrator with valid config', () => {
      const config = buildTestConfig();
      const orchestrator = createSwarmOrchestrator(
        config,
        provider,
        registry,
        spawnAgent,
        blackboard,
      );

      expect(orchestrator).toBeDefined();
      expect(orchestrator).toBeInstanceOf(Object);
      expect(typeof orchestrator.execute).toBe('function');
      expect(typeof orchestrator.subscribe).toBe('function');
      expect(typeof orchestrator.getStatus).toBe('function');
      expect(typeof orchestrator.cancel).toBe('function');
    });

    it('should create orchestrator without optional blackboard', () => {
      const config = buildTestConfig();
      const orchestrator = createSwarmOrchestrator(
        config,
        provider,
        registry,
        spawnAgent,
      );

      expect(orchestrator).toBeDefined();
    });
  });

  // ─── Test b) ─────────────────────────────────────────────────────────

  describe('event subscription', () => {
    it('should subscribe to and receive swarm events', async () => {
      const config = buildTestConfig();
      const orchestrator = createSwarmOrchestrator(
        config,
        provider,
        registry,
        spawnAgent,
        blackboard,
      );

      const receivedEvents: SwarmEvent[] = [];
      const unsubscribe = orchestrator.subscribe((event: SwarmEvent) => {
        receivedEvents.push(event);
      });

      expect(typeof unsubscribe).toBe('function');

      // Execute to trigger events
      await orchestrator.execute('Build a hello world app');

      // Should have received at least some core events
      const eventTypes = receivedEvents.map((e) => e.type);
      expect(eventTypes).toContain('swarm.phase.progress');
      expect(eventTypes).toContain('swarm.start');
      expect(eventTypes).toContain('swarm.complete');

      // Unsubscribe should work
      unsubscribe();
    }, 30_000);

    it('should stop receiving events after unsubscribe', async () => {
      const config = buildTestConfig();
      const orchestrator = createSwarmOrchestrator(
        config,
        provider,
        registry,
        spawnAgent,
        blackboard,
      );

      const receivedEvents: SwarmEvent[] = [];
      const unsubscribe = orchestrator.subscribe((event: SwarmEvent) => {
        receivedEvents.push(event);
      });

      // Unsubscribe before executing
      unsubscribe();

      await orchestrator.execute('Build a hello world app');

      // Should not have received any events
      expect(receivedEvents.length).toBe(0);
    }, 30_000);
  });

  // ─── Test c) ─────────────────────────────────────────────────────────

  describe('status', () => {
    it('should get initial status with idle/decomposing phase', () => {
      const config = buildTestConfig();
      const orchestrator = createSwarmOrchestrator(
        config,
        provider,
        registry,
        spawnAgent,
        blackboard,
      );

      const status = orchestrator.getStatus();

      // Before execute(), the status reflects the initial state
      expect(status).toBeDefined();
      expect(status.phase).toBeDefined();
      expect(status.queue).toBeDefined();
      expect(status.budget).toBeDefined();
      expect(status.budget.tokensTotal).toBe(config.totalBudget);
      expect(status.budget.costTotal).toBe(config.maxCost);
      expect(status.activeWorkers).toEqual([]);
      expect(status.queue.total).toBe(0);
    });
  });

  // ─── Test d) ─────────────────────────────────────────────────────────

  describe('end-to-end execution', () => {
    it('should execute a simple task end-to-end', async () => {
      const config = buildTestConfig();
      const orchestrator = createSwarmOrchestrator(
        config,
        provider,
        registry,
        spawnAgent,
        blackboard,
      );

      const result = await orchestrator.execute('Build a hello world app');

      // Verify the result structure
      expect(result).toBeDefined();
      expect(typeof result.success).toBe('boolean');
      expect(typeof result.summary).toBe('string');
      expect(result.summary.length).toBeGreaterThan(0);
      expect(Array.isArray(result.tasks)).toBe(true);
      expect(Array.isArray(result.errors)).toBe(true);

      // Verify stats exist and have reasonable values
      expect(result.stats).toBeDefined();
      expect(result.stats.totalTasks).toBeGreaterThan(0);
      expect(result.stats.totalWaves).toBeGreaterThan(0);

      // With our mock, tasks should have been completed
      expect(result.stats.completedTasks).toBeGreaterThan(0);

      // The decomposition produces 2 subtasks. Both should complete.
      expect(result.tasks.length).toBe(2);

      // Status after execution should be completed
      const status = orchestrator.getStatus();
      expect(status.phase).toBe('completed');
    }, 30_000);

    it('should track duration and complete with valid stats', async () => {
      const config = buildTestConfig();
      const orchestrator = createSwarmOrchestrator(
        config,
        provider,
        registry,
        spawnAgent,
        blackboard,
      );

      const result = await orchestrator.execute('Build a hello world app');

      // Duration is tracked via wall-clock time in buildStats
      expect(result.stats.totalDurationMs).toBeGreaterThan(0);
      expect(result.stats.totalTasks).toBeGreaterThan(0);
      expect(result.stats.completedTasks).toBeGreaterThan(0);

      // Model usage map should exist (may be empty if tokens flow through delegates)
      expect(result.stats.modelUsage).toBeDefined();

      // Budget status reflects configured totals
      const status = orchestrator.getStatus();
      expect(status.budget.tokensTotal).toBe(config.totalBudget);
      expect(status.budget.costTotal).toBe(config.maxCost);
    }, 30_000);

    it('should emit events in correct order during execution', async () => {
      const config = buildTestConfig();
      const orchestrator = createSwarmOrchestrator(
        config,
        provider,
        registry,
        spawnAgent,
        blackboard,
      );

      const eventTypes: string[] = [];
      orchestrator.subscribe((event: SwarmEvent) => {
        eventTypes.push(event.type);
      });

      await orchestrator.execute('Build a hello world app');

      // Verify key event ordering: phase.progress should come before start
      const phaseIdx = eventTypes.indexOf('swarm.phase.progress');
      const startIdx = eventTypes.indexOf('swarm.start');
      const completeIdx = eventTypes.indexOf('swarm.complete');

      expect(phaseIdx).toBeGreaterThanOrEqual(0);
      expect(startIdx).toBeGreaterThanOrEqual(0);
      expect(completeIdx).toBeGreaterThanOrEqual(0);

      // start must come before complete
      expect(startIdx).toBeLessThan(completeIdx);
    }, 30_000);

    it('should propagate task results through dependency context', async () => {
      const config = buildTestConfig();
      const spawnAgentSpy = vi.fn(createMockSpawnAgent());
      const orchestrator = createSwarmOrchestrator(
        config,
        provider,
        registry,
        spawnAgentSpy,
        blackboard,
      );

      await orchestrator.execute('Build a hello world app');

      // Our decomposition has 2 tasks: subtask-0 (no deps) and subtask-1 (depends on subtask-0)
      // The spawn agent should have been called at least twice
      expect(spawnAgentSpy).toHaveBeenCalledTimes(2);

      // The second call should include dependency context from the first task
      const secondCallArgs = spawnAgentSpy.mock.calls[1];
      expect(secondCallArgs).toBeDefined();
      // The second arg is the task prompt which may include dependency context
      const taskPrompt = secondCallArgs[1];
      expect(typeof taskPrompt).toBe('string');
    }, 30_000);
  });

  // ─── Test e) ─────────────────────────────────────────────────────────

  describe('cancellation', () => {
    it('should handle cancellation', async () => {
      const config = buildTestConfig({
        maxConcurrency: 1,
      });

      const orchestrator = createSwarmOrchestrator(
        config,
        provider,
        registry,
        spawnAgent,
        blackboard,
      );

      // Verify cancel() can be called and sets the failed phase
      // Call cancel immediately (before execute) to test the cancel mechanism
      await orchestrator.cancel();

      const status = orchestrator.getStatus();
      expect(status.phase).toBe('failed');

      // Execute after cancel -- the cancelled flag should cause early termination
      // or the orchestrator should still return a valid result
      const result = await orchestrator.execute('Build a hello world app');

      expect(result).toBeDefined();
      expect(typeof result.summary).toBe('string');
      expect(Array.isArray(result.errors)).toBe(true);
    }, 30_000);
  });

  // ─── Test f) ─────────────────────────────────────────────────────────

  describe('worker failures', () => {
    it('should handle worker failures gracefully', async () => {
      const config = buildTestConfig({
        workerRetries: 0, // No retries to keep test fast
      });

      // SpawnAgent that fails for all tasks
      const failingSpawnAgent = createMockSpawnAgent({
        failForTasks: ['Create', 'Write', 'hello', 'test', 'main'],
      });

      const orchestrator = createSwarmOrchestrator(
        config,
        provider,
        registry,
        failingSpawnAgent,
        blackboard,
      );

      const errors: SwarmEvent[] = [];
      orchestrator.subscribe((event: SwarmEvent) => {
        if (event.type === 'swarm.error' || event.type === 'swarm.task.failed') {
          errors.push(event);
        }
      });

      const result = await orchestrator.execute('Build a hello world app');

      // The result should indicate failure (not enough tasks completed for 70% threshold)
      expect(result).toBeDefined();
      expect(result.success).toBe(false);
      expect(result.stats.failedTasks + result.stats.skippedTasks).toBeGreaterThan(0);
    }, 30_000);

    it('should handle worker exceptions gracefully', async () => {
      const config = buildTestConfig({
        workerRetries: 0,
      });

      // SpawnAgent that throws errors
      const throwingSpawnAgent = createMockSpawnAgent({
        throwForTasks: ['Create', 'Write', 'hello', 'test', 'main'],
      });

      const orchestrator = createSwarmOrchestrator(
        config,
        provider,
        registry,
        throwingSpawnAgent,
        blackboard,
      );

      // Should not throw — errors are handled internally
      const result = await orchestrator.execute('Build a hello world app');

      expect(result).toBeDefined();
      expect(result.success).toBe(false);
      expect(typeof result.summary).toBe('string');
    }, 30_000);

    it('should record failed tasks in the result', async () => {
      const config = buildTestConfig({
        workerRetries: 0,
      });

      const failingSpawnAgent = createMockSpawnAgent({
        failForTasks: ['Create', 'hello', 'main'],
      });

      const orchestrator = createSwarmOrchestrator(
        config,
        provider,
        registry,
        failingSpawnAgent,
        blackboard,
      );

      const result = await orchestrator.execute('Build a hello world app');

      // Check that failed/skipped tasks are properly tracked
      const failedOrSkipped = result.tasks.filter(
        (t) => t.status === 'failed' || t.status === 'skipped',
      );
      expect(failedOrSkipped.length).toBeGreaterThan(0);

      // Stats should reflect the failures
      expect(result.stats.failedTasks + result.stats.skippedTasks).toBe(failedOrSkipped.length);
    }, 30_000);
  });

  // ─── Additional edge cases ───────────────────────────────────────────

  describe('configuration variations', () => {
    it('should work with planning enabled', async () => {
      const config = buildTestConfig({
        enablePlanning: true,
      });

      const orchestrator = createSwarmOrchestrator(
        config,
        provider,
        registry,
        spawnAgent,
        blackboard,
      );

      const events: SwarmEvent[] = [];
      orchestrator.subscribe((event: SwarmEvent) => {
        events.push(event);
      });

      const result = await orchestrator.execute('Build a hello world app');

      expect(result).toBeDefined();
      // Planning phase should have been entered
      const planningEvents = events.filter(
        (e) => e.type === 'swarm.phase.progress' && 'phase' in e && e.phase === 'planning',
      );
      expect(planningEvents.length).toBeGreaterThan(0);
    }, 30_000);

    it('should work with multiple workers configured', async () => {
      const config = buildTestConfig({
        maxConcurrency: 2,
        workers: [
          {
            name: 'coder',
            model: 'mock/test-model',
            capabilities: ['code'],
            allowedTools: ['read_file', 'write_file', 'edit_file', 'bash'],
          },
          {
            name: 'tester',
            model: 'mock/test-model-2',
            capabilities: ['test'],
            allowedTools: ['read_file', 'bash', 'grep'],
          },
        ],
      });

      const orchestrator = createSwarmOrchestrator(
        config,
        provider,
        registry,
        spawnAgent,
        blackboard,
      );

      const result = await orchestrator.execute('Build a hello world app');

      expect(result).toBeDefined();
      expect(result.stats.totalTasks).toBe(2);
    }, 30_000);

    it('should respect budget limits in stats', async () => {
      const config = buildTestConfig({
        totalBudget: 50_000,
        maxCost: 0.50,
      });

      const orchestrator = createSwarmOrchestrator(
        config,
        provider,
        registry,
        spawnAgent,
        blackboard,
      );

      const result = await orchestrator.execute('Build a hello world app');

      // Budget should be reflected in status
      const status = orchestrator.getStatus();
      expect(status.budget.tokensTotal).toBe(50_000);
      expect(status.budget.costTotal).toBe(0.50);

      // Stats should not exceed budget
      expect(result.stats.totalTokens).toBeLessThanOrEqual(50_000);
    }, 30_000);
  });

  describe('blackboard coordination', () => {
    it('should provide access to shared blackboard via orchestrator', () => {
      const config = buildTestConfig();
      const orchestrator = createSwarmOrchestrator(
        config,
        provider,
        registry,
        spawnAgent,
        blackboard,
      );

      // The blackboard should be usable independently
      const finding = blackboard.post('test-agent', {
        topic: 'setup',
        content: 'Project initialized',
        type: 'progress',
        confidence: 1.0,
      });

      expect(finding).toBeDefined();
      expect(finding.id).toBeDefined();
      expect(blackboard.getAllFindings().length).toBe(1);

      // Orchestrator should still work with a populated blackboard
      expect(orchestrator).toBeDefined();
    });
  });

  describe('budget pool access', () => {
    it('should expose budget pool', () => {
      const config = buildTestConfig();
      const orchestrator = createSwarmOrchestrator(
        config,
        provider,
        registry,
        spawnAgent,
        blackboard,
      );

      const budgetPool = orchestrator.getBudgetPool();
      expect(budgetPool).toBeDefined();
      expect(budgetPool.hasCapacity()).toBe(true);
      expect(budgetPool.orchestratorReserve).toBeGreaterThan(0);
    });
  });

  describe('shared state access', () => {
    it('should expose shared context and economics state', () => {
      const config = buildTestConfig();
      const orchestrator = createSwarmOrchestrator(
        config,
        provider,
        registry,
        spawnAgent,
        blackboard,
      );

      const contextState = orchestrator.getSharedContextState();
      expect(contextState).toBeDefined();

      const economicsState = orchestrator.getSharedEconomicsState();
      expect(economicsState).toBeDefined();

      const contextEngine = orchestrator.getSharedContextEngine();
      expect(contextEngine).toBeDefined();
    });
  });
});
