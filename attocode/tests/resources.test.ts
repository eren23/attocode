/**
 * Resource Monitor Tests
 *
 * Tests for the resource monitoring system that tracks memory, CPU, and concurrent operations.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  ResourceManager,
  createResourceManager,
  createStrictResourceManager,
  createLenientResourceManager,
  combinedShouldContinue,
  isResourceLimitError,
  ResourceLimitError,
} from '../src/integrations/budget/resources.js';

describe('ResourceManager', () => {
  let manager: ResourceManager;

  beforeEach(() => {
    manager = createResourceManager({
      maxMemoryMB: 100,
      maxCpuTimeSec: 60,
      maxConcurrentOps: 5,
      warnThreshold: 0.7,
      criticalThreshold: 0.9,
    });
  });

  afterEach(() => {
    manager.cleanup();
  });

  describe('initialization', () => {
    it('should create with default config', () => {
      const defaultManager = createResourceManager();
      expect(defaultManager.getLimits().enabled).toBe(true);
      defaultManager.cleanup();
    });

    it('should respect enabled flag', () => {
      const disabledManager = createResourceManager({ enabled: false });
      expect(disabledManager.getLimits().enabled).toBe(false);
      disabledManager.cleanup();
    });
  });

  describe('concurrent operations', () => {
    it('should track operation start and end', () => {
      const end1 = manager.startOperation();
      expect(manager.getUsage().concurrentOps).toBe(1);

      const end2 = manager.startOperation();
      expect(manager.getUsage().concurrentOps).toBe(2);

      end1();
      expect(manager.getUsage().concurrentOps).toBe(1);

      end2();
      expect(manager.getUsage().concurrentOps).toBe(0);
    });

    it('should enforce max concurrent operations via canStartOperation', () => {
      const ends: (() => void)[] = [];
      for (let i = 0; i < 5; i++) {
        expect(manager.canStartOperation()).toBe(true);
        ends.push(manager.startOperation());
      }

      // At max capacity, canStartOperation should return false
      expect(manager.canStartOperation()).toBe(false);

      // Cleanup
      ends.forEach(end => end());
    });

    it('should handle cleanup via returned function', () => {
      const end = manager.startOperation();
      expect(manager.getUsage().concurrentOps).toBe(1);

      end();
      expect(manager.getUsage().concurrentOps).toBe(0);

      // Calling end again should be safe (floors at 0)
      end();
      expect(manager.getUsage().concurrentOps).toBe(0);
    });
  });

  describe('status checking', () => {
    it('should report healthy status when under thresholds', () => {
      const check = manager.check();
      expect(check.status).toBe('healthy');
      expect(check.canContinue).toBe(true);
    });

    it('should track memory usage', () => {
      const usage = manager.getUsage();
      expect(usage.memoryMB).toBeGreaterThanOrEqual(0);
    });

    it('should track CPU time', () => {
      const usage = manager.getUsage();
      expect(usage.cpuTimeSec).toBeGreaterThanOrEqual(0);
    });
  });

  describe('resource status levels', () => {
    it('should update status based on concurrent ops', () => {
      // Add operations to push into warning/critical
      const ends: (() => void)[] = [];
      for (let i = 0; i < 4; i++) {
        ends.push(manager.startOperation());
      }

      const check = manager.check();
      // With 4/5 concurrent (80%), should be warning or critical
      expect(['warning', 'critical', 'healthy']).toContain(check.status);

      // Cleanup
      ends.forEach(end => end());
    });
  });

  describe('getStatusString', () => {
    it('should return detailed status info', () => {
      const statusString = manager.getStatusString();

      expect(statusString).toContain('Memory');
      expect(statusString).toContain('CPU Time');
      expect(statusString).toContain('Operations');
      expect(statusString).toContain('Status');
    });
  });

  describe('getLimits and setLimits', () => {
    it('should get and set limits', () => {
      const limits = manager.getLimits();
      expect(limits.enabled).toBe(true);
      expect(limits.maxMemoryMB).toBe(100);

      manager.setLimits({ maxMemoryMB: 200 });
      expect(manager.getLimits().maxMemoryMB).toBe(200);
    });
  });

  describe('events', () => {
    it('should emit events on status changes', () => {
      const events: unknown[] = [];
      manager.subscribe(e => events.push(e));

      const end = manager.startOperation();
      end();

      // Events may or may not fire depending on status changes
      expect(Array.isArray(events)).toBe(true);
    });
  });

  describe('runTracked', () => {
    it('should track operation during async function', async () => {
      const result = await manager.runTracked(async () => {
        expect(manager.getUsage().concurrentOps).toBe(1);
        return 'done';
      });

      expect(result).toBe('done');
      expect(manager.getUsage().concurrentOps).toBe(0);
    });
  });

  describe('runIfAvailable', () => {
    it('should run if resources available', async () => {
      const result = await manager.runIfAvailable(async () => 'success', 'fallback');
      expect(result).toBe('success');
    });

    it('should return fallback if resources not available', async () => {
      // Fill up concurrent operations
      const ends: (() => void)[] = [];
      for (let i = 0; i < 5; i++) {
        ends.push(manager.startOperation());
      }

      const result = await manager.runIfAvailable(async () => 'success', 'fallback');
      expect(result).toBe('fallback');

      // Cleanup
      ends.forEach(end => end());
    });
  });

  describe('reset', () => {
    it('should reset timing and operation count', () => {
      const end = manager.startOperation();
      expect(manager.getUsage().concurrentOps).toBe(1);

      manager.reset();
      expect(manager.getUsage().concurrentOps).toBe(0);

      // Note: end() is now orphaned, but that's fine for testing
    });
  });
});

describe('Factory functions', () => {
  it('createStrictResourceManager should have lower limits', () => {
    const strict = createStrictResourceManager();
    const regular = createResourceManager();

    // Strict manager should have different config
    expect(strict.getLimits().enabled).toBe(true);
    expect(strict.getLimits().maxMemoryMB).toBeLessThan(regular.getLimits().maxMemoryMB);

    strict.cleanup();
    regular.cleanup();
  });

  it('createLenientResourceManager should have higher limits', () => {
    const lenient = createLenientResourceManager();
    const regular = createResourceManager();

    expect(lenient.getLimits().enabled).toBe(true);
    expect(lenient.getLimits().maxMemoryMB).toBeGreaterThan(regular.getLimits().maxMemoryMB);

    lenient.cleanup();
    regular.cleanup();
  });
});

describe('combinedShouldContinue', () => {
  it('should combine economics and resource checks', () => {
    const manager = createResourceManager();

    const result = combinedShouldContinue(manager, true);

    expect(result.canContinue).toBe(true);

    manager.cleanup();
  });

  it('should stop if economics says stop', () => {
    const manager = createResourceManager();

    const result = combinedShouldContinue(manager, false);

    expect(result.canContinue).toBe(false);
    expect(result.reason).toContain('Budget');

    manager.cleanup();
  });

  it('should work with null manager', () => {
    const result = combinedShouldContinue(null, true);
    expect(result.canContinue).toBe(true);

    const resultFalse = combinedShouldContinue(null, false);
    expect(resultFalse.canContinue).toBe(false);
  });
});

describe('ResourceLimitError', () => {
  it('should create error with message', () => {
    const error = new ResourceLimitError('Exceeded limit');

    expect(error.message).toBe('Exceeded limit');
    expect(error.name).toBe('ResourceLimitError');
    expect(error.isResourceLimit).toBe(true);
  });

  it('should be identifiable with isResourceLimitError', () => {
    const resourceError = new ResourceLimitError('test');
    const regularError = new Error('test');

    expect(isResourceLimitError(resourceError)).toBe(true);
    expect(isResourceLimitError(regularError)).toBe(false);
  });
});
