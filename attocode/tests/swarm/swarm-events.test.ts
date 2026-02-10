/**
 * Swarm Events Tests
 *
 * Tests for isSwarmEvent type guard and formatSwarmEvent formatter.
 */

import { describe, it, expect } from 'vitest';
import { isSwarmEvent, formatSwarmEvent, type SwarmEvent } from '../../src/integrations/swarm/swarm-events.js';

// =============================================================================
// isSwarmEvent
// =============================================================================

describe('isSwarmEvent', () => {
  it('returns true for all swarm.* event types', () => {
    const swarmTypes = [
      'swarm.start',
      'swarm.tasks.loaded',
      'swarm.wave.start',
      'swarm.wave.complete',
      'swarm.task.dispatched',
      'swarm.task.completed',
      'swarm.task.failed',
      'swarm.task.skipped',
      'swarm.quality.rejected',
      'swarm.budget.update',
      'swarm.status',
      'swarm.complete',
      'swarm.error',
      'swarm.plan.complete',
      'swarm.review.start',
      'swarm.review.complete',
      'swarm.verify.start',
      'swarm.verify.step',
      'swarm.verify.complete',
      'swarm.worker.stuck',
      'swarm.model.failover',
      'swarm.model.health',
      'swarm.state.checkpoint',
      'swarm.state.resume',
      'swarm.orchestrator.decision',
      'swarm.fixup.spawned',
      'swarm.circuit.open',
      'swarm.circuit.closed',
      'swarm.role.action',
    ];

    for (const type of swarmTypes) {
      expect(isSwarmEvent({ type })).toBe(true);
    }
  });

  it('returns false for non-swarm events', () => {
    expect(isSwarmEvent({ type: 'budget.warning' })).toBe(false);
    expect(isSwarmEvent({ type: 'phase.transition' })).toBe(false);
    expect(isSwarmEvent({ type: 'doom_loop.detected' })).toBe(false);
    expect(isSwarmEvent({ type: 'agent.started' })).toBe(false);
    expect(isSwarmEvent({ type: '' })).toBe(false);
  });
});

// =============================================================================
// formatSwarmEvent
// =============================================================================

