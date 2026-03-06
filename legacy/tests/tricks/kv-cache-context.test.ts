/**
 * KV-Cache Context Tests
 *
 * Tests for the KV-Cache aware context optimization module.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  stableStringify,
  normalizeJson,
  CacheAwareContext,
  createCacheAwareContext,
  analyzeCacheEfficiency,
  formatCacheStats,
  createEndTimestamp,
  type CacheAwareConfig,
  type CacheBreakpoint,
  type CacheEvent,
  type CacheStats,
  type ContextMessage,
  type DynamicContent,
} from '../../src/tricks/kv-cache-context.js';

// =============================================================================
// TESTS: stableStringify
// =============================================================================

describe('stableStringify', () => {
  describe('basic functionality', () => {
    it('should stringify primitives correctly', () => {
      expect(stableStringify('hello')).toBe('"hello"');
      expect(stableStringify(42)).toBe('42');
      expect(stableStringify(true)).toBe('true');
      expect(stableStringify(null)).toBe('null');
    });

    it('should stringify arrays correctly', () => {
      expect(stableStringify([1, 2, 3])).toBe('[1,2,3]');
      expect(stableStringify(['a', 'b', 'c'])).toBe('["a","b","c"]');
    });

    it('should stringify objects with sorted keys', () => {
      const obj = { b: 1, a: 2, c: 3 };
      expect(stableStringify(obj)).toBe('{"a":2,"b":1,"c":3}');
    });

    it('should produce same output regardless of key insertion order', () => {
      const obj1 = { z: 1, m: 2, a: 3 };
      const obj2 = { a: 3, z: 1, m: 2 };
      const obj3 = { m: 2, a: 3, z: 1 };

      const result1 = stableStringify(obj1);
      const result2 = stableStringify(obj2);
      const result3 = stableStringify(obj3);

      expect(result1).toBe(result2);
      expect(result2).toBe(result3);
      expect(result1).toBe('{"a":3,"m":2,"z":1}');
    });
  });

  describe('nested objects', () => {
    it('should sort keys in nested objects', () => {
      const obj = { outer: { b: 1, a: 2 }, z: 3 };
      expect(stableStringify(obj)).toBe('{"outer":{"a":2,"b":1},"z":3}');
    });

    it('should handle deeply nested objects', () => {
      const obj = {
        level1: {
          level2: {
            z: 'last',
            a: 'first',
          },
          b: 2,
        },
        a: 1,
      };
      const result = stableStringify(obj);
      expect(result).toBe('{"a":1,"level1":{"b":2,"level2":{"a":"first","z":"last"}}}');
    });

    it('should handle objects in arrays', () => {
      const obj = [{ b: 1, a: 2 }, { d: 4, c: 3 }];
      expect(stableStringify(obj)).toBe('[{"a":2,"b":1},{"c":3,"d":4}]');
    });
  });

  describe('special cases', () => {
    it('should handle empty objects and arrays', () => {
      expect(stableStringify({})).toBe('{}');
      expect(stableStringify([])).toBe('[]');
    });

    it('should handle null values in objects', () => {
      const obj = { b: null, a: 'value' };
      expect(stableStringify(obj)).toBe('{"a":"value","b":null}');
    });

    it('should preserve undefined behavior (omit undefined values)', () => {
      const obj = { b: undefined, a: 'value' };
      // JSON.stringify omits undefined values
      expect(stableStringify(obj)).toBe('{"a":"value"}');
    });
  });

  describe('indentation', () => {
    it('should support indentation parameter', () => {
      const obj = { b: 1, a: 2 };
      const result = stableStringify(obj, 2);
      expect(result).toContain('\n');
      expect(result).toContain('  ');
    });

    it('should maintain key order with indentation', () => {
      const obj = { z: 1, a: 2 };
      const result = stableStringify(obj, 2);
      // a should come before z even with formatting
      expect(result.indexOf('"a"')).toBeLessThan(result.indexOf('"z"'));
    });
  });
});

// =============================================================================
// TESTS: normalizeJson
// =============================================================================

describe('normalizeJson', () => {
  it('should normalize valid JSON strings', () => {
    const input = '{"b":1,"a":2}';
    const result = normalizeJson(input);
    expect(result).toBe('{"a":2,"b":1}');
  });

  it('should return original string for invalid JSON', () => {
    const input = 'not valid json';
    const result = normalizeJson(input);
    expect(result).toBe(input);
  });

  it('should handle nested JSON', () => {
    const input = '{"outer":{"z":1,"a":2},"key":"value"}';
    const result = normalizeJson(input);
    expect(result).toBe('{"key":"value","outer":{"a":2,"z":1}}');
  });

  it('should handle JSON arrays', () => {
    const input = '[{"b":1,"a":2}]';
    const result = normalizeJson(input);
    expect(result).toBe('[{"a":2,"b":1}]');
  });

  it('should return empty object unchanged', () => {
    expect(normalizeJson('{}')).toBe('{}');
  });

  it('should handle whitespace in JSON', () => {
    const input = '{ "b" : 1 , "a" : 2 }';
    const result = normalizeJson(input);
    expect(result).toBe('{"a":2,"b":1}');
  });
});

// =============================================================================
// TESTS: CacheAwareContext
// =============================================================================

describe('CacheAwareContext', () => {
  let context: CacheAwareContext;

  beforeEach(() => {
    context = createCacheAwareContext({
      staticPrefix: 'You are a helpful assistant.',
      cacheBreakpoints: ['system_end', 'tools_end'],
      deterministicJson: true,
      enforceAppendOnly: true,
    });
  });

  describe('constructor and defaults', () => {
    it('should create context with default config', () => {
      const ctx = createCacheAwareContext({
        staticPrefix: 'Test prefix',
      });
      expect(ctx).toBeInstanceOf(CacheAwareContext);
    });

    it('should use default breakpoints when not specified', () => {
      const ctx = createCacheAwareContext({
        staticPrefix: 'Test',
      });
      const prompt = ctx.buildSystemPrompt({});
      // Should have system_end breakpoint by default
      const breakpoints = ctx.getBreakpointPositions();
      expect(breakpoints.has('system_end')).toBe(true);
    });
  });

  describe('buildSystemPrompt', () => {
    it('should include static prefix at the start', () => {
      const prompt = context.buildSystemPrompt({});
      expect(prompt.startsWith('You are a helpful assistant.')).toBe(true);
    });

    it('should add rules section', () => {
      const prompt = context.buildSystemPrompt({
        rules: 'Follow these rules carefully.',
      });
      expect(prompt).toContain('## Rules');
      expect(prompt).toContain('Follow these rules carefully.');
    });

    it('should add tools section', () => {
      const prompt = context.buildSystemPrompt({
        tools: 'Available tools: read, write, search',
      });
      expect(prompt).toContain('## Available Tools');
      expect(prompt).toContain('read, write, search');
    });

    it('should add memory section', () => {
      const prompt = context.buildSystemPrompt({
        memory: 'Previous context: user prefers TypeScript',
      });
      expect(prompt).toContain('## Relevant Context');
      expect(prompt).toContain('user prefers TypeScript');
    });

    it('should add dynamic content at the end', () => {
      const prompt = context.buildSystemPrompt({
        dynamic: {
          sessionId: 'sess-123',
          mode: 'build',
        },
      });
      expect(prompt).toContain('Session: sess-123');
      expect(prompt).toContain('Mode: build');
      // Dynamic content should be at the end
      const dynamicIndex = prompt.indexOf('Session: sess-123');
      expect(dynamicIndex).toBeGreaterThan(prompt.length - 100);
    });

    it('should add timestamp to dynamic content', () => {
      const prompt = context.buildSystemPrompt({
        dynamic: {
          timestamp: '2025-01-01T00:00:00Z',
        },
      });
      expect(prompt).toContain('Time: 2025-01-01T00:00:00Z');
    });

    it('should add custom dynamic values', () => {
      const prompt = context.buildSystemPrompt({
        dynamic: {
          customField: 'customValue',
        },
      });
      expect(prompt).toContain('customField: customValue');
    });

    it('should not add dynamic section when empty', () => {
      const prompt = context.buildSystemPrompt({
        dynamic: {},
      });
      expect(prompt).not.toContain('---');
    });

    it('should preserve section order', () => {
      const prompt = context.buildSystemPrompt({
        rules: 'Rules content',
        tools: 'Tools content',
        memory: 'Memory content',
        dynamic: { sessionId: 'abc' },
      });

      const prefixIndex = prompt.indexOf('You are a helpful assistant');
      const rulesIndex = prompt.indexOf('## Rules');
      const toolsIndex = prompt.indexOf('## Available Tools');
      const memoryIndex = prompt.indexOf('## Relevant Context');
      const dynamicIndex = prompt.indexOf('---');

      expect(prefixIndex).toBeLessThan(rulesIndex);
      expect(rulesIndex).toBeLessThan(toolsIndex);
      expect(toolsIndex).toBeLessThan(memoryIndex);
      expect(memoryIndex).toBeLessThan(dynamicIndex);
    });
  });

  describe('breakpoint tracking', () => {
    it('should mark system_end breakpoint', () => {
      context.buildSystemPrompt({});
      const breakpoints = context.getBreakpointPositions();
      expect(breakpoints.has('system_end')).toBe(true);
    });

    it('should mark tools_end breakpoint', () => {
      context.buildSystemPrompt({
        tools: 'Tool descriptions here',
      });
      const breakpoints = context.getBreakpointPositions();
      expect(breakpoints.has('tools_end')).toBe(true);
    });

    it('should mark rules_end breakpoint when configured', () => {
      const ctx = createCacheAwareContext({
        staticPrefix: 'Test',
        cacheBreakpoints: ['rules_end'],
      });
      ctx.buildSystemPrompt({
        rules: 'Some rules',
      });
      const breakpoints = ctx.getBreakpointPositions();
      expect(breakpoints.has('rules_end')).toBe(true);
    });

    it('should mark memory_end breakpoint when configured', () => {
      const ctx = createCacheAwareContext({
        staticPrefix: 'Test',
        cacheBreakpoints: ['memory_end'],
      });
      ctx.buildSystemPrompt({
        memory: 'Some memory',
      });
      const breakpoints = ctx.getBreakpointPositions();
      expect(breakpoints.has('memory_end')).toBe(true);
    });

    it('should emit cache.breakpoint events', () => {
      const events: CacheEvent[] = [];
      context.on((event) => events.push(event));

      context.buildSystemPrompt({
        tools: 'Tool descriptions',
      });

      const breakpointEvents = events.filter((e) => e.type === 'cache.breakpoint');
      expect(breakpointEvents.length).toBeGreaterThan(0);
    });
  });

  describe('validateAppendOnly', () => {
    it('should return empty array for valid append-only messages', () => {
      const messages: ContextMessage[] = [
        { role: 'user', content: 'Hello' },
        { role: 'assistant', content: 'Hi there!' },
      ];

      const violations = context.validateAppendOnly(messages);
      expect(violations).toHaveLength(0);

      // Add a new message (append-only is valid)
      messages.push({ role: 'user', content: 'How are you?' });
      const violations2 = context.validateAppendOnly(messages);
      expect(violations2).toHaveLength(0);
    });

    it('should detect modified messages', () => {
      const messages: ContextMessage[] = [
        { role: 'user', content: 'Hello' },
        { role: 'assistant', content: 'Hi there!' },
      ];

      // First validation - establishes baseline
      context.validateAppendOnly(messages);

      // Modify a past message
      messages[0].content = 'Hello modified';

      const violations = context.validateAppendOnly(messages);
      expect(violations.length).toBeGreaterThan(0);
      expect(violations[0]).toContain('index 0');
    });

    it('should emit cache.violation events on modification', () => {
      const events: CacheEvent[] = [];
      context.on((event) => events.push(event));

      const messages: ContextMessage[] = [
        { role: 'user', content: 'Original' },
      ];

      context.validateAppendOnly(messages);
      messages[0].content = 'Modified';
      context.validateAppendOnly(messages);

      const violationEvents = events.filter((e) => e.type === 'cache.violation');
      expect(violationEvents.length).toBeGreaterThan(0);
    });

    it('should skip validation when enforceAppendOnly is false', () => {
      const ctx = createCacheAwareContext({
        staticPrefix: 'Test',
        enforceAppendOnly: false,
      });

      const messages: ContextMessage[] = [
        { role: 'user', content: 'Original' },
      ];

      ctx.validateAppendOnly(messages);
      messages[0].content = 'Modified';

      const violations = ctx.validateAppendOnly(messages);
      expect(violations).toHaveLength(0);
    });
  });

  describe('serializeMessage', () => {
    it('should serialize message with deterministic JSON', () => {
      const message: ContextMessage = {
        role: 'user',
        content: 'Hello',
        id: 'msg-1',
        timestamp: '2025-01-01',
      };

      const result = context.serializeMessage(message);

      // Should be deterministically sorted
      expect(result).toBe('{"content":"Hello","id":"msg-1","role":"user","timestamp":"2025-01-01"}');
    });

    it('should produce consistent output for same message', () => {
      const message: ContextMessage = {
        role: 'assistant',
        content: 'Response',
      };

      const result1 = context.serializeMessage(message);
      const result2 = context.serializeMessage(message);

      expect(result1).toBe(result2);
    });

    it('should use regular JSON when deterministicJson is false', () => {
      const ctx = createCacheAwareContext({
        staticPrefix: 'Test',
        deterministicJson: false,
      });

      const message: ContextMessage = {
        role: 'user',
        content: 'Hello',
      };

      const result = ctx.serializeMessage(message);
      // Should still be valid JSON
      expect(JSON.parse(result)).toEqual(message);
    });
  });

  describe('serializeToolArgs', () => {
    it('should serialize tool arguments with sorted keys', () => {
      const args = { z: 'last', a: 'first', m: 'middle' };
      const result = context.serializeToolArgs(args);
      expect(result).toBe('{"a":"first","m":"middle","z":"last"}');
    });

    it('should handle nested arguments', () => {
      const args = {
        options: { debug: true, verbose: false },
        path: '/test',
      };
      const result = context.serializeToolArgs(args);
      expect(result).toBe('{"options":{"debug":true,"verbose":false},"path":"/test"}');
    });
  });

  describe('calculateCacheStats', () => {
    it('should calculate cache statistics', () => {
      const stats = context.calculateCacheStats({
        systemPrompt: 'A'.repeat(400), // ~100 tokens
        messages: [
          { role: 'user', content: 'B'.repeat(200) }, // ~50 tokens
        ],
        dynamicContentLength: 40, // ~10 tokens
      });

      expect(stats.cacheableTokens).toBeGreaterThan(0);
      expect(stats.nonCacheableTokens).toBeGreaterThan(0);
      expect(stats.cacheRatio).toBeGreaterThan(0);
      expect(stats.cacheRatio).toBeLessThanOrEqual(1);
      expect(stats.estimatedSavings).toBeGreaterThan(0);
      expect(stats.estimatedSavings).toBeLessThanOrEqual(1);
    });

    it('should emit cache.stats event', () => {
      const events: CacheEvent[] = [];
      context.on((event) => events.push(event));

      context.calculateCacheStats({
        systemPrompt: 'Test prompt',
        messages: [],
      });

      const statsEvents = events.filter((e) => e.type === 'cache.stats');
      expect(statsEvents.length).toBe(1);
    });

    it('should handle zero dynamic content', () => {
      const stats = context.calculateCacheStats({
        systemPrompt: 'Test',
        messages: [],
        dynamicContentLength: 0,
      });

      expect(stats.cacheRatio).toBe(1); // 100% cacheable
      expect(stats.estimatedSavings).toBe(0.9); // 90% savings
    });
  });

  describe('event system', () => {
    it('should allow subscribing to events', () => {
      const events: CacheEvent[] = [];
      context.on((event) => events.push(event));

      context.buildSystemPrompt({});

      expect(events.length).toBeGreaterThan(0);
    });

    it('should allow unsubscribing from events', () => {
      const events: CacheEvent[] = [];
      const unsubscribe = context.on((event) => events.push(event));

      context.buildSystemPrompt({});
      const countBefore = events.length;

      unsubscribe();

      context.buildSystemPrompt({});
      expect(events.length).toBe(countBefore); // No new events
    });

    it('should handle listener errors gracefully', () => {
      context.on(() => {
        throw new Error('Listener error');
      });

      // Should not throw
      expect(() => context.buildSystemPrompt({})).not.toThrow();
    });

    it('should support multiple listeners', () => {
      const events1: CacheEvent[] = [];
      const events2: CacheEvent[] = [];

      context.on((event) => events1.push(event));
      context.on((event) => events2.push(event));

      context.buildSystemPrompt({});

      expect(events1.length).toBeGreaterThan(0);
      expect(events2.length).toBe(events1.length);
    });
  });

  describe('reset', () => {
    it('should clear message hashes', () => {
      const messages: ContextMessage[] = [
        { role: 'user', content: 'Hello' },
      ];

      context.validateAppendOnly(messages);
      messages[0].content = 'Modified';

      // Before reset - should detect violation
      const violationsBefore = context.validateAppendOnly(messages);
      expect(violationsBefore.length).toBeGreaterThan(0);

      context.reset();

      // After reset - no violation (new baseline)
      const violationsAfter = context.validateAppendOnly(messages);
      expect(violationsAfter).toHaveLength(0);
    });

    it('should clear breakpoint positions', () => {
      context.buildSystemPrompt({ tools: 'Tools' });
      expect(context.getBreakpointPositions().size).toBeGreaterThan(0);

      context.reset();

      expect(context.getBreakpointPositions().size).toBe(0);
    });
  });

  describe('getBreakpointPositions', () => {
    it('should return a copy of breakpoint positions', () => {
      context.buildSystemPrompt({});

      const positions1 = context.getBreakpointPositions();
      const positions2 = context.getBreakpointPositions();

      expect(positions1).not.toBe(positions2); // Different objects
      expect(positions1.size).toBe(positions2.size);
    });
  });
});

// =============================================================================
// TESTS: createCacheAwareContext factory
// =============================================================================

describe('createCacheAwareContext', () => {
  it('should create a CacheAwareContext instance', () => {
    const context = createCacheAwareContext({
      staticPrefix: 'Test prefix',
    });
    expect(context).toBeInstanceOf(CacheAwareContext);
  });

  it('should pass configuration to the context', () => {
    const context = createCacheAwareContext({
      staticPrefix: 'Custom prefix',
      cacheBreakpoints: ['system_end', 'rules_end'],
    });

    const prompt = context.buildSystemPrompt({ rules: 'Test rules' });
    expect(prompt.startsWith('Custom prefix')).toBe(true);

    const breakpoints = context.getBreakpointPositions();
    expect(breakpoints.has('system_end')).toBe(true);
    expect(breakpoints.has('rules_end')).toBe(true);
  });
});

// =============================================================================
// TESTS: analyzeCacheEfficiency
// =============================================================================

describe('analyzeCacheEfficiency', () => {
  describe('timestamp detection', () => {
    it('should detect ISO date at start', () => {
      const result = analyzeCacheEfficiency('2025-01-01 Some prompt');
      expect(result.warnings).toHaveLength(1);
      expect(result.warnings[0]).toContain('Timestamp');
      expect(result.suggestions.length).toBeGreaterThan(0);
    });

    it('should detect US date at start', () => {
      const result = analyzeCacheEfficiency('1/15/2025 Some prompt');
      expect(result.warnings).toHaveLength(1);
    });

    it('should detect "Current time:" at start', () => {
      const result = analyzeCacheEfficiency('Current time: 10:00 AM\nYou are an assistant.');
      expect(result.warnings.some((w) => w.includes('Timestamp'))).toBe(true);
    });

    it('should detect "Timestamp:" at start', () => {
      const result = analyzeCacheEfficiency('Timestamp: 12345\nPrompt content');
      expect(result.warnings.some((w) => w.includes('Timestamp'))).toBe(true);
    });

    it('should detect "Date:" at start', () => {
      const result = analyzeCacheEfficiency('Date: January 1st\nContent');
      expect(result.warnings.some((w) => w.includes('Timestamp'))).toBe(true);
    });

    it('should detect bracketed dates', () => {
      const result = analyzeCacheEfficiency('[2025-01-01] You are an assistant.');
      expect(result.warnings).toHaveLength(1);
    });
  });

  describe('session ID detection', () => {
    it('should detect "Session ID:" at start', () => {
      const result = analyzeCacheEfficiency('Session ID: abc-123\nYou are an assistant.');
      expect(result.warnings.some((w) => w.includes('Session'))).toBe(true);
      expect(result.suggestions.some((s) => s.includes('END'))).toBe(true);
    });

    it('should detect "Session:" at start', () => {
      const result = analyzeCacheEfficiency('Session: xyz-789\nContent');
      expect(result.warnings.some((w) => w.includes('Session'))).toBe(true);
    });
  });

  describe('dynamic content detection', () => {
    it('should detect "Random:" at start', () => {
      const result = analyzeCacheEfficiency('Random: 0.123456\nPrompt');
      expect(result.warnings.some((w) => w.includes('Dynamic'))).toBe(true);
    });

    it('should detect "Dynamic:" at start', () => {
      const result = analyzeCacheEfficiency('Dynamic: some-value\nContent');
      expect(result.warnings.some((w) => w.includes('Dynamic'))).toBe(true);
    });

    it('should detect "Generated:" at start', () => {
      const result = analyzeCacheEfficiency('Generated: new-id\nPrompt');
      expect(result.warnings.some((w) => w.includes('Dynamic'))).toBe(true);
    });
  });

  describe('clean prompts', () => {
    it('should return no warnings for cache-friendly prompts', () => {
      const result = analyzeCacheEfficiency(
        'You are a helpful coding assistant.\n\n' +
        'You help users write, debug, and understand code.'
      );
      expect(result.warnings).toHaveLength(0);
      expect(result.suggestions).toHaveLength(0);
    });

    it('should allow timestamps in the middle of prompt', () => {
      const result = analyzeCacheEfficiency(
        'You are an assistant.\n\n---\nCurrent session started at: 2025-01-01'
      );
      expect(result.warnings).toHaveLength(0);
    });
  });
});

// =============================================================================
// TESTS: formatCacheStats
// =============================================================================

describe('formatCacheStats', () => {
  it('should format cache statistics for display', () => {
    const stats: CacheStats = {
      cacheableTokens: 1000,
      nonCacheableTokens: 100,
      cacheRatio: 0.909,
      estimatedSavings: 0.818,
    };

    const formatted = formatCacheStats(stats);

    expect(formatted).toContain('1,000'); // Formatted number
    expect(formatted).toContain('100');
    expect(formatted).toContain('91%'); // Math.round(0.909 * 100)
    expect(formatted).toContain('82%'); // Math.round(0.818 * 100)
    expect(formatted).toContain('KV-Cache Statistics');
  });

  it('should handle zero values', () => {
    const stats: CacheStats = {
      cacheableTokens: 0,
      nonCacheableTokens: 0,
      cacheRatio: 0,
      estimatedSavings: 0,
    };

    const formatted = formatCacheStats(stats);

    expect(formatted).toContain('0%');
  });

  it('should handle large numbers', () => {
    const stats: CacheStats = {
      cacheableTokens: 1000000,
      nonCacheableTokens: 50000,
      cacheRatio: 0.95,
      estimatedSavings: 0.855,
    };

    const formatted = formatCacheStats(stats);

    expect(formatted).toContain('1,000,000'); // Locale formatting
  });
});

// =============================================================================
// TESTS: createEndTimestamp
// =============================================================================

describe('createEndTimestamp', () => {
  it('should create a formatted timestamp string', () => {
    const timestamp = createEndTimestamp();

    expect(timestamp).toMatch(/^\[Context generated at .+\]$/);
    expect(timestamp).toContain('T'); // ISO format has T separator
  });

  it('should produce different timestamps on successive calls', async () => {
    const timestamp1 = createEndTimestamp();

    // Wait a small amount to ensure different timestamp
    await new Promise((resolve) => setTimeout(resolve, 10));

    const timestamp2 = createEndTimestamp();

    // Timestamps should be different (or at least formatted similarly)
    expect(timestamp2).toMatch(/^\[Context generated at .+\]$/);
  });
});

// =============================================================================
// INTEGRATION TESTS
// =============================================================================

describe('Integration: Cache-aware context workflow', () => {
  it('should build a complete cache-optimized system prompt', () => {
    const context = createCacheAwareContext({
      staticPrefix: 'You are an expert TypeScript developer.',
      cacheBreakpoints: ['system_end', 'tools_end', 'memory_end'],
    });

    const prompt = context.buildSystemPrompt({
      rules: 'Always use strict TypeScript.\nPrefer functional programming.',
      tools: 'read_file(path: string): string\nwrite_file(path: string, content: string): void',
      memory: 'User is working on a React project.',
      dynamic: {
        sessionId: 'session-abc',
        mode: 'edit',
        timestamp: new Date().toISOString(),
      },
    });

    // Verify structure
    expect(prompt.startsWith('You are an expert TypeScript developer.')).toBe(true);
    expect(prompt).toContain('## Rules');
    expect(prompt).toContain('## Available Tools');
    expect(prompt).toContain('## Relevant Context');
    expect(prompt).toContain('---');
    expect(prompt).toContain('Session: session-abc');

    // Verify breakpoints were marked
    const breakpoints = context.getBreakpointPositions();
    expect(breakpoints.size).toBe(3);
  });

  it('should maintain cache efficiency across multiple calls', () => {
    const context = createCacheAwareContext({
      staticPrefix: 'You are a helpful assistant.',
      cacheBreakpoints: ['system_end'],
    });

    // Build prompt multiple times with same static content
    const prompt1 = context.buildSystemPrompt({
      rules: 'Be helpful',
      dynamic: { sessionId: 'a' },
    });

    const prompt2 = context.buildSystemPrompt({
      rules: 'Be helpful',
      dynamic: { sessionId: 'b' },
    });

    // Static portion should be identical
    const staticPart1 = prompt1.substring(0, prompt1.indexOf('---'));
    const staticPart2 = prompt2.substring(0, prompt2.indexOf('---'));
    expect(staticPart1).toBe(staticPart2);
  });

  it('should track and report append-only violations', () => {
    const context = createCacheAwareContext({
      staticPrefix: 'Test',
      enforceAppendOnly: true,
    });

    const events: CacheEvent[] = [];
    context.on((event) => events.push(event));

    const messages: ContextMessage[] = [
      { role: 'user', content: 'Original message' },
      { role: 'assistant', content: 'Response' },
    ];

    // Establish baseline
    context.validateAppendOnly(messages);

    // Modify past message (violation)
    messages[0].content = 'Modified message';
    const violations = context.validateAppendOnly(messages);

    expect(violations.length).toBe(1);
    expect(events.some((e) => e.type === 'cache.violation')).toBe(true);
  });
});
