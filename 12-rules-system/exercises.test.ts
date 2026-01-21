/**
 * Exercise Tests: Lesson 12 - Rules Merger
 */
import { describe, it, expect } from 'vitest';
import { RulesMerger, deepMerge } from './exercises/answers/exercise-1.js';

describe('RulesMerger', () => {
  it('should add and merge sources', () => {
    const merger = new RulesMerger();
    merger.addSource('base', { a: 1 }, 1);
    merger.addSource('override', { b: 2 }, 2);

    const merged = merger.merge();
    expect(merged).toEqual({ a: 1, b: 2 });
  });

  it('should respect priority (higher wins)', () => {
    const merger = new RulesMerger();
    merger.addSource('low', { value: 'low' }, 1);
    merger.addSource('high', { value: 'high' }, 2);

    expect(merger.merge().value).toBe('high');
  });

  it('should deep merge nested objects', () => {
    const merger = new RulesMerger();
    merger.addSource('base', { nested: { a: 1, b: 2 } }, 1);
    merger.addSource('override', { nested: { b: 3, c: 4 } }, 2);

    expect(merger.merge().nested).toEqual({ a: 1, b: 3, c: 4 });
  });

  it('should get value by path', () => {
    const merger = new RulesMerger();
    merger.addSource('test', { deep: { nested: { value: 42 } } }, 1);

    expect(merger.get('deep.nested.value')).toBe(42);
  });

  it('should remove sources', () => {
    const merger = new RulesMerger();
    merger.addSource('test', { a: 1 }, 1);
    merger.removeSource('test');

    expect(merger.getSources()).toHaveLength(0);
  });
});

describe('deepMerge', () => {
  it('should merge simple objects', () => {
    const result = deepMerge({ a: 1 }, { b: 2 });
    expect(result).toEqual({ a: 1, b: 2 });
  });

  it('should override primitives', () => {
    const result = deepMerge({ a: 1 }, { a: 2 });
    expect(result).toEqual({ a: 2 });
  });

  it('should deep merge nested objects', () => {
    const result = deepMerge({ n: { a: 1 } }, { n: { b: 2 } });
    expect(result).toEqual({ n: { a: 1, b: 2 } });
  });
});
