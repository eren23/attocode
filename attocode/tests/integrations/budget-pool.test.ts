/**
 * Unit tests for SharedBudgetPool.
 *
 * Tests the pooled budget system that limits total tree cost
 * across parent + subagent hierarchies.
 */

import { describe, it, expect } from 'vitest';
import {
  SharedBudgetPool,
  createBudgetPool,
} from '../../src/integrations/budget/budget-pool.js';

describe('SharedBudgetPool', () => {
  describe('reserve', () => {
    it('should allocate up to maxPerChild', () => {
      const pool = new SharedBudgetPool({
        totalTokens: 200000,
        maxPerChild: 100000,
      });

      const alloc = pool.reserve('child-1');
      expect(alloc).not.toBeNull();
      expect(alloc!.tokenBudget).toBe(100000);
      expect(alloc!.tokensUsed).toBe(0);
    });

    it('should allocate remaining tokens when less than maxPerChild available', () => {
      const pool = new SharedBudgetPool({
        totalTokens: 150000,
        maxPerChild: 100000,
      });

      const alloc1 = pool.reserve('child-1');
      expect(alloc1).not.toBeNull();
      expect(alloc1!.tokenBudget).toBe(100000);

      // Second child gets only 50K (remaining after 100K reserved)
      const alloc2 = pool.reserve('child-2');
      expect(alloc2).not.toBeNull();
      expect(alloc2!.tokenBudget).toBe(50000);
    });

    it('should return null when pool is exhausted', () => {
      const pool = new SharedBudgetPool({
        totalTokens: 100000,
        maxPerChild: 100000,
      });

      const alloc1 = pool.reserve('child-1');
      expect(alloc1).not.toBeNull();

      const alloc2 = pool.reserve('child-2');
      expect(alloc2).toBeNull();
    });

    it('should use pessimistic accounting for concurrent reservations', () => {
      const pool = new SharedBudgetPool({
        totalTokens: 150000,
        maxPerChild: 100000,
      });

      // Reserve 100K for child-1
      const alloc1 = pool.reserve('child-1');
      expect(alloc1).not.toBeNull();
      expect(alloc1!.tokenBudget).toBe(100000);

      // Child-2 should only get 50K (pessimistic: 100K already reserved)
      const alloc2 = pool.reserve('child-2');
      expect(alloc2).not.toBeNull();
      expect(alloc2!.tokenBudget).toBe(50000);

      // No room left
      const alloc3 = pool.reserve('child-3');
      expect(alloc3).toBeNull();
    });

    it('should respect cost limits', () => {
      const pool = new SharedBudgetPool({
        totalTokens: 500000,
        maxPerChild: 200000,
        totalCost: 1.00,
        maxCostPerChild: 0.50,
      });

      const alloc1 = pool.reserve('child-1');
      expect(alloc1).not.toBeNull();
      expect(alloc1!.costBudget).toBe(0.50);

      const alloc2 = pool.reserve('child-2');
      expect(alloc2).not.toBeNull();
      expect(alloc2!.costBudget).toBe(0.50);

      // Cost pool exhausted
      const alloc3 = pool.reserve('child-3');
      expect(alloc3).toBeNull();
    });
  });

  describe('recordUsage', () => {
    it('should track token consumption', () => {
      const pool = new SharedBudgetPool({
        totalTokens: 200000,
        maxPerChild: 100000,
      });

      pool.reserve('child-1');
      const withinBudget = pool.recordUsage('child-1', 50000, 0.10);
      expect(withinBudget).toBe(true);

      const stats = pool.getStats();
      expect(stats.tokensUsed).toBe(50000);
    });

    it('should return false when exceeding allocation', () => {
      const pool = new SharedBudgetPool({
        totalTokens: 200000,
        maxPerChild: 100000,
      });

      pool.reserve('child-1');
      pool.recordUsage('child-1', 80000, 0.20);
      const withinBudget = pool.recordUsage('child-1', 30000, 0.10);
      expect(withinBudget).toBe(false); // 110K > 100K allocation
    });

    it('should return false for unknown child', () => {
      const pool = new SharedBudgetPool({
        totalTokens: 200000,
        maxPerChild: 100000,
      });

      const result = pool.recordUsage('unknown', 1000, 0.01);
      expect(result).toBe(false);
    });

    it('should accumulate across multiple calls', () => {
      const pool = new SharedBudgetPool({
        totalTokens: 200000,
        maxPerChild: 100000,
      });

      pool.reserve('child-1');
      pool.recordUsage('child-1', 20000, 0.05);
      pool.recordUsage('child-1', 30000, 0.08);

      const stats = pool.getStats();
      expect(stats.tokensUsed).toBe(50000);
    });
  });

  describe('release', () => {
    it('should release reservation, freeing budget for new allocations', () => {
      const pool = new SharedBudgetPool({
        totalTokens: 100000,
        maxPerChild: 100000,
      });

      pool.reserve('child-1');
      // Pool is exhausted (100K reserved)
      expect(pool.reserve('child-2')).toBeNull();

      // Record actual usage (only 30K) and release
      pool.recordUsage('child-1', 30000, 0.05);
      pool.release('child-1');

      // Now there's room: 100K total - 30K used = 70K available
      const alloc2 = pool.reserve('child-2');
      expect(alloc2).not.toBeNull();
      expect(alloc2!.tokenBudget).toBe(70000);
    });

    it('should be safe to call for non-existent allocation', () => {
      const pool = new SharedBudgetPool({
        totalTokens: 100000,
        maxPerChild: 100000,
      });

      // Should not throw
      pool.release('nonexistent');
    });

    it('should reduce active allocations count', () => {
      const pool = new SharedBudgetPool({
        totalTokens: 200000,
        maxPerChild: 100000,
      });

      pool.reserve('child-1');
      pool.reserve('child-2');
      expect(pool.getStats().activeAllocations).toBe(2);

      pool.release('child-1');
      expect(pool.getStats().activeAllocations).toBe(1);
    });
  });

  describe('getRemainingForChild', () => {
    it('should return remaining budget for active allocation', () => {
      const pool = new SharedBudgetPool({
        totalTokens: 200000,
        maxPerChild: 100000,
      });

      pool.reserve('child-1');
      pool.recordUsage('child-1', 40000, 0.10);

      expect(pool.getRemainingForChild('child-1')).toBe(60000);
    });

    it('should return 0 for unknown child', () => {
      const pool = new SharedBudgetPool({
        totalTokens: 200000,
        maxPerChild: 100000,
      });

      expect(pool.getRemainingForChild('unknown')).toBe(0);
    });

    it('should return 0 when budget fully consumed', () => {
      const pool = new SharedBudgetPool({
        totalTokens: 200000,
        maxPerChild: 100000,
      });

      pool.reserve('child-1');
      pool.recordUsage('child-1', 120000, 0.30); // Over budget

      expect(pool.getRemainingForChild('child-1')).toBe(0);
    });
  });

  describe('getStats', () => {
    it('should reflect accurate utilization with reservations', () => {
      const pool = new SharedBudgetPool({
        totalTokens: 200000,
        maxPerChild: 100000,
      });

      pool.reserve('child-1');
      const stats = pool.getStats();

      // 100K reserved out of 200K = 50% utilization
      expect(stats.utilization).toBe(0.5);
      expect(stats.tokensRemaining).toBe(100000);
      expect(stats.activeAllocations).toBe(1);
    });

    it('should show 0 utilization for empty pool', () => {
      const pool = new SharedBudgetPool({
        totalTokens: 200000,
        maxPerChild: 100000,
      });

      const stats = pool.getStats();
      expect(stats.utilization).toBe(0);
      expect(stats.tokensRemaining).toBe(200000);
    });
  });

  describe('hasCapacity', () => {
    it('should return true when pool has > 10K available', () => {
      const pool = new SharedBudgetPool({
        totalTokens: 200000,
        maxPerChild: 100000,
      });

      expect(pool.hasCapacity()).toBe(true);
    });

    it('should return false when pool is nearly exhausted', () => {
      const pool = new SharedBudgetPool({
        totalTokens: 100000,
        maxPerChild: 100000,
      });

      pool.reserve('child-1');
      expect(pool.hasCapacity()).toBe(false);
    });
  });
});

