/**
 * Exercise 22: Complexity Router
 * Implement model selection based on task complexity.
 */

export type ComplexityLevel = 'simple' | 'moderate' | 'complex';

export interface TaskContext {
  taskType: 'coding' | 'reasoning' | 'simple';
  estimatedTokens: number;
  requiresTools: boolean;
  qualityRequirement: 'standard' | 'high' | 'maximum';
}

export interface RoutingDecision {
  model: string;
  reason: string;
  complexity: ComplexityLevel;
  score: number;
}

/**
 * TODO: Implement ComplexityRouter
 */
export class ComplexityRouter {
  constructor(
    private _modelMapping: Record<ComplexityLevel, string> = {
      simple: 'claude-3-haiku',
      moderate: 'claude-3-sonnet',
      complex: 'claude-3-opus',
    }
  ) {}

  route(_task: TaskContext): RoutingDecision {
    // TODO: Calculate complexity score and route to appropriate model
    // Factors: taskType (reasoning = +40), estimatedTokens > 2000 (+20),
    // requiresTools (+15), qualityRequirement maximum (+30)
    throw new Error('TODO: Implement route');
  }

  calculateComplexity(_task: TaskContext): number {
    // TODO: Calculate complexity score 0-100
    throw new Error('TODO: Implement calculateComplexity');
  }

  getComplexityLevel(_score: number): ComplexityLevel {
    // TODO: Convert score to level
    // 0-30: simple, 30-60: moderate, 60+: complex
    throw new Error('TODO: Implement getComplexityLevel');
  }
}
