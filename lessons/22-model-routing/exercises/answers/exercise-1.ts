/**
 * Exercise 22: Complexity Router - REFERENCE SOLUTION
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

export class ComplexityRouter {
  constructor(
    private modelMapping: Record<ComplexityLevel, string> = {
      simple: 'claude-3-haiku',
      moderate: 'claude-3-sonnet',
      complex: 'claude-3-opus',
    }
  ) {}

  route(task: TaskContext): RoutingDecision {
    const score = this.calculateComplexity(task);
    const complexity = this.getComplexityLevel(score);
    const model = this.modelMapping[complexity];

    const reasons: string[] = [];
    if (task.taskType === 'reasoning') reasons.push('reasoning task');
    if (task.qualityRequirement === 'maximum') reasons.push('maximum quality required');
    if (task.estimatedTokens > 2000) reasons.push('large context');
    if (task.requiresTools) reasons.push('requires tools');

    return {
      model,
      reason: reasons.length > 0 ? reasons.join(', ') : 'standard routing',
      complexity,
      score,
    };
  }

  calculateComplexity(task: TaskContext): number {
    let score = 0;

    // Task type factor
    if (task.taskType === 'reasoning') score += 40;
    else if (task.taskType === 'coding') score += 25;
    else score += 10;

    // Token count factor
    if (task.estimatedTokens > 2000) score += 20;
    else if (task.estimatedTokens > 500) score += 10;

    // Tools factor
    if (task.requiresTools) score += 15;

    // Quality requirement factor
    if (task.qualityRequirement === 'maximum') score += 30;
    else if (task.qualityRequirement === 'high') score += 15;

    return Math.min(100, score);
  }

  getComplexityLevel(score: number): ComplexityLevel {
    if (score < 30) return 'simple';
    if (score < 60) return 'moderate';
    return 'complex';
  }
}
