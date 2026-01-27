/**
 * Exercise Tests: Lesson 8 - Cache Marker Injection
 *
 * Run with: npm run test:lesson:8:exercise
 */

import { describe, it, expect, beforeEach } from 'vitest';

// Import from answers for testing
import {
  CacheOptimizer,
  estimateTokens,
  type Message,
  type CacheOptimizerConfig,
} from './exercises/answers/exercise-1.js';

// =============================================================================
// TEST DATA
// =============================================================================

const shortContent = 'Hello';
const longContent = 'A'.repeat(500); // ~125 tokens

const sampleMessages: Message[] = [
  { role: 'system', content: 'You are a helpful assistant.' },
  { role: 'user', content: 'What is 2+2?' },
  { role: 'assistant', content: 'The answer is 4.' },
  { role: 'user', content: 'Thanks!' },
];

const defaultConfig: CacheOptimizerConfig = {
  minTokensForCache: 100,
  maxCacheableMessages: 3,
};

// =============================================================================
// TESTS: estimateTokens helper
// =============================================================================

describe('estimateTokens', () => {
  it('should estimate ~1 token per 4 characters', () => {
    expect(estimateTokens('abcd')).toBe(1);
    expect(estimateTokens('abcdefgh')).toBe(2);
    expect(estimateTokens('a'.repeat(100))).toBe(25);
  });

  it('should round up', () => {
    expect(estimateTokens('abc')).toBe(1); // 0.75 -> 1
    expect(estimateTokens('abcde')).toBe(2); // 1.25 -> 2
  });

  it('should handle empty string', () => {
    expect(estimateTokens('')).toBe(0);
  });
});

// =============================================================================
// TESTS: CacheOptimizer - optimize
// =============================================================================

describe('CacheOptimizer - optimize', () => {
  let optimizer: CacheOptimizer;

  beforeEach(() => {
    optimizer = new CacheOptimizer(defaultConfig);
  });

  it('should add cache_control to system messages', () => {
    const optimized = optimizer.optimize(sampleMessages);

    expect(optimized[0].cache_control).toEqual({ type: 'ephemeral' });
  });

  it('should add cache_control to messages meeting token threshold', () => {
    const messages: Message[] = [
      { role: 'user', content: longContent }, // ~125 tokens, > 100 threshold
    ];

    const optimized = optimizer.optimize(messages);

    expect(optimized[0].cache_control).toBeDefined();
  });

  it('should not add cache_control to short messages', () => {
    const messages: Message[] = [
      { role: 'user', content: shortContent },
    ];

    const optimized = optimizer.optimize(messages);

    expect(optimized[0].cache_control).toBeUndefined();
  });

  it('should respect maxCacheableMessages limit', () => {
    const messages: Message[] = [
      { role: 'system', content: longContent },
      { role: 'user', content: longContent },
      { role: 'assistant', content: longContent },
      { role: 'user', content: longContent },
      { role: 'assistant', content: longContent },
    ];

    const optimized = optimizer.optimize(messages);
    const cachedCount = optimized.filter(m => m.cache_control).length;

    expect(cachedCount).toBe(3); // maxCacheableMessages
  });

  it('should not mutate original messages', () => {
    const original = [...sampleMessages];
    optimizer.optimize(sampleMessages);

    expect(sampleMessages).toEqual(original);
    expect(sampleMessages[0]).not.toHaveProperty('cache_control');
  });

  it('should handle empty messages array', () => {
    const optimized = optimizer.optimize([]);

    expect(optimized).toEqual([]);
  });
});

// =============================================================================
// TESTS: CacheOptimizer - statistics
// =============================================================================

describe('CacheOptimizer - statistics', () => {
  let optimizer: CacheOptimizer;

  beforeEach(() => {
    optimizer = new CacheOptimizer(defaultConfig);
  });

  it('should track cache hits', () => {
    optimizer.recordCacheHit(100);
    optimizer.recordCacheHit(50);

    const stats = optimizer.getStats();

    expect(stats.totalHits).toBe(2);
    expect(stats.tokensFromCache).toBe(150);
  });

  it('should track cache misses', () => {
    optimizer.recordCacheMiss(200);
    optimizer.recordCacheMiss(100);

    const stats = optimizer.getStats();

    expect(stats.totalMisses).toBe(2);
    expect(stats.tokensFetched).toBe(300);
  });

  it('should calculate estimated savings', () => {
    optimizer.recordCacheHit(100);
    optimizer.recordCacheMiss(100);

    const stats = optimizer.getStats();

    expect(stats.estimatedSavings).toBe(50); // 100 / 200 * 100
  });

  it('should return copy of stats', () => {
    optimizer.recordCacheHit(100);

    const stats1 = optimizer.getStats();
    const stats2 = optimizer.getStats();

    expect(stats1).not.toBe(stats2);
    expect(stats1).toEqual(stats2);
  });

  it('should reset statistics', () => {
    optimizer.recordCacheHit(100);
    optimizer.recordCacheMiss(50);

    optimizer.resetStats();
    const stats = optimizer.getStats();

    expect(stats.totalHits).toBe(0);
    expect(stats.totalMisses).toBe(0);
    expect(stats.tokensFromCache).toBe(0);
    expect(stats.tokensFetched).toBe(0);
  });

  it('should handle zero tokens gracefully', () => {
    const stats = optimizer.getStats();

    expect(stats.estimatedSavings).toBe(0);
  });
});
