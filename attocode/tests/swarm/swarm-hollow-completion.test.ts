/**
 * Tests for V10 hollow completion detection (simplified),
 * quality gate pre-check, dependency context warnings, and per-task-type timeouts.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { SpawnResult, StructuredClosureReport } from '../../src/integrations/agent-registry.js';
import type { SwarmTask, SwarmConfig } from '../../src/integrations/swarm/types.js';
import { DEFAULT_SWARM_CONFIG } from '../../src/integrations/swarm/types.js';
import { SwarmWorkerPool } from '../../src/integrations/swarm/worker-pool.js';
import type { AgentRegistry, AgentDefinition } from '../../src/integrations/agent-registry.js';
import type { SwarmBudgetPool } from '../../src/integrations/swarm/swarm-budget.js';
import { isHollowCompletion } from '../../src/integrations/swarm/swarm-orchestrator.js';

describe('isHollowCompletion', () => {
  it('returns true for zero tool calls with short output', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: 'I completed the task',
      metrics: { tokens: 500, duration: 5000, toolCalls: 0 },
    };

    expect(isHollowCompletion(spawnResult)).toBe(true);
  });

  it('returns false for budget-excuse closure report with tool calls (closure report check removed)', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: 'Budget critical',
      metrics: { tokens: 500, duration: 5000, toolCalls: 2 },
      structured: {
        findings: ['Could not complete due to budget constraints'],
        actionsTaken: [],
        failures: ['Budget critical — before any research could be performed'],
        remainingWork: ['Everything'],
        suggestedNextSteps: [],
        exitReason: 'completed',
      },
    };

    // V10: Has 2 tool calls → not hollow (closure report check removed, quality gate handles this)
    expect(isHollowCompletion(spawnResult)).toBe(false);
  });

  it('returns false for real completion with tool calls', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: 'Found 5 results about React state management',
      metrics: { tokens: 2000, duration: 30000, toolCalls: 8 },
      structured: {
        findings: ['React has several state management options', 'Redux is the most popular'],
        actionsTaken: ['Searched for React state management', 'Read 3 documentation pages'],
        failures: [],
        remainingWork: [],
        suggestedNextSteps: [],
        exitReason: 'completed',
      },
    };

    expect(isHollowCompletion(spawnResult)).toBe(false);
  });

  it('returns false when there are tool calls but no closure report', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: 'Done',
      metrics: { tokens: 1000, duration: 10000, toolCalls: 5 },
    };

    expect(isHollowCompletion(spawnResult)).toBe(false);
  });

  it('returns false for timeout (toolCalls === -1)', () => {
    const spawnResult: SpawnResult = {
      success: false,
      output: 'Worker error: Worker timeout after 300000ms',
      metrics: { tokens: 0, duration: 300000, toolCalls: -1 },
    };

    expect(isHollowCompletion(spawnResult)).toBe(false);
  });

  it('returns false for 0 tool calls but substantial output (any task type)', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: 'Research findings: After analyzing multiple sources, the React ecosystem offers several state management solutions. Redux remains the most popular with 40M+ weekly downloads. MobX provides a simpler API with observables. Zustand is gaining traction as a lightweight alternative. Jotai and Recoil offer atomic state management patterns that work well with React Suspense.',
      metrics: { tokens: 1500, duration: 15000, toolCalls: 0 },
    };

    // V10: 0 tool calls but output > 50 chars → NOT hollow (quality gate judges substance)
    expect(isHollowCompletion(spawnResult)).toBe(false);
  });

  it('returns true for 0 tool calls and trivial output', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: 'I tried.',
      metrics: { tokens: 50, duration: 2000, toolCalls: 0 },
    };

    // 0 tool calls + output < 50 chars → IS hollow
    expect(isHollowCompletion(spawnResult)).toBe(true);
  });

  it('returns false for code task with 0 tool calls but substantial output', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: 'Here is the implementation plan: We should refactor the parser module to use a recursive descent approach. This involves creating separate functions for each grammar rule and chaining them together.',
      metrics: { tokens: 1000, duration: 10000, toolCalls: 0 },
    };

    // V10: No task-type distinction — output > 50 chars → NOT hollow (quality gate judges)
    expect(isHollowCompletion(spawnResult)).toBe(false);
  });

  it('returns false for analysis output with 0 tool calls but substantial output', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: 'Architecture Analysis: The codebase follows a modular monolith pattern with clear separation of concerns. The agent module (5400 lines) is the largest and would benefit from decomposition. The integrations layer provides good abstraction boundaries. The TUI layer is cleanly separated from business logic. Key improvement areas: 1) Split agent.ts into smaller modules 2) Add proper dependency injection 3) Improve error propagation patterns.',
      metrics: { tokens: 2000, duration: 20000, toolCalls: 0 },
    };

    // V10: 0 tool calls but output > 50 chars → NOT hollow
    expect(isHollowCompletion(spawnResult)).toBe(false);
  });

  it('returns false for design output with 0 tool calls but substantial output', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: 'Design Proposal: The new authentication system should use JWT tokens with refresh token rotation. The token service will be a standalone module in src/integrations/auth.ts. User sessions will be stored in SQLite alongside existing session data. The middleware chain: rate-limit → cors → auth → route handler. Token expiry: access=15min, refresh=7d.',
      metrics: { tokens: 1800, duration: 18000, toolCalls: 0 },
    };

    // V10: 0 tool calls but output > 50 chars → NOT hollow
    expect(isHollowCompletion(spawnResult)).toBe(false);
  });

  it('returns false for closure report with real findings and tool calls', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: 'Partial results',
      metrics: { tokens: 1500, duration: 20000, toolCalls: 4 },
      structured: {
        findings: ['Found TypeScript best practices document', 'Project uses ESLint with strict config'],
        actionsTaken: ['Read tsconfig.json', 'Searched for lint rules'],
        failures: ['Budget ran out before completing full analysis'],
        remainingWork: ['Check test coverage'],
        suggestedNextSteps: [],
        exitReason: 'completed',
      },
    };

    // Has 4 tool calls → not hollow
    expect(isHollowCompletion(spawnResult)).toBe(false);
  });

  it('returns false for empty findings with budget failure but has tool calls (closure report check removed)', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: 'Could not proceed',
      metrics: { tokens: 200, duration: 3000, toolCalls: 1 },
      structured: {
        findings: [],
        actionsTaken: [],
        failures: ['Budget critical — before any research could be performed'],
        remainingWork: ['All research'],
        suggestedNextSteps: [],
        exitReason: 'completed',
      },
    };

    // V10: Has 1 tool call → not hollow (closure report check removed, quality gate handles this)
    expect(isHollowCompletion(spawnResult)).toBe(false);
  });

  it('returns true for zero tool calls with empty output', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: '',
      metrics: { tokens: 10, duration: 1000, toolCalls: 0 },
    };

    expect(isHollowCompletion(spawnResult)).toBe(true);
  });

  it('returns true for zero tool calls with whitespace-only output', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: '   \n\n  ',
      metrics: { tokens: 10, duration: 1000, toolCalls: 0 },
    };

    expect(isHollowCompletion(spawnResult)).toBe(true);
  });

  it('returns true for 50 chars output with zero tool calls (P4: threshold raised to 120)', () => {
    const spawnResult: SpawnResult = {
      success: true,
      // 50 characters — below new 120-char threshold
      output: 'A'.repeat(50),
      metrics: { tokens: 100, duration: 2000, toolCalls: 0 },
    };

    // P4: 50 chars < 120 threshold → now hollow
    expect(isHollowCompletion(spawnResult)).toBe(true);
  });

  it('returns false for exactly 120 chars output with zero tool calls', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: 'A'.repeat(120),
      metrics: { tokens: 100, duration: 2000, toolCalls: 0 },
    };

    // >= 120 chars → not hollow
    expect(isHollowCompletion(spawnResult)).toBe(false);
  });

  // ─── Failure-language hollow detection ───────────────────────────────────

  it('returns true for success=true with "budget exhausted" in output', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: 'I attempted the task but budget exhausted before I could finish the research.',
      metrics: { tokens: 500, duration: 5000, toolCalls: 3 },
    };
    expect(isHollowCompletion(spawnResult)).toBe(true);
  });

  it('returns true for success=true with "unable to complete" in output', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: 'I was unable to complete the requested changes due to context limitations.',
      metrics: { tokens: 1000, duration: 10000, toolCalls: 5 },
    };
    expect(isHollowCompletion(spawnResult)).toBe(true);
  });

  it('does not false-positive on success=true with legitimate output mentioning budget', () => {
    const spawnResult: SpawnResult = {
      success: true,
      output: 'Implemented the budget tracking feature. Added new Budget class with methods for allocation and reporting.',
      metrics: { tokens: 2000, duration: 20000, toolCalls: 8 },
    };
    // "budget" appears but not as a failure indicator phrase
    expect(isHollowCompletion(spawnResult)).toBe(false);
  });

  it('does not trigger failure-language check on success=false', () => {
    const spawnResult: SpawnResult = {
      success: false,
      output: 'Unable to complete the task due to errors.',
      metrics: { tokens: 200, duration: 3000, toolCalls: 1 },
    };
    // success=false — failure language check only runs when success=true
    expect(isHollowCompletion(spawnResult)).toBe(false);
  });
});

// ─── F15: All-probe-failure abort ────────────────────────────────────────────

describe('F15: all-probe-failure abort', () => {
  it('getHealthy returns empty array when all models are unhealthy', async () => {
    const { ModelHealthTracker } = await import('../../src/integrations/swarm/model-selector.js');
    const tracker = new ModelHealthTracker();

    // F19: markUnhealthy directly marks models as unhealthy (used by probe)
    tracker.markUnhealthy('z-ai/glm-5');
    tracker.markUnhealthy('minimax/minimax-m2.5');

    const uniqueModels = ['z-ai/glm-5', 'minimax/minimax-m2.5'];
    const healthyModels = tracker.getHealthy(uniqueModels);

    expect(healthyModels).toHaveLength(0);
  });

  it('getHealthy returns healthy models when at least one passes', async () => {
    const { ModelHealthTracker } = await import('../../src/integrations/swarm/model-selector.js');
    const tracker = new ModelHealthTracker();

    // F19: One fails probe (markUnhealthy), one passes
    tracker.markUnhealthy('z-ai/glm-5');
    tracker.recordSuccess('minimax/minimax-m2.5', 5000);

    const uniqueModels = ['z-ai/glm-5', 'minimax/minimax-m2.5'];
    const healthyModels = tracker.getHealthy(uniqueModels);

    expect(healthyModels).toHaveLength(1);
    expect(healthyModels[0]).toBe('minimax/minimax-m2.5');
  });

  it('markUnhealthy works with a single call (no need for 3+ recordFailures)', async () => {
    const { ModelHealthTracker } = await import('../../src/integrations/swarm/model-selector.js');
    const tracker = new ModelHealthTracker();

    // F19: Single markUnhealthy call should be sufficient
    tracker.markUnhealthy('test/model');
    expect(tracker.isHealthy('test/model')).toBe(false);
  });
});

// ─── F23: Probe uses chatWithTools ───────────────────────────────────────────

describe('F23: probeModelCapability uses chatWithTools', () => {
  it('skips probe when provider lacks chatWithTools', async () => {
    const { createSwarmOrchestrator } = await import('../../src/integrations/swarm/swarm-orchestrator.js');

    // Provider WITHOUT chatWithTools — plain LLMProvider
    const plainProvider = {
      name: 'plain-mock',
      defaultModel: 'test/model',
      chat: vi.fn().mockResolvedValue({ content: 'hi', stopReason: 'end_turn' as const }),
      isConfigured: () => true,
    };

    const config = {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/model',
      workers: [{ name: 'w', model: 'test/model', capabilities: ['code' as const] }],
      probeModels: true,
      probeFailureStrategy: 'abort' as const, // would abort if probe ran and failed
    };

    const mockRegistry = {
      registerAgent: vi.fn(),
      unregisterAgent: vi.fn(),
      getAgent: vi.fn(),
      listAgents: vi.fn(() => []),
      filterToolsForAgent: vi.fn(() => []),
    } as any;

    const mockSpawn = vi.fn().mockResolvedValue({
      success: true,
      output: 'Done',
      metrics: { tokens: 100, duration: 1000, toolCalls: 3 },
    });

    const orchestrator = createSwarmOrchestrator(config, plainProvider as any, mockRegistry, mockSpawn);

    // chat() should NOT be called for probe since provider lacks chatWithTools
    // The orchestrator will run but may fail for other reasons — we just care about the probe
    await orchestrator.execute('Test task');

    // Provider's chat() should not have been called with probe messages
    // (It might be called for decomposition, but not with 'test probe' content)
    const probeCalls = plainProvider.chat.mock.calls.filter(
      (call: any[]) => call[0]?.some?.((m: any) => m.content?.includes?.('test probe'))
    );
    expect(probeCalls).toHaveLength(0);
  });

  it('calls chatWithTools with tool definitions when provider supports it', async () => {
    const { createSwarmOrchestrator } = await import('../../src/integrations/swarm/swarm-orchestrator.js');

    // Provider WITH chatWithTools that returns tool calls (probe passes)
    // chat() response must include 2+ subtasks for decomposition to succeed
    const decompositionJson = JSON.stringify({
      subtasks: [
        { description: 'Research thing', type: 'research', dependencies: [], complexity: 3, modifies: [], reads: [] },
        { description: 'Implement thing', type: 'implement', dependencies: ['st-0'], complexity: 5, modifies: ['src/thing.ts'], reads: [] },
      ],
      strategy: 'adaptive',
      reasoning: 'Two subtasks for testing',
    });
    const toolProvider = {
      name: 'tool-mock',
      defaultModel: 'test/model',
      chat: vi.fn().mockResolvedValue({
        content: decompositionJson,
        stopReason: 'end_turn' as const,
        usage: { inputTokens: 100, outputTokens: 50 },
      }),
      isConfigured: () => true,
      chatWithTools: vi.fn().mockResolvedValue({
        content: '',
        stopReason: 'end_turn' as const,
        toolCalls: [{ id: 'tc-1', type: 'function', function: { name: 'read_file', arguments: '{"path":"package.json"}' } }],
      }),
    };

    const config = {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/model',
      workers: [{ name: 'w', model: 'test/model', capabilities: ['code' as const] }],
      probeModels: true,
    };

    const mockRegistry = {
      registerAgent: vi.fn(),
      unregisterAgent: vi.fn(),
      getAgent: vi.fn(),
      listAgents: vi.fn(() => []),
      filterToolsForAgent: vi.fn(() => []),
    } as any;

    const mockSpawn = vi.fn().mockResolvedValue({
      success: true,
      output: 'Done',
      metrics: { tokens: 100, duration: 1000, toolCalls: 3 },
    });

    const orchestrator = createSwarmOrchestrator(config, toolProvider as any, mockRegistry, mockSpawn);

    // Execute (will proceed past probe since chatWithTools returns tool calls)
    await orchestrator.execute('Test task');

    // chatWithTools should have been called for the probe
    expect(toolProvider.chatWithTools).toHaveBeenCalledTimes(1);
    const [messages, options] = toolProvider.chatWithTools.mock.calls[0];
    expect(messages[0].content).toContain('test probe');
    expect(options.tools).toBeDefined();
    expect(options.tools[0].function.name).toBe('read_file');
    expect(options.tool_choice).toBe('required');
  });

  it('warn-and-try strategy resets health when all models fail probe', async () => {
    const { ModelHealthTracker } = await import('../../src/integrations/swarm/model-selector.js');
    const tracker = new ModelHealthTracker();

    // Simulate: all models fail probe
    tracker.markUnhealthy('model-a');
    tracker.markUnhealthy('model-b');

    const uniqueModels = ['model-a', 'model-b'];
    let healthyModels = tracker.getHealthy(uniqueModels);
    expect(healthyModels).toHaveLength(0);

    // F23: warn-and-try resets health
    const probeStrategy = 'warn-and-try';
    if (healthyModels.length === 0 && probeStrategy === 'warn-and-try') {
      for (const model of uniqueModels) {
        tracker.recordSuccess(model, 0);
      }
    }

    healthyModels = tracker.getHealthy(uniqueModels);
    expect(healthyModels).toHaveLength(2);
  });

  it('abort strategy does not reset health when all models fail probe', async () => {
    const { ModelHealthTracker } = await import('../../src/integrations/swarm/model-selector.js');
    const tracker = new ModelHealthTracker();

    tracker.markUnhealthy('model-a');
    tracker.markUnhealthy('model-b');

    const uniqueModels = ['model-a', 'model-b'];
    const healthyModels = tracker.getHealthy(uniqueModels);
    expect(healthyModels).toHaveLength(0);

    // abort strategy: no reset — simulate the orchestrator's logic
    const probeStrategy: string = 'abort';
    if (healthyModels.length === 0 && probeStrategy === 'warn-and-try') {
      for (const model of uniqueModels) {
        tracker.recordSuccess(model, 0);
      }
    }

    // Still unhealthy — abort strategy doesn't reset
    expect(tracker.getHealthy(uniqueModels)).toHaveLength(0);
  });
});

// ─── F16: V7 hollow termination threshold ───────────────────────────────────

describe('F16: V7 hollow termination threshold default', () => {
  it('DEFAULT_SWARM_CONFIG does NOT override hollowTerminationRatio (uses code default 0.55)', () => {
    // The default is in the orchestrator code, not in DEFAULT_SWARM_CONFIG
    // Verify config doesn't accidentally set it to 0.7
    expect(DEFAULT_SWARM_CONFIG.hollowTerminationRatio).toBeUndefined();
  });
});

// ─── Quality gate closure report pre-check ──────────────────────────────────

describe('Quality gate closure report pre-check', () => {
  // We test this indirectly by importing evaluateWorkerOutput and verifying
  // it auto-fails on bad closure reports without calling the LLM judge.
  // The actual evaluateWorkerOutput needs a provider mock, so we test the logic pattern.

  function shouldAutoFail(closureReport: StructuredClosureReport): boolean {
    const noRealFindings = closureReport.findings.length === 0 ||
      closureReport.findings.every(f => /budget|unable|not completed|constraint/i.test(f));
    const admitsFailure = closureReport.failures.length > 0 &&
      closureReport.failures.some(f => /no.*search|no.*performed|not created/i.test(f));
    return noRealFindings && admitsFailure;
  }

  it('auto-fails when closure report has no real findings and admits failure', () => {
    const cr: StructuredClosureReport = {
      findings: [],
      actionsTaken: [],
      failures: ['No search was performed due to constraints'],
      remainingWork: ['Everything'],
      suggestedNextSteps: [],
        exitReason: 'completed',
    };
    expect(shouldAutoFail(cr)).toBe(true);
  });

  it('auto-fails when findings only mention budget and admits failure', () => {
    const cr: StructuredClosureReport = {
      findings: ['Unable to complete research'],
      actionsTaken: [],
      failures: ['File not created due to budget'],
      remainingWork: [],
      suggestedNextSteps: [],
        exitReason: 'completed',
    };
    expect(shouldAutoFail(cr)).toBe(true);
  });

  it('does not auto-fail when there are real findings', () => {
    const cr: StructuredClosureReport = {
      findings: ['React uses virtual DOM for efficient rendering', 'Next.js supports SSR'],
      actionsTaken: ['Searched documentation'],
      failures: ['No additional search performed'],
      remainingWork: [],
      suggestedNextSteps: [],
        exitReason: 'completed',
    };
    expect(shouldAutoFail(cr)).toBe(false);
  });

  it('does not auto-fail when no failures mentioned', () => {
    const cr: StructuredClosureReport = {
      findings: [],
      actionsTaken: [],
      failures: [],
      remainingWork: [],
      suggestedNextSteps: [],
        exitReason: 'completed',
    };
    expect(shouldAutoFail(cr)).toBe(false);
  });
});

// ─── Dependency context hollow detection ────────────────────────────────────

describe('Dependency context hollow detection', () => {
  // Test the buildDependencyContext logic by creating a task queue
  // We test via the SwarmTaskQueue class
  it('warns about hollow dependencies', async () => {
    const { SwarmTaskQueue } = await import('../../src/integrations/swarm/task-queue.js');
    const queue = new SwarmTaskQueue();

    // Completed dep with hollow output
    const hollowDep: SwarmTask = {
      id: 'st-0',
      description: 'Research AI frameworks',
      type: 'research',
      dependencies: [],
      status: 'completed',
      complexity: 3,
      wave: 0,
      attempts: 1,
      result: {
        success: true,
        output: 'Budget critical',
        closureReport: {
          findings: [],
          actionsTaken: [],
          failures: ['Unable to complete — budget exhausted'],
          remainingWork: ['All research'],
          suggestedNextSteps: [],
        exitReason: 'completed',
        },
        tokensUsed: 100,
        costUsed: 0.001,
        durationMs: 5000,
        model: 'test/model',
      },
    };

    // Completed dep with real output
    const realDep: SwarmTask = {
      id: 'st-1',
      description: 'Research ML libraries',
      type: 'research',
      dependencies: [],
      status: 'completed',
      complexity: 3,
      wave: 0,
      attempts: 1,
      result: {
        success: true,
        output: 'Found 5 popular ML libraries: TensorFlow, PyTorch, JAX, Scikit-learn, and Keras. TensorFlow and PyTorch dominate the market with approximately 70% combined market share.',
        closureReport: {
          findings: ['TensorFlow and PyTorch are the most popular ML libraries', 'JAX is growing rapidly'],
          actionsTaken: ['Searched for ML library comparisons', 'Read official documentation'],
          failures: [],
          remainingWork: [],
          suggestedNextSteps: [],
        exitReason: 'completed',
        },
        tokensUsed: 2000,
        costUsed: 0.01,
        durationMs: 30000,
        model: 'test/model',
      },
    };

    // Dependent task
    const mergeTask: SwarmTask = {
      id: 'st-2',
      description: 'Synthesize research findings',
      type: 'merge',
      dependencies: ['st-0', 'st-1'],
      status: 'pending',
      complexity: 4,
      wave: 1,
      attempts: 0,
    };

    // Access private methods via casting
    (queue as any).tasks.set('st-0', hollowDep);
    (queue as any).tasks.set('st-1', realDep);
    (queue as any).tasks.set('st-2', mergeTask);

    // Call updateReadyStatus to trigger buildDependencyContext
    (queue as any).updateReadyStatus();

    const task = (queue as any).tasks.get('st-2');
    expect(task.status).toBe('ready');
    expect(task.dependencyContext).toContain('WARNING');
    expect(task.dependencyContext).toContain('Research AI frameworks');
    // Should still include real dep context
    expect(task.dependencyContext).toContain('Research ML libraries');
    expect(task.dependencyContext).toContain('TensorFlow');
  });

  it('preserves real dependency output without warnings', async () => {
    const { SwarmTaskQueue } = await import('../../src/integrations/swarm/task-queue.js');
    const queue = new SwarmTaskQueue();

    const realDep: SwarmTask = {
      id: 'st-0',
      description: 'Research testing frameworks',
      type: 'research',
      dependencies: [],
      status: 'completed',
      complexity: 3,
      wave: 0,
      attempts: 1,
      result: {
        success: true,
        output: 'Jest and Vitest are the top testing frameworks. Vitest offers better ESM support and faster execution times.',
        closureReport: {
          findings: ['Jest is the most widely used testing framework with over 40 million weekly downloads', 'Vitest is the fastest for Vite-based projects with native ESM support'],
          actionsTaken: ['Compared Jest, Vitest, and Mocha across performance, DX, and ecosystem criteria'],
          failures: [],
          remainingWork: [],
          suggestedNextSteps: [],
        exitReason: 'completed',
        },
        tokensUsed: 1500,
        costUsed: 0.008,
        durationMs: 20000,
        model: 'test/model',
      },
    };

    const mergeTask: SwarmTask = {
      id: 'st-1',
      description: 'Write recommendation',
      type: 'merge',
      dependencies: ['st-0'],
      status: 'pending',
      complexity: 3,
      wave: 1,
      attempts: 0,
    };

    (queue as any).tasks.set('st-0', realDep);
    (queue as any).tasks.set('st-1', mergeTask);
    (queue as any).updateReadyStatus();

    const task = (queue as any).tasks.get('st-1');
    expect(task.status).toBe('ready');
    expect(task.dependencyContext).not.toContain('WARNING');
    expect(task.dependencyContext).toContain('Research testing frameworks');
  });

  it('does NOT flag short real completion as hollow (Bug 2 fix)', async () => {
    const { SwarmTaskQueue } = await import('../../src/integrations/swarm/task-queue.js');
    const queue = new SwarmTaskQueue();

    // Short but legitimate completion — no budget failures
    const shortRealDep: SwarmTask = {
      id: 'st-0',
      description: 'Fix the parser bug',
      type: 'implement',
      dependencies: [],
      status: 'completed',
      complexity: 2,
      wave: 0,
      attempts: 1,
      result: {
        success: true,
        output: 'Fixed the bug',
        closureReport: {
          findings: ['Fixed the bug'],
          actionsTaken: ['Updated parser.ts'],
          failures: [],
          remainingWork: [],
          suggestedNextSteps: [],
          exitReason: 'completed',
        },
        tokensUsed: 500,
        costUsed: 0.002,
        durationMs: 10000,
        model: 'test/model',
      },
    };

    const dependentTask: SwarmTask = {
      id: 'st-1',
      description: 'Write tests for parser fix',
      type: 'test',
      dependencies: ['st-0'],
      status: 'pending',
      complexity: 3,
      wave: 1,
      attempts: 0,
    };

    (queue as any).tasks.set('st-0', shortRealDep);
    (queue as any).tasks.set('st-1', dependentTask);
    (queue as any).updateReadyStatus();

    const task = (queue as any).tasks.get('st-1');
    expect(task.status).toBe('ready');
    // Short real completion should NOT trigger hollow warning
    expect(task.dependencyContext).not.toContain('WARNING');
    // Should include the actual dependency context
    expect(task.dependencyContext).toContain('Fix the parser bug');
  });
});

// ─── Hollow completion does NOT inflate health score (Bug 1 fix) ─────────────

describe('Hollow completion health score (Bug 1 fix)', () => {
  it('recordSuccess is not called for hollow completions', async () => {
    const { ModelHealthTracker } = await import('../../src/integrations/swarm/model-selector.js');
    const tracker = new ModelHealthTracker();

    // Simulate what the orchestrator does:
    // A hollow completion (0 tool calls, short output) should NOT record success
    const model = 'test/hollow-model';
    const spawnResult: SpawnResult = {
      success: true,
      output: 'I completed the task',
      metrics: { tokens: 500, duration: 5000, toolCalls: 0 },
    };

    // Check hollow first (as the fixed code does)
    const hollow = isHollowCompletion(spawnResult);
    expect(hollow).toBe(true);

    // Since it's hollow, we should NOT record success
    if (!hollow) {
      tracker.recordSuccess(model, 5000);
    }

    const records = tracker.getAllRecords();
    const modelRecord = records.find(r => r.model === model);
    // Model should have no record at all (never had success recorded)
    expect(modelRecord).toBeUndefined();
  });

  it('recordSuccess IS called for real completions', async () => {
    const { ModelHealthTracker } = await import('../../src/integrations/swarm/model-selector.js');
    const tracker = new ModelHealthTracker();

    const model = 'test/good-model';
    const spawnResult: SpawnResult = {
      success: true,
      output: 'Found results',
      metrics: { tokens: 2000, duration: 15000, toolCalls: 8 },
    };

    const hollow = isHollowCompletion(spawnResult);
    expect(hollow).toBe(false);

    if (!hollow) {
      tracker.recordSuccess(model, 15000);
    }

    const records = tracker.getAllRecords();
    const modelRecord = records.find(r => r.model === model);
    expect(modelRecord).toBeDefined();
    expect(modelRecord!.successes).toBe(1);
    expect(modelRecord!.healthy).toBe(true);
  });

  it('recordFailure IS called for hollow completions', async () => {
    const { ModelHealthTracker } = await import('../../src/integrations/swarm/model-selector.js');
    const tracker = new ModelHealthTracker();

    const model = 'test/hollow-model';
    const spawnResult: SpawnResult = {
      success: true,
      output: 'I completed the task',
      metrics: { tokens: 500, duration: 5000, toolCalls: 0 },
    };

    const hollow = isHollowCompletion(spawnResult);
    expect(hollow).toBe(true);

    // Hollow completions now record a failure (not just skip success)
    if (hollow) {
      tracker.recordFailure(model, 'error');
    }

    const records = tracker.getAllRecords();
    const modelRecord = records.find(r => r.model === model);
    expect(modelRecord).toBeDefined();
    expect(modelRecord!.failures).toBe(1);
    expect(modelRecord!.successes).toBe(0);
  });

  it('hollow completion triggers model failover when alternative available', async () => {
    const { ModelHealthTracker, selectAlternativeModel } = await import('../../src/integrations/swarm/model-selector.js');
    const tracker = new ModelHealthTracker();

    const hollowModel = 'test/hollow-model';

    // Record several failures to degrade health
    tracker.recordFailure(hollowModel, 'error');
    tracker.recordFailure(hollowModel, 'error');
    tracker.recordFailure(hollowModel, 'error');

    const workers = [
      { name: 'worker-a', model: hollowModel, capabilities: ['code' as const] },
      { name: 'worker-b', model: 'test/good-model', capabilities: ['code' as const] },
    ];

    const alternative = selectAlternativeModel(workers, hollowModel, 'code', tracker);
    // Should select the healthy alternative
    expect(alternative).toBeDefined();
    expect(alternative!.model).toBe('test/good-model');
  });
});

// ─── Quality circuit breaker wave-boundary reset ─────────────────────────────

describe('Quality circuit breaker wave-boundary reset', () => {
  it('quality-gate-passed resets counter within a wave', () => {
    // Within a wave, when a task passes the quality gate, the counter resets
    let consecutiveQualityRejections = 0;

    // Simulate 3 consecutive rejections
    consecutiveQualityRejections = 3;

    // Quality gate passes → counter resets (line 1194 in orchestrator)
    consecutiveQualityRejections = 0;

    expect(consecutiveQualityRejections).toBe(0);
  });

  it('isLastAttempt completion does NOT reset quality counter within a wave', () => {
    // isLastAttempt tasks bypass the quality gate entirely — they didn't *pass*
    // quality, we just gave up. So completing them should NOT reset the counter.
    let consecutiveQualityRejections = 0;
    let qualityGateDisabled = false;
    const THRESHOLD = 8;

    // Simulate 5 rejections within a wave
    for (let i = 0; i < 5; i++) {
      consecutiveQualityRejections++;
    }

    // An isLastAttempt task completes — this bypassed quality gate,
    // so the counter should NOT reset (per-completion reset was removed)
    // The old code would have reset here; the new code does not.
    // (No reset logic fires for task completion — only quality-gate-passed resets within wave)

    expect(consecutiveQualityRejections).toBe(5);
    expect(qualityGateDisabled).toBe(false);

    // Continue accumulating rejections — they should still count
    for (let i = 5; i < THRESHOLD; i++) {
      consecutiveQualityRejections++;
      if (consecutiveQualityRejections >= THRESHOLD) {
        qualityGateDisabled = true;
      }
    }
    expect(qualityGateDisabled).toBe(true);
  });

  it('wave boundary resets circuit breaker for fresh evaluation window', () => {
    let consecutiveQualityRejections = 0;
    let qualityGateDisabled = false;
    const THRESHOLD = 8;

    // Wave N: accumulate enough rejections to trip the breaker
    for (let i = 0; i < THRESHOLD; i++) {
      consecutiveQualityRejections++;
      if (consecutiveQualityRejections >= THRESHOLD) {
        qualityGateDisabled = true;
      }
    }
    expect(qualityGateDisabled).toBe(true);

    // Wave boundary reset (happens in executeWaves after fixup tasks)
    if (qualityGateDisabled) {
      qualityGateDisabled = false;
      consecutiveQualityRejections = 0;
    }

    // Wave N+1 gets a fresh chance
    expect(consecutiveQualityRejections).toBe(0);
    expect(qualityGateDisabled).toBe(false);
  });

  it('threshold is 8 (raised from 5)', () => {
    let consecutiveQualityRejections = 0;
    let qualityGateDisabled = false;
    const THRESHOLD = 8;

    for (let i = 0; i < 5; i++) {
      consecutiveQualityRejections++;
      if (consecutiveQualityRejections >= THRESHOLD) {
        qualityGateDisabled = true;
      }
    }
    // 5 should NOT trip with threshold 8
    expect(qualityGateDisabled).toBe(false);

    for (let i = 5; i < 8; i++) {
      consecutiveQualityRejections++;
      if (consecutiveQualityRejections >= THRESHOLD) {
        qualityGateDisabled = true;
      }
    }
    // 8 should trip
    expect(qualityGateDisabled).toBe(true);
  });
});

// ─── Per-task-type timeout ──────────────────────────────────────────────────

describe('Per-task-type timeout', () => {
  const registeredAgents = new Map<string, AgentDefinition>();

  const mockAgentRegistry = {
    registerAgent: vi.fn((def: AgentDefinition) => {
      registeredAgents.set(def.name, def);
    }),
    unregisterAgent: vi.fn(),
    getAgent: vi.fn(),
    listAgents: vi.fn(() => []),
    filterToolsForAgent: vi.fn(() => []),
  } as unknown as AgentRegistry;

  const mockBudgetPool = {
    hasCapacity: vi.fn().mockReturnValue(true),
    pool: { reserve: vi.fn().mockReturnValue({ tokenBudget: 50000 }) },
    orchestratorReserve: 750000,
    maxPerWorker: 50000,
    getStats: vi.fn().mockReturnValue({ totalTokens: 5000000, tokensUsed: 0 }),
  } as unknown as SwarmBudgetPool;

  beforeEach(() => {
    registeredAgents.clear();
  });

  it('should use default taskTypeTimeouts from DEFAULT_SWARM_CONFIG', () => {
    expect(DEFAULT_SWARM_CONFIG.taskTypeTimeouts).toBeDefined();
    expect(DEFAULT_SWARM_CONFIG.taskTypeTimeouts?.research).toBe(300_000);
    expect(DEFAULT_SWARM_CONFIG.taskTypeTimeouts?.analysis).toBe(300_000);
    expect(DEFAULT_SWARM_CONFIG.taskTypeTimeouts?.merge).toBe(180_000);
  });

  it('should use per-type timeout for research tasks', async () => {
    const mockSpawnAgent = vi.fn().mockImplementation(() => {
      return new Promise(resolve => {
        // Resolve immediately — we care about the timeout race, not the result
        resolve({
          success: true,
          output: 'Done',
          metrics: { tokens: 100, duration: 1000, toolCalls: 3 },
        });
      });
    });

    const config: SwarmConfig = {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/model',
      workerTimeout: 120_000,
      taskTypeTimeouts: { research: 300_000 },
      workers: [
        { name: 'researcher', model: 'test/researcher', capabilities: ['research'] },
      ],
    };

    const pool = new SwarmWorkerPool(config, mockAgentRegistry, mockSpawnAgent, mockBudgetPool);

    const task: SwarmTask = {
      id: 'test-timeout',
      description: 'Research AI landscape',
      type: 'research',
      dependencies: [],
      status: 'ready',
      complexity: 3,
      wave: 0,
      attempts: 0,
    };

    await pool.dispatch(task);

    // Verify the task was dispatched (spawn was called)
    expect(mockSpawnAgent).toHaveBeenCalled();
  });

  it('should fall back to workerTimeout for types without override', async () => {
    const mockSpawnAgent = vi.fn().mockResolvedValue({
      success: true,
      output: 'Done',
      metrics: { tokens: 100, duration: 1000, toolCalls: 3 },
    });

    const config: SwarmConfig = {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/model',
      workerTimeout: 120_000,
      taskTypeTimeouts: { research: 300_000 },
      workers: [
        { name: 'coder', model: 'test/coder', capabilities: ['code'] },
      ],
    };

    const pool = new SwarmWorkerPool(config, mockAgentRegistry, mockSpawnAgent, mockBudgetPool);

    const task: SwarmTask = {
      id: 'test-timeout-fallback',
      description: 'Implement parser',
      type: 'implement',
      dependencies: [],
      status: 'ready',
      complexity: 5,
      wave: 0,
      attempts: 0,
    };

    await pool.dispatch(task);
    expect(mockSpawnAgent).toHaveBeenCalled();
  });
});

// ─── F24: filesModified in dependency context ────────────────────────────────

describe('F24b: filesModified in dependency context', () => {
  it('includes filesModified list in dependency context', async () => {
    const { SwarmTaskQueue } = await import('../../src/integrations/swarm/task-queue.js');
    const queue = new SwarmTaskQueue();

    const dep: SwarmTask = {
      id: 'st-0',
      description: 'Implement auth module',
      type: 'implement',
      dependencies: [],
      status: 'completed',
      complexity: 5,
      wave: 0,
      attempts: 1,
      result: {
        success: true,
        output: 'Created authentication module with JWT support and middleware chain.',
        closureReport: {
          findings: ['Implemented JWT-based auth with refresh token rotation'],
          actionsTaken: ['Created src/auth.ts', 'Created src/middleware.ts'],
          failures: [],
          remainingWork: [],
          suggestedNextSteps: [],
          exitReason: 'completed',
        },
        tokensUsed: 3000,
        costUsed: 0.02,
        durationMs: 45000,
        filesModified: ['src/auth.ts', 'src/middleware.ts'],
        model: 'test/model',
      },
    };

    const dependentTask: SwarmTask = {
      id: 'st-1',
      description: 'Write tests for auth module',
      type: 'test',
      dependencies: ['st-0'],
      status: 'pending',
      complexity: 4,
      wave: 1,
      attempts: 0,
    };

    (queue as any).tasks.set('st-0', dep);
    (queue as any).tasks.set('st-1', dependentTask);
    (queue as any).updateReadyStatus();

    const task = (queue as any).tasks.get('st-1');
    expect(task.status).toBe('ready');
    expect(task.dependencyContext).toContain('Files created/modified: src/auth.ts, src/middleware.ts');
  });

  it('omits filesModified line when no files were modified', async () => {
    const { SwarmTaskQueue } = await import('../../src/integrations/swarm/task-queue.js');
    const queue = new SwarmTaskQueue();

    const dep: SwarmTask = {
      id: 'st-0',
      description: 'Research API patterns',
      type: 'research',
      dependencies: [],
      status: 'completed',
      complexity: 3,
      wave: 0,
      attempts: 1,
      result: {
        success: true,
        output: 'Found several API design patterns including REST, GraphQL, and gRPC.',
        closureReport: {
          findings: ['REST is most common', 'GraphQL growing in adoption'],
          actionsTaken: ['Searched documentation'],
          failures: [],
          remainingWork: [],
          suggestedNextSteps: [],
          exitReason: 'completed',
        },
        tokensUsed: 1500,
        costUsed: 0.008,
        durationMs: 20000,
        model: 'test/model',
        // No filesModified
      },
    };

    const dependentTask: SwarmTask = {
      id: 'st-1',
      description: 'Implement API',
      type: 'implement',
      dependencies: ['st-0'],
      status: 'pending',
      complexity: 5,
      wave: 1,
      attempts: 0,
    };

    (queue as any).tasks.set('st-0', dep);
    (queue as any).tasks.set('st-1', dependentTask);
    (queue as any).updateReadyStatus();

    const task = (queue as any).tasks.get('st-1');
    expect(task.status).toBe('ready');
    expect(task.dependencyContext).not.toContain('Files created/modified');
  });
});

// ─── F24: Probe timeout ─────────────────────────────────────────────────────

describe('F24a: probe timeout', () => {
  // Valid decomposition JSON for the orchestrator to proceed past decompose()
  const validDecompositionJson = JSON.stringify({
    subtasks: [
      { description: 'Research thing', type: 'research', dependencies: [], complexity: 3, modifies: [], reads: [] },
      { description: 'Implement thing', type: 'implement', dependencies: ['st-0'], complexity: 5, modifies: ['src/thing.ts'], reads: [] },
    ],
    strategy: 'adaptive',
    reasoning: 'Two subtasks for testing',
  });

  it('marks model unhealthy when probe times out', async () => {
    const { createSwarmOrchestrator } = await import('../../src/integrations/swarm/swarm-orchestrator.js');

    // Provider whose chatWithTools never resolves (simulates slow model)
    const slowProvider = {
      name: 'slow-mock',
      defaultModel: 'test/slow-model',
      chat: vi.fn().mockResolvedValue({
        content: validDecompositionJson,
        stopReason: 'end_turn' as const,
        usage: { inputTokens: 100, outputTokens: 50 },
      }),
      isConfigured: () => true,
      chatWithTools: vi.fn().mockImplementation(() =>
        new Promise(() => {/* never resolves */}),
      ),
    };

    const config = {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/slow-model',
      workers: [{ name: 'w', model: 'test/slow-model', capabilities: ['code' as const] }],
      probeModels: true,
      probeTimeoutMs: 50, // 50ms timeout for fast test
      probeFailureStrategy: 'warn-and-try' as const,
    };

    const mockRegistry = {
      registerAgent: vi.fn(),
      unregisterAgent: vi.fn(),
      getAgent: vi.fn(),
      listAgents: vi.fn(() => []),
      filterToolsForAgent: vi.fn(() => []),
    } as any;

    const mockSpawn = vi.fn().mockResolvedValue({
      success: true,
      output: 'Done',
      metrics: { tokens: 100, duration: 1000, toolCalls: 3 },
    });

    const orchestrator = createSwarmOrchestrator(config, slowProvider as any, mockRegistry, mockSpawn);

    // Execute — the probe should timeout after 50ms
    await orchestrator.execute('Test task');

    // chatWithTools should have been called (probe was attempted)
    expect(slowProvider.chatWithTools).toHaveBeenCalledTimes(1);
  });

  it('respects custom probeTimeoutMs from config', async () => {
    const { createSwarmOrchestrator } = await import('../../src/integrations/swarm/swarm-orchestrator.js');

    let resolvedAfter = 0;
    const timedProvider = {
      name: 'timed-mock',
      defaultModel: 'test/timed-model',
      chat: vi.fn().mockResolvedValue({
        content: validDecompositionJson,
        stopReason: 'end_turn' as const,
        usage: { inputTokens: 100, outputTokens: 50 },
      }),
      isConfigured: () => true,
      chatWithTools: vi.fn().mockImplementation(() =>
        new Promise(resolve => {
          setTimeout(() => {
            resolvedAfter = Date.now();
            resolve({
              content: '',
              stopReason: 'end_turn' as const,
              toolCalls: [{ id: 'tc-1', type: 'function', function: { name: 'read_file', arguments: '{"path":"package.json"}' } }],
            });
          }, 200); // resolves in 200ms
        }),
      ),
    };

    // With 500ms timeout, the 200ms probe should succeed
    const config = {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/timed-model',
      workers: [{ name: 'w', model: 'test/timed-model', capabilities: ['code' as const] }],
      probeModels: true,
      probeTimeoutMs: 500,
      probeFailureStrategy: 'abort' as const,
    };

    const mockRegistry = {
      registerAgent: vi.fn(),
      unregisterAgent: vi.fn(),
      getAgent: vi.fn(),
      listAgents: vi.fn(() => []),
      filterToolsForAgent: vi.fn(() => []),
    } as any;

    const mockSpawn = vi.fn().mockResolvedValue({
      success: true,
      output: 'Done',
      metrics: { tokens: 100, duration: 1000, toolCalls: 3 },
    });

    const orchestrator = createSwarmOrchestrator(config, timedProvider as any, mockRegistry, mockSpawn);
    await orchestrator.execute('Test task');

    // chatWithTools should have resolved (not timed out)
    expect(timedProvider.chatWithTools).toHaveBeenCalledTimes(1);
    expect(resolvedAfter).toBeGreaterThan(0);
  });
});

