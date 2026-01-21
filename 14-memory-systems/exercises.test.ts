/**
 * Exercise Tests: Lesson 14 - Memory Retrieval
 */
import { describe, it, expect } from 'vitest';
import { MemoryStore } from './exercises/answers/exercise-1.js';

describe('MemoryStore', () => {
  it('should add memories', () => {
    const store = new MemoryStore();
    const memory = store.add('test content', 5, ['tag1']);
    expect(memory.content).toBe('test content');
    expect(memory.importance).toBe(5);
  });

  it('should retrieve by query', () => {
    const store = new MemoryStore();
    store.add('the quick brown fox', 5);
    store.add('lazy dog', 5);

    const results = store.retrieve('fox');
    expect(results.length).toBe(1);
    expect(results[0].content).toContain('fox');
  });

  it('should filter by minimum importance', () => {
    const store = new MemoryStore();
    store.add('low importance', 2);
    store.add('high importance', 8);

    const results = store.retrieve('importance', { minImportance: 5 });
    expect(results.length).toBe(1);
  });

  it('should filter by tags', () => {
    const store = new MemoryStore();
    store.add('tagged', 5, ['important']);
    store.add('untagged', 5);

    const results = store.retrieve('', { tags: ['important'] });
    expect(results.length).toBe(1);
  });

  it('should rank by importance', () => {
    const store = new MemoryStore();
    store.add('test low', 1);
    store.add('test high', 10);

    const results = store.retrieve('test');
    expect(results[0].importance).toBe(10);
  });

  it('should remove memories', () => {
    const store = new MemoryStore();
    const memory = store.add('to delete', 5);
    store.remove(memory.id);
    expect(store.getById(memory.id)).toBeUndefined();
  });
});
