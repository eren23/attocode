/**
 * Tests for the health check system.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  HealthChecker,
  createHealthChecker,
  formatHealthReport,
  healthReportToJSON,
  type HealthCheckResult,
  type HealthReport,
} from '../../src/integrations/quality/health-check.js';

describe('Health Check System', () => {
  let checker: HealthChecker;

  beforeEach(() => {
    checker = createHealthChecker();
    vi.useFakeTimers();
  });

  afterEach(() => {
    checker.dispose();
    vi.useRealTimers();
  });

  describe('HealthChecker', () => {
    it('should register and run a health check', async () => {
      const checkFn = vi.fn().mockResolvedValue(true);
      checker.register('test', checkFn);

      const result = await checker.check('test');

      expect(result.healthy).toBe(true);
      expect(result.name).toBe('test');
      expect(result.latencyMs).toBeGreaterThanOrEqual(0);
      expect(checkFn).toHaveBeenCalledTimes(1);
    });

    it('should return unhealthy when check returns false', async () => {
      checker.register('test', async () => false);

      const result = await checker.check('test');

      expect(result.healthy).toBe(false);
    });

    it('should return unhealthy when check throws', async () => {
      checker.register('test', async () => {
        throw new Error('Check failed');
      });

      const result = await checker.check('test');

      expect(result.healthy).toBe(false);
      expect(result.error).toBe('Check failed');
    });

    it('should timeout slow checks', async () => {
      checker.register('slow', async () => {
        await new Promise(resolve => setTimeout(resolve, 10000));
        return true;
      }, { timeout: 100 });

      const resultPromise = checker.check('slow');
      await vi.advanceTimersByTimeAsync(150);
      const result = await resultPromise;

      expect(result.healthy).toBe(false);
      expect(result.error).toBe('Health check timeout');
    });

    it('should run all checks', async () => {
      checker.register('check1', async () => true);
      checker.register('check2', async () => true);
      checker.register('check3', async () => false);

      const report = await checker.checkAll();

      expect(report.totalCount).toBe(3);
      expect(report.healthyCount).toBe(2);
      expect(report.healthy).toBe(false); // One check failed
      expect(report.checks).toHaveLength(3);
    });

    it('should emit events', async () => {
      const events: string[] = [];
      checker.on(event => events.push(event.type));

      checker.register('test', async () => true);
      await checker.check('test');

      expect(events).toContain('check.started');
      expect(events).toContain('check.completed');
    });

    it('should emit status change events', async () => {
      const changes: Array<{ name: string; healthy: boolean; previous: boolean | undefined }> = [];
      checker.on(event => {
        if (event.type === 'status.changed') {
          changes.push({ name: event.name, healthy: event.healthy, previous: event.previous });
        }
      });

      let healthy = true;
      checker.register('test', async () => healthy);

      // First check - no previous state
      await checker.check('test');
      expect(changes).toHaveLength(1);
      expect(changes[0]).toEqual({ name: 'test', healthy: true, previous: undefined });

      // Second check - same state, no event
      await checker.check('test');
      expect(changes).toHaveLength(1);

      // Third check - state changed
      healthy = false;
      await checker.check('test');
      expect(changes).toHaveLength(2);
      expect(changes[1]).toEqual({ name: 'test', healthy: false, previous: true });
    });

    it('should track last results', async () => {
      checker.register('test', async () => true);
      await checker.check('test');

      const lastResult = checker.getLastResult('test');
      expect(lastResult?.healthy).toBe(true);
    });

    it('should determine overall health', async () => {
      checker.register('critical', async () => true, { critical: true });
      checker.register('optional', async () => false, { critical: false });

      await checker.checkAll();

      // System should be healthy since critical checks pass
      expect(checker.isHealthy()).toBe(true);
    });

    it('should be unhealthy when critical check fails', async () => {
      checker.register('critical', async () => false, { critical: true });

      await checker.checkAll();

      expect(checker.isHealthy()).toBe(false);
    });

    it('should list unhealthy checks', async () => {
      checker.register('healthy1', async () => true);
      checker.register('unhealthy1', async () => false);
      checker.register('healthy2', async () => true);
      checker.register('unhealthy2', async () => false);

      await checker.checkAll();

      const unhealthy = checker.getUnhealthyChecks();
      expect(unhealthy).toContain('unhealthy1');
      expect(unhealthy).toContain('unhealthy2');
      expect(unhealthy).not.toContain('healthy1');
      expect(unhealthy).not.toContain('healthy2');
    });

    it('should unregister checks', async () => {
      checker.register('test', async () => true);
      expect(checker.getCheckNames()).toContain('test');

      checker.unregister('test');
      expect(checker.getCheckNames()).not.toContain('test');
    });

    it('should start and stop periodic checks', async () => {
      const checkFn = vi.fn().mockResolvedValue(true);
      checker.register('test', checkFn);

      checker.startPeriodicChecks(1000);

      // Initial check runs immediately
      await vi.advanceTimersByTimeAsync(0);
      expect(checkFn).toHaveBeenCalledTimes(1);

      // Wait for next interval
      await vi.advanceTimersByTimeAsync(1000);
      expect(checkFn).toHaveBeenCalledTimes(2);

      // Stop periodic checks
      checker.stopPeriodicChecks();

      // No more checks after stopping
      await vi.advanceTimersByTimeAsync(1000);
      expect(checkFn).toHaveBeenCalledTimes(2);
    });

    it('should run checks in parallel by default', async () => {
      const order: number[] = [];

      checker.register('slow', async () => {
        await new Promise(resolve => setTimeout(resolve, 100));
        order.push(1);
        return true;
      });

      checker.register('fast', async () => {
        await new Promise(resolve => setTimeout(resolve, 10));
        order.push(2);
        return true;
      });

      const reportPromise = checker.checkAll();
      await vi.advanceTimersByTimeAsync(100);
      await reportPromise;

      // Fast should complete before slow in parallel mode
      expect(order).toEqual([2, 1]);
    });

    it('should run checks sequentially when configured', async () => {
      const sequentialChecker = createHealthChecker({ parallel: false });
      const order: number[] = [];

      sequentialChecker.register('first', async () => {
        await new Promise(resolve => setTimeout(resolve, 10));
        order.push(1);
        return true;
      });

      sequentialChecker.register('second', async () => {
        await new Promise(resolve => setTimeout(resolve, 10));
        order.push(2);
        return true;
      });

      const reportPromise = sequentialChecker.checkAll();
      await vi.advanceTimersByTimeAsync(30);
      await reportPromise;

      // Should run in registration order
      expect(order).toEqual([1, 2]);

      sequentialChecker.dispose();
    });

    it('should handle missing check gracefully', async () => {
      const result = await checker.check('nonexistent');

      expect(result.healthy).toBe(false);
      expect(result.error).toContain('not found');
    });
  });

  describe('formatHealthReport', () => {
    it('should format healthy report', () => {
      const report: HealthReport = {
        healthy: true,
        healthyCount: 2,
        totalCount: 2,
        timestamp: new Date(),
        totalLatencyMs: 150,
        checks: [
          { name: 'db', healthy: true, latencyMs: 50, timestamp: new Date() },
          { name: 'api', healthy: true, latencyMs: 100, timestamp: new Date() },
        ],
      };

      const output = formatHealthReport(report);

      expect(output).toContain('✓');
      expect(output).toContain('HEALTHY');
      expect(output).toContain('2/2 passing');
      expect(output).toContain('db');
      expect(output).toContain('api');
    });

    it('should format unhealthy report with errors', () => {
      const report: HealthReport = {
        healthy: false,
        healthyCount: 1,
        totalCount: 2,
        timestamp: new Date(),
        totalLatencyMs: 150,
        checks: [
          { name: 'db', healthy: true, latencyMs: 50, timestamp: new Date() },
          { name: 'api', healthy: false, latencyMs: 100, error: 'Connection refused', timestamp: new Date() },
        ],
      };

      const output = formatHealthReport(report);

      expect(output).toContain('✗');
      expect(output).toContain('UNHEALTHY');
      expect(output).toContain('1/2 passing');
      expect(output).toContain('Connection refused');
    });
  });

  describe('healthReportToJSON', () => {
    it('should convert report to JSON format', () => {
      const report: HealthReport = {
        healthy: true,
        healthyCount: 1,
        totalCount: 1,
        timestamp: new Date('2024-01-01T00:00:00Z'),
        totalLatencyMs: 100,
        checks: [
          { name: 'test', healthy: true, latencyMs: 100, timestamp: new Date('2024-01-01T00:00:00Z') },
        ],
      };

      const json = healthReportToJSON(report);

      expect(json.status).toBe('healthy');
      expect(json.healthyCount).toBe(1);
      expect(json.totalCount).toBe(1);
      expect(json.timestamp).toBe('2024-01-01T00:00:00.000Z');
      expect(json.checks).toHaveLength(1);
    });
  });
});