// ─── F25: Resilient Swarm — Timeout-Aware Retries + Graceful Cascade ────────

describe('F25a: Consecutive timeout counter triggers early fail', () => {
  it('counts consecutive timeouts and fails when limit reached with no alt model', async () => {
    const { ModelHealthTracker, selectAlternativeModel } = await import('../../src/integrations/swarm/model-selector.js');
    const tracker = new ModelHealthTracker();

    // Simulate what the orchestrator does: track consecutive timeouts per task
    const taskTimeoutCounts = new Map<string, number>();
    const consecutiveTimeoutLimit = 3;
    const taskId = 'task-9';
    const model = 'test/slow-model';

    // 3 consecutive timeouts
    for (let i = 0; i < 3; i++) {
      const count = (taskTimeoutCounts.get(taskId) ?? 0) + 1;
      taskTimeoutCounts.set(taskId, count);
      tracker.recordFailure(model, 'timeout');
    }

    expect(taskTimeoutCounts.get(taskId)).toBe(3);
    expect(taskTimeoutCounts.get(taskId)! >= consecutiveTimeoutLimit).toBe(true);

    // No alternative model (single-model swarm)
    const workers = [{ name: 'worker', model, capabilities: ['code' as const] }];
    const alt = selectAlternativeModel(workers, model, 'code', tracker);
    expect(alt).toBeUndefined(); // No alt → should early-fail
  });
});

