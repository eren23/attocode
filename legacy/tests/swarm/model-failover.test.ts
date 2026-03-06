/**
 * Tests for ModelHealthTracker and model failover
 */
import { describe, it, expect } from 'vitest';
import { ModelHealthTracker, selectAlternativeModel } from '../../src/integrations/swarm/model-selector.js';
import type { SwarmWorkerSpec } from '../../src/integrations/swarm/types.js';

describe('ModelHealthTracker', () => {
  it('should record successes and track latency', () => {
    const tracker = new ModelHealthTracker();
    tracker.recordSuccess('model/a', 100);
    tracker.recordSuccess('model/a', 200);

    const records = tracker.getAllRecords();
    expect(records.length).toBe(1);
    expect(records[0].successes).toBe(2);
    expect(records[0].healthy).toBe(true);
    expect(records[0].averageLatencyMs).toBeGreaterThan(0);
  });

  it('should mark unhealthy after repeated rate limits', () => {
    const tracker = new ModelHealthTracker();
    tracker.recordFailure('model/a', '429');
    expect(tracker.isHealthy('model/a')).toBe(true); // 1 rate limit, need 2

    tracker.recordFailure('model/a', '429');
    expect(tracker.isHealthy('model/a')).toBe(false); // 2 rate limits in 60s
  });

  it('should mark unhealthy on high failure rate', () => {
    const tracker = new ModelHealthTracker();
    tracker.recordSuccess('model/a', 100);
    tracker.recordFailure('model/a', 'error');
    tracker.recordFailure('model/a', 'error');

    // 2 failures out of 3 total = 66% failure rate > 50%
    expect(tracker.isHealthy('model/a')).toBe(false);
  });

  it('should treat unknown models as healthy', () => {
    const tracker = new ModelHealthTracker();
    expect(tracker.isHealthy('never/seen')).toBe(true);
  });

  it('should filter healthy models from list', () => {
    const tracker = new ModelHealthTracker();
    tracker.recordFailure('model/a', '429');
    tracker.recordFailure('model/a', '429');
    tracker.recordSuccess('model/b', 100);

    const healthy = tracker.getHealthy(['model/a', 'model/b', 'model/c']);
    expect(healthy).toEqual(['model/b', 'model/c']); // a is unhealthy, c is unknown (healthy)
  });

  it('should restore from saved records', () => {
    const tracker = new ModelHealthTracker();
    tracker.recordSuccess('model/a', 100);
    tracker.recordFailure('model/b', '429');
    tracker.recordFailure('model/b', '429');

    const saved = tracker.getAllRecords();

    const restored = new ModelHealthTracker();
    restored.restore(saved);

    expect(restored.isHealthy('model/a')).toBe(true);
    expect(restored.isHealthy('model/b')).toBe(false);
  });
});

describe('selectAlternativeModel', () => {
  const workers: SwarmWorkerSpec[] = [
    { name: 'coder1', model: 'model/a', capabilities: ['code'] },
    { name: 'coder2', model: 'model/b', capabilities: ['code'] },
    { name: 'researcher', model: 'model/c', capabilities: ['research'] },
  ];

  it('should select a different model with same capability', () => {
    const tracker = new ModelHealthTracker();
    const alt = selectAlternativeModel(workers, 'model/a', 'code', tracker);
    expect(alt).toBeDefined();
    expect(alt!.model).toBe('model/b');
  });

  it('should prefer healthy alternatives', () => {
    const tracker = new ModelHealthTracker();
    tracker.recordFailure('model/b', '429');
    tracker.recordFailure('model/b', '429');

    const alt = selectAlternativeModel(workers, 'model/a', 'code', tracker);
    // model/b is unhealthy, but it's the only alternative for 'code'
    // Since no healthy alternatives exist, falls back to any different model
    expect(alt).toBeDefined();
    expect(alt!.model).toBe('model/b');
  });

  it('should return undefined when no config alternatives exist (no ghost models)', () => {
    const tracker = new ModelHealthTracker();
    const alt = selectAlternativeModel(workers, 'model/c', 'research', tracker);
    // No configured worker has 'research' capability — return undefined instead of
    // injecting unconfigured ghost models from FALLBACK_WORKERS
    expect(alt).toBeUndefined();
  });

  it('should fall back to code workers when write capability has no match', () => {
    const tracker = new ModelHealthTracker();
    // No worker has 'write' capability, but coder1/coder2 have 'code'
    const alt = selectAlternativeModel(workers, 'model/c', 'write', tracker);
    expect(alt).toBeDefined();
    expect(alt!.capabilities).toContain('code');
  });

  it('should prefer healthy code workers for write fallback', () => {
    const tracker = new ModelHealthTracker();
    tracker.recordFailure('model/a', '429');
    tracker.recordFailure('model/a', '429'); // model/a unhealthy

    const alt = selectAlternativeModel(workers, 'model/c', 'write', tracker);
    expect(alt).toBeDefined();
    expect(alt!.model).toBe('model/b'); // healthy code worker
  });

  it('should select write-capable worker over code fallback when available', () => {
    const workersWithWrite: SwarmWorkerSpec[] = [
      ...workers,
      { name: 'synthesizer', model: 'model/d', capabilities: ['write'] },
    ];
    const tracker = new ModelHealthTracker();
    const alt = selectAlternativeModel(workersWithWrite, 'model/x', 'write', tracker);
    expect(alt).toBeDefined();
    expect(alt!.name).toBe('synthesizer');
  });
});
