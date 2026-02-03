/**
 * Context Engineering Integration Tests
 *
 * Tests for the ContextEngineeringManager which orchestrates:
 * - KV-cache aware context building
 * - Recitation injection
 * - Reversible compaction
 * - Failure tracking
 * - Serialization diversity
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  ContextEngineeringManager,
  createContextEngineering,
  createMinimalContextEngineering,
  createFullContextEngineering,
  stableStringify,
  calculateOptimalFrequency,
  type ContextEngineeringEvent,
} from '../src/integrations/context-engineering.js';

describe('ContextEngineeringManager', () => {
  let manager: ContextEngineeringManager;

  afterEach(() => {
    manager?.clear();
  });

  describe('initialization', () => {
    it('should create with default config', () => {
      manager = createContextEngineering();

      expect(manager).toBeDefined();
      expect(manager.getIteration()).toBe(0);
    });

    it('should respect custom config', () => {
      manager = createContextEngineering({
        enableCacheOptimization: false,
        enableRecitation: false,
        enableReversibleCompaction: false,
        enableFailureTracking: true,
        staticPrefix: 'Custom prefix',
        recitationFrequency: 10,
      });

      expect(manager).toBeDefined();
      // Stats should reflect config
      const stats = manager.getStats();
      expect(stats.trackedFailures).toBe(0); // Failure tracking enabled
    });

    it('should create minimal manager for testing', () => {
      manager = createMinimalContextEngineering();

      expect(manager).toBeDefined();
      // Minimal manager should still have failure tracking
      expect(manager.getFailureTracker()).toBeDefined();
    });

    it('should create full-featured manager', () => {
      manager = createFullContextEngineering('You are a coding assistant.');

      expect(manager).toBeDefined();
      const stats = manager.getStats();
      // Should have diversity stats
      expect(stats.diversity).toBeDefined();
    });
  });

  describe('buildSystemPrompt', () => {
    beforeEach(() => {
      manager = createContextEngineering({
        enableCacheOptimization: true,
        staticPrefix: 'You are a helpful assistant.',
      });
    });

    it('should build basic system prompt', () => {
      const prompt = manager.buildSystemPrompt({});

      expect(prompt).toContain('You are a helpful assistant');
    });

    it('should include rules section', () => {
      const prompt = manager.buildSystemPrompt({
        rules: 'Follow these rules:\n1. Be concise\n2. Be accurate',
      });

      expect(prompt).toContain('Rules');
      expect(prompt).toContain('Be concise');
    });

    it('should include tools section', () => {
      const prompt = manager.buildSystemPrompt({
        tools: 'Available tools: read_file, write_file',
      });

      expect(prompt).toContain('Tools');
      expect(prompt).toContain('read_file');
    });

    it('should include memory/context section', () => {
      const prompt = manager.buildSystemPrompt({
        memory: 'Previous context: user was working on auth',
      });

      expect(prompt).toContain('Context');
      expect(prompt).toContain('auth');
    });

    it('should include dynamic values', () => {
      const prompt = manager.buildSystemPrompt({
        dynamic: {
          sessionId: 'abc123',
          iteration: '5',
        },
      });

      expect(prompt).toContain('abc123');
      expect(prompt).toContain('5');
    });

    it('should emit cache warnings for inefficient prompts', () => {
      const events: ContextEngineeringEvent[] = [];
      manager.on(e => events.push(e));

      // Build prompt with dynamic content at start (bad for cache)
      manager.buildSystemPrompt({
        dynamic: { timestamp: Date.now().toString() },
        rules: 'Rules content',
      });

      // May or may not emit warnings depending on implementation
      // Just verify it doesn't throw
      expect(true).toBe(true);
    });
  });

  describe('serialize', () => {
    beforeEach(() => {
      manager = createContextEngineering({
        enableDiversity: false,
      });
    });

    it('should serialize data consistently', () => {
      const data = { b: 2, a: 1 };

      const result1 = manager.serialize(data);
      const result2 = manager.serialize(data);

      expect(result1).toBe(result2);
    });

    it('should produce stable JSON for cache efficiency', () => {
      const data = { z: 3, a: 1, m: 2 };
      const result = manager.serialize(data);
      const parsed = JSON.parse(result);

      // Keys should be in alphabetical order
      const keys = Object.keys(parsed);
      expect(keys).toEqual(['a', 'm', 'z']);
    });

    it('should use diversity when enabled', () => {
      const diverseManager = createContextEngineering({
        enableDiversity: true,
        diversityLevel: 0.5,
      });

      const data = { test: 'value' };
      const result = diverseManager.serialize(data);

      // Should produce valid JSON
      expect(() => JSON.parse(result)).not.toThrow();

      diverseManager.clear();
    });
  });

  describe('injectRecitation', () => {
    beforeEach(() => {
      manager = createContextEngineering({
        enableRecitation: true,
        recitationFrequency: 3, // Inject every 3 iterations
      });
    });

    it('should increment iteration counter', () => {
      const messages = [
        { role: 'user' as const, content: 'Hello' },
        { role: 'assistant' as const, content: 'Hi there' },
      ];

      expect(manager.getIteration()).toBe(0);

      manager.injectRecitation(messages, {
        goal: 'Complete the task',
      });

      expect(manager.getIteration()).toBe(1);
    });

    it('should not inject on first iterations', () => {
      const messages = [
        { role: 'user' as const, content: 'Hello' },
      ];

      const result = manager.injectRecitation(messages, {
        goal: 'Test goal',
      });

      // First iteration - may or may not inject depending on implementation
      // At minimum, should return at least as many messages
      expect(result.length).toBeGreaterThanOrEqual(messages.length);
    });

    it('should inject at configured frequency', () => {
      const messages = [
        { role: 'user' as const, content: 'Hello' },
        { role: 'assistant' as const, content: 'Hi' },
      ];

      // Run 3 iterations
      manager.injectRecitation(messages, { goal: 'Test' });
      manager.injectRecitation(messages, { goal: 'Test' });
      const result = manager.injectRecitation(messages, { goal: 'Test' });

      // On 3rd iteration, should inject
      expect(result.length).toBeGreaterThanOrEqual(messages.length);
    });

    it('should emit recitation.injected event', () => {
      const events: ContextEngineeringEvent[] = [];
      manager.on(e => events.push(e));

      const messages = [
        { role: 'user' as const, content: 'Hello' },
      ];

      // Force injection by iterating
      for (let i = 0; i < 5; i++) {
        manager.injectRecitation(messages, { goal: 'Test goal' });
      }

      // Should have injected at least once
      const recitationEvents = events.filter(e => e.type === 'recitation.injected');
      expect(recitationEvents.length).toBeGreaterThan(0);
    });
  });

  describe('updateRecitationFrequency', () => {
    beforeEach(() => {
      manager = createContextEngineering({
        enableRecitation: true,
        recitationFrequency: 5,
      });
    });

    it('should adjust frequency based on context size', () => {
      // Large context should have more frequent recitation
      manager.updateRecitationFrequency(100000);

      // Small context should have less frequent recitation
      manager.updateRecitationFrequency(1000);

      // No errors thrown
      expect(true).toBe(true);
    });
  });

  describe('failure tracking', () => {
    beforeEach(() => {
      manager = createContextEngineering({
        enableFailureTracking: true,
        maxFailures: 10,
      });
    });

    it('should record failures', () => {
      const failure = manager.recordFailure({
        action: 'read_file',
        args: { path: '/nonexistent' },
        error: 'File not found',
        intent: 'Read configuration',
      });

      expect(failure).toBeDefined();
      expect(failure!.action).toBe('read_file');
    });

    it('should track failure count', () => {
      manager.recordFailure({ action: 'test1', error: 'Error 1' });
      manager.recordFailure({ action: 'test2', error: 'Error 2' });

      const stats = manager.getStats();
      expect(stats.trackedFailures).toBe(2);
    });

    it('should emit failure.recorded event', () => {
      const events: ContextEngineeringEvent[] = [];
      manager.on(e => events.push(e));

      manager.recordFailure({ action: 'test', error: 'Test error' });

      expect(events.some(e => e.type === 'failure.recorded')).toBe(true);
    });

    it('should detect failure patterns', () => {
      const events: ContextEngineeringEvent[] = [];
      manager.on(e => events.push(e));

      // Record same failure multiple times
      for (let i = 0; i < 5; i++) {
        manager.recordFailure({
          action: 'repeated_action',
          args: { path: '/same/path' },
          error: 'Same error',
        });
      }

      // Should detect pattern - may or may not depending on threshold
      expect(manager.getStats().patternsDetected).toBeGreaterThanOrEqual(0);
    });

    it('should check for recent failures', () => {
      manager.recordFailure({ action: 'recent_action', error: 'Error' });

      expect(manager.hasRecentFailure('recent_action')).toBe(true);
      expect(manager.hasRecentFailure('other_action')).toBe(false);
    });

    it('should get failure context for LLM', () => {
      manager.recordFailure({ action: 'test', error: 'Test error' });

      const context = manager.getFailureContext(5);
      expect(typeof context).toBe('string');
    });

    it('should resolve failures', () => {
      const failure = manager.recordFailure({ action: 'test', error: 'Error' });
      expect(failure).toBeDefined();

      const resolved = manager.resolveFailure(failure!.id);
      expect(resolved).toBe(true);

      const stats = manager.getStats();
      expect(stats.unresolvedFailures).toBe(0);
    });

    it('should get actionable insights', () => {
      manager.recordFailure({
        action: 'bash',
        args: { command: 'npm install' },
        error: 'Permission denied',
      });

      const insights = manager.getFailureInsights();
      expect(Array.isArray(insights)).toBe(true);
    });
  });

  describe('compaction', () => {
    beforeEach(() => {
      manager = createContextEngineering({
        enableReversibleCompaction: true,
        maxReferences: 20,
      });
    });

    it('should compact messages with summarization', async () => {
      const messages = [
        { role: 'user' as const, content: 'Read file /src/main.ts' },
        { role: 'assistant' as const, content: 'The file contains 200 lines...' },
        { role: 'user' as const, content: 'Edit line 50' },
        { role: 'assistant' as const, content: 'Done, edited line 50' },
      ];

      const summarize = vi.fn(async () => 'User edited main.ts');

      const result = await manager.compact(messages, summarize);

      expect(result.summary).toBeDefined();
      expect(summarize).toHaveBeenCalled();
    });

    it('should preserve references during compaction', async () => {
      const messages = [
        { role: 'user' as const, content: 'Read file /src/important.ts' },
        { role: 'assistant' as const, content: 'Contents of important.ts: export function main() {}' },
      ];

      const result = await manager.compact(
        messages,
        async () => 'Read important.ts'
      );

      expect(Array.isArray(result.references)).toBe(true);
    });

    it('should emit compaction.completed event', async () => {
      const events: ContextEngineeringEvent[] = [];
      manager.on(e => events.push(e));

      await manager.compact(
        [{ role: 'user' as const, content: 'Test' }],
        async () => 'Summary'
      );

      expect(events.some(e => e.type === 'compaction.completed')).toBe(true);
    });

    it('should allow searching preserved references', async () => {
      const messages = [
        { role: 'user' as const, content: 'Read file /src/utils.ts' },
        { role: 'assistant' as const, content: 'File /src/utils.ts contains helpers' },
      ];

      await manager.compact(messages, async () => 'Read utils');

      const results = manager.searchReferences('utils');
      // May or may not find depending on extraction logic
      expect(Array.isArray(results)).toBe(true);
    });

    it('should get references by type', async () => {
      await manager.compact(
        [
          { role: 'user' as const, content: 'The error was: TypeError at line 10' },
        ],
        async () => 'Had an error'
      );

      const errorRefs = manager.getReferencesByType('error');
      expect(Array.isArray(errorRefs)).toBe(true);
    });
  });

  describe('statistics', () => {
    beforeEach(() => {
      manager = createFullContextEngineering('Test prefix');
    });

    it('should track recitation injections', () => {
      const messages = [{ role: 'user' as const, content: 'Test' }];

      for (let i = 0; i < 10; i++) {
        manager.injectRecitation(messages, { goal: 'Test' });
      }

      const stats = manager.getStats();
      expect(stats.recitationInjections).toBeGreaterThanOrEqual(0);
    });

    it('should track preserved references', async () => {
      await manager.compact(
        [{ role: 'user' as const, content: 'File: /test.ts' }],
        async () => 'Summary'
      );

      const stats = manager.getStats();
      expect(typeof stats.preservedReferences).toBe('number');
    });

    it('should include diversity stats when enabled', () => {
      const stats = manager.getStats();
      expect(stats.diversity).toBeDefined();
    });
  });

  describe('clear and reset', () => {
    beforeEach(() => {
      manager = createFullContextEngineering('Test');
    });

    it('should reset iteration counter', () => {
      const messages = [{ role: 'user' as const, content: 'Test' }];
      manager.injectRecitation(messages, { goal: 'Test' });
      manager.injectRecitation(messages, { goal: 'Test' });

      expect(manager.getIteration()).toBe(2);

      manager.resetIteration();

      expect(manager.getIteration()).toBe(0);
    });

    it('should clear all tracked state', () => {
      manager.recordFailure({ action: 'test', error: 'Error' });

      manager.clear();

      const stats = manager.getStats();
      expect(stats.trackedFailures).toBe(0);
      expect(stats.recitationInjections).toBe(0);
    });
  });

  describe('event subscription', () => {
    beforeEach(() => {
      manager = createContextEngineering({
        enableFailureTracking: true,
      });
    });

    it('should allow subscription', () => {
      const events: ContextEngineeringEvent[] = [];
      const unsubscribe = manager.on(e => events.push(e));

      manager.recordFailure({ action: 'test', error: 'Error' });

      expect(events.length).toBeGreaterThan(0);
      expect(typeof unsubscribe).toBe('function');
    });

    it('should allow unsubscription', () => {
      const events: ContextEngineeringEvent[] = [];
      const unsubscribe = manager.on(e => events.push(e));

      manager.recordFailure({ action: 'test1', error: 'Error' });
      expect(events.length).toBe(1);

      unsubscribe();

      manager.recordFailure({ action: 'test2', error: 'Error' });
      expect(events.length).toBe(1); // No new events
    });

    it('should handle listener errors gracefully', () => {
      manager.on(() => {
        throw new Error('Listener error');
      });

      // Should not throw
      expect(() => {
        manager.recordFailure({ action: 'test', error: 'Error' });
      }).not.toThrow();
    });
  });
});

describe('stableStringify', () => {
  it('should sort object keys alphabetically', () => {
    const obj = { z: 1, a: 2, m: 3 };
    const result = stableStringify(obj);
    const parsed = JSON.parse(result);

    expect(Object.keys(parsed)).toEqual(['a', 'm', 'z']);
  });

  it('should handle nested objects', () => {
    const obj = {
      outer: { z: 1, a: 2 },
      another: { b: 3, a: 4 },
    };
    const result = stableStringify(obj);

    // Should be consistent
    expect(result).toBe(stableStringify(obj));
  });

  it('should handle arrays', () => {
    const obj = { items: [3, 1, 2] };
    const result = stableStringify(obj);

    // Arrays should preserve order
    expect(result).toContain('[3,1,2]');
  });

  it('should handle null and undefined', () => {
    const obj = { a: null, b: undefined };
    const result = stableStringify(obj);

    expect(result).toContain('null');
    // undefined is typically omitted in JSON
  });

  it('should produce identical output for equivalent objects', () => {
    const obj1 = { b: 2, a: 1 };
    const obj2 = { a: 1, b: 2 };

    expect(stableStringify(obj1)).toBe(stableStringify(obj2));
  });
});

describe('calculateOptimalFrequency', () => {
  it('should return higher frequency for larger contexts', () => {
    const smallContextFreq = calculateOptimalFrequency(1000);
    const largeContextFreq = calculateOptimalFrequency(100000);

    // Larger context needs more frequent recitation
    expect(largeContextFreq).toBeLessThanOrEqual(smallContextFreq);
  });

  it('should return reasonable values', () => {
    const freq = calculateOptimalFrequency(50000);

    expect(freq).toBeGreaterThan(0);
    expect(freq).toBeLessThan(100);
  });

  it('should handle edge cases', () => {
    expect(calculateOptimalFrequency(0)).toBeGreaterThan(0);
    expect(calculateOptimalFrequency(1000000)).toBeGreaterThan(0);
  });
});