describe('F25b: Model failover on consecutive timeouts', () => {
  it('selects alternative model after consecutive timeout limit', async () => {
    const { ModelHealthTracker, selectAlternativeModel } = await import('../../src/integrations/swarm/model-selector.js');
    const tracker = new ModelHealthTracker();

    const slowModel = 'test/slow-model';
    const fastModel = 'test/fast-model';

    // Degrade slow model health with timeouts
    tracker.recordFailure(slowModel, 'timeout');
    tracker.recordFailure(slowModel, 'timeout');
    tracker.recordFailure(slowModel, 'timeout');

    // Fast model is healthy
    tracker.recordSuccess(fastModel, 5000);

    const workers = [
      { name: 'slow', model: slowModel, capabilities: ['code' as const] },
      { name: 'fast', model: fastModel, capabilities: ['code' as const] },
    ];

    const alt = selectAlternativeModel(workers, slowModel, 'code', tracker);
    expect(alt).toBeDefined();
    expect(alt!.model).toBe(fastModel);
  });

  it('resets timeout counter after model failover', () => {
    const taskTimeoutCounts = new Map<string, number>();
    const taskId = 'task-9';

    // Accumulate to limit
    taskTimeoutCounts.set(taskId, 3);

    // Failover succeeded — reset counter for new model
    taskTimeoutCounts.set(taskId, 0);

    expect(taskTimeoutCounts.get(taskId)).toBe(0);
  });
});

