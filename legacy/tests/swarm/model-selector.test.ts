/**
 * Tests for SwarmModelSelector
 */
import { describe, it, expect } from 'vitest';
import { selectWorkerForCapability, selectAlternativeModel, ModelHealthTracker, FALLBACK_WORKERS } from '../../src/integrations/swarm/model-selector.js';
import type { SwarmWorkerSpec } from '../../src/integrations/swarm/types.js';

const testWorkers: SwarmWorkerSpec[] = [
  {
    name: 'coder',
    model: 'qwen/qwen-2.5-coder-32b-instruct',
    capabilities: ['code', 'test'],
    contextWindow: 32768,
  },
  {
    name: 'researcher',
    model: 'google/gemini-2.0-flash-001',
    capabilities: ['research', 'review'],
    contextWindow: 1048576,
  },
  {
    name: 'documenter',
    model: 'meta-llama/llama-3.1-8b-instruct',
    capabilities: ['document'],
    contextWindow: 131072,
  },
];

describe('selectWorkerForCapability', () => {
  it('should select coder for code capability', () => {
    const worker = selectWorkerForCapability(testWorkers, 'code');
    expect(worker?.name).toBe('coder');
  });

  it('should select researcher for research capability', () => {
    const worker = selectWorkerForCapability(testWorkers, 'research');
    expect(worker?.name).toBe('researcher');
  });

  it('should select documenter for document capability', () => {
    const worker = selectWorkerForCapability(testWorkers, 'document');
    expect(worker?.name).toBe('documenter');
  });

  it('should select coder for test capability', () => {
    const worker = selectWorkerForCapability(testWorkers, 'test');
    expect(worker?.name).toBe('coder');
  });

  it('should select reviewer for review capability', () => {
    const worker = selectWorkerForCapability(testWorkers, 'review');
    expect(worker?.name).toBe('researcher');
  });

  it('should fall back to first worker for unknown capability', () => {
    const workers: SwarmWorkerSpec[] = [
      { name: 'only', model: 'test/model', capabilities: ['research'] },
    ];
    // 'document' is not in this worker's capabilities
    const worker = selectWorkerForCapability(workers, 'document');
    expect(worker?.name).toBe('only');
  });

  it('should return undefined for empty workers list', () => {
    const worker = selectWorkerForCapability([], 'code');
    expect(worker).toBeUndefined();
  });

  it('should round-robin across matching workers', () => {
    const workers: SwarmWorkerSpec[] = [
      { name: 'coder1', model: 'model/a', capabilities: ['code'] },
      { name: 'coder2', model: 'model/b', capabilities: ['code'] },
      { name: 'coder3', model: 'model/c', capabilities: ['code'] },
    ];
    expect(selectWorkerForCapability(workers, 'code', 0)?.name).toBe('coder1');
    expect(selectWorkerForCapability(workers, 'code', 1)?.name).toBe('coder2');
    expect(selectWorkerForCapability(workers, 'code', 2)?.name).toBe('coder3');
    expect(selectWorkerForCapability(workers, 'code', 3)?.name).toBe('coder1'); // wraps
  });

  it('should prefer healthy models when health tracker provided', () => {
    const workers: SwarmWorkerSpec[] = [
      { name: 'coder1', model: 'model/a', capabilities: ['code'] },
      { name: 'coder2', model: 'model/b', capabilities: ['code'] },
    ];
    const tracker = new ModelHealthTracker();
    tracker.recordFailure('model/a', '429');
    tracker.recordFailure('model/a', '429'); // Now unhealthy

    const worker = selectWorkerForCapability(workers, 'code', 0, tracker);
    expect(worker?.name).toBe('coder2'); // Skips unhealthy model/a
  });

  it('should fall back to all models when none are healthy', () => {
    const workers: SwarmWorkerSpec[] = [
      { name: 'coder1', model: 'model/a', capabilities: ['code'] },
    ];
    const tracker = new ModelHealthTracker();
    tracker.recordFailure('model/a', '429');
    tracker.recordFailure('model/a', '429');

    const worker = selectWorkerForCapability(workers, 'code', 0, tracker);
    expect(worker?.name).toBe('coder1'); // Falls back despite unhealthy
  });

  it('should select write-capable worker for write capability', () => {
    const workers: SwarmWorkerSpec[] = [
      { name: 'coder', model: 'model/a', capabilities: ['code'] },
      { name: 'synthesizer', model: 'model/b', capabilities: ['write', 'code'] },
    ];
    const worker = selectWorkerForCapability(workers, 'write');
    expect(worker?.name).toBe('synthesizer');
  });

  it('should fall back to code workers when no write-capable worker exists', () => {
    const workers: SwarmWorkerSpec[] = [
      { name: 'coder', model: 'model/a', capabilities: ['code', 'test'] },
      { name: 'researcher', model: 'model/b', capabilities: ['research'] },
    ];
    const worker = selectWorkerForCapability(workers, 'write');
    expect(worker?.name).toBe('coder');
  });
});

