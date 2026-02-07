/**
 * Tests for SwarmModelSelector
 */
import { describe, it, expect } from 'vitest';
import { selectWorkerForCapability, ModelHealthTracker } from '../../src/integrations/swarm/model-selector.js';
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
});