describe('setMaxPerChild / resetMaxPerChild', () => {
  it('should cap reserves at the new maxPerChild', () => {
    const pool = new SharedBudgetPool({
      totalTokens: 200000,
      maxPerChild: 100000,
    });

    pool.setMaxPerChild(50000);

    const alloc = pool.reserve('child-1');
    expect(alloc).not.toBeNull();
    expect(alloc!.tokenBudget).toBe(50000);
  });

  it('should restore original maxPerChild after reset', () => {
    const pool = new SharedBudgetPool({
      totalTokens: 200000,
      maxPerChild: 100000,
    });

    pool.setMaxPerChild(50000);
    pool.resetMaxPerChild();

    const alloc = pool.reserve('child-1');
    expect(alloc).not.toBeNull();
    expect(alloc!.tokenBudget).toBe(100000);
  });

  it('should divide pool equally among parallel children', () => {
    const pool = new SharedBudgetPool({
      totalTokens: 150000,
      maxPerChild: 100000,
    });

    // Simulate parallel spawn: 3 children each get 50K
    pool.setMaxPerChild(50000);

    const alloc1 = pool.reserve('child-1');
    const alloc2 = pool.reserve('child-2');
    const alloc3 = pool.reserve('child-3');

    expect(alloc1).not.toBeNull();
    expect(alloc2).not.toBeNull();
    expect(alloc3).not.toBeNull();
    expect(alloc1!.tokenBudget).toBe(50000);
    expect(alloc2!.tokenBudget).toBe(50000);
    expect(alloc3!.tokenBudget).toBe(50000);

    pool.resetMaxPerChild();
  });

  it('should still function correctly if resetMaxPerChild is never called', () => {
    const pool = new SharedBudgetPool({
      totalTokens: 200000,
      maxPerChild: 100000,
    });

    pool.setMaxPerChild(30000);

    // Pool works with reduced maxPerChild
    const alloc1 = pool.reserve('child-1');
    expect(alloc1).not.toBeNull();
    expect(alloc1!.tokenBudget).toBe(30000);

    // Record usage and release
    pool.recordUsage('child-1', 20000, 0.05);
    pool.release('child-1');

    // Pool still works
    const stats = pool.getStats();
    expect(stats.tokensUsed).toBe(20000);
    expect(stats.tokensRemaining).toBe(180000);

    // Can still reserve
    const alloc2 = pool.reserve('child-2');
    expect(alloc2).not.toBeNull();
    expect(alloc2!.tokenBudget).toBe(30000); // Still capped at 30K
  });

  it('should handle setMaxPerChild larger than remaining tokens', () => {
    const pool = new SharedBudgetPool({
      totalTokens: 100000,
      maxPerChild: 50000,
    });

    // Reserve 50K
    pool.reserve('child-1');

    // Set maxPerChild higher than remaining
    pool.setMaxPerChild(80000);

    // Should get only what's remaining (50K)
    const alloc = pool.reserve('child-2');
    expect(alloc).not.toBeNull();
    expect(alloc!.tokenBudget).toBe(50000); // min(80K, 50K remaining)

    pool.resetMaxPerChild();
  });

  it('should handle setMaxPerChild(0) — all reserves return null', () => {
    const pool = new SharedBudgetPool({ totalTokens: 100000, maxPerChild: 100000 });
    pool.setMaxPerChild(0);
    const alloc = pool.reserve('child-1');
    expect(alloc).toBeNull();
    pool.resetMaxPerChild();
  });
});

