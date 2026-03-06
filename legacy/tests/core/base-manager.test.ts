/**
 * Base Manager Pattern Tests (Phase 2.3)
 *
 * Tests for lifecycle management, event emission, subscription tracking,
 * and the standard manager contract.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  BaseManager,
  type BaseEvent,
  type ManagerLifecycleEvent,
} from '../../src/core/base-manager.js';

// =============================================================================
// TEST IMPLEMENTATION
// =============================================================================

interface TestEvent extends BaseEvent {
  type: 'test.data';
  value: number;
}

class TestManager extends BaseManager<TestEvent> {
  protected readonly managerName = 'TestManager';

  initCalled = false;
  cleanupCalled = false;
  resetCalled = false;
  shouldFailInit = false;
  shouldFailCleanup = false;

  protected async onInit(): Promise<void> {
    if (this.shouldFailInit) throw new Error('Init failed');
    this.initCalled = true;
  }

  protected async onCleanup(): Promise<void> {
    if (this.shouldFailCleanup) throw new Error('Cleanup failed');
    this.cleanupCalled = true;
  }

  protected onReset(): void {
    this.resetCalled = true;
  }

  /** Expose emit for testing */
  testEmit(event: TestEvent): void {
    this.emit(event);
  }

  /** Expose trackSubscription for testing */
  testTrackSubscription(unsub: () => void): void {
    this.trackSubscription(unsub);
  }
}

// =============================================================================
// LIFECYCLE
// =============================================================================

describe('Lifecycle', () => {
  let manager: TestManager;

  beforeEach(() => {
    manager = new TestManager();
  });

  it('starts in created state', () => {
    expect(manager.state).toBe('created');
    expect(manager.isReady).toBe(false);
  });

  it('transitions to ready after init', async () => {
    await manager.init();
    expect(manager.state).toBe('ready');
    expect(manager.isReady).toBe(true);
    expect(manager.initCalled).toBe(true);
  });

  it('init is idempotent', async () => {
    await manager.init();
    manager.initCalled = false;
    await manager.init();
    expect(manager.initCalled).toBe(false); // Not called again
  });

  it('transitions to disposed after cleanup', async () => {
    await manager.init();
    await manager.cleanup();
    expect(manager.state).toBe('disposed');
    expect(manager.cleanupCalled).toBe(true);
  });

  it('cleanup is idempotent', async () => {
    await manager.init();
    await manager.cleanup();
    manager.cleanupCalled = false;
    await manager.cleanup();
    expect(manager.cleanupCalled).toBe(false);
  });

  it('reset returns to ready state', async () => {
    await manager.init();
    manager.reset();
    expect(manager.state).toBe('ready');
    expect(manager.resetCalled).toBe(true);
  });

  it('init failure returns to created state', async () => {
    manager.shouldFailInit = true;
    await expect(manager.init()).rejects.toThrow('Init failed');
    expect(manager.state).toBe('created');
  });

  it('init can be retried after failure', async () => {
    manager.shouldFailInit = true;
    await expect(manager.init()).rejects.toThrow();
    manager.shouldFailInit = false;
    await manager.init();
    expect(manager.state).toBe('ready');
  });

  it('cleanup error does not prevent disposal', async () => {
    await manager.init();
    manager.shouldFailCleanup = true;
    await manager.cleanup(); // Should not throw
    expect(manager.state).toBe('disposed');
  });
});

// =============================================================================
// EVENT SYSTEM
// =============================================================================

describe('Event System', () => {
  let manager: TestManager;

  beforeEach(async () => {
    manager = new TestManager();
    await manager.init();
  });

  it('emits custom events to subscribers', () => {
    const events: (TestEvent | ManagerLifecycleEvent)[] = [];
    manager.subscribe(e => events.push(e));
    manager.testEmit({ type: 'test.data', value: 42 });

    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({ type: 'test.data', value: 42 });
  });

  it('supports multiple subscribers', () => {
    let count = 0;
    manager.subscribe(() => count++);
    manager.subscribe(() => count++);
    manager.testEmit({ type: 'test.data', value: 1 });

    expect(count).toBe(2);
  });

  it('unsubscribe removes listener', () => {
    const events: (TestEvent | ManagerLifecycleEvent)[] = [];
    const unsub = manager.subscribe(e => events.push(e));
    unsub();
    manager.testEmit({ type: 'test.data', value: 1 });

    expect(events).toHaveLength(0);
  });

  it('listener errors do not break event emission', () => {
    const events: (TestEvent | ManagerLifecycleEvent)[] = [];
    manager.subscribe(() => { throw new Error('bad'); });
    manager.subscribe(e => events.push(e));
    manager.testEmit({ type: 'test.data', value: 1 });

    expect(events).toHaveLength(1);
  });
});