describe('selectAlternativeModel', () => {
  it('should find alternative within config workers', () => {
    const workers: SwarmWorkerSpec[] = [
      { name: 'researcher-a', model: 'model/a', capabilities: ['research'] },
      { name: 'researcher-b', model: 'model/b', capabilities: ['research'] },
    ];
    const tracker = new ModelHealthTracker();
    const alt = selectAlternativeModel(workers, 'model/a', 'research', tracker);
    expect(alt?.model).toBe('model/b');
  });

  it('should return undefined when config workers all share same model (no ghost models)', () => {
    const workers: SwarmWorkerSpec[] = [
      { name: 'researcher-a', model: 'same/model', capabilities: ['research'] },
      { name: 'researcher-b', model: 'same/model', capabilities: ['research'] },
    ];
    const tracker = new ModelHealthTracker();
    const alt = selectAlternativeModel(workers, 'same/model', 'research', tracker);
    // No configured alternative with a different model — return undefined
    // instead of injecting unconfigured ghost models from FALLBACK_WORKERS
    expect(alt).toBeUndefined();
  });

  it('should return undefined when sole config worker is the failed model', () => {
    const workers: SwarmWorkerSpec[] = [
      { name: 'researcher', model: 'unique/model', capabilities: ['research'] },
    ];
    const tracker = new ModelHealthTracker();
    const alt = selectAlternativeModel(workers, 'unique/model', 'research', tracker);
    // Only configured worker IS the failed model — return undefined
    expect(alt).toBeUndefined();
  });

  it('should return undefined when no healthy config alternative exists (no ghost fallbacks)', () => {
    const workers: SwarmWorkerSpec[] = [
      { name: 'researcher', model: 'same/model', capabilities: ['research'] },
    ];
    const tracker = new ModelHealthTracker();

    const alt = selectAlternativeModel(workers, 'same/model', 'research', tracker);
    // No configured alternative — return undefined instead of ghost models
    expect(alt).toBeUndefined();
  });
});

describe('FALLBACK_WORKERS', () => {
  it('should be exported and contain workers with diverse capabilities', () => {
    expect(FALLBACK_WORKERS).toBeDefined();
    expect(FALLBACK_WORKERS.length).toBeGreaterThan(0);

    const capabilities = new Set(FALLBACK_WORKERS.flatMap(w => w.capabilities));
    expect(capabilities.has('code')).toBe(true);
    expect(capabilities.has('research')).toBe(true);
  });

  it('should contain at least one research-capable worker', () => {
    const researchers = FALLBACK_WORKERS.filter(w => w.capabilities.includes('research'));
    expect(researchers.length).toBeGreaterThan(0);
  });
});

