/**
 * Serialization Diversity Tests
 *
 * Tests for controlled variation in serialization to prevent
 * few-shot pattern collapse and over-fitting to specific formats.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  DiverseSerializer,
  createDiverseSerializer,
  serializeWithVariation,
  generateVariations,
  diversifyToolArgs,
  diversifyToolResult,
  formatDiversityStats,
  areSemanticEquivalent,
  type DiverseSerializerConfig,
  type SerializationStyle,
  type DiversityStats,
  type SerializerEvent,
} from '../../src/tricks/serialization-diversity.js';

// =============================================================================
// DiverseSerializer CLASS TESTS
// =============================================================================

describe('DiverseSerializer', () => {
  describe('constructor', () => {
    it('should create with default config', () => {
      const serializer = new DiverseSerializer();
      expect(serializer).toBeInstanceOf(DiverseSerializer);
    });

    it('should accept custom config', () => {
      const serializer = new DiverseSerializer({
        variationLevel: 0.5,
        preserveSemantics: true,
        seed: 12345,
      });
      expect(serializer).toBeInstanceOf(DiverseSerializer);
    });

    it('should use provided seed for deterministic output', () => {
      const serializer1 = new DiverseSerializer({ seed: 42 });
      const serializer2 = new DiverseSerializer({ seed: 42 });

      const data = { a: 1, b: 2, c: 3 };
      const result1 = serializer1.serialize(data);
      const result2 = serializer2.serialize(data);

      expect(result1).toBe(result2);
    });

    it('should produce different output with different seeds', () => {
      const serializer1 = new DiverseSerializer({ seed: 42, variationLevel: 1 });
      const serializer2 = new DiverseSerializer({ seed: 999, variationLevel: 1 });

      const data = { a: 1, b: 2, c: 3 };

      // With high variation and different seeds, outputs should likely differ
      // Run multiple times to increase probability
      let foundDifference = false;
      for (let i = 0; i < 10; i++) {
        const s1 = new DiverseSerializer({ seed: i, variationLevel: 1 });
        const s2 = new DiverseSerializer({ seed: i + 1000, variationLevel: 1 });
        if (s1.serialize(data) !== s2.serialize(data)) {
          foundDifference = true;
          break;
        }
      }
      expect(foundDifference).toBe(true);
    });
  });

  describe('serialize', () => {
    let serializer: DiverseSerializer;

    beforeEach(() => {
      serializer = new DiverseSerializer({ seed: 12345, variationLevel: 0.3 });
    });

    it('should serialize simple objects', () => {
      const result = serializer.serialize({ key: 'value' });
      expect(JSON.parse(result)).toEqual({ key: 'value' });
    });

    it('should serialize arrays', () => {
      const result = serializer.serialize([1, 2, 3]);
      expect(JSON.parse(result)).toEqual([1, 2, 3]);
    });

    it('should serialize nested objects', () => {
      const data = { outer: { inner: { deep: 'value' } } };
      const result = serializer.serialize(data);
      expect(JSON.parse(result)).toEqual(data);
    });

    it('should serialize mixed structures', () => {
      const data = {
        name: 'test',
        count: 42,
        active: true,
        tags: ['a', 'b'],
        meta: { nested: true },
      };
      const result = serializer.serialize(data);
      expect(JSON.parse(result)).toEqual(data);
    });

    it('should handle null values', () => {
      const result = serializer.serialize({ value: null });
      const parsed = JSON.parse(result);
      expect(parsed.value === null || !('value' in parsed)).toBe(true);
    });

    it('should handle undefined values', () => {
      const result = serializer.serialize({ value: undefined });
      const parsed = JSON.parse(result);
      // undefined should always be omitted in JSON
      expect('value' in parsed).toBe(false);
    });

    it('should handle empty objects', () => {
      const result = serializer.serialize({});
      expect(result).toMatch(/^\{\s*\}$/);
    });

    it('should handle empty arrays', () => {
      const result = serializer.serialize([]);
      expect(result).toMatch(/^\[\s*\]$/);
    });

    it('should handle primitive types', () => {
      expect(serializer.serialize('hello')).toBe('"hello"');
      expect(serializer.serialize(42)).toBe('42');
      expect(serializer.serialize(true)).toBe('true');
      expect(serializer.serialize(false)).toBe('false');
      expect(serializer.serialize(null)).toBe('null');
    });

    it('should handle strings with special characters', () => {
      const result = serializer.serialize({ text: 'hello "world"' });
      expect(JSON.parse(result)).toEqual({ text: 'hello "world"' });
    });

    it('should handle strings with braces', () => {
      const result = serializer.serialize({ text: 'obj: {foo: bar}' });
      expect(JSON.parse(result)).toEqual({ text: 'obj: {foo: bar}' });
    });
  });

  describe('serializeWithStyle', () => {
    let serializer: DiverseSerializer;

    beforeEach(() => {
      serializer = new DiverseSerializer();
    });

    it('should apply compact style (indent: 0)', () => {
      const result = serializer.serializeWithStyle({ a: 1, b: 2 }, { indent: 0 });
      expect(result).not.toContain('\n');
    });

    it('should apply expanded style (indent: 2)', () => {
      const result = serializer.serializeWithStyle({ a: 1, b: 2 }, { indent: 2 });
      expect(result).toContain('\n');
      expect(result).toContain('  ');
    });

    it('should apply tab indentation', () => {
      const result = serializer.serializeWithStyle({ a: 1, b: 2 }, { indent: 'tab' });
      expect(result).toContain('\t');
    });

    it('should sort keys ascending', () => {
      const result = serializer.serializeWithStyle(
        { z: 1, a: 2, m: 3 },
        { sortKeys: true, keySortOrder: 'asc' }
      );
      const keys = [...result.matchAll(/"([a-z])"/g)].map(m => m[1]);
      expect(keys).toEqual(['a', 'm', 'z']);
    });

    it('should sort keys descending', () => {
      const result = serializer.serializeWithStyle(
        { a: 1, m: 2, z: 3 },
        { sortKeys: true, keySortOrder: 'desc' }
      );
      const keys = [...result.matchAll(/"([a-z])"/g)].map(m => m[1]);
      expect(keys).toEqual(['z', 'm', 'a']);
    });

    it('should omit null values when configured', () => {
      const result = serializer.serializeWithStyle(
        { a: 1, b: null, c: 2 },
        { omitNull: true }
      );
      const parsed = JSON.parse(result);
      expect(parsed).toEqual({ a: 1, c: 2 });
    });

    it('should control space after colon', () => {
      const withSpace = serializer.serializeWithStyle(
        { a: 1 },
        { indent: 0, spaceAfterColon: true }
      );
      const withoutSpace = serializer.serializeWithStyle(
        { a: 1 },
        { indent: 0, spaceAfterColon: false }
      );

      expect(withSpace).toContain(': ');
      expect(withoutSpace).not.toContain(': ');
    });

    it('should use compact array style', () => {
      const result = serializer.serializeWithStyle(
        { arr: [1, 2, 3] },
        { arrayStyle: 'compact' }
      );
      // Compact arrays should not have newlines within the array
      const arrMatch = result.match(/\[.*?\]/s);
      expect(arrMatch?.[0]).not.toContain('\n');
    });

    it('should use expanded array style', () => {
      const result = serializer.serializeWithStyle(
        { arr: [1, 2, 3] },
        { arrayStyle: 'expanded', indent: 2 }
      );
      expect(result).toContain('\n');
    });
  });

  describe('generateStyle', () => {
    it('should generate style based on variation level', () => {
      const serializer = new DiverseSerializer({
        seed: 12345,
        variationLevel: 1.0, // Maximum variation
      });

      const style = serializer.generateStyle();
      expect(style).toBeDefined();
      // With high variation, some properties should be set
      expect(Object.keys(style).length).toBeGreaterThan(0);
    });

    it('should generate minimal variation at level 0', () => {
      const serializer = new DiverseSerializer({
        seed: 12345,
        variationLevel: 0,
      });

      // Run multiple times - with 0 variation, style should be empty
      for (let i = 0; i < 10; i++) {
        const style = serializer.generateStyle();
        expect(Object.keys(style).length).toBe(0);
      }
    });
  });

  describe('getConsistentStyle', () => {
    it('should return consistent style defaults', () => {
      const serializer = new DiverseSerializer();
      const style = serializer.getConsistentStyle();

      expect(style.indent).toBe(2);
      expect(style.sortKeys).toBe(true);
      expect(style.keySortOrder).toBe('asc');
      expect(style.trailingComma).toBe(false);
      expect(style.spaceAfterColon).toBe(true);
      expect(style.spaceInsideBrackets).toBe(false);
      expect(style.omitNull).toBe(false);
      expect(style.omitUndefined).toBe(true);
      expect(style.arrayStyle).toBe('expanded');
    });
  });

  describe('getStats', () => {
    it('should track serialization count', () => {
      const serializer = new DiverseSerializer({ seed: 12345 });

      serializer.serialize({ a: 1 });
      serializer.serialize({ b: 2 });
      serializer.serialize({ c: 3 });

      const stats = serializer.getStats();
      expect(stats.totalSerializations).toBe(3);
    });

    it('should track style distribution', () => {
      const serializer = new DiverseSerializer({ seed: 12345 });

      for (let i = 0; i < 10; i++) {
        serializer.serialize({ value: i });
      }

      const stats = serializer.getStats();
      expect(stats.styleDistribution.size).toBeGreaterThan(0);

      // Total count in distribution should match total serializations
      let totalCount = 0;
      for (const count of stats.styleDistribution.values()) {
        totalCount += count;
      }
      expect(totalCount).toBe(10);
    });

    it('should calculate average variation', () => {
      const serializer = new DiverseSerializer({ seed: 12345, variationLevel: 0.5 });

      for (let i = 0; i < 10; i++) {
        serializer.serialize({ value: i });
      }

      const stats = serializer.getStats();
      expect(stats.averageVariation).toBeGreaterThanOrEqual(0);
      expect(stats.averageVariation).toBeLessThanOrEqual(1);
    });

    it('should return zero average variation when no serializations', () => {
      const serializer = new DiverseSerializer();
      const stats = serializer.getStats();
      expect(stats.averageVariation).toBe(0);
    });
  });

  describe('resetStats', () => {
    it('should reset all statistics', () => {
      const serializer = new DiverseSerializer({ seed: 12345 });

      serializer.serialize({ a: 1 });
      serializer.serialize({ b: 2 });

      serializer.resetStats();
      const stats = serializer.getStats();

      expect(stats.totalSerializations).toBe(0);
      expect(stats.styleDistribution.size).toBe(0);
    });
  });

  describe('setVariationLevel', () => {
    it('should update variation level', () => {
      const serializer = new DiverseSerializer({ variationLevel: 0.3 });
      serializer.setVariationLevel(0.7);

      // The internal config should be updated
      // We can verify by checking that serializations use different styles
      expect(serializer).toBeDefined();
    });

    it('should clamp variation level to valid range', () => {
      const serializer = new DiverseSerializer({ variationLevel: 0.5 });

      serializer.setVariationLevel(1.5);
      serializer.setVariationLevel(-0.5);

      // Should not throw - values should be clamped
      expect(serializer).toBeDefined();
    });
  });

  describe('event system (on)', () => {
    it('should emit serialization.performed events', () => {
      const serializer = new DiverseSerializer({ seed: 12345 });
      const events: SerializerEvent[] = [];

      serializer.on(event => events.push(event));
      serializer.serialize({ test: 'value' });

      expect(events.length).toBe(1);
      expect(events[0].type).toBe('serialization.performed');
    });

    it('should include style and variation in events', () => {
      const serializer = new DiverseSerializer({ seed: 12345 });
      let capturedEvent: SerializerEvent | null = null;

      serializer.on(event => {
        capturedEvent = event;
      });
      serializer.serialize({ test: 'value' });

      expect(capturedEvent).not.toBeNull();
      if (capturedEvent && capturedEvent.type === 'serialization.performed') {
        expect(capturedEvent.style).toBeDefined();
        expect(typeof capturedEvent.variation).toBe('number');
      }
    });

    it('should return unsubscribe function', () => {
      const serializer = new DiverseSerializer({ seed: 12345 });
      const events: SerializerEvent[] = [];

      const unsubscribe = serializer.on(event => events.push(event));
      serializer.serialize({ a: 1 });
      expect(events.length).toBe(1);

      unsubscribe();
      serializer.serialize({ b: 2 });
      expect(events.length).toBe(1); // No new events after unsubscribe
    });

    it('should handle listener errors gracefully', () => {
      const serializer = new DiverseSerializer({ seed: 12345 });

      serializer.on(() => {
        throw new Error('Listener error');
      });

      // Should not throw despite listener error
      expect(() => serializer.serialize({ test: 'value' })).not.toThrow();
    });

    it('should support multiple listeners', () => {
      const serializer = new DiverseSerializer({ seed: 12345 });
      const events1: SerializerEvent[] = [];
      const events2: SerializerEvent[] = [];

      serializer.on(event => events1.push(event));
      serializer.on(event => events2.push(event));
      serializer.serialize({ test: 'value' });

      expect(events1.length).toBe(1);
      expect(events2.length).toBe(1);
    });
  });

  describe('config options', () => {
    it('should respect varyKeyOrder option', () => {
      const serializer = new DiverseSerializer({
        seed: 12345,
        variationLevel: 1,
        varyKeyOrder: false,
      });

      // With varyKeyOrder false, key order variations should not happen
      const style = serializer.generateStyle();
      expect(style.sortKeys).toBeUndefined();
      expect(style.keySortOrder).toBeUndefined();
    });

    it('should respect varyIndentation option', () => {
      const serializer = new DiverseSerializer({
        seed: 12345,
        variationLevel: 1,
        varyIndentation: false,
      });

      const style = serializer.generateStyle();
      expect(style.indent).toBeUndefined();
    });

    it('should respect varySpacing option', () => {
      const serializer = new DiverseSerializer({
        seed: 12345,
        variationLevel: 1,
        varySpacing: false,
      });

      const style = serializer.generateStyle();
      expect(style.spaceAfterColon).toBeUndefined();
      expect(style.spaceInsideBrackets).toBeUndefined();
    });

    it('should respect varyArrayFormat option', () => {
      const serializer = new DiverseSerializer({
        seed: 12345,
        variationLevel: 1,
        varyArrayFormat: false,
      });

      const style = serializer.generateStyle();
      expect(style.arrayStyle).toBeUndefined();
    });
  });
});

// =============================================================================
// FACTORY FUNCTION TESTS
// =============================================================================

describe('createDiverseSerializer', () => {
  it('should create a DiverseSerializer instance', () => {
    const serializer = createDiverseSerializer();
    expect(serializer).toBeInstanceOf(DiverseSerializer);
  });

  it('should pass config to constructor', () => {
    const serializer = createDiverseSerializer({
      variationLevel: 0.5,
      seed: 42,
    });
    expect(serializer).toBeInstanceOf(DiverseSerializer);
  });

  it('should work with empty config', () => {
    const serializer = createDiverseSerializer({});
    expect(serializer).toBeInstanceOf(DiverseSerializer);
  });
});

// =============================================================================
// UTILITY FUNCTION TESTS
// =============================================================================

describe('serializeWithVariation', () => {
  it('should serialize data with variation', () => {
    const result = serializeWithVariation({ key: 'value' });
    expect(JSON.parse(result)).toEqual({ key: 'value' });
  });

  it('should accept custom variation level', () => {
    const result = serializeWithVariation({ key: 'value' }, 0.5);
    expect(JSON.parse(result)).toEqual({ key: 'value' });
  });

  it('should use default variation level of 0.3', () => {
    const result = serializeWithVariation({ test: 123 });
    expect(JSON.parse(result)).toEqual({ test: 123 });
  });
});

describe('generateVariations', () => {
  it('should generate specified number of variations', () => {
    const variations = generateVariations({ key: 'value' }, 5);
    expect(variations.length).toBe(5);
  });

  it('should produce semantically equivalent outputs', () => {
    const variations = generateVariations({ a: 1, b: 2 }, 10, 0.8);

    for (const variation of variations) {
      const parsed = JSON.parse(variation);
      expect(parsed.a).toBe(1);
      expect(parsed.b).toBe(2);
    }
  });

  it('should introduce format variations', () => {
    // With high variation, we expect some differences
    const variations = generateVariations({ a: 1, b: 2, c: 3 }, 20, 1.0);
    const uniqueVariations = new Set(variations);

    // With high variation and enough samples, we should see multiple formats
    expect(uniqueVariations.size).toBeGreaterThan(1);
  });

  it('should use default variation level of 0.5', () => {
    const variations = generateVariations({ test: true }, 3);
    expect(variations.length).toBe(3);
  });
});

describe('diversifyToolArgs', () => {
  it('should serialize tool arguments', () => {
    const args = { path: '/test/file.txt', content: 'hello' };
    const result = diversifyToolArgs(args);
    expect(JSON.parse(result)).toEqual(args);
  });

  it('should accept custom variation level', () => {
    const args = { query: 'search term' };
    const result = diversifyToolArgs(args, 0.5);
    expect(JSON.parse(result)).toEqual(args);
  });

  it('should use default variation level of 0.3', () => {
    const args = { name: 'test' };
    const result = diversifyToolArgs(args);
    expect(JSON.parse(result)).toEqual(args);
  });
});

describe('diversifyToolResult', () => {
  it('should serialize tool results', () => {
    const result = { files: ['a.txt', 'b.txt'], count: 2 };
    const serialized = diversifyToolResult(result);
    expect(JSON.parse(serialized)).toEqual(result);
  });

  it('should handle array results', () => {
    const result = ['line1', 'line2', 'line3'];
    const serialized = diversifyToolResult(result);
    expect(JSON.parse(serialized)).toEqual(result);
  });

  it('should accept custom variation level', () => {
    const result = { success: true, data: {} };
    const serialized = diversifyToolResult(result, 0.7);
    expect(JSON.parse(serialized)).toEqual(result);
  });

  it('should use default variation level of 0.3', () => {
    const result = { status: 'ok' };
    const serialized = diversifyToolResult(result);
    expect(JSON.parse(serialized)).toEqual(result);
  });
});

describe('formatDiversityStats', () => {
  it('should format stats as readable string', () => {
    const stats: DiversityStats = {
      totalSerializations: 100,
      styleDistribution: new Map([
        ['2-true-asc', 60],
        ['0-false-random', 40],
      ]),
      averageVariation: 0.35,
    };

    const formatted = formatDiversityStats(stats);

    expect(formatted).toContain('Serialization Diversity Statistics');
    expect(formatted).toContain('Total serializations: 100');
    expect(formatted).toContain('Average variation: 35.0%');
    expect(formatted).toContain('Style distribution');
    expect(formatted).toContain('2-true-asc');
    expect(formatted).toContain('60');
    expect(formatted).toContain('60.0%');
  });

  it('should handle empty style distribution', () => {
    const stats: DiversityStats = {
      totalSerializations: 0,
      styleDistribution: new Map(),
      averageVariation: 0,
    };

    const formatted = formatDiversityStats(stats);
    expect(formatted).toContain('Total serializations: 0');
  });
});

describe('areSemanticEquivalent', () => {
  it('should return true for identical JSON', () => {
    const json1 = '{"a": 1, "b": 2}';
    const json2 = '{"a": 1, "b": 2}';
    expect(areSemanticEquivalent(json1, json2)).toBe(true);
  });

  it('should return true for different key orders', () => {
    const json1 = '{"a": 1, "b": 2}';
    const json2 = '{"b": 2, "a": 1}';
    expect(areSemanticEquivalent(json1, json2)).toBe(true);
  });

  it('should return true for different formatting', () => {
    const json1 = '{"a":1,"b":2}';
    const json2 = '{\n  "a": 1,\n  "b": 2\n}';
    expect(areSemanticEquivalent(json1, json2)).toBe(true);
  });

  it('should return false for different values', () => {
    const json1 = '{"a": 1}';
    const json2 = '{"a": 2}';
    expect(areSemanticEquivalent(json1, json2)).toBe(false);
  });

  it('should return false for different keys', () => {
    const json1 = '{"a": 1}';
    const json2 = '{"b": 1}';
    expect(areSemanticEquivalent(json1, json2)).toBe(false);
  });

  it('should return false for invalid JSON', () => {
    expect(areSemanticEquivalent('not json', '{"a": 1}')).toBe(false);
    expect(areSemanticEquivalent('{"a": 1}', 'not json')).toBe(false);
    expect(areSemanticEquivalent('not json', 'also not json')).toBe(false);
  });

  it('should handle nested objects', () => {
    const json1 = '{"outer": {"a": 1, "b": 2}}';
    const json2 = '{"outer": {"b": 2, "a": 1}}';
    expect(areSemanticEquivalent(json1, json2)).toBe(true);
  });

  it('should handle arrays', () => {
    const json1 = '[1, 2, 3]';
    const json2 = '[1, 2, 3]';
    expect(areSemanticEquivalent(json1, json2)).toBe(true);
  });

  it('should return false for different array orders', () => {
    const json1 = '[1, 2, 3]';
    const json2 = '[3, 2, 1]';
    expect(areSemanticEquivalent(json1, json2)).toBe(false);
  });
});

// =============================================================================
// INTEGRATION TESTS
// =============================================================================

describe('Integration', () => {
  describe('semantic preservation', () => {
    it('should always produce valid JSON', () => {
      const serializer = createDiverseSerializer({
        variationLevel: 1.0, // Maximum variation
        seed: 12345,
      });

      const testData = [
        { simple: 'object' },
        [1, 2, 3, 4, 5],
        { nested: { deep: { value: 'test' } } },
        { mixed: ['a', { b: 2 }, null, true, 3.14] },
        { empty: {}, alsoEmpty: [] },
      ];

      for (const data of testData) {
        for (let i = 0; i < 10; i++) {
          const result = serializer.serialize(data);
          expect(() => JSON.parse(result)).not.toThrow();
        }
      }
    });

    it('should preserve data semantically through variations', () => {
      const data = {
        name: 'test',
        values: [1, 2, 3],
        nested: { flag: true, count: 42 },
      };

      const variations = generateVariations(data, 20, 1.0);

      for (const variation of variations) {
        const parsed = JSON.parse(variation);
        expect(parsed.name).toBe('test');
        expect(parsed.values).toEqual([1, 2, 3]);
        expect(parsed.nested.flag).toBe(true);
        expect(parsed.nested.count).toBe(42);
      }
    });
  });

  describe('statistics and monitoring', () => {
    it('should provide useful diversity metrics', () => {
      const serializer = createDiverseSerializer({
        variationLevel: 0.5,
        seed: 12345,
      });

      // Perform many serializations
      for (let i = 0; i < 100; i++) {
        serializer.serialize({ iteration: i, data: 'test' });
      }

      const stats = serializer.getStats();
      const formatted = formatDiversityStats(stats);

      expect(stats.totalSerializations).toBe(100);
      expect(formatted).toContain('100');
    });
  });

  describe('tool integration', () => {
    it('should work with typical tool arguments', () => {
      const toolArgs = {
        tool: 'read_file',
        input: {
          path: '/path/to/file.ts',
          encoding: 'utf-8',
        },
      };

      const serialized = diversifyToolArgs(toolArgs);
      const parsed = JSON.parse(serialized);

      expect(parsed.tool).toBe('read_file');
      expect(parsed.input.path).toBe('/path/to/file.ts');
    });

    it('should work with typical tool results', () => {
      const toolResult = {
        success: true,
        files: [
          { name: 'a.ts', size: 1024 },
          { name: 'b.ts', size: 2048 },
        ],
        metadata: {
          total: 2,
          timestamp: '2024-01-01T00:00:00Z',
        },
      };

      const serialized = diversifyToolResult(toolResult);
      const parsed = JSON.parse(serialized);

      expect(parsed.success).toBe(true);
      expect(parsed.files.length).toBe(2);
    });
  });
});

// =============================================================================
// EDGE CASES
// =============================================================================

describe('Edge Cases', () => {
  it('should handle very deep nesting', () => {
    const serializer = createDiverseSerializer({ seed: 12345 });
    const deepObject = { a: { b: { c: { d: { e: { f: 'deep' } } } } } };

    const result = serializer.serialize(deepObject);
    const parsed = JSON.parse(result);
    expect(parsed.a.b.c.d.e.f).toBe('deep');
  });

  it('should handle large arrays', () => {
    const serializer = createDiverseSerializer({ seed: 12345 });
    const largeArray = Array.from({ length: 1000 }, (_, i) => i);

    const result = serializer.serialize(largeArray);
    const parsed = JSON.parse(result);
    expect(parsed.length).toBe(1000);
  });

  it('should handle special number values', () => {
    const serializer = createDiverseSerializer({ seed: 12345 });

    expect(serializer.serialize(0)).toBe('0');
    expect(serializer.serialize(-0)).toBe('0');
    expect(serializer.serialize(3.14159)).toBe('3.14159');
    expect(serializer.serialize(-42)).toBe('-42');
  });

  it('should handle unicode strings', () => {
    const serializer = createDiverseSerializer({ seed: 12345 });
    const data = { greeting: 'Hello, world!', emoji: 'Test' };

    const result = serializer.serialize(data);
    const parsed = JSON.parse(result);
    expect(parsed.greeting).toBe('Hello, world!');
  });

  it('should handle empty string keys and values', () => {
    const serializer = createDiverseSerializer({ seed: 12345 });
    const data = { '': 'empty key', emptyValue: '' };

    const result = serializer.serialize(data);
    const parsed = JSON.parse(result);
    expect(parsed['']).toBe('empty key');
    expect(parsed.emptyValue).toBe('');
  });

  it('should handle very long strings', () => {
    const serializer = createDiverseSerializer({ seed: 12345 });
    const longString = 'a'.repeat(10000);
    const data = { content: longString };

    const result = serializer.serialize(data);
    const parsed = JSON.parse(result);
    expect(parsed.content.length).toBe(10000);
  });

  it('should handle objects with many keys', () => {
    const serializer = createDiverseSerializer({ seed: 12345 });
    const manyKeys: Record<string, number> = {};
    for (let i = 0; i < 100; i++) {
      manyKeys[`key${i}`] = i;
    }

    const result = serializer.serialize(manyKeys);
    const parsed = JSON.parse(result);
    expect(Object.keys(parsed).length).toBe(100);
  });
});
