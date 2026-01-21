/**
 * Exercise 23: Policy Matcher - REFERENCE SOLUTION
 */

export type PolicyDecision = 'allow' | 'prompt' | 'forbidden';

export interface PolicyRule {
  tool: string;
  defaultPolicy: PolicyDecision;
  conditions?: PolicyCondition[];
}

export interface PolicyCondition {
  argMatch: Record<string, string | RegExp>;
  policy: PolicyDecision;
  reason: string;
}

export interface ToolCall {
  name: string;
  args: Record<string, unknown>;
}

export interface EvaluationResult {
  decision: PolicyDecision;
  reason: string;
  matchedCondition?: PolicyCondition;
}

export class PolicyMatcher {
  private rules: Map<string, PolicyRule> = new Map();

  constructor(private defaultPolicy: PolicyDecision = 'prompt') {}

  addRule(rule: PolicyRule): void {
    this.rules.set(rule.tool, rule);
  }

  evaluate(toolCall: ToolCall): EvaluationResult {
    const rule = this.rules.get(toolCall.name);

    if (!rule) {
      return {
        decision: this.defaultPolicy,
        reason: 'No rule defined, using default policy',
      };
    }

    // Check conditions
    if (rule.conditions) {
      for (const condition of rule.conditions) {
        if (this.matchesCondition(toolCall.args, condition)) {
          return {
            decision: condition.policy,
            reason: condition.reason,
            matchedCondition: condition,
          };
        }
      }
    }

    return {
      decision: rule.defaultPolicy,
      reason: `Default policy for ${toolCall.name}`,
    };
  }

  matchesCondition(args: Record<string, unknown>, condition: PolicyCondition): boolean {
    for (const [key, pattern] of Object.entries(condition.argMatch)) {
      const value = args[key];
      if (value === undefined) return false;

      const strValue = String(value);

      if (pattern instanceof RegExp) {
        if (!pattern.test(strValue)) return false;
      } else {
        if (strValue !== pattern) return false;
      }
    }

    return true;
  }
}