describe('formatSwarmEvent', () => {
  it('swarm.start', () => {
    const event: SwarmEvent = {
      type: 'swarm.start',
      taskCount: 5,
      waveCount: 3,
      config: { maxConcurrency: 4, totalBudget: 1000000, maxCost: 1.0 },
    };
    const formatted = formatSwarmEvent(event);
    expect(formatted).toContain('5 tasks');
    expect(formatted).toContain('3 waves');
    expect(formatted).toContain('max 4 concurrent');
  });

  it('swarm.wave.start', () => {
    const formatted = formatSwarmEvent({
      type: 'swarm.wave.start',
      wave: 2,
      totalWaves: 4,
      taskCount: 3,
    });
    expect(formatted).toContain('Wave 2/4');
    expect(formatted).toContain('3 tasks');
  });

  it('swarm.wave.complete', () => {
    const formatted = formatSwarmEvent({
      type: 'swarm.wave.complete',
      wave: 1,
      totalWaves: 3,
      completed: 2,
      failed: 1,
      skipped: 0,
    });
    expect(formatted).toContain('Wave 1/3');
    expect(formatted).toContain('2 done');
    expect(formatted).toContain('1 failed');
    expect(formatted).toContain('0 skipped');
  });

  it('swarm.task.completed', () => {
    const formatted = formatSwarmEvent({
      type: 'swarm.task.completed',
      taskId: 't-1',
      success: true,
      tokensUsed: 5000,
      costUsed: 0.0123,
      durationMs: 3500,
    });
    expect(formatted).toContain('t-1');
    expect(formatted).toContain('completed');
    expect(formatted).toContain('5000 tokens');
    expect(formatted).toContain('3.5s');
  });

  it('swarm.task.failed with retry', () => {
    const formatted = formatSwarmEvent({
      type: 'swarm.task.failed',
      taskId: 't-2',
      error: 'Rate limited',
      attempt: 1,
      maxAttempts: 3,
      willRetry: true,
    });
    expect(formatted).toContain('t-2');
    expect(formatted).toContain('Rate limited');
    expect(formatted).toContain('will retry');
  });

  it('swarm.budget.update with zero tokens', () => {
    const formatted = formatSwarmEvent({
      type: 'swarm.budget.update',
      tokensUsed: 0,
      tokensTotal: 1000000,
      costUsed: 0,
      costTotal: 1.0,
    });
    expect(formatted).toContain('0k');
    expect(formatted).toContain('$0.0000');
  });

  it('swarm.complete', () => {
    const formatted = formatSwarmEvent({
      type: 'swarm.complete',
      stats: {
        completedTasks: 8,
        totalTasks: 10,
        totalTokens: 50000,
        totalCost: 0.1234,
        failedTasks: 1,
        skippedTasks: 1,
        totalWaves: 3,
        totalDurationMs: 60000,
        qualityRejections: 0,
        retries: 2,
        modelUsage: new Map(),
      },
      errors: [],
    });
    expect(formatted).toContain('8/10 tasks');
    expect(formatted).toContain('50k tokens');
  });

  it('swarm.error', () => {
    const formatted = formatSwarmEvent({
      type: 'swarm.error',
      error: 'Something broke',
      phase: 'dispatch',
    });
    expect(formatted).toContain('dispatch');
    expect(formatted).toContain('Something broke');
  });

  it('swarm.model.failover', () => {
    const formatted = formatSwarmEvent({
      type: 'swarm.model.failover',
      taskId: 't-3',
      fromModel: 'model-a',
      toModel: 'model-b',
      reason: '429',
    });
    expect(formatted).toContain('model-a');
    expect(formatted).toContain('model-b');
    expect(formatted).toContain('429');
  });

  it('swarm.circuit.open', () => {
    const formatted = formatSwarmEvent({
      type: 'swarm.circuit.open',
      recentCount: 5,
      pauseMs: 30000,
    });
    expect(formatted).toContain('OPEN');
    expect(formatted).toContain('5 rate limits');
    expect(formatted).toContain('30s');
  });

  it('swarm.circuit.closed', () => {
    const formatted = formatSwarmEvent({ type: 'swarm.circuit.closed' });
    expect(formatted).toContain('CLOSED');
    expect(formatted).toContain('resumed');
  });

  it('swarm.role.action', () => {
    const formatted = formatSwarmEvent({
      type: 'swarm.role.action',
      role: 'judge',
      action: 'quality-gate',
      model: 'provider/judge-model-v1',
      taskId: 't-5',
    });
    expect(formatted).toContain('Judge');
    expect(formatted).toContain('quality-gate');
    expect(formatted).toContain('judge-model-v1');
    expect(formatted).toContain('t-5');
  });

  it('swarm.task.dispatched with empty description', () => {
    const formatted = formatSwarmEvent({
      type: 'swarm.task.dispatched',
      taskId: 't-0',
      description: '',
      model: 'test-model',
      workerName: 'coder',
    });
    expect(formatted).toContain('t-0');
    expect(formatted).toContain('coder');
  });

  it('swarm.verify.step', () => {
    const formatted = formatSwarmEvent({
      type: 'swarm.verify.step',
      stepIndex: 0,
      description: 'Run unit tests',
      passed: true,
    });
    expect(formatted).toContain('step 1');
    expect(formatted).toContain('Run unit tests');
    expect(formatted).toContain('PASS');
  });

  it('swarm.model.health', () => {
    const formatted = formatSwarmEvent({
      type: 'swarm.model.health',
      record: {
        model: 'test/model-v1',
        successes: 10,
        failures: 2,
        rateLimits: 1,
        healthy: true,
        averageLatencyMs: 1500,
      },
    });
    expect(formatted).toContain('test/model-v1');
    expect(formatted).toContain('healthy');
    expect(formatted).toContain('10ok');
    expect(formatted).toContain('2fail');
    expect(formatted).toContain('1rl');
  });
});
