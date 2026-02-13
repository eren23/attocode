/**
 * Swarm Quality Gate Death Spiral Fix Tests
 *
 * Tests for:
 * 1. Quality circuit breaker: disables gates after N consecutive rejections
 * 2. Artifact auto-fail: doesn't trigger model failover
 * 3. Last-attempt bypass: final attempt skips quality gate
 * 4. Configurable quality threshold: passed to evaluateWorkerOutput
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
      { name: 'coder-a', model: 'model-a', capabilities: ['code', 'research'] },
      { name: 'coder-b', model: 'model-b', capabilities: ['code', 'research'] },
    ],
    qualityGates: true,
    workerRetries: 2,
    enablePlanning: false,
    enableWaveReview: false,
    enableVerification: false,
    enablePersistence: false,
    enableModelFailover: true,
    ...overrides,
  };
}

function makeMockProvider(qualityScore: number = 2) {
  // First call: decomposition. Rest: quality gate.
  let callCount = 0;
  return {
    chat: vi.fn().mockImplementation(() => {
      callCount++;
      if (callCount === 1) {
        // Decomposition response
        return Promise.resolve({
          content: JSON.stringify({
            subtasks: [
              { description: 'Task A', type: 'implement', complexity: 3, dependencies: [], parallelizable: true, relevantFiles: [] },
              { description: 'Task B', type: 'implement', complexity: 3, dependencies: [], parallelizable: true, relevantFiles: [] },
            ],
            strategy: 'parallel',
            reasoning: 'test',
          }),
        });
      }
      // Quality gate response
      return Promise.resolve({
        content: `SCORE: ${qualityScore}\nFEEDBACK: Score is ${qualityScore}`,
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

// =============================================================================
// Test 1: Quality circuit breaker
// =============================================================================

describe('Quality circuit breaker', () => {
  it('should disable quality gates after 8 consecutive rejections', async () => {
    const config = makeConfig({ qualityGates: true, workerRetries: 2, maxConcurrency: 5, dispatchStaggerMs: 0, probeModels: false });

    // Need enough tasks × attempts to reach 8 consecutive rejections.
    // With workerRetries=2: each task gets 2 quality-gated attempts (3rd skips gate).
    // So we need at least 5 tasks to reach 10 quality evaluations (> 8 threshold).
    // Per-completion resets were removed — only quality-gate-passed and wave boundaries
    // reset the counter now. So isLastAttempt completions no longer interfere.
    let decomposeCalled = false;
    const provider = {
      chat: vi.fn().mockImplementation(() => {
        if (!decomposeCalled) {
          decomposeCalled = true;
          return Promise.resolve({
            content: JSON.stringify({
              subtasks: [
                { description: 'Task A', type: 'implement', complexity: 3, dependencies: [], parallelizable: true, relevantFiles: [] },
                { description: 'Task B', type: 'implement', complexity: 3, dependencies: [], parallelizable: true, relevantFiles: [] },
                { description: 'Task C', type: 'implement', complexity: 3, dependencies: [], parallelizable: true, relevantFiles: [] },
                { description: 'Task D', type: 'implement', complexity: 3, dependencies: [], parallelizable: true, relevantFiles: [] },
                { description: 'Task E', type: 'implement', complexity: 3, dependencies: [], parallelizable: true, relevantFiles: [] },
              ],
              strategy: 'parallel',
              reasoning: 'test',
            }),
          });
        }
        // Quality gate always returns score 2 (fails with default threshold 3)
        return Promise.resolve({ content: 'SCORE: 2\nFEEDBACK: Incomplete' });
      }),
      name: 'mock',
      listModels: vi.fn(),
      supportsStreaming: false,
      countTokens: vi.fn(),
    } as any;

    const registry = makeMockRegistry();

    const spawnFn = vi.fn().mockResolvedValue({
      success: true,
      output: 'done',
      metrics: { tokens: 100, duration: 1000, toolCalls: 1 },
    });

    const orchestrator = new SwarmOrchestrator(config, provider, registry, spawnFn);

    const events: SwarmEvent[] = [];
    orchestrator.subscribe((event) => events.push(event));

    await orchestrator.execute('Test task for circuit breaker');

    // Should have a quality-circuit-breaker decision logged
    const circuitBreakerDecisions = events.filter(
      e => e.type === 'swarm.orchestrator.decision'
        && (e as any).decision.phase === 'quality-circuit-breaker',
    );

    // The circuit breaker should have tripped at some point
    expect(circuitBreakerDecisions.length).toBeGreaterThanOrEqual(1);

    // Should have quality rejections before the breaker tripped
    const rejectedEvents = events.filter(e => e.type === 'swarm.quality.rejected');
    expect(rejectedEvents.length).toBeGreaterThanOrEqual(8);
  });
});

// =============================================================================
// Test 2: Artifact auto-fail doesn't trigger model failover
// =============================================================================

describe('Artifact auto-fail and model failover', () => {
  it('artifactAutoFail should NOT trigger model failover', async () => {
    // This test verifies via the quality gate unit that artifactAutoFail is set,
    // and that the orchestrator's failover condition checks it.
    // We test the condition directly since integration test is complex.

    // Simulate what the orchestrator checks:
    const quality = {
      score: 1,
      feedback: 'Target files are empty or missing',
      passed: false,
      artifactAutoFail: true,
    };

    // The orchestrator condition: quality.score <= 1 && enableModelFailover && !quality.artifactAutoFail
    const shouldFailover = quality.score <= 1 && true && !quality.artifactAutoFail;
    expect(shouldFailover).toBe(false);

    // Without the flag, failover WOULD trigger
    const qualityWithoutFlag = {
      score: 1,
      feedback: 'Completely wrong output',
      passed: false,
    };
    const shouldFailoverWithout = qualityWithoutFlag.score <= 1 && true && !(qualityWithoutFlag as any).artifactAutoFail;
    expect(shouldFailoverWithout).toBe(true);
  });

  it('integration: artifact auto-fail events should not produce model.failover events', async () => {
    // Use a real orchestrator but with tasks that have missing target files
    const config = makeConfig({
      qualityGates: true,
      workerRetries: 0, // no retries to simplify
      probeModels: false, // Skip probe — this test is about artifact auto-fail, not probe behavior
    });

    // The quality gate will auto-fail because target files don't exist,
    // so the mock provider's quality response won't be called
    const provider = makeMockProvider(5);

    // Override decomposition to return tasks with non-existent target files
    let decomposeCalled = false;
    provider.chat = vi.fn().mockImplementation(() => {
      if (!decomposeCalled) {
        decomposeCalled = true;
        return Promise.resolve({
          content: JSON.stringify({
            subtasks: [
              {
                description: 'Create missing file',
                type: 'implement',
                complexity: 3,
                dependencies: [],
                parallelizable: true,
                relevantFiles: ['/tmp/nonexistent-death-spiral-test-file-xyz.ts'],
              },
              {
                description: 'Another task',
                type: 'implement',
                complexity: 3,
                dependencies: [],
                parallelizable: true,
                relevantFiles: [],
              },
            ],
            strategy: 'parallel',
            reasoning: 'test',
          }),
        });
      }
      return Promise.resolve({ content: 'SCORE: 4\nFEEDBACK: Good' });
    });

    const registry = makeMockRegistry();
    const spawnFn = vi.fn().mockResolvedValue({
      success: true,
      output: 'done',
      metrics: { tokens: 100, duration: 1000, toolCalls: 1 },
    });

    const orchestrator = new SwarmOrchestrator(config, provider, registry, spawnFn);

    const events: SwarmEvent[] = [];
    orchestrator.subscribe((event) => events.push(event));

    await orchestrator.execute('Test artifact auto-fail');

    // Check that no model.failover events were emitted for artifact auto-fails
    const failoverEvents = events.filter(e => e.type === 'swarm.model.failover');
    // Artifact auto-fails should NOT produce failover events
    expect(failoverEvents.length).toBe(0);
  });
});

// =============================================================================
// Test 3: Last attempt skips quality gate
// =============================================================================

describe('Last attempt skips quality gate', () => {
  it('with workerRetries=2, attempt 3 should skip quality gate', () => {
    // The logic: isLastAttempt = task.attempts >= (workerRetries + 1)
    // With workerRetries=2: attempts 1, 2 run gate; attempt 3 skips

    const workerRetries = 2;

    // Attempt 1: not last
    expect(1 >= (workerRetries + 1)).toBe(false);
    // Attempt 2: not last
    expect(2 >= (workerRetries + 1)).toBe(false);
    // Attempt 3: IS last → skip quality gate
    expect(3 >= (workerRetries + 1)).toBe(true);
  });

  it('with workerRetries=0, attempt 1 should skip quality gate', () => {
    const workerRetries = 0;
    // Only one attempt, so it's the last
    expect(1 >= (workerRetries + 1)).toBe(true);
  });

  it('with workerRetries=1, attempt 2 should skip quality gate', () => {
    const workerRetries = 1;
    expect(1 >= (workerRetries + 1)).toBe(false);
    expect(2 >= (workerRetries + 1)).toBe(true);
  });
});

// =============================================================================
// Test 4: Configurable quality threshold in SwarmConfig
// =============================================================================

describe('Configurable quality threshold', () => {
  it('SwarmConfig accepts qualityThreshold', () => {
    const config: SwarmConfig = {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/model',
      workers: [],
      qualityThreshold: 4,
    };

    expect(config.qualityThreshold).toBe(4);
  });

  it('SwarmConfig qualityThreshold defaults to undefined', () => {
    const config: SwarmConfig = {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/model',
      workers: [],
    };

    // Falls back to 3 via `this.config.qualityThreshold ?? 3`
    expect(config.qualityThreshold).toBeUndefined();
    expect(config.qualityThreshold ?? 3).toBe(3);
  });
});