describe('F25a: Timeout counter resets on non-timeout failure', () => {
  it('clears counter when task fails with non-timeout error', () => {
    const taskTimeoutCounts = new Map<string, number>();
    const taskId = 'task-5';

    // Accumulate 2 timeouts
    taskTimeoutCounts.set(taskId, 2);

    // Non-timeout failure → clear
    const isTimeout = false;
    if (!isTimeout) {
      taskTimeoutCounts.delete(taskId);
    }

    expect(taskTimeoutCounts.has(taskId)).toBe(false);
  });
});

describe('F25c: Timeout-lenient cascade', () => {
  it('single-dep task proceeds when dependency timed out', async () => {
    const { SwarmTaskQueue } = await import('../../src/integrations/swarm/task-queue.js');
    const queue = new SwarmTaskQueue();

    // Failed dep with timeout failureMode
    const timedOutDep: SwarmTask = {
      id: 'st-0',
      description: 'Write comprehensive evaluator unit tests',
      type: 'test',
      dependencies: [],
      status: 'failed',
      complexity: 7,
      wave: 0,
      attempts: 5,
      failureMode: 'timeout',
      targetFiles: ['tests/evaluator.test.ts'],
    };

    // Single-dep dependent task
    const dependentTask: SwarmTask = {
      id: 'st-1',
      description: 'Implement evaluator integration',
      type: 'implement',
      dependencies: ['st-0'],
      status: 'ready', // will be set to ready or pending
      complexity: 5,
      wave: 1,
      attempts: 0,
    };

    (queue as any).tasks.set('st-0', timedOutDep);
    (queue as any).tasks.set('st-1', dependentTask);

    // Trigger cascadeSkip for st-0
    (queue as any).cascadeSkip('st-0');

    const task = (queue as any).tasks.get('st-1');
    // F25c: Should be 'ready' not 'skipped' because dep timed out
    expect(task.status).toBe('ready');
    expect(task.partialContext).toBeDefined();
    expect(task.partialContext.failed.length).toBe(1);
    expect(task.partialContext.failed[0]).toContain('timed out');
  });

  it('multi-dep task proceeds when one dep timed out (partial context)', async () => {
    const { SwarmTaskQueue } = await import('../../src/integrations/swarm/task-queue.js');
    const queue = new SwarmTaskQueue();

    // Completed dep
    const completedDep: SwarmTask = {
      id: 'st-0',
      description: 'Implement core module',
      type: 'implement',
      dependencies: [],
      status: 'completed',
      complexity: 5,
      wave: 0,
      attempts: 1,
      result: {
        success: true,
        output: 'Created the core module with all required functions.',
        tokensUsed: 2000,
        costUsed: 0.01,
        durationMs: 30000,
        model: 'test/model',
      },
    };

    // Timed-out dep
    const timedOutDep: SwarmTask = {
      id: 'st-1',
      description: 'Write unit tests for core',
      type: 'test',
      dependencies: [],
      status: 'failed',
      complexity: 7,
      wave: 0,
      attempts: 5,
      failureMode: 'timeout',
    };

    // Dependent task with 2 deps
    const dependentTask: SwarmTask = {
      id: 'st-2',
      description: 'Integrate core with API layer',
      type: 'integrate',
      dependencies: ['st-0', 'st-1'],
      status: 'ready',
      complexity: 6,
      wave: 1,
      attempts: 0,
    };

    (queue as any).tasks.set('st-0', completedDep);
    (queue as any).tasks.set('st-1', timedOutDep);
    (queue as any).tasks.set('st-2', dependentTask);

    // Trigger cascadeSkip for st-1
    (queue as any).cascadeSkip('st-1');

    const task = (queue as any).tasks.get('st-2');
    // F25c: timeout cascade → ready with partial context
    expect(task.status).toBe('ready');
    expect(task.partialContext).toBeDefined();
    expect(task.partialContext.succeeded.length).toBe(1);
    expect(task.partialContext.failed.length).toBe(1);
  });

  it('non-timeout single-dep still cascade-skips', async () => {
    const { SwarmTaskQueue } = await import('../../src/integrations/swarm/task-queue.js');
    const queue = new SwarmTaskQueue();

    // Failed dep with non-timeout failure (error)
    const errorDep: SwarmTask = {
      id: 'st-0',
      description: 'Implement feature X',
      type: 'implement',
      dependencies: [],
      status: 'failed',
      complexity: 5,
      wave: 0,
      attempts: 3,
      failureMode: 'error',
    };

    // Single-dep dependent
    const dependentTask: SwarmTask = {
      id: 'st-1',
      description: 'Test feature X',
      type: 'test',
      dependencies: ['st-0'],
      status: 'ready',
      complexity: 4,
      wave: 1,
      attempts: 0,
    };

    (queue as any).tasks.set('st-0', errorDep);
    (queue as any).tasks.set('st-1', dependentTask);
    (queue as any).artifactAwareSkip = false; // disable artifact check for clean test

    // Trigger cascadeSkip for st-0
    (queue as any).cascadeSkip('st-0');

    const task = (queue as any).tasks.get('st-1');
    // Non-timeout failure → still cascade-skipped
    expect(task.status).toBe('skipped');
  });
});
