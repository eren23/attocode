/**
 * Tests for SharedEconomicsState
 *
 * Verifies cross-worker doom loop aggregation.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { SharedEconomicsState, createSharedEconomicsState } from '../../src/shared/shared-economics-state.js';

describe('SharedEconomicsState', () => {
  let shared: SharedEconomicsState;

  beforeEach(() => {
    shared = createSharedEconomicsState({ globalDoomLoopThreshold: 5 });
  });

  describe('factory', () => {
    it('creates instance with defaults', () => {
      const instance = createSharedEconomicsState();
      expect(instance).toBeInstanceOf(SharedEconomicsState);
      expect(instance.getStats().fingerprints).toBe(0);
    });
  });

  describe('recordToolCall', () => {
    it('records calls from different workers', () => {
      shared.recordToolCall('worker-1', 'read_file:/src/a.ts');
      shared.recordToolCall('worker-2', 'read_file:/src/a.ts');

      const info = shared.getGlobalLoopInfo('read_file:/src/a.ts');
      expect(info).not.toBeNull();
      expect(info!.count).toBe(2);
      expect(info!.workerCount).toBe(2);
    });

    it('tracks same worker multiple calls', () => {
      shared.recordToolCall('worker-1', 'bash:npm test');
      shared.recordToolCall('worker-1', 'bash:npm test');
      shared.recordToolCall('worker-1', 'bash:npm test');

      const info = shared.getGlobalLoopInfo('bash:npm test');
      expect(info!.count).toBe(3);
      expect(info!.workerCount).toBe(1);
    });
  });

  describe('isGlobalDoomLoop', () => {
    it('returns false below threshold', () => {
      for (let i = 0; i < 4; i++) {
        shared.recordToolCall(`worker-${i}`, 'read_file:/same.ts');
      }
      expect(shared.isGlobalDoomLoop('read_file:/same.ts')).toBe(false);
    });

    it('returns true at threshold', () => {
      for (let i = 0; i < 5; i++) {
        shared.recordToolCall(`worker-${i}`, 'read_file:/same.ts');
      }
      expect(shared.isGlobalDoomLoop('read_file:/same.ts')).toBe(true);
    });

    it('returns true above threshold', () => {
      for (let i = 0; i < 8; i++) {
        shared.recordToolCall(`worker-${i % 3}`, 'bash:cat /etc/hosts');
      }
      expect(shared.isGlobalDoomLoop('bash:cat /etc/hosts')).toBe(true);
    });

    it('returns false for unknown fingerprint', () => {
      expect(shared.isGlobalDoomLoop('nonexistent')).toBe(false);
    });
  });

  describe('getGlobalLoopInfo', () => {
    it('returns null for unknown fingerprint', () => {
      expect(shared.getGlobalLoopInfo('nonexistent')).toBeNull();
    });

    it('returns correct count and worker count', () => {
      shared.recordToolCall('w1', 'fp1');
      shared.recordToolCall('w2', 'fp1');
      shared.recordToolCall('w1', 'fp1'); // same worker again

      const info = shared.getGlobalLoopInfo('fp1');
      expect(info!.count).toBe(3);
      expect(info!.workerCount).toBe(2);
    });
  });

  describe('getStats', () => {
    it('returns correct fingerprint count', () => {
      shared.recordToolCall('w1', 'fp1');
      shared.recordToolCall('w2', 'fp2');
      shared.recordToolCall('w3', 'fp1');

      expect(shared.getStats().fingerprints).toBe(2);
    });

    it('lists global doom loops', () => {
      // fp1: 5 calls (at threshold)
      for (let i = 0; i < 5; i++) {
        shared.recordToolCall(`w-${i}`, 'fp1');
      }
      // fp2: 2 calls (below threshold)
      shared.recordToolCall('w-a', 'fp2');
      shared.recordToolCall('w-b', 'fp2');

      const stats = shared.getStats();
      expect(stats.globalLoops).toContain('fp1');
      expect(stats.globalLoops).not.toContain('fp2');
    });
  });

  describe('clear', () => {
    it('clears all state', () => {
      shared.recordToolCall('w1', 'fp1');
      shared.recordToolCall('w2', 'fp2');

      shared.clear();

      expect(shared.getStats().fingerprints).toBe(0);
      expect(shared.getStats().globalLoops).toHaveLength(0);
    });
  });

  describe('default threshold', () => {
    it('defaults to 10', () => {
      const defaultInstance = createSharedEconomicsState();

      // 9 calls should not trigger
      for (let i = 0; i < 9; i++) {
        defaultInstance.recordToolCall(`w-${i}`, 'fp');
      }
      expect(defaultInstance.isGlobalDoomLoop('fp')).toBe(false);

      // 10th call triggers
      defaultInstance.recordToolCall('w-9', 'fp');
      expect(defaultInstance.isGlobalDoomLoop('fp')).toBe(true);
    });
  });

  describe('multi-worker doom loop scenario', () => {
    it('detects swarm-wide stuck pattern across 3 workers', () => {
      const swarmShared = createSharedEconomicsState({ globalDoomLoopThreshold: 6 });

      // 3 workers each try reading the same file twice
      for (const worker of ['w1', 'w2', 'w3']) {
        swarmShared.recordToolCall(worker, 'read_file:{"path":"/config.json"}');
        swarmShared.recordToolCall(worker, 'read_file:{"path":"/config.json"}');
      }

      // Total: 6 calls across 3 workers → triggers global doom loop
      expect(swarmShared.isGlobalDoomLoop('read_file:{"path":"/config.json"}')).toBe(true);
      const info = swarmShared.getGlobalLoopInfo('read_file:{"path":"/config.json"}');
      expect(info!.workerCount).toBe(3);
    });
  });
});
