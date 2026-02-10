/**
 * Injection Budget Manager Tests
 */

import { describe, it, expect } from 'vitest';
import {
  InjectionBudgetManager,
  createInjectionBudgetManager,
  type InjectionSlot,
} from '../src/integrations/injection-budget.js';

function makeSlot(name: string, priority: number, content: string, maxTokens = 500): InjectionSlot {
  return { name, priority, maxTokens, content };
}

describe('InjectionBudgetManager', () => {
  describe('allocate', () => {
    it('should accept all proposals when under budget', () => {
      const mgr = new InjectionBudgetManager({ maxTotalTokens: 5000 });
      const proposals = [
        makeSlot('budget_warning', 0, 'Budget is low'),
        makeSlot('recitation', 3, 'Your goal is X'),
      ];
      expect(mgr.allocate(proposals)).toHaveLength(2);
    });

    it('should drop low-priority proposals when over budget', () => {
      const mgr = new InjectionBudgetManager({ maxTotalTokens: 100 });
      const proposals = [
        makeSlot('budget_warning', 0, 'B'.repeat(300)),
        makeSlot('recitation', 3, 'R'.repeat(200)),
      ];
      const accepted = mgr.allocate(proposals);
      expect(accepted.length).toBeLessThan(proposals.length);
      expect(accepted[0].name).toBe('budget_warning');
    });

    it('should sort by priority (lower number first)', () => {
      const mgr = new InjectionBudgetManager({ maxTotalTokens: 5000 });
      const proposals = [
        makeSlot('recitation', 3, 'low'),
        makeSlot('budget_warning', 0, 'critical'),
        makeSlot('doom_loop', 1, 'high'),
      ];
      const accepted = mgr.allocate(proposals);
      expect(accepted[0].name).toBe('budget_warning');
      expect(accepted[1].name).toBe('doom_loop');
      expect(accepted[2].name).toBe('recitation');
    });

    it('should use config priorities over slot-provided priorities', () => {
      const mgr = new InjectionBudgetManager({
        slotPriorities: { custom_slot: 0 },
      });
      const proposals = [
        makeSlot('recitation', 3, 'recitation'),
        makeSlot('custom_slot', 5, 'custom'),
      ];
      const accepted = mgr.allocate(proposals);
      expect(accepted[0].name).toBe('custom_slot');
    });

    it('should return empty for empty input', () => {
      expect(new InjectionBudgetManager().allocate([])).toHaveLength(0);
    });

    it('should truncate partially-fitting proposals', () => {
      // Budget 500. First uses ~150 tokens (600 chars/4). Remaining ~350.
      // Second uses ~100 tokens (400 chars/4) but we set maxTokens low so it partially fits.
      const mgr = new InjectionBudgetManager({ maxTotalTokens: 500 });
      const proposals = [
        makeSlot('first', 0, 'A'.repeat(1200), 500), // ~300 tokens
        makeSlot('second', 1, 'B'.repeat(1200), 500), // ~300 tokens, won't fully fit
      ];
      const accepted = mgr.allocate(proposals);
      expect(accepted.length).toBe(2);
      const second = accepted.find(s => s.name === 'second');
      expect(second).toBeDefined();
      expect(second!.content).toContain('truncated');
    });
  });

  describe('getLastStats', () => {
    it('should return null before any allocation', () => {
      expect(new InjectionBudgetManager().getLastStats()).toBeNull();
    });

    it('should return stats after allocation', () => {
      const mgr = new InjectionBudgetManager({ maxTotalTokens: 5000 });
      mgr.allocate([makeSlot('test', 0, 'hello')]);
      const stats = mgr.getLastStats()!;
      expect(stats.proposedTokens).toBeGreaterThan(0);
      expect(stats.acceptedTokens).toBeGreaterThan(0);
    });

    it('should track dropped names', () => {
      const mgr = new InjectionBudgetManager({ maxTotalTokens: 10 });
      mgr.allocate([
        makeSlot('first', 0, 'A'.repeat(40)),
        makeSlot('dropped', 1, 'B'.repeat(400)),
      ]);
      expect(mgr.getLastStats()!.droppedNames).toContain('dropped');
    });
  });

  describe('getPriority', () => {
    it('should return configured priorities', () => {
      const mgr = new InjectionBudgetManager();
      expect(mgr.getPriority('budget_warning')).toBe(0);
      expect(mgr.getPriority('doom_loop')).toBe(1);
      expect(mgr.getPriority('recitation')).toBe(3);
    });

    it('should return 5 for unknown slots', () => {
      expect(new InjectionBudgetManager().getPriority('unknown')).toBe(5);
    });
  });

  describe('setMaxTokens', () => {
    it('should update the budget', () => {
      const mgr = new InjectionBudgetManager({ maxTotalTokens: 100 });
      mgr.setMaxTokens(5000);
      const accepted = mgr.allocate([
        makeSlot('a', 0, 'A'.repeat(1000)),
        makeSlot('b', 1, 'B'.repeat(1000)),
      ]);
      expect(accepted).toHaveLength(2);
    });
  });
});

describe('createInjectionBudgetManager', () => {
  it('should create with defaults', () => {
    expect(createInjectionBudgetManager()).toBeInstanceOf(InjectionBudgetManager);
  });
});
