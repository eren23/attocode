/**
 * Tests for global doom loop detection integration.
 *
 * Verifies that ExecutionEconomicsManager consumes the global doom loop signal
 * from SharedEconomicsState in checkBudget().
 */

import { describe, it, expect } from 'vitest';
import { ExecutionEconomicsManager } from '../../src/integrations/budget/economics.js';
import { SharedEconomicsState } from '../../src/shared/shared-economics-state.js';

describe('Global doom loop detection in checkBudget()', () => {
  it('returns GLOBAL DOOM LOOP prompt when shared economics threshold is exceeded', () => {
    const shared = new SharedEconomicsState({ globalDoomLoopThreshold: 5 });
    const manager = new ExecutionEconomicsManager(
      { targetIterations: 50, maxIterations: 100 },
      shared,
      'worker-1',
    );

    // Record enough calls across workers to trigger global doom loop
    shared.recordToolCall('worker-2', 'read_file:{"path":"/config.json"}');
    shared.recordToolCall('worker-3', 'read_file:{"path":"/config.json"}');
    shared.recordToolCall('worker-4', 'read_file:{"path":"/config.json"}');
    shared.recordToolCall('worker-5', 'read_file:{"path":"/config.json"}');

    // This worker's own call pushes it to threshold (5 total)
    manager.recordToolCall('read_file', { path: '/config.json' });

    const result = manager.checkBudget();
    expect(result.canContinue).toBe(true);
    expect(result.isSoftLimit).toBe(true);
    expect(result.injectedPrompt).toContain('GLOBAL DOOM LOOP');
    expect(result.injectedPrompt).toContain('read_file');
    expect(result.reason).toContain('Global doom loop');
  });

  it('does not trigger global doom loop below threshold', () => {
    const shared = new SharedEconomicsState({ globalDoomLoopThreshold: 5 });
    const manager = new ExecutionEconomicsManager(
      { targetIterations: 50, maxIterations: 100 },
      shared,
      'worker-1',
    );

    // Only 3 total calls (below threshold of 5)
    shared.recordToolCall('worker-2', 'read_file:{"path":"/config.json"}');
    shared.recordToolCall('worker-3', 'read_file:{"path":"/config.json"}');
    manager.recordToolCall('read_file', { path: '/config.json' });

    const result = manager.checkBudget();
    // Should not contain global doom loop prompt
    expect(result.injectedPrompt ?? '').not.toContain('GLOBAL DOOM LOOP');
  });

  it('per-agent doom loop takes priority over global doom loop', () => {
    const shared = new SharedEconomicsState({ globalDoomLoopThreshold: 3 });
    const manager = new ExecutionEconomicsManager(
      { targetIterations: 50, maxIterations: 100 },
      shared,
      'worker-1',
    );

    // Trigger both per-agent (3 consecutive identical calls) and global doom loop
    shared.recordToolCall('worker-2', 'bash:{"command":"npm test"}');
    shared.recordToolCall('worker-3', 'bash:{"command":"npm test"}');

    // 3 identical calls from this worker triggers per-agent doom loop
    manager.recordToolCall('bash', { command: 'npm test' });
    manager.recordToolCall('bash', { command: 'npm test' });
    manager.recordToolCall('bash', { command: 'npm test' });

    const result = manager.checkBudget();
    // Per-agent doom loop fires first (checked before global)
    expect(result.injectedPrompt).toBeDefined();
    expect(result.injectedPrompt).toContain("You've called");
    expect(result.reason).toContain('Doom loop detected');
  });

  it('does not check global doom loop without shared economics', () => {
    const manager = new ExecutionEconomicsManager(
      { targetIterations: 50, maxIterations: 100 },
    );

    manager.recordToolCall('read_file', { path: '/config.json' });

    const result = manager.checkBudget();
    expect(result.injectedPrompt ?? '').not.toContain('GLOBAL DOOM LOOP');
  });
});
