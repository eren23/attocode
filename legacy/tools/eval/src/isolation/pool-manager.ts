/**
 * Generic Pool Manager
 *
 * Manages a pool of reusable slots with acquire/release semantics.
 * Used by isolation providers to manage worktree or container slots.
 */

import type { PoolStats } from './types.js';

// =============================================================================
// TYPES
// =============================================================================

export interface PoolSlot<T = unknown> {
  id: string;
  resource: T;
  inUse: boolean;
  createdAt: number;
  reuseCount: number;
}

export interface PoolManagerOptions<T> {
  /** Maximum number of slots */
  maxSlots: number;

  /** Factory function to create a new slot resource */
  create: (slotId: string) => Promise<T>;

  /** Reset function to restore a slot to clean state */
  reset: (slotId: string, resource: T) => Promise<void>;

  /** Destroy function to clean up a slot resource */
  destroy: (slotId: string, resource: T) => Promise<void>;
}

// =============================================================================
// POOL MANAGER
// =============================================================================

export class PoolManager<T = unknown> {
  private slots: Map<string, PoolSlot<T>> = new Map();
  private waitQueue: Array<{
    resolve: (slot: PoolSlot<T>) => void;
    reject: (err: Error) => void;
  }> = [];
  private options: PoolManagerOptions<T>;
  private nextSlotId = 0;
  private totalAcquires = 0;
  private totalResets = 0;
  private destroyed = false;

  constructor(options: PoolManagerOptions<T>) {
    this.options = options;
  }

  /**
   * Pre-warm the pool by creating slots ahead of time.
   */
  async warmup(count?: number): Promise<void> {
    const toCreate = Math.min(count ?? this.options.maxSlots, this.options.maxSlots);

    const promises: Promise<void>[] = [];
    for (let i = 0; i < toCreate; i++) {
      promises.push(this.createSlot());
    }
    await Promise.all(promises);
  }

  /**
   * Acquire a slot from the pool. Blocks if none are available.
   */
  async acquire(): Promise<PoolSlot<T>> {
    if (this.destroyed) {
      throw new Error('Pool has been destroyed');
    }

    // Try to find an available slot
    for (const slot of this.slots.values()) {
      if (!slot.inUse) {
        slot.inUse = true;
        this.totalAcquires++;
        return slot;
      }
    }

    // If we haven't hit max, create a new slot
    if (this.slots.size < this.options.maxSlots) {
      const slot = await this.createSlotAndReturn();
      slot.inUse = true;
      this.totalAcquires++;
      return slot;
    }

    // All slots in use and at max - wait for one to be released
    return new Promise<PoolSlot<T>>((resolve, reject) => {
      this.waitQueue.push({ resolve, reject });
    });
  }

  /**
   * Reset and release a slot back to the pool.
   */
  async release(slotId: string): Promise<void> {
    const slot = this.slots.get(slotId);
    if (!slot) {
      throw new Error(`Unknown slot: ${slotId}`);
    }

    // Reset the slot to clean state
    await this.options.reset(slotId, slot.resource);
    slot.reuseCount++;
    slot.inUse = false;
    this.totalResets++;

    // If someone is waiting, give them this slot
    if (this.waitQueue.length > 0) {
      const waiter = this.waitQueue.shift()!;
      slot.inUse = true;
      this.totalAcquires++;
      waiter.resolve(slot);
    }
  }

  /**
   * Destroy all slots and release resources.
   */
  async destroyAll(): Promise<void> {
    this.destroyed = true;

    // Reject all waiters
    for (const waiter of this.waitQueue) {
      waiter.reject(new Error('Pool destroyed'));
    }
    this.waitQueue = [];

    // Destroy all slots
    const destroyPromises: Promise<void>[] = [];
    for (const slot of this.slots.values()) {
      destroyPromises.push(
        this.options.destroy(slot.id, slot.resource).catch((err) => {
          console.warn(`[PoolManager] Failed to destroy slot ${slot.id}:`, err);
        }),
      );
    }
    await Promise.all(destroyPromises);
    this.slots.clear();
  }

  /**
   * Get current pool statistics.
   */
  getStats(): PoolStats {
    let active = 0;
    for (const slot of this.slots.values()) {
      if (slot.inUse) active++;
    }

    return {
      totalSlots: this.slots.size,
      activeSlots: active,
      availableSlots: this.slots.size - active,
      pendingAcquires: this.waitQueue.length,
      totalAcquires: this.totalAcquires,
      totalResets: this.totalResets,
    };
  }

  /**
   * Get a slot by ID.
   */
  getSlot(slotId: string): PoolSlot<T> | undefined {
    return this.slots.get(slotId);
  }

  // ---------------------------------------------------------------------------
  // PRIVATE
  // ---------------------------------------------------------------------------

  private async createSlot(): Promise<void> {
    await this.createSlotAndReturn();
  }

  private async createSlotAndReturn(): Promise<PoolSlot<T>> {
    const slotId = `slot-${this.nextSlotId++}`;
    const resource = await this.options.create(slotId);
    const slot: PoolSlot<T> = {
      id: slotId,
      resource,
      inUse: false,
      createdAt: Date.now(),
      reuseCount: 0,
    };
    this.slots.set(slotId, slot);
    return slot;
  }
}
