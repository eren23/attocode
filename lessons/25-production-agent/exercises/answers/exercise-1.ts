/**
 * Exercise 25: Feature Flag Manager - REFERENCE SOLUTION
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

export class FeatureFlagManager {
  private flags: Map<string, FeatureFlag> = new Map();

  registerFlag(flag: FeatureFlag): void {
    this.flags.set(flag.name, flag);
  }

  isEnabled(flagName: string, context?: EvaluationContext): boolean {
    const flag = this.flags.get(flagName);
    if (!flag) return false;

    // Base check
    if (!flag.enabled) return false;

    // If no conditions, flag is simply enabled
    if (!flag.conditions || flag.conditions.length === 0) {
      return true;
    }

    // All conditions must pass
    if (!context) return false;

    return flag.conditions.every(condition =>
      this.evaluateCondition(condition, context)
    );
  }

  evaluateCondition(condition: FeatureCondition, context: EvaluationContext): boolean {
    switch (condition.type) {
      case 'user_role':
        return context.userRole === condition.value;

      case 'environment':
        return context.environment === condition.value;

      case 'percentage':
        if (!context.userId) return false;
        const hash = hashUserId(context.userId);
        return hash < (condition.value as number);

      default:
        return false;
    }
  }

  getAllFlags(): FeatureFlag[] {
    return Array.from(this.flags.values());
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
