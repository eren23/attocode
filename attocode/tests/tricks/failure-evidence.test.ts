/**
 * Failure Evidence Tests
 *
 * Tests for the failure tracking, error categorization, and pattern detection.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  FailureTracker,
  createFailureTracker,
  categorizeError,
  generateSuggestion,
  formatFailureContext,
  createRepeatWarning,
  extractInsights,
  formatFailureStats,
  type Failure,
  type FailureCategory,
  type FailureEvent,
  type FailureInput,
} from '../../src/tricks/failure-evidence.js';

// =============================================================================
// TEST HELPERS
// =============================================================================

function createTestFailure(overrides: Partial<Failure> = {}): Failure {
  return {
    id: `fail-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    timestamp: new Date().toISOString(),
    action: 'test_action',
    args: { path: '/test/path' },
    error: 'Test error message',
    category: 'unknown',
    resolved: false,
    repeatCount: 1,
    suggestion: 'Test suggestion',
    ...overrides,
  };
}

function createTestInput(overrides: Partial<FailureInput> = {}): FailureInput {
  return {
    action: 'test_action',
    args: { path: '/test/path' },
    error: 'Test error message',
    ...overrides,
  };
}

// =============================================================================
// TESTS: categorizeError
// =============================================================================

describe('categorizeError', () => {
  describe('permission category', () => {
    it('should categorize "permission denied" as permission', () => {
      expect(categorizeError('Permission denied')).toBe('permission');
    });

    it('should categorize "access denied" as permission', () => {
      expect(categorizeError('Access denied to file')).toBe('permission');
    });

    it('should categorize "not permitted" as permission', () => {
      expect(categorizeError('Operation not permitted')).toBe('permission');
    });

    it('should categorize "EACCES" as permission', () => {
      expect(categorizeError('EACCES: permission denied')).toBe('permission');
    });

    it('should categorize "unauthorized" as permission', () => {
      expect(categorizeError('401 Unauthorized')).toBe('permission');
    });
  });

  describe('not_found category', () => {
    it('should categorize "not found" as not_found', () => {
      expect(categorizeError('File not found')).toBe('not_found');
    });

    it('should categorize "no such file" as not_found', () => {
      expect(categorizeError('No such file or directory')).toBe('not_found');
    });

    it('should categorize "ENOENT" as not_found', () => {
      expect(categorizeError('ENOENT: no such file')).toBe('not_found');
    });

    it('should categorize "does not exist" as not_found', () => {
      expect(categorizeError('Path does not exist')).toBe('not_found');
    });

    it('should categorize "404" as not_found', () => {
      expect(categorizeError('HTTP 404 error')).toBe('not_found');
    });
  });

  describe('syntax category', () => {
    it('should categorize "syntax error" as syntax', () => {
      expect(categorizeError('SyntaxError: unexpected token')).toBe('syntax');
    });

    it('should categorize "unexpected token" as syntax', () => {
      expect(categorizeError('Unexpected token }' )).toBe('syntax');
    });

    it('should categorize "parse error" as syntax', () => {
      expect(categorizeError('JSON parse error')).toBe('syntax');
    });

    it('should categorize "invalid json" as syntax', () => {
      expect(categorizeError('Invalid JSON at position 5')).toBe('syntax');
    });
  });

  describe('type category', () => {
    it('should categorize "type error" as type', () => {
      expect(categorizeError('Type error occurred')).toBe('type');
    });

    it('should categorize "TypeError" as type', () => {
      expect(categorizeError('TypeError: undefined is not a function')).toBe('type');
    });

    it('should categorize "is not a function" as type', () => {
      expect(categorizeError('x.map is not a function')).toBe('type');
    });

    it('should categorize "undefined is not" as type', () => {
      expect(categorizeError('undefined is not an object')).toBe('type');
    });

    it('should categorize "cannot read propert" as type', () => {
      expect(categorizeError('Cannot read property \'x\' of undefined')).toBe('type');
    });
  });

  describe('network category', () => {
    it('should categorize "network" errors as network', () => {
      expect(categorizeError('Network error')).toBe('network');
    });

    it('should categorize "connection" errors as network', () => {
      expect(categorizeError('Connection refused')).toBe('network');
    });

    it('should categorize "ECONNREFUSED" as network', () => {
      expect(categorizeError('ECONNREFUSED localhost:3000')).toBe('network');
    });

    it('should categorize "socket" errors as network', () => {
      expect(categorizeError('Socket hang up')).toBe('network');
    });

    it('should categorize "dns" errors as network', () => {
      expect(categorizeError('DNS resolution failed')).toBe('network');
    });

    it('should categorize "fetch failed" as network', () => {
      expect(categorizeError('fetch failed')).toBe('network');
    });
  });

  describe('timeout category', () => {
    it('should categorize "timeout" as timeout', () => {
      expect(categorizeError('Operation timeout')).toBe('timeout');
    });

    it('should categorize "timed out" as timeout', () => {
      expect(categorizeError('Request timed out')).toBe('timeout');
    });

    it('should categorize "ETIMEDOUT" as timeout', () => {
      expect(categorizeError('ETIMEDOUT')).toBe('timeout');
    });
  });

  describe('validation category', () => {
    it('should categorize "validation" as validation', () => {
      expect(categorizeError('Validation failed')).toBe('validation');
    });

    it('should categorize "invalid" as validation', () => {
      expect(categorizeError('Invalid email format')).toBe('validation');
    });

    it('should categorize "required" as validation', () => {
      expect(categorizeError('Field is required')).toBe('validation');
    });

    it('should categorize "must be" as validation', () => {
      expect(categorizeError('Value must be positive')).toBe('validation');
    });
  });

  describe('resource category', () => {
    it('should categorize "out of memory" as resource', () => {
      expect(categorizeError('Out of memory')).toBe('resource');
    });

    it('should categorize "disk full" as resource', () => {
      expect(categorizeError('Disk full')).toBe('resource');
    });

    it('should categorize "ENOMEM" as resource', () => {
      expect(categorizeError('ENOMEM')).toBe('resource');
    });

    it('should categorize "ENOSPC" as resource', () => {
      expect(categorizeError('ENOSPC: no space left')).toBe('resource');
    });

    it('should categorize "quota" as resource', () => {
      expect(categorizeError('Quota exceeded')).toBe('resource');
    });
  });

  describe('logic category', () => {
    it('should categorize "assertion" as logic', () => {
      expect(categorizeError('Assertion failed')).toBe('logic');
    });

    it('should categorize "invariant" as logic', () => {
      expect(categorizeError('Invariant violation')).toBe('logic');
    });

    it('should categorize "expect" as logic', () => {
      expect(categorizeError('Expected true but got false')).toBe('logic');
    });
  });

  describe('unknown category', () => {
    it('should return unknown for unrecognized errors', () => {
      expect(categorizeError('Something went wrong')).toBe('unknown');
    });

    it('should handle empty strings', () => {
      expect(categorizeError('')).toBe('unknown');
    });

    it('should be case insensitive', () => {
      expect(categorizeError('PERMISSION DENIED')).toBe('permission');
      expect(categorizeError('Not Found')).toBe('not_found');
    });
  });
});

// =============================================================================
// TESTS: generateSuggestion
// =============================================================================

describe('generateSuggestion', () => {
  it('should generate suggestion for permission failures', () => {
    const failure = createTestFailure({ category: 'permission', action: 'read_file' });
    const suggestion = generateSuggestion(failure);

    expect(suggestion).toContain('permission');
    expect(suggestion).toContain('read_file');
  });

  it('should generate suggestion for not_found failures', () => {
    const failure = createTestFailure({ category: 'not_found' });
    const suggestion = generateSuggestion(failure);

    expect(suggestion).toContain('Verify');
    expect(suggestion).toContain('exists');
  });

  it('should generate suggestion for syntax failures', () => {
    const failure = createTestFailure({ category: 'syntax' });
    const suggestion = generateSuggestion(failure);

    expect(suggestion).toContain('syntax');
  });

  it('should generate suggestion for type failures', () => {
    const failure = createTestFailure({ category: 'type' });
    const suggestion = generateSuggestion(failure);

    expect(suggestion).toContain('type');
  });

  it('should generate suggestion for network failures', () => {
    const failure = createTestFailure({ category: 'network' });
    const suggestion = generateSuggestion(failure);

    expect(suggestion).toContain('network');
  });

  it('should generate suggestion for timeout failures', () => {
    const failure = createTestFailure({ category: 'timeout' });
    const suggestion = generateSuggestion(failure);

    expect(suggestion).toContain('timeout');
  });

  it('should generate suggestion for validation failures', () => {
    const failure = createTestFailure({ category: 'validation' });
    const suggestion = generateSuggestion(failure);

    expect(suggestion).toContain('input');
  });

  it('should generate suggestion for resource failures', () => {
    const failure = createTestFailure({ category: 'resource' });
    const suggestion = generateSuggestion(failure);

    expect(suggestion).toContain('resource');
  });

  it('should generate suggestion for logic failures', () => {
    const failure = createTestFailure({ category: 'logic' });
    const suggestion = generateSuggestion(failure);

    expect(suggestion).toContain('logic');
  });

  it('should generate generic suggestion for unknown failures', () => {
    const failure = createTestFailure({ category: 'unknown' });
    const suggestion = generateSuggestion(failure);

    expect(suggestion).toContain('Analyze');
  });

  it('should generate suggestion for runtime failures (default case)', () => {
    const failure = createTestFailure({ category: 'runtime' });
    const suggestion = generateSuggestion(failure);

    expect(suggestion).toBeDefined();
  });
});

// =============================================================================
// TESTS: FailureTracker
// =============================================================================

describe('FailureTracker', () => {
  let tracker: FailureTracker;

  beforeEach(() => {
    tracker = createFailureTracker({
      maxFailures: 10,
      preserveStackTraces: true,
      categorizeErrors: true,
      detectRepeats: true,
      repeatWarningThreshold: 3,
    });
  });

  describe('initialization', () => {
    it('should create tracker with default config', () => {
      const t = createFailureTracker();
      expect(t).toBeInstanceOf(FailureTracker);
    });

    it('should create tracker with custom config', () => {
      const t = createFailureTracker({ maxFailures: 5 });
      expect(t).toBeInstanceOf(FailureTracker);
    });
  });

  describe('recordFailure', () => {
    it('should record a basic failure', () => {
      const failure = tracker.recordFailure({
        action: 'read_file',
        error: 'File not found',
      });

      expect(failure.id).toBeDefined();
      expect(failure.action).toBe('read_file');
      expect(failure.error).toBe('File not found');
      expect(failure.resolved).toBe(false);
    });

    it('should record failure with args', () => {
      const failure = tracker.recordFailure({
        action: 'read_file',
        args: { path: '/test/file.txt' },
        error: 'File not found',
      });

      expect(failure.args).toEqual({ path: '/test/file.txt' });
    });

    it('should record failure with iteration and intent', () => {
      const failure = tracker.recordFailure({
        action: 'read_file',
        error: 'File not found',
        iteration: 5,
        intent: 'Read configuration',
      });

      expect(failure.iteration).toBe(5);
      expect(failure.intent).toBe('Read configuration');
    });

    it('should handle Error objects', () => {
      const error = new Error('Something went wrong');
      error.stack = 'Error: Something went wrong\n    at test.js:1:1';

      const failure = tracker.recordFailure({
        action: 'test_action',
        error,
      });

      expect(failure.error).toBe('Something went wrong');
      expect(failure.stackTrace).toContain('at test.js:1:1');
    });

    it('should auto-categorize errors when enabled', () => {
      const failure = tracker.recordFailure({
        action: 'read_file',
        error: 'Permission denied',
      });

      expect(failure.category).toBe('permission');
    });

    it('should use provided category over auto-categorization', () => {
      const failure = tracker.recordFailure({
        action: 'read_file',
        error: 'Permission denied',
        category: 'logic',
      });

      expect(failure.category).toBe('logic');
    });

    it('should not auto-categorize when disabled', () => {
      const t = createFailureTracker({ categorizeErrors: false });

      const failure = t.recordFailure({
        action: 'read_file',
        error: 'Permission denied',
      });

      expect(failure.category).toBe('unknown');
    });

    it('should generate suggestion for failure', () => {
      const failure = tracker.recordFailure({
        action: 'read_file',
        error: 'Permission denied',
      });

      expect(failure.suggestion).toBeDefined();
      expect(failure.suggestion.length).toBeGreaterThan(0);
    });

    it('should set timestamp', () => {
      const before = new Date().toISOString();
      const failure = tracker.recordFailure({
        action: 'test',
        error: 'error',
      });
      const after = new Date().toISOString();

      expect(failure.timestamp >= before).toBe(true);
      expect(failure.timestamp <= after).toBe(true);
    });
  });

  describe('repeat detection', () => {
    it('should detect repeated failures', () => {
      tracker.recordFailure({
        action: 'read_file',
        error: 'Permission denied',
      });

      const second = tracker.recordFailure({
        action: 'read_file',
        error: 'Permission denied',
      });

      expect(second.repeatCount).toBe(2);
    });

    it('should track repeat count across multiple failures', () => {
      for (let i = 0; i < 5; i++) {
        tracker.recordFailure({
          action: 'read_file',
          error: 'Permission denied',
        });
      }

      const failures = tracker.getFailuresByAction('read_file');
      expect(failures[failures.length - 1].repeatCount).toBe(5);
    });

    it('should not count different actions as repeats', () => {
      tracker.recordFailure({
        action: 'read_file',
        error: 'Permission denied',
      });

      const second = tracker.recordFailure({
        action: 'write_file',
        error: 'Permission denied',
      });

      expect(second.repeatCount).toBe(1);
    });

    it('should not count different errors as repeats', () => {
      tracker.recordFailure({
        action: 'read_file',
        error: 'Permission denied',
      });

      const second = tracker.recordFailure({
        action: 'read_file',
        error: 'File not found',
      });

      expect(second.repeatCount).toBe(1);
    });

    it('should not detect repeats when disabled', () => {
      const t = createFailureTracker({ detectRepeats: false });

      t.recordFailure({
        action: 'read_file',
        error: 'Permission denied',
      });

      const second = t.recordFailure({
        action: 'read_file',
        error: 'Permission denied',
      });

      expect(second.repeatCount).toBe(1);
    });
  });

  describe('max failures eviction', () => {
    it('should evict oldest failures when max is reached', () => {
      const t = createFailureTracker({ maxFailures: 3 });

      // Suppress console.warn for this test
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

      t.recordFailure({ action: 'action1', error: 'error1' });
      t.recordFailure({ action: 'action2', error: 'error2' });
      t.recordFailure({ action: 'action3', error: 'error3' });
      t.recordFailure({ action: 'action4', error: 'error4' });

      const recent = t.getRecentFailures(10);
      expect(recent.length).toBe(3);
      expect(recent[0].action).toBe('action2');
      expect(recent[2].action).toBe('action4');

      warnSpy.mockRestore();
    });

    it('should emit eviction event when evicting', () => {
      const t = createFailureTracker({ maxFailures: 2 });

      // Suppress console.warn for this test
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

      const events: FailureEvent[] = [];
      t.on((event) => events.push(event));

      t.recordFailure({ action: 'action1', error: 'error1' });
      t.recordFailure({ action: 'action2', error: 'error2' });
      t.recordFailure({ action: 'action3', error: 'error3' });

      const evictionEvents = events.filter(e => e.type === 'failure.evicted');
      expect(evictionEvents.length).toBe(1);
      expect(evictionEvents[0].type === 'failure.evicted' && evictionEvents[0].failure.action).toBe('action1');

      warnSpy.mockRestore();
    });
  });

  describe('event emission', () => {
    it('should emit failure.recorded event', () => {
      const events: FailureEvent[] = [];
      tracker.on((event) => events.push(event));

      tracker.recordFailure({ action: 'test', error: 'error' });

      expect(events.some(e => e.type === 'failure.recorded')).toBe(true);
    });

    it('should emit failure.repeated event when threshold is reached', () => {
      const events: FailureEvent[] = [];
      tracker.on((event) => events.push(event));

      for (let i = 0; i < 3; i++) {
        tracker.recordFailure({ action: 'test', error: 'same error' });
      }

      const repeatedEvents = events.filter(e => e.type === 'failure.repeated');
      expect(repeatedEvents.length).toBe(1);
      expect(repeatedEvents[0].type === 'failure.repeated' && repeatedEvents[0].count).toBe(3);
    });

    it('should emit pattern.detected for repeated actions', () => {
      const events: FailureEvent[] = [];
      tracker.on((event) => events.push(event));

      for (let i = 0; i < 4; i++) {
        tracker.recordFailure({ action: 'failing_action', error: `error ${i}` });
      }

      const patternEvents = events.filter(e => e.type === 'pattern.detected');
      expect(patternEvents.length).toBeGreaterThan(0);
    });

    it('should allow unsubscribing from events', () => {
      const events: FailureEvent[] = [];
      const unsubscribe = tracker.on((event) => events.push(event));

      tracker.recordFailure({ action: 'test1', error: 'error1' });
      unsubscribe();
      tracker.recordFailure({ action: 'test2', error: 'error2' });

      expect(events.length).toBe(1);
    });

    it('should handle listener errors gracefully', () => {
      tracker.on(() => {
        throw new Error('Listener error');
      });

      // Should not throw
      expect(() => {
        tracker.recordFailure({ action: 'test', error: 'error' });
      }).not.toThrow();
    });
  });

  describe('resolveFailure', () => {
    it('should mark failure as resolved', () => {
      const failure = tracker.recordFailure({ action: 'test', error: 'error' });

      const result = tracker.resolveFailure(failure.id);

      expect(result).toBe(true);
      expect(tracker.getUnresolvedFailures().length).toBe(0);
    });

    it('should return false for non-existent failure', () => {
      const result = tracker.resolveFailure('non-existent-id');
      expect(result).toBe(false);
    });

    it('should emit failure.resolved event', () => {
      const events: FailureEvent[] = [];
      tracker.on((event) => events.push(event));

      const failure = tracker.recordFailure({ action: 'test', error: 'error' });
      tracker.resolveFailure(failure.id);

      expect(events.some(e => e.type === 'failure.resolved')).toBe(true);
    });
  });

  describe('getUnresolvedFailures', () => {
    it('should return only unresolved failures', () => {
      const f1 = tracker.recordFailure({ action: 'test1', error: 'error1' });
      tracker.recordFailure({ action: 'test2', error: 'error2' });

      tracker.resolveFailure(f1.id);

      const unresolved = tracker.getUnresolvedFailures();
      expect(unresolved.length).toBe(1);
      expect(unresolved[0].action).toBe('test2');
    });
  });

  describe('getFailuresByCategory', () => {
    it('should filter failures by category', () => {
      tracker.recordFailure({ action: 'test', error: 'Permission denied' });
      tracker.recordFailure({ action: 'test', error: 'File not found' });
      tracker.recordFailure({ action: 'test', error: 'Access denied' });

      const permissionFailures = tracker.getFailuresByCategory('permission');
      expect(permissionFailures.length).toBe(2);
    });

    it('should return empty array for category with no failures', () => {
      tracker.recordFailure({ action: 'test', error: 'Permission denied' });

      const networkFailures = tracker.getFailuresByCategory('network');
      expect(networkFailures.length).toBe(0);
    });
  });

  describe('getFailuresByAction', () => {
    it('should filter failures by action', () => {
      tracker.recordFailure({ action: 'read_file', error: 'error1' });
      tracker.recordFailure({ action: 'write_file', error: 'error2' });
      tracker.recordFailure({ action: 'read_file', error: 'error3' });

      const readFailures = tracker.getFailuresByAction('read_file');
      expect(readFailures.length).toBe(2);
    });

    it('should return empty array for action with no failures', () => {
      tracker.recordFailure({ action: 'read_file', error: 'error' });

      const deleteFailures = tracker.getFailuresByAction('delete_file');
      expect(deleteFailures.length).toBe(0);
    });
  });

  describe('getRecentFailures', () => {
    it('should return last N failures', () => {
      for (let i = 0; i < 5; i++) {
        tracker.recordFailure({ action: `action${i}`, error: `error${i}` });
      }

      const recent = tracker.getRecentFailures(3);
      expect(recent.length).toBe(3);
      expect(recent[0].action).toBe('action2');
      expect(recent[2].action).toBe('action4');
    });

    it('should return all failures if count exceeds total', () => {
      tracker.recordFailure({ action: 'action1', error: 'error1' });
      tracker.recordFailure({ action: 'action2', error: 'error2' });

      const recent = tracker.getRecentFailures(10);
      expect(recent.length).toBe(2);
    });

    it('should use default count of 10', () => {
      for (let i = 0; i < 15; i++) {
        tracker.recordFailure({ action: `action${i}`, error: `error${i}` });
      }

      const recent = tracker.getRecentFailures();
      expect(recent.length).toBeLessThanOrEqual(10);
    });
  });

  describe('getFailureContext', () => {
    it('should format failure context for LLM', () => {
      tracker.recordFailure({ action: 'read_file', error: 'Permission denied' });

      const context = tracker.getFailureContext();

      expect(context).toContain('read_file');
      expect(context).toContain('Permission denied');
    });

    it('should return empty string when no failures', () => {
      const context = tracker.getFailureContext();
      expect(context).toBe('');
    });

    it('should exclude resolved failures by default', () => {
      const f1 = tracker.recordFailure({ action: 'resolved_action', error: 'error1' });
      tracker.recordFailure({ action: 'pending_action', error: 'error2' });
      tracker.resolveFailure(f1.id);

      const context = tracker.getFailureContext();

      expect(context).not.toContain('resolved_action');
      expect(context).toContain('pending_action');
    });

    it('should include resolved failures when requested', () => {
      const f1 = tracker.recordFailure({ action: 'resolved_action', error: 'error1' });
      tracker.recordFailure({ action: 'pending_action', error: 'error2' });
      tracker.resolveFailure(f1.id);

      const context = tracker.getFailureContext({ includeResolved: true });

      expect(context).toContain('resolved_action');
      expect(context).toContain('pending_action');
    });

    it('should limit failures when specified', () => {
      for (let i = 0; i < 10; i++) {
        tracker.recordFailure({ action: `action${i}`, error: `error${i}` });
      }

      const context = tracker.getFailureContext({ maxFailures: 3 });

      // Should only contain last 3
      expect(context).toContain('action7');
      expect(context).toContain('action8');
      expect(context).toContain('action9');
      expect(context).not.toContain('action0');
    });

    it('should include stack traces when requested', () => {
      const error = new Error('Test error');
      error.stack = 'Error: Test error\n    at test.js:1:1\n    at another.js:2:2';

      tracker.recordFailure({ action: 'test', error });

      const context = tracker.getFailureContext({ includeStackTraces: true });

      expect(context).toContain('Stack:');
    });
  });

  describe('hasRecentFailure', () => {
    it('should return true if action failed recently', () => {
      tracker.recordFailure({ action: 'read_file', error: 'error' });

      expect(tracker.hasRecentFailure('read_file')).toBe(true);
    });

    it('should return false if action has not failed', () => {
      tracker.recordFailure({ action: 'read_file', error: 'error' });

      expect(tracker.hasRecentFailure('write_file')).toBe(false);
    });

    it('should respect time window', async () => {
      tracker.recordFailure({ action: 'read_file', error: 'error' });

      // Check with very short window - failure should be "recent" still
      expect(tracker.hasRecentFailure('read_file', 1000)).toBe(true);
    });
  });

  describe('getStats', () => {
    it('should return failure statistics', () => {
      tracker.recordFailure({ action: 'read_file', error: 'Permission denied' });
      tracker.recordFailure({ action: 'read_file', error: 'File not found' });
      tracker.recordFailure({ action: 'write_file', error: 'Permission denied' });

      const stats = tracker.getStats();

      expect(stats.total).toBe(3);
      expect(stats.unresolved).toBe(3);
      expect(stats.byCategory.permission).toBe(2);
      expect(stats.byCategory.not_found).toBe(1);
    });

    it('should track most failed actions', () => {
      for (let i = 0; i < 5; i++) {
        tracker.recordFailure({ action: 'failing_action', error: `error${i}` });
      }
      tracker.recordFailure({ action: 'other_action', error: 'error' });

      const stats = tracker.getStats();

      expect(stats.mostFailedActions[0].action).toBe('failing_action');
      expect(stats.mostFailedActions[0].count).toBe(5);
    });

    it('should update unresolved count when failures are resolved', () => {
      const f1 = tracker.recordFailure({ action: 'test', error: 'error' });
      tracker.recordFailure({ action: 'test2', error: 'error' });
      tracker.resolveFailure(f1.id);

      const stats = tracker.getStats();
      expect(stats.total).toBe(2);
      expect(stats.unresolved).toBe(1);
    });
  });

  describe('clear', () => {
    it('should remove all failures', () => {
      tracker.recordFailure({ action: 'test', error: 'error' });
      tracker.recordFailure({ action: 'test2', error: 'error2' });

      tracker.clear();

      expect(tracker.getRecentFailures().length).toBe(0);
      expect(tracker.getStats().total).toBe(0);
    });

    it('should clear action history', () => {
      tracker.recordFailure({ action: 'test', error: 'error' });
      tracker.clear();

      const failures = tracker.getFailuresByAction('test');
      expect(failures.length).toBe(0);
    });
  });
});

// =============================================================================
// TESTS: Utility Functions
// =============================================================================

describe('formatFailureContext', () => {
  it('should format failures as context', () => {
    const failures = [
      createTestFailure({ action: 'read_file', error: 'Permission denied', category: 'permission' }),
    ];

    const context = formatFailureContext(failures);

    expect(context).toContain('[Previous Failures');
    expect(context).toContain('read_file');
    expect(context).toContain('permission');
  });

  it('should include args when present', () => {
    const failures = [
      createTestFailure({
        action: 'read_file',
        error: 'error',
        args: { path: '/test/path' },
      }),
    ];

    const context = formatFailureContext(failures);

    expect(context).toContain('/test/path');
  });

  it('should include suggestions', () => {
    const failures = [
      createTestFailure({
        action: 'read_file',
        error: 'error',
        suggestion: 'Try a different approach',
      }),
    ];

    const context = formatFailureContext(failures);

    expect(context).toContain('Try a different approach');
  });

  it('should include stack traces when requested', () => {
    const failures = [
      createTestFailure({
        action: 'read_file',
        error: 'error',
        stackTrace: 'Error: test\n    at file.js:1:1\n    at another.js:2:2\n    at third.js:3:3\n    at fourth.js:4:4',
      }),
    ];

    const context = formatFailureContext(failures, { includeStackTraces: true });

    expect(context).toContain('Stack:');
    expect(context).toContain('file.js:1:1');
  });

  it('should return empty string for empty array', () => {
    const context = formatFailureContext([]);
    expect(context).toBe('');
  });
});

describe('createRepeatWarning', () => {
  it('should create warning for repeated action', () => {
    const warning = createRepeatWarning('read_file', 3);

    expect(warning).toContain('read_file');
    expect(warning).toContain('3 times');
  });

  it('should include review suggestion for count >= 3', () => {
    const warning = createRepeatWarning('read_file', 3);

    expect(warning).toContain('Review');
  });

  it('should include different approach suggestion for count >= 5', () => {
    const warning = createRepeatWarning('read_file', 5);

    expect(warning).toContain('different approach');
  });

  it('should include provided suggestion', () => {
    const warning = createRepeatWarning('read_file', 3, 'Check permissions');

    expect(warning).toContain('Check permissions');
  });
});

describe('extractInsights', () => {
  it('should extract insights for multiple permission errors', () => {
    const failures = [
      createTestFailure({ category: 'permission' }),
      createTestFailure({ category: 'permission' }),
    ];

    const insights = extractInsights(failures);

    expect(insights.some(i => i.includes('permission'))).toBe(true);
  });

  it('should extract insights for multiple not_found errors', () => {
    const failures = [
      createTestFailure({ category: 'not_found' }),
      createTestFailure({ category: 'not_found' }),
    ];

    const insights = extractInsights(failures);

    expect(insights.some(i => i.includes('not-found'))).toBe(true);
  });

  it('should extract insights for multiple syntax errors', () => {
    const failures = [
      createTestFailure({ category: 'syntax' }),
      createTestFailure({ category: 'syntax' }),
    ];

    const insights = extractInsights(failures);

    expect(insights.some(i => i.includes('syntax'))).toBe(true);
  });

  it('should extract insights for network errors', () => {
    const failures = [
      createTestFailure({ category: 'network' }),
    ];

    const insights = extractInsights(failures);

    expect(insights.some(i => i.includes('Network'))).toBe(true);
  });

  it('should extract insights for timeout errors', () => {
    const failures = [
      createTestFailure({ category: 'timeout' }),
    ];

    const insights = extractInsights(failures);

    expect(insights.some(i => i.includes('Timeout'))).toBe(true);
  });

  it('should extract insights for repeated action failures', () => {
    const failures = [
      createTestFailure({ action: 'failing_action' }),
      createTestFailure({ action: 'failing_action' }),
      createTestFailure({ action: 'failing_action' }),
    ];

    const insights = extractInsights(failures);

    expect(insights.some(i => i.includes('failing_action') && i.includes('3 times'))).toBe(true);
  });

  it('should return empty array when no patterns found', () => {
    const failures = [
      createTestFailure({ category: 'unknown', action: 'action1' }),
    ];

    const insights = extractInsights(failures);

    expect(insights.length).toBe(0);
  });
});

describe('formatFailureStats', () => {
  it('should format stats for display', () => {
    const stats = {
      total: 10,
      unresolved: 5,
      byCategory: {
        permission: 3,
        not_found: 2,
        syntax: 0,
        type: 0,
        runtime: 0,
        network: 0,
        timeout: 0,
        validation: 0,
        logic: 0,
        resource: 0,
        unknown: 5,
      },
      mostFailedActions: [
        { action: 'read_file', count: 5 },
        { action: 'write_file', count: 3 },
      ],
    };

    const formatted = formatFailureStats(stats);

    expect(formatted).toContain('Total: 10');
    expect(formatted).toContain('5 unresolved');
    expect(formatted).toContain('permission: 3');
    expect(formatted).toContain('not_found: 2');
    expect(formatted).toContain('read_file: 5');
  });

  it('should not show categories with zero count', () => {
    const stats = {
      total: 1,
      unresolved: 1,
      byCategory: {
        permission: 1,
        not_found: 0,
        syntax: 0,
        type: 0,
        runtime: 0,
        network: 0,
        timeout: 0,
        validation: 0,
        logic: 0,
        resource: 0,
        unknown: 0,
      },
      mostFailedActions: [],
    };

    const formatted = formatFailureStats(stats);

    expect(formatted).toContain('permission: 1');
    expect(formatted).not.toContain('not_found:');
  });
});

// =============================================================================
// TESTS: Pattern Detection
// =============================================================================

describe('Pattern Detection', () => {
  let tracker: FailureTracker;

  beforeEach(() => {
    tracker = createFailureTracker({
      detectRepeats: true,
      repeatWarningThreshold: 2,
    });
  });

  it('should detect repeated_action pattern', () => {
    const events: FailureEvent[] = [];
    tracker.on((event) => events.push(event));

    // Same action failing multiple times
    for (let i = 0; i < 4; i++) {
      tracker.recordFailure({ action: 'stubborn_action', error: `error ${i}` });
    }

    const patterns = events.filter(
      e => e.type === 'pattern.detected' && e.pattern.type === 'repeated_action'
    );

    expect(patterns.length).toBeGreaterThan(0);
  });

  it('should detect category_cluster pattern', () => {
    const events: FailureEvent[] = [];
    tracker.on((event) => events.push(event));

    // Many permission errors in sequence
    for (let i = 0; i < 6; i++) {
      tracker.recordFailure({ action: `action${i}`, error: 'Permission denied' });
    }

    const patterns = events.filter(
      e => e.type === 'pattern.detected' && e.pattern.type === 'category_cluster'
    );

    expect(patterns.length).toBeGreaterThan(0);
  });

  it('should include failure IDs in pattern', () => {
    const events: FailureEvent[] = [];
    tracker.on((event) => events.push(event));

    for (let i = 0; i < 4; i++) {
      tracker.recordFailure({ action: 'failing_action', error: 'error' });
    }

    const pattern = events.find(
      e => e.type === 'pattern.detected' && e.pattern.type === 'repeated_action'
    );

    expect(pattern).toBeDefined();
    if (pattern && pattern.type === 'pattern.detected') {
      expect(pattern.pattern.failureIds.length).toBeGreaterThan(0);
    }
  });

  it('should include suggestion in pattern', () => {
    const events: FailureEvent[] = [];
    tracker.on((event) => events.push(event));

    for (let i = 0; i < 4; i++) {
      tracker.recordFailure({ action: 'failing_action', error: 'error' });
    }

    const pattern = events.find(
      e => e.type === 'pattern.detected' && e.pattern.type === 'repeated_action'
    );

    expect(pattern).toBeDefined();
    if (pattern && pattern.type === 'pattern.detected') {
      expect(pattern.pattern.suggestion).toBeDefined();
      expect(pattern.pattern.suggestion.length).toBeGreaterThan(0);
    }
  });
});
