/**
 * Exercise 21: Risk Assessor - REFERENCE SOLUTION
 */

export type RiskLevel = 'none' | 'low' | 'medium' | 'high' | 'critical';

export interface RiskAssessment {
  level: RiskLevel;
  score: number;
  factors: string[];
  recommendation: 'auto_approve' | 'require_approval' | 'block';
}

export interface Action {
  type: string;
  target: string;
  recursive?: boolean;
  environment?: string;
}

export class RiskAssessor {
  constructor(private thresholds: { approve: number; block: number }) {}

  assess(action: Action): RiskAssessment {
    let score = 0;
    const factors: string[] = [];

    // Evaluate action type
    switch (action.type) {
      case 'file_delete':
        score += action.recursive ? 70 : 40;
        factors.push(action.recursive ? 'recursive_delete' : 'file_delete');
        break;
      case 'deployment':
        score += action.environment === 'production' ? 85 : 30;
        factors.push(`deployment_${action.environment}`);
        break;
      case 'file_read':
        score += 5;
        factors.push('file_read');
        break;
      case 'command_execute':
        score += 50;
        factors.push('command_execute');
        break;
      default:
        score += 20;
        factors.push('unknown_action');
    }

    const level = this.getLevel(score);
    const recommendation = this.getRecommendation(level);

    return { level, score, factors, recommendation };
  }

  getLevel(score: number): RiskLevel {
    if (score < 10) return 'none';
    if (score < 30) return 'low';
    if (score < 50) return 'medium';
    if (score < 80) return 'high';
    return 'critical';
  }

  getRecommendation(level: RiskLevel): RiskAssessment['recommendation'] {
    if (level === 'none' || level === 'low') return 'auto_approve';
    if (level === 'critical') return 'block';
    return 'require_approval';
  }
}

export const DEFAULT_THRESHOLDS = { approve: 30, block: 80 };
