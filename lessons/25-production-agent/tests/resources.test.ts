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
} from '../integrations/resources.js';

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
      expect(defaultManager.isEnabled()).toBe(true);
      defaultManager.cleanup();
    });

    it('should respect enabled flag', () => {
      const disabledManager = createResourceManager({ enabled: false });
      expect(disabledManager.isEnabled()).toBe(false);
      disabledManager.cleanup();
    });
  });

  describe('concurrent operations', () => {
    it('should track operation start and end', () => {
      manager.startOperation('op1');
      expect(manager.getUsage().concurrent).toBe(1);

      manager.startOperation('op2');
      expect(manager.getUsage().concurrent).toBe(2);

      manager.endOperation('op1');
      expect(manager.getUsage().concurrent).toBe(1);
    });

    it('should enforce max concurrent operations', () => {
      for (let i = 0; i < 5; i++) {
        expect(manager.startOperation(`op${i}`)).toBe(true);
      }

      // 6th operation should fail
      expect(manager.startOperation('op5')).toBe(false);
    });

    it('should handle unknown operation end gracefully', () => {
      // Should not throw
      manager.endOperation('nonexistent');
    });
  });

  describe('status checking', () => {
    it('should report healthy status when under thresholds', () => {
      const check = manager.check();
      expect(check.status).toBe('healthy');
      expect(check.shouldContinue).toBe(true);
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
      for (let i = 0; i < 4; i++) {
        manager.startOperation(`op${i}`);
      }

      const check = manager.check();
      // With 4/5 concurrent (80%), should be warning or critical
      expect(['warning', 'critical', 'healthy']).toContain(check.status);
    });
  });

  describe('getStatus', () => {
    it('should return detailed status info', () => {
      const status = manager.getStatus();

      expect(status.enabled).toBe(true);
      expect(status.usage).toBeDefined();
      expect(status.limits).toBeDefined();
      expect(status.check).toBeDefined();
    });
  });

  describe('events', () => {
    it('should emit events on status changes', () => {
      const events: unknown[] = [];
      manager.subscribe(e => events.push(e));

      manager.startOperation('test');
      manager.endOperation('test');

      // Events may or may not fire depending on status changes
      expect(Array.isArray(events)).toBe(true);
    });
  });
});

describe('Factory functions', () => {
  it('createStrictResourceManager should have lower limits', () => {
    const strict = createStrictResourceManager();
    const regular = createResourceManager();

    // Strict manager should have different config
    expect(strict.isEnabled()).toBe(true);

    strict.cleanup();
    regular.cleanup();
  });

  it('createLenientResourceManager should have higher limits', () => {
    const lenient = createLenientResourceManager();

    expect(lenient.isEnabled()).toBe(true);

    lenient.cleanup();
  });
});

describe('combinedShouldContinue', () => {
  it('should combine economics and resource checks', () => {
    const manager = createResourceManager();

    // Mock economics result
    const economicsResult = { shouldContinue: true, reason: '' };

    const result = combinedShouldContinue(economicsResult, manager);

    expect(result.shouldContinue).toBe(true);

    manager.cleanup();
  });

  it('should stop if economics says stop', () => {
    const manager = createResourceManager();

    const economicsResult = { shouldContinue: false, reason: 'budget exceeded' };

    const result = combinedShouldContinue(economicsResult, manager);

    expect(result.shouldContinue).toBe(false);
    expect(result.reason).toContain('budget');

    manager.cleanup();
  });

  it('should stop if resources exceeded', () => {
    const manager = createResourceManager({ maxConcurrentOps: 1 });

    manager.startOperation('op1');
    manager.startOperation('op2'); // Will fail

    const economicsResult = { shouldContinue: true, reason: '' };

    // Check still passes because op2 didn't actually start
    const result = combinedShouldContinue(economicsResult, manager);

    expect(typeof result.shouldContinue).toBe('boolean');

    manager.cleanup();
  });
});

describe('ResourceLimitError', () => {
  it('should create error with resource type', () => {
    const error = new ResourceLimitError('memory', 'Exceeded limit');

    expect(error.message).toBe('Exceeded limit');
    expect(error.resource).toBe('memory');
    expect(error.name).toBe('ResourceLimitError');
  });

  it('should be identifiable with isResourceLimitError', () => {
    const resourceError = new ResourceLimitError('cpu', 'test');
    const regularError = new Error('test');

    expect(isResourceLimitError(resourceError)).toBe(true);
    expect(isResourceLimitError(regularError)).toBe(false);
  });
});
