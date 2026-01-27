/**
 * Exercise Tests: Lesson 26 - Metrics Calculator
 */
import { describe, it, expect } from 'vitest';
import { MetricsCalculator, IterationTrace } from './exercises/answers/exercise-1.js';

describe('MetricsCalculator', () => {
  const calculator = new MetricsCalculator();

  const createIteration = (
    num: number,
    inputTokens: number,
    outputTokens: number,
    cacheReadTokens: number = 0
  ): IterationTrace => ({
    iterationNumber: num,
    durationMs: 1000,
    tokens: { inputTokens, outputTokens, cacheReadTokens },
    toolCalls: 2,
  });

  it('should handle empty iterations', () => {
    const metrics = calculator.calculate([]);
    expect(metrics.totalInputTokens).toBe(0);
    expect(metrics.estimatedCost).toBe(0);
  });

  it('should calculate total tokens', () => {
    const iterations = [
      createIteration(1, 1000, 500),
      createIteration(2, 2000, 1000),
    ];

    const metrics = calculator.calculate(iterations);
    expect(metrics.totalInputTokens).toBe(3000);
    expect(metrics.totalOutputTokens).toBe(1500);
  });

  it('should calculate cache hit rate', () => {
    const iterations = [
      createIteration(1, 1000, 100, 800), // 80% cache hit
      createIteration(2, 1000, 100, 600), // 60% cache hit
    ];

    const hitRate = calculator.calculateCacheHitRate(iterations);
    expect(hitRate).toBe(0.7); // 1400/2000 = 70%
  });

  it('should calculate cost with cache savings', () => {
    const tokens = { inputTokens: 1000, outputTokens: 500, cacheReadTokens: 800 };

    const cost = calculator.calculateCost(tokens);

    // Fresh: 200 tokens at 0.003/1k = 0.0006
    // Cached: 800 tokens at 0.0003/1k = 0.00024
    // Output: 500 tokens at 0.015/1k = 0.0075
    // Total: ~0.00834
    expect(cost).toBeCloseTo(0.00834, 4);
  });

  it('should calculate cost savings from cache', () => {
    const iterations = [
      createIteration(1, 1000, 100, 800),
    ];

    const savings = calculator.calculateCostSaved(iterations);

    // Without cache: 1000 * 0.003/1k + 100 * 0.015/1k = 0.003 + 0.0015 = 0.0045
    // With cache: 200 * 0.003/1k + 800 * 0.0003/1k + 100 * 0.015/1k
    //           = 0.0006 + 0.00024 + 0.0015 = 0.00234
    // Savings: 0.0045 - 0.00234 = 0.00216
    expect(savings).toBeCloseTo(0.00216, 4);
  });

  it('should aggregate all metrics', () => {
    const iterations = [
      createIteration(1, 1000, 500, 500),
      createIteration(2, 2000, 1000, 1500),
    ];

    const metrics = calculator.calculate(iterations);

    expect(metrics.totalInputTokens).toBe(3000);
    expect(metrics.totalOutputTokens).toBe(1500);
    expect(metrics.totalCacheHits).toBe(2000);
    expect(metrics.totalToolCalls).toBe(4);
    expect(metrics.averageIterationDuration).toBe(1000);
    expect(metrics.cacheHitRate).toBeCloseTo(0.667, 2);
    expect(metrics.costSavedByCache).toBeGreaterThan(0);
  });
});
