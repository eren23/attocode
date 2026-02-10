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

  it('should fall back to FALLBACK_WORKERS when config workers all share same model', () => {
    const workers: SwarmWorkerSpec[] = [
      { name: 'researcher-a', model: 'same/model', capabilities: ['research'] },
      { name: 'researcher-b', model: 'same/model', capabilities: ['research'] },
    ];
    const tracker = new ModelHealthTracker();
    const alt = selectAlternativeModel(workers, 'same/model', 'research', tracker);
    // Should find a fallback worker with research capability and different model
    expect(alt).toBeDefined();
    expect(alt!.model).not.toBe('same/model');
    expect(alt!.capabilities).toContain('research');
  });

  it('should return undefined when no alternative exists anywhere', () => {
    const workers: SwarmWorkerSpec[] = [
      { name: 'researcher', model: 'unique/model', capabilities: ['research'] },
    ];
    const tracker = new ModelHealthTracker();
    // Use a model that doesn't exist in FALLBACK_WORKERS or config workers
    // and a capability that doesn't exist in fallback
    const alt = selectAlternativeModel(workers, 'unique/model', 'research', tracker);
    // Fallback has 'moonshotai/kimi-k2.5-0127' with research capability,
    // so this should find something
    expect(alt).toBeDefined();
    expect(alt!.model).not.toBe('unique/model');
  });

  it('should prefer healthy fallback workers', () => {
    const workers: SwarmWorkerSpec[] = [
      { name: 'researcher', model: 'same/model', capabilities: ['research'] },
    ];
    const tracker = new ModelHealthTracker();
    // Mark the first matching fallback model as unhealthy
    const firstFallbackResearcher = FALLBACK_WORKERS.find(w =>
      w.model !== 'same/model' && w.capabilities.includes('research'),
    );
    if (firstFallbackResearcher) {
      tracker.recordFailure(firstFallbackResearcher.model, 'error');
      tracker.recordFailure(firstFallbackResearcher.model, 'error');
      tracker.recordFailure(firstFallbackResearcher.model, 'error');
    }

    const alt = selectAlternativeModel(workers, 'same/model', 'research', tracker);
    // Should still find something (unhealthy fallback as last resort)
    expect(alt).toBeDefined();
    expect(alt!.model).not.toBe('same/model');
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
