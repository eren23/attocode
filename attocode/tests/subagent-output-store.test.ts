/**
 * Subagent Output Store Tests
 */

import { describe, it, expect, beforeEach } from 'vitest';
import {
  SubagentOutputStore,
  createSubagentOutputStore,
  type SubagentOutput,
} from '../src/integrations/subagent-output-store.js';

function makeOutput(overrides?: Partial<SubagentOutput>): SubagentOutput {
  return {
    id: `test-${Date.now()}-${Math.random().toString(36).slice(2, 4)}`,
    agentId: 'agent-1',
    agentName: 'researcher',
    task: 'Analyze the codebase',
    fullOutput: 'The codebase uses TypeScript with a modular architecture.',
    filesModified: [],
    filesCreated: [],
    timestamp: new Date(),
    tokensUsed: 500,
    durationMs: 3000,
    ...overrides,
  };
}

describe('SubagentOutputStore (memory-only)', () => {
  let store: SubagentOutputStore;

  beforeEach(() => {
    store = new SubagentOutputStore({ persistToFile: false, maxOutputs: 10 });
  });

  describe('save and load', () => {
    it('should save and load an output by ID', () => {
      const output = makeOutput({ id: 'out-1' });
      const id = store.save(output);
      expect(id).toBe('out-1');

      const loaded = store.load('out-1');
      expect(loaded).not.toBeNull();
      expect(loaded!.agentName).toBe('researcher');
      expect(loaded!.fullOutput).toContain('TypeScript');
    });

    it('should return null for unknown ID', () => {
      expect(store.load('nonexistent')).toBeNull();
    });

    it('should generate an ID if none provided', () => {
      const output = makeOutput({ id: '' });
      const id = store.save(output);
      expect(id).toBeTruthy();
      expect(id).toContain('output-');
    });
  });

  describe('list', () => {
    it('should list all outputs', () => {
      store.save(makeOutput({ id: 'a', agentName: 'researcher' }));
      store.save(makeOutput({ id: 'b', agentName: 'coder' }));
      const list = store.list();
      expect(list).toHaveLength(2);
    });

    it('should filter by agent name', () => {
      store.save(makeOutput({ id: 'a', agentName: 'researcher' }));
      store.save(makeOutput({ id: 'b', agentName: 'coder' }));
      const list = store.list({ agentName: 'coder' });
      expect(list).toHaveLength(1);
      expect(list[0].agentName).toBe('coder');
    });

    it('should respect limit', () => {
      for (let i = 0; i < 5; i++) {
        store.save(makeOutput({ id: `o-${i}` }));
      }
      const list = store.list({ limit: 2 });
      expect(list).toHaveLength(2);
    });
  });

  describe('getSummary', () => {
    it('should return a summary string', () => {
      store.save(makeOutput({ id: 'sum-1', task: 'Analyze auth flow' }));
      const summary = store.getSummary('sum-1');
      expect(summary).toContain('researcher');
      expect(summary).toContain('Analyze auth flow');
      expect(summary).toContain('Tokens');
    });

    it('should handle structured report in summary', () => {
      store.save(makeOutput({
        id: 'sum-2',
        structured: {
          findings: ['Found SQL injection vulnerability'],
          actionsTaken: ['Fixed query parameterization'],
          remainingWork: ['Review other endpoints'],
          failures: [],
          exitReason: 'completed',
        },
      }));
      const summary = store.getSummary('sum-2');
      expect(summary).toContain('Findings: 1');
      expect(summary).toContain('Fixed query');
    });

    it('should return not-found message for missing ID', () => {
      const summary = store.getSummary('nonexistent');
      expect(summary).toContain('not found');
    });
  });

  describe('getReference', () => {
    it('should return memory reference when not persisting', () => {
      const ref = store.getReference('test-id');
      expect(ref).toContain('memory:test-id');
    });
  });

  describe('cleanup', () => {
    it('should auto-cleanup when saving past maxOutputs', () => {
      for (let i = 0; i < 15; i++) {
        store.save(makeOutput({
          id: `c-${i}`,
          timestamp: new Date(Date.now() - (15 - i) * 1000),
        }));
      }
      // Auto-cleanup happens during save(), so the store should already be bounded
      const remaining = store.list();
      expect(remaining.length).toBeLessThanOrEqual(10);
    });
  });
});

describe('createSubagentOutputStore', () => {
  it('should create a store with defaults', () => {
    const store = createSubagentOutputStore({ persistToFile: false });
    expect(store).toBeInstanceOf(SubagentOutputStore);
  });
});