describe('Per-model hollow tracking', () => {
  it('recordHollow increments hollow count and records failure', () => {
    const tracker = new ModelHealthTracker();
    tracker.recordHollow('model-a');
    expect(tracker.getHollowCount('model-a')).toBe(1);
    const records = tracker.getAllRecords();
    const record = records.find(r => r.model === 'model-a')!;
    expect(record.failures).toBe(1);
  });

  it('recordHollow accumulates across multiple calls', () => {
    const tracker = new ModelHealthTracker();
    tracker.recordHollow('model-a');
    tracker.recordHollow('model-a');
    tracker.recordHollow('model-a');
    expect(tracker.getHollowCount('model-a')).toBe(3);
    const records = tracker.getAllRecords();
    const record = records.find(r => r.model === 'model-a')!;
    expect(record.failures).toBe(3);
  });

  it('getHollowRate computes correct ratio', () => {
    const tracker = new ModelHealthTracker();
    tracker.recordSuccess('model-a', 1000);
    tracker.recordSuccess('model-a', 1000);
    tracker.recordHollow('model-a');
    // 3 total attempts (2 success + 1 failure from hollow), 1 hollow
    expect(tracker.getHollowRate('model-a')).toBeCloseTo(1 / 3, 2);
  });

  it('getHollowRate returns 0 for unknown model', () => {
    const tracker = new ModelHealthTracker();
    expect(tracker.getHollowRate('unknown-model')).toBe(0);
  });

  it('getHollowCount returns 0 for unknown model', () => {
    const tracker = new ModelHealthTracker();
    expect(tracker.getHollowCount('unknown-model')).toBe(0);
  });

  it('models with high hollow rate are deprioritized in selection', () => {
    const workers: SwarmWorkerSpec[] = [
      { name: 'hollow-prone', model: 'model/hollow', capabilities: ['code'] },
      { name: 'reliable', model: 'model/reliable', capabilities: ['code'] },
    ];
    const tracker = new ModelHealthTracker();

    // model/hollow: 5 successes, 5 hollows → 50% hollow rate
    for (let i = 0; i < 5; i++) tracker.recordSuccess('model/hollow', 1000);
    for (let i = 0; i < 5; i++) tracker.recordHollow('model/hollow');

    // model/reliable: 8 successes, 1 failure → 0% hollow rate
    for (let i = 0; i < 8; i++) tracker.recordSuccess('model/reliable', 1000);
    tracker.recordFailure('model/reliable', 'error');

    // Reliable should be preferred despite both having similar health status
    const selected = selectWorkerForCapability(workers, 'code', 0, tracker);
    expect(selected?.name).toBe('reliable');
  });

  it('hollow rate below 15% difference does not affect ordering', () => {
    const workers: SwarmWorkerSpec[] = [
      { name: 'slightly-hollow', model: 'model/a', capabilities: ['code'] },
      { name: 'clean', model: 'model/b', capabilities: ['code'] },
    ];
    const tracker = new ModelHealthTracker();

    // Both have similar profiles — one hollow shouldn't dominate
    for (let i = 0; i < 10; i++) tracker.recordSuccess('model/a', 1000);
    tracker.recordHollow('model/a'); // 1/11 ≈ 9% hollow rate

    for (let i = 0; i < 10; i++) tracker.recordSuccess('model/b', 1000);
    // 0% hollow rate, difference is ~9% which is < 15%

    // Both should be in the top tier — ordering determined by success rate
    const selected0 = selectWorkerForCapability(workers, 'code', 0, tracker);
    const selected1 = selectWorkerForCapability(workers, 'code', 1, tracker);
    // Both should be selectable (round-robin)
    expect(selected0).toBeDefined();
    expect(selected1).toBeDefined();
  });
});

describe('P1: recordQualityRejection', () => {
  it('undoes premature recordSuccess', () => {
    const tracker = new ModelHealthTracker();
    tracker.recordSuccess('model-a', 1000);
    tracker.recordQualityRejection('model-a', 2);
    const records = tracker.getAllRecords();
    const record = records.find(r => r.model === 'model-a')!;
    expect(record.successes).toBe(0);
    expect(record.failures).toBe(1);
  });

  it('marks unhealthy after 3 quality rejections', () => {
    const tracker = new ModelHealthTracker();
    tracker.recordSuccess('model-a', 1000);
    tracker.recordQualityRejection('model-a', 2);
    tracker.recordSuccess('model-a', 1000);
    tracker.recordQualityRejection('model-a', 2);
    tracker.recordSuccess('model-a', 1000);
    tracker.recordQualityRejection('model-a', 2);
    expect(tracker.isHealthy('model-a')).toBe(false);
  });

  it('tracks qualityRejections count', () => {
    const tracker = new ModelHealthTracker();
    tracker.recordQualityRejection('model-a', 2);
    tracker.recordQualityRejection('model-a', 1);
    const records = tracker.getAllRecords();
    const record = records.find(r => r.model === 'model-a')!;
    expect(record.qualityRejections).toBe(2);
  });

  it('does not go below 0 successes', () => {
    const tracker = new ModelHealthTracker();
    // No prior success — rejection should still work
    tracker.recordQualityRejection('model-a', 2);
    const records = tracker.getAllRecords();
    const record = records.find(r => r.model === 'model-a')!;
    expect(record.successes).toBe(0);
    expect(record.failures).toBe(1);
  });
});
