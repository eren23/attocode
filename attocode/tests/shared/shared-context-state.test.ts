/**
 * Tests for SharedContextState
 *
 * Verifies cross-worker failure learning, reference pooling,
 * and static prefix sharing.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { SharedContextState, createSharedContextState } from '../../src/shared/shared-context-state.js';

describe('SharedContextState', () => {
  let shared: SharedContextState;

  beforeEach(() => {
    shared = createSharedContextState({
      maxFailures: 10,
      maxReferences: 5,
      staticPrefix: 'Test prefix',
    });
  });

  describe('factory', () => {
    it('creates instance with defaults', () => {
      const instance = createSharedContextState();
      expect(instance).toBeInstanceOf(SharedContextState);
      expect(instance.getStats().failures).toBe(0);
      expect(instance.getStats().references).toBe(0);
    });
  });

  describe('failure tracking', () => {
    it('records failures from different workers', () => {
      shared.recordFailure('worker-1', {
        action: 'read_file',
        error: 'File not found',
      });
      shared.recordFailure('worker-2', {
        action: 'write_file',
        error: 'Permission denied',
      });

      expect(shared.getStats().failures).toBe(2);
    });

    it('prefixes action with workerId', () => {
      shared.recordFailure('worker-1', {
        action: 'read_file',
        error: 'File not found',
      });

      const context = shared.getFailureContext(10);
      expect(context).toContain('[worker-1] read_file');
    });

    it('generates insights across workers', () => {
      // Record multiple not_found errors to trigger insight
      shared.recordFailure('worker-1', { action: 'read_file', error: 'not found' });
      shared.recordFailure('worker-2', { action: 'read_file', error: 'not found' });

      const insights = shared.getFailureInsights();
      expect(insights.length).toBeGreaterThan(0);
    });

    it('resolves failures', () => {
      const failure = shared.recordFailure('worker-1', {
        action: 'test_action',
        error: 'test error',
      });

      expect(shared.resolveFailure(failure.id)).toBe(true);
      expect(shared.resolveFailure('nonexistent')).toBe(false);
    });

    it('provides shared failure tracker', () => {
      const tracker = shared.getFailureTracker();
      expect(tracker).toBeDefined();

      // Recording directly on the shared tracker should be visible
      tracker.recordFailure({ action: 'direct', error: 'test' });
      expect(shared.getStats().failures).toBe(1);
    });

    it('enforces maxFailures limit', () => {
      const small = createSharedContextState({ maxFailures: 3 });

      for (let i = 0; i < 5; i++) {
        small.recordFailure('w', { action: `action-${i}`, error: 'err' });
      }

      // Should have at most 3 (eviction happens)
      expect(small.getStats().failures).toBeLessThanOrEqual(3);
    });

    it('hasRecentFailure checks across all workers', () => {
      shared.recordFailure('worker-1', {
        action: 'bash',
        error: 'command failed',
      });

      // The action is stored with prefix [worker-1]
      expect(shared.hasRecentFailure('[worker-1] bash')).toBe(true);
      expect(shared.hasRecentFailure('nonexistent')).toBe(false);
    });
  });

  describe('reference pool', () => {
    it('adds and searches references', () => {
      shared.addReferences([
        { id: 'ref-1', type: 'file', value: '/src/agent.ts', timestamp: new Date().toISOString() },
        { id: 'ref-2', type: 'url', value: 'https://example.com', timestamp: new Date().toISOString() },
      ]);

      expect(shared.getStats().references).toBe(2);

      const results = shared.searchReferences('agent');
      expect(results).toHaveLength(1);
      expect(results[0].value).toBe('/src/agent.ts');
    });

    it('deduplicates by type:value', () => {
      const ref = { id: 'ref-1', type: 'file' as const, value: '/src/agent.ts', timestamp: new Date().toISOString() };
      shared.addReferences([ref]);
      shared.addReferences([{ ...ref, id: 'ref-2' }]); // Same type:value, different id

      expect(shared.getStats().references).toBe(1);
    });

    it('enforces maxReferences limit', () => {
      // maxReferences is 5
      const refs = Array.from({ length: 8 }, (_, i) => ({
        id: `ref-${i}`,
        type: 'file' as const,
        value: `/src/file-${i}.ts`,
        timestamp: new Date().toISOString(),
      }));

      shared.addReferences(refs);
      expect(shared.getStats().references).toBeLessThanOrEqual(5);
    });

    it('getAllReferences returns all stored references', () => {
      shared.addReferences([
        { id: 'ref-1', type: 'file', value: '/a.ts', timestamp: new Date().toISOString() },
        { id: 'ref-2', type: 'url', value: 'https://b.com', timestamp: new Date().toISOString() },
      ]);

      const all = shared.getAllReferences();
      expect(all).toHaveLength(2);
    });
  });

  describe('static prefix', () => {
    it('returns the configured static prefix', () => {
      expect(shared.getStaticPrefix()).toBe('Test prefix');
    });

    it('defaults to empty string', () => {
      const instance = createSharedContextState();
      expect(instance.getStaticPrefix()).toBe('');
    });
  });

  describe('clear', () => {
    it('clears all state', () => {
      shared.recordFailure('w1', { action: 'a', error: 'e' });
      shared.addReferences([
        { id: 'r', type: 'file', value: '/f', timestamp: new Date().toISOString() },
      ]);

      shared.clear();

      expect(shared.getStats().failures).toBe(0);
      expect(shared.getStats().references).toBe(0);
    });
  });

  describe('multi-worker integration', () => {
    it('worker A failure is visible to worker B via shared tracker', () => {
      // Simulate: worker A records a failure
      shared.recordFailure('worker-A', {
        action: 'bash',
        error: 'npm test failed',
      });

      // Simulate: worker B checks for failures
      const context = shared.getFailureContext();
      expect(context).toContain('[worker-A] bash');
      expect(context).toContain('npm test failed');
    });

    it('worker A compaction references available to worker B search', () => {
      // Simulate: worker A compacts and pushes refs
      shared.addReferences([
        { id: 'r1', type: 'function', value: 'handleAuth', timestamp: new Date().toISOString(), context: 'definition' },
      ]);

      // Simulate: worker B searches
      const results = shared.searchReferences('Auth');
      expect(results).toHaveLength(1);
      expect(results[0].value).toBe('handleAuth');
    });
  });
});