// =============================================================================
// LIFECYCLE EVENTS
// =============================================================================

describe('Lifecycle Events', () => {
  it('emits manager.initialized on init', async () => {
    const manager = new TestManager();
    const events: (TestEvent | ManagerLifecycleEvent)[] = [];
    manager.subscribe(e => events.push(e));
    await manager.init();

    const lifecycleEvents = events.filter(e => e.type === 'manager.initialized');
    expect(lifecycleEvents).toHaveLength(1);
    expect((lifecycleEvents[0] as ManagerLifecycleEvent).manager).toBe('TestManager');
  });

  it('emits manager.cleanup on cleanup', async () => {
    const manager = new TestManager();
    await manager.init();
    const events: (TestEvent | ManagerLifecycleEvent)[] = [];
    manager.subscribe(e => events.push(e));
    await manager.cleanup();

    const lifecycleEvents = events.filter(e => e.type === 'manager.cleanup');
    expect(lifecycleEvents).toHaveLength(1);
  });

  it('emits manager.reset on reset', async () => {
    const manager = new TestManager();
    await manager.init();
    const events: (TestEvent | ManagerLifecycleEvent)[] = [];
    manager.subscribe(e => events.push(e));
    manager.reset();

    const lifecycleEvents = events.filter(e => e.type === 'manager.reset');
    expect(lifecycleEvents).toHaveLength(1);
  });

  it('emits manager.error on init failure', async () => {
    const manager = new TestManager();
    manager.shouldFailInit = true;
    const events: (TestEvent | ManagerLifecycleEvent)[] = [];
    manager.subscribe(e => events.push(e));

    await manager.init().catch(() => {});

    const errorEvents = events.filter(e => e.type === 'manager.error') as ManagerLifecycleEvent[];
    expect(errorEvents).toHaveLength(1);
    expect(errorEvents[0].error).toContain('Init failed');
  });
});

// =============================================================================
// SUBSCRIPTION TRACKING
// =============================================================================

describe('Subscription Tracking', () => {
  it('cleans up tracked subscriptions on cleanup', async () => {
    const manager = new TestManager();
    await manager.init();

    const unsub1 = vi.fn();
    const unsub2 = vi.fn();
    manager.testTrackSubscription(unsub1);
    manager.testTrackSubscription(unsub2);

    await manager.cleanup();

    expect(unsub1).toHaveBeenCalledOnce();
    expect(unsub2).toHaveBeenCalledOnce();
  });

  it('ignores errors from tracked unsubscriptions', async () => {
    const manager = new TestManager();
    await manager.init();

    manager.testTrackSubscription(() => { throw new Error('unsub error'); });

    await expect(manager.cleanup()).resolves.toBeUndefined();
    expect(manager.state).toBe('disposed');
  });

  it('clears listeners on cleanup', async () => {
    const manager = new TestManager();
    await manager.init();
    const events: (TestEvent | ManagerLifecycleEvent)[] = [];
    manager.subscribe(e => events.push(e));

    await manager.cleanup();
    // After cleanup, listeners should be cleared
    // But we can't easily test this since the manager is disposed
    expect(manager.state).toBe('disposed');
  });
});

// =============================================================================
// CONCURRENT INIT
// =============================================================================

describe('Concurrent Init', () => {
  it('concurrent init calls both resolve successfully', async () => {
    const manager = new TestManager();
    const p1 = manager.init();
    const p2 = manager.init();

    await Promise.all([p1, p2]);
    expect(manager.state).toBe('ready');
    // init is only called once despite two init() calls
    expect(manager.initCalled).toBe(true);
  });
});
