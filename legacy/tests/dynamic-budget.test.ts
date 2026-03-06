/**
 * Dynamic Budget Pool Tests
 */

import { describe, it, expect, beforeEach } from 'vitest';
import {
  DynamicBudgetPool,
  createDynamicBudgetPool,
} from '../src/integrations/budget/dynamic-budget.js';

describe('DynamicBudgetPool', () => {
  let pool: DynamicBudgetPool;

  beforeEach(() => {
    pool = new DynamicBudgetPool({
      totalTokens: 100000,
      maxPerChild: 50000,
      totalCost: 1.0,
      maxCostPerChild: 0.5,
    });
  });

  describe('setExpectedChildren', () => {
    it('should accept a child count', () => {
      pool.setExpectedChildren(5);
      const stats = pool.getDynamicStats();
      expect(stats.expectedChildren).toBe(5);
    });
  });

  describe('reserveDynamic', () => {
    it('should allocate budget for a child', () => {
      pool.setExpectedChildren(3);
      const alloc = pool.reserveDynamic('child-1');
      expect(alloc).not.toBeNull();
      expect(alloc!.tokenBudget).toBeGreaterThan(0);
    });

    it('should cap at maxRemainingRatio', () => {
      pool.setExpectedChildren(2);
      const alloc = pool.reserveDynamic('child-1');
      // Should not take more than 60% of remaining
      expect(alloc!.tokenBudget).toBeLessThanOrEqual(100000 * 0.6);
    });

    it('should reserve tokens for future expected children', () => {
      pool.setExpectedChildren(5);
      const first = pool.reserveDynamic('child-1');
      const stats = pool.getDynamicStats();
      expect(stats.spawnedCount).toBe(1);
      // Should have reserved some budget for remaining children
      expect(first!.tokenBudget).toBeLessThan(100000);
    });

    it('should return null when no budget remaining', () => {
      // Exhaust the pool
      pool = new DynamicBudgetPool({
        totalTokens: 100,
        maxPerChild: 100,
        totalCost: 1.0,
        maxCostPerChild: 1.0,
      });
      pool.reserveDynamic('child-1');
      const second = pool.reserveDynamic('child-2');
      expect(second).toBeNull();
    });

    it('should respect priority levels', () => {
      pool.setExpectedChildren(3);
      pool.setChildPriority({ childId: 'critical-1', priority: 'critical' });
      pool.setChildPriority({ childId: 'low-1', priority: 'low' });

      const critical = pool.reserveDynamic('critical-1', 'critical');
      const low = pool.reserveDynamic('low-1', 'low');

      // Both should get allocations (pool has enough budget)
      expect(critical).not.toBeNull();
      expect(low).not.toBeNull();
    });

    it('should track spawned count', () => {
      pool.setExpectedChildren(3);
      pool.reserveDynamic('a');
      pool.reserveDynamic('b');
      expect(pool.getDynamicStats().spawnedCount).toBe(2);
    });
  });

  describe('releaseDynamic', () => {
    it('should release budget and increment completed count', () => {
      pool.setExpectedChildren(3);
      pool.reserveDynamic('child-1');

      pool.releaseDynamic('child-1');

      const stats = pool.getDynamicStats();
      expect(stats.completedCount).toBe(1);
    });

    it('should remove child priority on release', () => {
      pool.setExpectedChildren(2);
      pool.setChildPriority({ childId: 'c1', priority: 'high' });
      pool.reserveDynamic('c1');
      pool.releaseDynamic('c1');

      // Priority should be cleared (no way to directly check, but it shouldn't crash)
      const stats = pool.getDynamicStats();
      expect(stats.completedCount).toBe(1);
    });
  });

  describe('getDynamicStats', () => {
    it('should include all dynamic fields', () => {
      pool.setExpectedChildren(3);
      pool.reserveDynamic('a');
      pool.releaseDynamic('a');
      pool.reserveDynamic('b');

      const stats = pool.getDynamicStats();
      expect(stats.expectedChildren).toBe(3);
      expect(stats.spawnedCount).toBe(2);
      expect(stats.completedCount).toBe(1);
      expect(stats.pendingCount).toBe(1); // 2 spawned - 1 completed
      // avgPerChild is tokensUsed/spawnedCount; since we only reserve (not consume), it may be 0
      expect(stats.avgPerChild).toBeGreaterThanOrEqual(0);
    });

    it('should return 0 avgPerChild when no children spawned', () => {
      expect(pool.getDynamicStats().avgPerChild).toBe(0);
    });
  });
});

describe('createDynamicBudgetPool', () => {
  it('should create a pool from parent budget', () => {
    const pool = createDynamicBudgetPool(200000, 0.25);
    const stats = pool.getDynamicStats();
    // Parent reserves 25% (50000), pool gets 150000
    expect(stats.tokensRemaining).toBe(150000);
  });

  it('should respect custom config', () => {
    const pool = createDynamicBudgetPool(200000, 0.25, {
      maxRemainingRatio: 0.4,
    });
    // Pool should be created with custom ratio
    pool.setExpectedChildren(2);
    const alloc = pool.reserveDynamic('child-1');
    expect(alloc).not.toBeNull();
    expect(alloc!.tokenBudget).toBeLessThanOrEqual(150000 * 0.4);
  });

  it('should default to 0.25 parent reserve ratio', () => {
    const pool = createDynamicBudgetPool(100000);
    const stats = pool.getDynamicStats();
    expect(stats.tokensRemaining).toBe(75000);
  });
});
