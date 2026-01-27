/**
 * Exercise 25: Feature Flag Manager
 * Implement feature flag evaluation for agent configuration.
 */

export interface FeatureFlag {
  name: string;
  enabled: boolean;
  conditions?: FeatureCondition[];
}

export interface FeatureCondition {
  type: 'user_role' | 'environment' | 'percentage';
  value: string | number;
}

export interface EvaluationContext {
  userId?: string;
  userRole?: string;
  environment?: string;
}

/**
 * TODO: Implement FeatureFlagManager
 */
export class FeatureFlagManager {
  private flags: Map<string, FeatureFlag> = new Map();

  registerFlag(_flag: FeatureFlag): void {
    // TODO: Store the flag
    throw new Error('TODO: Implement registerFlag');
  }

  isEnabled(_flagName: string, _context?: EvaluationContext): boolean {
    // TODO: Evaluate flag with optional conditions
    // If no conditions, return flag.enabled
    // If conditions exist, all must pass for flag to be enabled
    throw new Error('TODO: Implement isEnabled');
  }

  evaluateCondition(_condition: FeatureCondition, _context: EvaluationContext): boolean {
    // TODO: Check if context satisfies condition
    // user_role: context.userRole === value
    // environment: context.environment === value
    // percentage: hash(userId) % 100 < value
    throw new Error('TODO: Implement evaluateCondition');
  }

  getAllFlags(): FeatureFlag[] {
    // TODO: Return all registered flags
    throw new Error('TODO: Implement getAllFlags');
  }
}

// Simple hash function for percentage rollouts
export function hashUserId(userId: string): number {
  let hash = 0;
  for (let i = 0; i < userId.length; i++) {
    hash = (hash << 5) - hash + userId.charCodeAt(i);
    hash = hash & hash;
  }
  return Math.abs(hash) % 100;
}
