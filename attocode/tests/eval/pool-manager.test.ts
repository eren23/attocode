/**
 * Tests for the PoolManager - generic warm pool with acquire/release/reset.
 */

import { describe, it, expect, vi } from 'vitest';
import { PoolManager } from '../../tools/eval/src/isolation/pool-manager.js';

function createTestPool(maxSlots = 3) {
  const mocks = {
    create: vi.fn(async (slotId: string) => ({ id: slotId, data: 'resource' })),
    reset: vi.fn(async (_slotId: string, _resource: unknown) => {}),
    destroy: vi.fn(async (_slotId: string, _resource: unknown) => {}),
  };

  const pool = new PoolManager({
    maxSlots,
    create: mocks.create,
    reset: mocks.reset,
    destroy: mocks.destroy,
  });

  return { pool, mocks };
}

describe('PoolManager', () => {
  describe('warmup', () => {
    it('pre-creates the specified number of slots', async () => {
      const { pool, mocks } = createTestPool(5);
      await pool.warmup(3);

      expect(mocks.create).toHaveBeenCalledTimes(3);
      const stats = pool.getStats();
      expect(stats.totalSlots).toBe(3);
      expect(stats.availableSlots).toBe(3);
      expect(stats.activeSlots).toBe(0);
    });

    it('caps warmup at maxSlots', async () => {
      const { pool, mocks } = createTestPool(2);
      await pool.warmup(5);

      expect(mocks.create).toHaveBeenCalledTimes(2);
      expect(pool.getStats().totalSlots).toBe(2);
    });
  });

  describe('acquire', () => {
    it('returns an available slot', async () => {
      const { pool } = createTestPool(3);
      await pool.warmup(2);

      const slot = await pool.acquire();
      expect(slot).toBeDefined();
      expect(slot.inUse).toBe(true);
      expect(pool.getStats().activeSlots).toBe(1);
    });

    it('creates a new slot if none available but under max', async () => {
      const { pool, mocks } = createTestPool(3);
      // No warmup - acquire should create on demand
      const slot = await pool.acquire();
      expect(slot).toBeDefined();
      expect(mocks.create).toHaveBeenCalledTimes(1);
    });

    it('blocks when all slots are in use and at max', async () => {
      const { pool } = createTestPool(2);
      await pool.warmup(2);

      // Acquire both slots
      const slot1 = await pool.acquire();
      await pool.acquire(); // slot2

      // Third acquire should block
      let acquired = false;
      const acquirePromise = pool.acquire().then((s) => {
        acquired = true;
        return s;
      });

      // Give it a moment to verify it's not resolved yet
      await new Promise((r) => setTimeout(r, 50));
      expect(acquired).toBe(false);
      expect(pool.getStats().pendingAcquires).toBe(1);

      // Release one slot
      await pool.release(slot1.id);

      // Now the pending acquire should resolve
      const slot3 = await acquirePromise;
      expect(acquired).toBe(true);
      expect(slot3.id).toBe(slot1.id);
    });

    it('increments totalAcquires counter', async () => {
      const { pool } = createTestPool(3);
      await pool.acquire();
      await pool.acquire();
      expect(pool.getStats().totalAcquires).toBe(2);
    });
  });

  describe('release', () => {
    it('makes the slot available again', async () => {
      const { pool, mocks } = createTestPool(2);
      const slot = await pool.acquire();
      expect(pool.getStats().availableSlots).toBe(0);

      await pool.release(slot.id);
      expect(pool.getStats().availableSlots).toBe(1);
      expect(mocks.reset).toHaveBeenCalledOnce();
    });

    it('increments the reuseCount', async () => {
      const { pool } = createTestPool(1);
      const slot = await pool.acquire();
      expect(slot.reuseCount).toBe(0);

      await pool.release(slot.id);
      const reacquired = await pool.acquire();
      expect(reacquired.reuseCount).toBe(1);
    });

    it('throws for unknown slot', async () => {
      const { pool } = createTestPool(2);
      await expect(pool.release('nonexistent')).rejects.toThrow('Unknown slot');
    });
  });

  describe('destroyAll', () => {
    it('destroys all slots', async () => {
      const { pool, mocks } = createTestPool(3);
      await pool.warmup(3);

      await pool.destroyAll();
      expect(mocks.destroy).toHaveBeenCalledTimes(3);
      expect(pool.getStats().totalSlots).toBe(0);
    });

    it('rejects pending acquires', async () => {
      const { pool } = createTestPool(1);
      await pool.acquire(); // fill the only slot

      const acquirePromise = pool.acquire();
      await pool.destroyAll();

      await expect(acquirePromise).rejects.toThrow('Pool destroyed');
    });

    it('prevents further acquires', async () => {
      const { pool } = createTestPool(2);
      await pool.destroyAll();
      await expect(pool.acquire()).rejects.toThrow('Pool has been destroyed');
    });
  });

  describe('getStats', () => {
    it('returns accurate statistics', async () => {
      const { pool } = createTestPool(3);
      await pool.warmup(3);

      const s1 = await pool.acquire();
      await pool.acquire();

      expect(pool.getStats()).toEqual({
        totalSlots: 3,
        activeSlots: 2,
        availableSlots: 1,
        pendingAcquires: 0,
        totalAcquires: 2,
        totalResets: 0,
      });

      await pool.release(s1.id);

      expect(pool.getStats()).toEqual({
        totalSlots: 3,
        activeSlots: 1,
        availableSlots: 2,
        pendingAcquires: 0,
        totalAcquires: 2,
        totalResets: 1,
      });
    });
  });
});
