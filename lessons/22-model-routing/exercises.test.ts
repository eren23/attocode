/**
 * Exercise Tests: Lesson 22 - Complexity Router
 */
import { describe, it, expect } from 'vitest';
import { ComplexityRouter } from './exercises/answers/exercise-1.js';

describe('ComplexityRouter', () => {
  const router = new ComplexityRouter();

  it('should route simple tasks to haiku', () => {
    const result = router.route({
      taskType: 'simple',
      estimatedTokens: 100,
      requiresTools: false,
      qualityRequirement: 'standard',
    });
    expect(result.model).toBe('claude-3-haiku');
    expect(result.complexity).toBe('simple');
  });

  it('should route moderate tasks to sonnet', () => {
    const result = router.route({
      taskType: 'coding',
      estimatedTokens: 300,
      requiresTools: false,
      qualityRequirement: 'high',
    });
    expect(result.model).toBe('claude-3-sonnet');
    expect(result.complexity).toBe('moderate');
  });

  it('should route complex tasks to opus', () => {
    const result = router.route({
      taskType: 'reasoning',
      estimatedTokens: 3000,
      requiresTools: true,
      qualityRequirement: 'maximum',
    });
    expect(result.model).toBe('claude-3-opus');
    expect(result.complexity).toBe('complex');
  });

  it('should calculate complexity scores correctly', () => {
    expect(router.calculateComplexity({
      taskType: 'simple',
      estimatedTokens: 100,
      requiresTools: false,
      qualityRequirement: 'standard',
    })).toBeLessThan(30);

    expect(router.calculateComplexity({
      taskType: 'reasoning',
      estimatedTokens: 3000,
      requiresTools: true,
      qualityRequirement: 'maximum',
    })).toBeGreaterThanOrEqual(60);
  });

  it('should include reasons in decision', () => {
    const result = router.route({
      taskType: 'reasoning',
      estimatedTokens: 100,
      requiresTools: false,
      qualityRequirement: 'standard',
    });
    expect(result.reason).toContain('reasoning');
  });
});
