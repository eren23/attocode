/**
 * Exercise Tests: Lesson 16 - Reflection Loop
 */
import { describe, it, expect, vi } from 'vitest';
import { ReflectionLoop } from './exercises/answers/exercise-1.js';

describe('ReflectionLoop', () => {
  it('should run generate and critique', async () => {
    const loop = new ReflectionLoop({ maxIterations: 3, targetConfidence: 0.9 });

    const result = await loop.run(
      async () => 'initial',
      async () => ({ issues: [], suggestions: [], confidence: 0.95 }),
      async (o) => o
    );

    expect(result.output).toBe('initial');
    expect(result.finalConfidence).toBe(0.95);
  });

  it('should iterate until confidence met', async () => {
    const loop = new ReflectionLoop({ maxIterations: 5, targetConfidence: 0.8 });
    let confidence = 0.5;

    const result = await loop.run(
      async () => 'v1',
      async () => {
        const c = confidence;
        confidence += 0.2;
        return { issues: [], suggestions: [], confidence: c };
      },
      async (o, c) => o + '+improved'
    );

    expect(result.iterations).toBe(3);
    expect(result.finalConfidence).toBeGreaterThanOrEqual(0.8);
  });

  it('should stop at max iterations', async () => {
    const loop = new ReflectionLoop({ maxIterations: 2, targetConfidence: 0.99 });

    const result = await loop.run(
      async () => 'output',
      async () => ({ issues: ['issue'], suggestions: [], confidence: 0.5 }),
      async (o) => o
    );

    expect(result.iterations).toBe(2);
  });

  it('should collect all critiques', async () => {
    const loop = new ReflectionLoop({ maxIterations: 3, targetConfidence: 0.9 });
    let iter = 0;

    const result = await loop.run(
      async () => 'output',
      async () => ({ issues: [`issue-${iter++}`], suggestions: [], confidence: iter >= 2 ? 0.95 : 0.5 }),
      async (o) => o
    );

    expect(result.critiques).toHaveLength(2);
  });
});
