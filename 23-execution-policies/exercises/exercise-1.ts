/**
 * Exercise 23: Policy Matcher
 * Implement tool policy evaluation with conditions.
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

/**
 * TODO: Implement PolicyMatcher
 */
export class PolicyMatcher {
  private rules: Map<string, PolicyRule> = new Map();

  constructor(private _defaultPolicy: PolicyDecision = 'prompt') {}

  addRule(_rule: PolicyRule): void {
    // TODO: Store rule by tool name
    throw new Error('TODO: Implement addRule');
  }

  evaluate(_toolCall: ToolCall): EvaluationResult {
    // TODO: Evaluate tool call against rules
    // 1. Find matching rule
    // 2. Check conditions
    // 3. Return decision with reason
    throw new Error('TODO: Implement evaluate');
  }

  matchesCondition(_args: Record<string, unknown>, _condition: PolicyCondition): boolean {
    // TODO: Check if args match condition patterns
    // Support string equality and regex matching
    throw new Error('TODO: Implement matchesCondition');
  }
}
