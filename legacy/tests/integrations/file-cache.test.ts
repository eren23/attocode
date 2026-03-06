/**
 * Unit tests for SharedFileCache.
 *
 * Tests the LRU file cache shared across parent and child agents
 * to eliminate redundant file reads in multi-agent workflows.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  SharedFileCache,
  createSharedFileCache,
} from '../../src/integrations/context/file-cache.js';

describe('SharedFileCache', () => {
  describe('get/set basics', () => {
    it('should cache and retrieve file content', () => {
      const cache = new SharedFileCache();

      cache.set('/path/to/file.ts', 'const x = 1;');
      expect(cache.get('/path/to/file.ts')).toBe('const x = 1;');
    });

    it('should return undefined for uncached file', () => {
      const cache = new SharedFileCache();
      expect(cache.get('/not/cached.ts')).toBeUndefined();
    });

    it('should update content when set is called again', () => {
      const cache = new SharedFileCache();

      cache.set('/file.ts', 'version 1');
      cache.set('/file.ts', 'version 2');
      expect(cache.get('/file.ts')).toBe('version 2');
    });
  });

  describe('path normalization', () => {
    it('should treat relative and absolute paths as same entry', () => {
      const cache = new SharedFileCache();

      // Set with a path, get with another form — both resolve to same absolute
      const cwd = process.cwd();
      cache.set(`${cwd}/src/file.ts`, 'content');
      expect(cache.get('src/file.ts')).toBe('content');
    });

    it('should handle paths with ../ segments', () => {
      const cache = new SharedFileCache();

      cache.set('/a/b/c/file.ts', 'content');
      expect(cache.get('/a/b/c/../c/file.ts')).toBe('content');
    });

    it('should invalidate normalized paths correctly', () => {
      const cache = new SharedFileCache();

      cache.set('/a/b/file.ts', 'content');
      cache.invalidate('/a/b/../b/file.ts');
      expect(cache.get('/a/b/file.ts')).toBeUndefined();
    });
  });

  describe('TTL expiration', () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it('should return cached content within TTL', () => {
      const cache = new SharedFileCache({ ttlMs: 60000 }); // 1 min TTL

      cache.set('/file.ts', 'content');
      vi.advanceTimersByTime(30000); // 30s later
      expect(cache.get('/file.ts')).toBe('content');
    });

    it('should expire entries after TTL', () => {
      const cache = new SharedFileCache({ ttlMs: 60000 });

      cache.set('/file.ts', 'content');
      vi.advanceTimersByTime(61000); // Past TTL
      expect(cache.get('/file.ts')).toBeUndefined();
    });

    it('should count expired access as miss', () => {
      const cache = new SharedFileCache({ ttlMs: 60000 });

      cache.set('/file.ts', 'content');
      vi.advanceTimersByTime(61000);
      cache.get('/file.ts'); // Miss

      const stats = cache.getStats();
      expect(stats.misses).toBe(1);
    });
  });

  describe('LRU eviction', () => {
    it('should evict least recently used entry when at capacity', () => {
      // 100 byte max cache
      const cache = new SharedFileCache({ maxCacheBytes: 100 });

      cache.set('/a.ts', 'a'.repeat(40)); // 40 bytes
      cache.set('/b.ts', 'b'.repeat(40)); // 40 bytes, total = 80
      cache.set('/c.ts', 'c'.repeat(40)); // Would be 120 bytes — must evict /a.ts

      expect(cache.get('/a.ts')).toBeUndefined(); // Evicted (LRU)
      expect(cache.get('/b.ts')).toBe('b'.repeat(40)); // Kept
      expect(cache.get('/c.ts')).toBe('c'.repeat(40)); // New entry
    });

    it('should update LRU order on access', () => {
      const cache = new SharedFileCache({ maxCacheBytes: 100 });

      cache.set('/a.ts', 'a'.repeat(30)); // 30 bytes
      cache.set('/b.ts', 'b'.repeat(30)); // 30 bytes
      cache.set('/c.ts', 'c'.repeat(30)); // 30 bytes, total = 90

      // Access /a.ts to make it recently used
      cache.get('/a.ts');

      // Adding /d.ts should evict /b.ts (now LRU), not /a.ts
      cache.set('/d.ts', 'd'.repeat(30));

      expect(cache.get('/a.ts')).toBe('a'.repeat(30)); // Kept (recently accessed)
      expect(cache.get('/b.ts')).toBeUndefined(); // Evicted (LRU)
      expect(cache.get('/d.ts')).toBe('d'.repeat(30)); // New entry
    });

    it('should track eviction count', () => {
      const cache = new SharedFileCache({ maxCacheBytes: 100 });

      cache.set('/a.ts', 'a'.repeat(40));
      cache.set('/b.ts', 'b'.repeat(40));
      cache.set('/c.ts', 'c'.repeat(40)); // Evicts /a.ts

      const stats = cache.getStats();
      expect(stats.evictions).toBeGreaterThanOrEqual(1);
    });
  });

  describe('size limits', () => {
    it('should reject files larger than 50% of max cache size', () => {
      const cache = new SharedFileCache({ maxCacheBytes: 100 });

      cache.set('/big.ts', 'x'.repeat(60)); // 60% of 100 = too large
      expect(cache.get('/big.ts')).toBeUndefined();
    });

    it('should accept files at exactly 50% of max cache size', () => {
      const cache = new SharedFileCache({ maxCacheBytes: 100 });

      cache.set('/half.ts', 'x'.repeat(50)); // Exactly 50%
      expect(cache.get('/half.ts')).toBe('x'.repeat(50));
    });
  });

  describe('invalidate', () => {
    it('should remove a cached entry', () => {
      const cache = new SharedFileCache();

      cache.set('/file.ts', 'content');
      cache.invalidate('/file.ts');
      expect(cache.get('/file.ts')).toBeUndefined();
    });

    it('should be safe to invalidate non-existent entry', () => {
      const cache = new SharedFileCache();
      // Should not throw
      cache.invalidate('/nonexistent.ts');
    });

    it('should track invalidation count', () => {
      const cache = new SharedFileCache();

      cache.set('/file.ts', 'content');
      cache.invalidate('/file.ts');

      const stats = cache.getStats();
      expect(stats.invalidations).toBe(1);
    });
  });

  describe('clear', () => {
    it('should remove all entries', () => {
      const cache = new SharedFileCache();

      cache.set('/a.ts', 'a');
      cache.set('/b.ts', 'b');
      cache.clear();

      expect(cache.get('/a.ts')).toBeUndefined();
      expect(cache.get('/b.ts')).toBeUndefined();
    });
  });

  describe('getStats', () => {
    it('should track hits and misses', () => {
      const cache = new SharedFileCache();

      cache.set('/file.ts', 'content');
      cache.get('/file.ts');  // Hit
      cache.get('/file.ts');  // Hit
      cache.get('/other.ts'); // Miss

      const stats = cache.getStats();
      expect(stats.hits).toBe(2);
      expect(stats.misses).toBe(1);
      expect(stats.hitRate).toBeCloseTo(2 / 3, 2);
    });

    it('should report cache size in bytes', () => {
      const cache = new SharedFileCache();

      cache.set('/file.ts', 'hello'); // 5 bytes

      const stats = cache.getStats();
      expect(stats.currentBytes).toBe(5);
      expect(stats.entries).toBe(1);
    });
  });
});

describe('createSharedFileCache', () => {
  it('should create cache with default config', () => {
    const cache = createSharedFileCache();
    expect(cache).toBeInstanceOf(SharedFileCache);
  });

  it('should create cache with custom config', () => {
    const cache = createSharedFileCache({
      maxCacheBytes: 1024,
      ttlMs: 10000,
    });

    // Verify config by testing behavior
    cache.set('/file.ts', 'x'.repeat(600)); // Over 50% of 1024 — rejected
    expect(cache.get('/file.ts')).toBeUndefined();
  });
});
