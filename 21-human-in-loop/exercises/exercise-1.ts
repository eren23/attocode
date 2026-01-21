/**
 * Exercise 21: Risk Assessor
 * Implement action risk assessment with configurable rules.
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

/**
 * TODO: Implement RiskAssessor
 */
export class RiskAssessor {
  constructor(private _thresholds: { approve: number; block: number }) {}

  assess(_action: Action): RiskAssessment {
    // TODO: Assess risk based on action properties
    // - file_delete: high risk if recursive
    // - deployment: critical if production
    // - file_read: low risk
    // - Return appropriate level, score, factors, recommendation
    throw new Error('TODO: Implement assess');
  }

  getLevel(_score: number): RiskLevel {
    // TODO: Convert score to risk level
    // 0-10: none, 10-30: low, 30-50: medium, 50-80: high, 80+: critical
    throw new Error('TODO: Implement getLevel');
  }

  getRecommendation(_level: RiskLevel): RiskAssessment['recommendation'] {
    // TODO: Map risk level to recommendation
    throw new Error('TODO: Implement getRecommendation');
  }
}

export const DEFAULT_THRESHOLDS = { approve: 30, block: 80 };
