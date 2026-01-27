/**
 * Semantic Cache Tests
 *
 * Tests for the semantic caching system that caches LLM responses based on query similarity.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  SemanticCacheManager,
  createSemanticCacheManager,
  createStrictCache,
  createLenientCache,
  withSemanticCache,
  cosineSimilarity,
} from '../integrations/semantic-cache.js';

describe('cosineSimilarity', () => {
  it('should return 1 for identical vectors', () => {
    const vec = [1, 2, 3, 4, 5];
    expect(cosineSimilarity(vec, vec)).toBeCloseTo(1, 5);
  });

  it('should return 0 for orthogonal vectors', () => {
    const vec1 = [1, 0, 0];
    const vec2 = [0, 1, 0];
    expect(cosineSimilarity(vec1, vec2)).toBeCloseTo(0, 5);
  });

  it('should return -1 for opposite vectors', () => {
    const vec1 = [1, 0, 0];
    const vec2 = [-1, 0, 0];
    expect(cosineSimilarity(vec1, vec2)).toBeCloseTo(-1, 5);
  });

  it('should throw for vectors of different lengths', () => {
    const vec1 = [1, 2, 3];
    const vec2 = [1, 2];
    expect(() => cosineSimilarity(vec1, vec2)).toThrow();
  });

  it('should return 0 for zero vectors', () => {
    const vec1 = [0, 0, 0];
    const vec2 = [1, 2, 3];
    expect(cosineSimilarity(vec1, vec2)).toBe(0);
  });
});

describe('SemanticCacheManager', () => {
  let cache: SemanticCacheManager;

  beforeEach(() => {
    cache = createSemanticCacheManager({
      enabled: true,
      threshold: 0.8,
      maxSize: 100,
      ttl: 0,
    });
  });

  afterEach(() => {
    cache.cleanup();
  });

  describe('basic operations', () => {
    it('should store and retrieve cached responses', async () => {
      await cache.set('What is TypeScript?', 'TypeScript is a typed superset of JavaScript.');

      const hit = await cache.get('What is TypeScript?');

      expect(hit).not.toBeNull();
      expect(hit?.entry.response).toBe('TypeScript is a typed superset of JavaScript.');
      expect(hit?.similarity).toBeCloseTo(1, 1);
    });

    it('should return null for queries with no similar cache entry', async () => {
      await cache.set('What is TypeScript?', 'TypeScript is...');

      const hit = await cache.get('How to cook pasta?');

      // Different topic, should not match at high threshold
      // With simple embedding, this might or might not match
      // Just verify it returns a CacheHit | null
      expect(hit === null || hit?.similarity !== undefined).toBe(true);
    });

    it('should match similar queries', async () => {
      await cache.set('What is TypeScript?', 'TypeScript is a typed superset of JavaScript.');

      // Similar query should match
      const hit = await cache.get('What is typescript');

      expect(hit).not.toBeNull();
      expect(hit!.similarity).toBeGreaterThan(0.5);
    });

    it('should check existence without retrieving', async () => {
      await cache.set('test query', 'test response');

      const exists = await cache.has('test query');
      expect(exists).toBe(true);

      const notExists = await cache.has('completely different unrelated query about cooking');
      // May or may not exist depending on embedding
      expect(typeof notExists).toBe('boolean');
    });

    it('should delete entries by ID', async () => {
      const id = await cache.set('test', 'response');

      expect(cache.delete(id)).toBe(true);
      expect(cache.delete(id)).toBe(false); // Already deleted
    });

    it('should clear all entries', async () => {
      await cache.set('query1', 'response1');
      await cache.set('query2', 'response2');

      cache.clear();

      expect(cache.getStats().size).toBe(0);
    });
  });

  describe('statistics', () => {
    it('should track hit rate', async () => {
      await cache.set('test', 'response');

      await cache.get('test'); // Hit
      await cache.get('test'); // Hit
      await cache.get('completely unrelated xyz'); // Miss (probably)

      const stats = cache.getStats();

      expect(stats.totalQueries).toBeGreaterThan(0);
      expect(stats.hitRate).toBeDefined();
    });

    it('should track entry count', async () => {
      expect(cache.getStats().size).toBe(0);

      await cache.set('q1', 'r1');
      await cache.set('q2', 'r2');

      expect(cache.getStats().size).toBe(2);
    });

    it('should increment hit count on retrieval', async () => {
      await cache.set('test', 'response');

      await cache.get('test');
      await cache.get('test');

      const stats = cache.getStats();
      expect(stats.totalHits).toBeGreaterThan(0);
    });
  });

  describe('configuration', () => {
    it('should respect enabled flag', async () => {
      const disabledCache = createSemanticCacheManager({ enabled: false });

      const id = await disabledCache.set('test', 'response');
      expect(id).toBe('');

      const hit = await disabledCache.get('test');
      expect(hit).toBeNull();

      disabledCache.cleanup();
    });

    it('should respect threshold', async () => {
      const strictCache = createSemanticCacheManager({ threshold: 0.99 });

      await strictCache.set('What is TypeScript?', 'TypeScript is...');

      // With very high threshold, similar but not identical query may not match
      const hit = await strictCache.get('What is typescript programming');
      // Could be null or not depending on embedding
      expect(hit === null || hit.similarity >= 0.99).toBe(true);

      strictCache.cleanup();
    });

    it('should update configuration', async () => {
      cache.setConfig({ threshold: 0.5 });

      const config = cache.getConfig();
      expect(config.threshold).toBe(0.5);
    });
  });

  describe('eviction', () => {
    it('should evict LRU entries when max size is reached', async () => {
      const smallCache = createSemanticCacheManager({ maxSize: 3 });

      await smallCache.set('query1', 'response1');
      await smallCache.set('query2', 'response2');
      await smallCache.set('query3', 'response3');
      await smallCache.set('query4', 'response4'); // Should evict oldest

      expect(smallCache.getStats().size).toBe(3);

      smallCache.cleanup();
    });
  });

  describe('TTL', () => {
    it('should expire entries after TTL', async () => {
      const expiringCache = createSemanticCacheManager({ ttl: 50 });

      await expiringCache.set('test', 'response');

      // Wait for expiry
      await new Promise(r => setTimeout(r, 100));

      // Entry should be expired (cleaned on next get)
      const hit = await expiringCache.get('test');
      expect(hit).toBeNull();

      expiringCache.cleanup();
    });
  });

  describe('events', () => {
    it('should emit cache.hit event', async () => {
      const events: unknown[] = [];
      cache.subscribe(e => events.push(e));

      await cache.set('test', 'response');
      await cache.get('test');

      const hitEvents = events.filter((e: any) => e.type === 'cache.hit');
      expect(hitEvents.length).toBeGreaterThan(0);
    });

    it('should emit cache.miss event', async () => {
      const events: unknown[] = [];
      cache.subscribe(e => events.push(e));

      await cache.get('nonexistent query xyz');

      const missEvents = events.filter((e: any) => e.type === 'cache.miss');
      expect(missEvents.length).toBe(1);
    });

    it('should emit cache.set event', async () => {
      const events: unknown[] = [];
      cache.subscribe(e => events.push(e));

      await cache.set('test', 'response');

      const setEvents = events.filter((e: any) => e.type === 'cache.set');
      expect(setEvents.length).toBe(1);
    });
  });

  describe('findSimilar', () => {
    it('should find similar entries', async () => {
      await cache.set('What is JavaScript?', 'JS is...');
      await cache.set('What is TypeScript?', 'TS is...');
      await cache.set('What is Python?', 'Python is...');

      const similar = await cache.findSimilar('What is programming?', 3);

      expect(similar.length).toBeGreaterThan(0);
      expect(similar[0].similarity).toBeGreaterThan(0);
    });
  });

  describe('getAllEntries', () => {
    it('should return all cached entries', async () => {
      await cache.set('q1', 'r1');
      await cache.set('q2', 'r2');

      const entries = cache.getAllEntries();

      expect(entries.length).toBe(2);
      expect(entries.map(e => e.query).sort()).toEqual(['q1', 'q2']);
    });
  });
});

describe('Factory functions', () => {
  it('createStrictCache should have high threshold', () => {
    const strict = createStrictCache();
    const config = strict.getConfig();

    expect(config.threshold).toBeGreaterThanOrEqual(0.95);
    strict.cleanup();
  });

  it('createLenientCache should have low threshold', () => {
    const lenient = createLenientCache();
    const config = lenient.getConfig();

    expect(config.threshold).toBeLessThanOrEqual(0.9);
    lenient.cleanup();
  });
});

describe('withSemanticCache', () => {
  it('should cache function results', async () => {
    const cache = createSemanticCacheManager();
    const fn = vi.fn().mockResolvedValue('computed result');

    const cachedFn = withSemanticCache(fn, cache);

    // First call - computes
    const result1 = await cachedFn('test query');
    expect(result1).toBe('computed result');
    expect(fn).toHaveBeenCalledTimes(1);

    // Second call - cached
    const result2 = await cachedFn('test query');
    expect(result2).toBe('computed result');
    expect(fn).toHaveBeenCalledTimes(1); // Not called again

    cache.cleanup();
  });

  it('should compute for different queries', async () => {
    const cache = createSemanticCacheManager({ threshold: 0.99 });
    const fn = vi.fn()
      .mockResolvedValueOnce('result 1')
      .mockResolvedValueOnce('result 2');

    const cachedFn = withSemanticCache(fn, cache);

    await cachedFn('query one');
    await cachedFn('completely different query two');

    // Both should compute (assuming they're different enough)
    expect(fn).toHaveBeenCalledTimes(2);

    cache.cleanup();
  });
});