describe('createBudgetPool', () => {
  it('should reserve parentReserveRatio for parent', () => {
    const pool = createBudgetPool(200000, 0.25, 100000);
    const stats = pool.getStats();

    // 200K * 0.75 = 150K for pool
    expect(stats.totalTokens).toBe(150000);
  });

  it('should cap maxPerChild to pool size', () => {
    // Pool = 200K * 0.75 = 150K, but maxPerChild = 200K
    const pool = createBudgetPool(200000, 0.25, 200000);

    const alloc = pool.reserve('child-1');
    expect(alloc).not.toBeNull();
    // Should be capped to pool size (150K), not 200K
    expect(alloc!.tokenBudget).toBe(150000);
  });

  it('should use default reserve ratio of 25%', () => {
    const pool = createBudgetPool(200000);
    const stats = pool.getStats();
    expect(stats.totalTokens).toBe(150000);
  });

  it('should handle full reserve-use-release lifecycle', () => {
    const pool = createBudgetPool(200000, 0.25, 80000);

    // Spawn 2 children
    const alloc1 = pool.reserve('child-1');
    const alloc2 = pool.reserve('child-2');
    expect(alloc1).not.toBeNull();
    expect(alloc2).not.toBeNull();
    expect(alloc1!.tokenBudget).toBe(80000);
    expect(alloc2!.tokenBudget).toBe(70000); // 150K - 80K reserved

    // Child 1 uses only 30K, child 2 uses 50K
    pool.recordUsage('child-1', 30000, 0.05);
    pool.recordUsage('child-2', 50000, 0.10);

    // Release both
    pool.release('child-1');
    pool.release('child-2');

    // Pool should have 150K - 80K used = 70K remaining
    const stats = pool.getStats();
    expect(stats.tokensUsed).toBe(80000);
    expect(stats.tokensRemaining).toBe(70000);
    expect(stats.activeAllocations).toBe(0);
  });
});
