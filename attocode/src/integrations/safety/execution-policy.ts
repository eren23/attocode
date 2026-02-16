/**
 * Lesson 25: Execution Policy Integration
 *
 * Integrates execution policies and intent classification (from Lesson 23)
 * into the production agent. Provides three-tier tool access control
 * and intent-aware policy decisions.
 */

import type { ToolCall, Message } from '../../types.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Execution policy level.
 */
export type PolicyLevel = 'allow' | 'prompt' | 'forbidden';

/**
 * Intent classification result.
 */
export type IntentType = 'deliberate' | 'accidental' | 'inferred';

/**
 * Policy condition for conditional tool policies.
 */
export interface PolicyCondition {
  /** Argument pattern to match */
  argMatch?: Record<string, string | RegExp>;
  /** Context condition */
  contextMatch?: (context: PolicyContext) => boolean;
  /** Resulting policy if condition matches */
  policy: PolicyLevel;
  /** Reason for this condition */
  reason?: string;
}

/**
 * Tool policy configuration.
 */
export interface ToolPolicy {
  /** Base policy for this tool */
  policy: PolicyLevel;
  /** Conditional overrides */
  conditions?: PolicyCondition[];
  /** Reason for policy */
  reason?: string;
}

/**
 * Full policy configuration.
 */
export interface ExecutionPolicyConfig {
  /** Default policy for unlisted tools */
  defaultPolicy: PolicyLevel;
  /** Per-tool policies */
  toolPolicies: Record<string, ToolPolicy>;
  /** Enable intent-aware decisions */
  intentAware?: boolean;
  /** Minimum confidence for intent */
  intentConfidenceThreshold?: number;
}

/**
 * Context for policy evaluation.
 */
export interface PolicyContext {
  /** Conversation history */
  messages: Message[];
  /** Current user message */
  currentMessage?: string;
  /** Previous tool calls in this turn */
  previousToolCalls?: ToolCall[];
  /** Custom context data */
  custom?: Record<string, unknown>;
}

/**
 * Intent classification result.
 */
export interface IntentClassification {
  type: IntentType;
  confidence: number;
  evidence: string[];
}

/**
 * Permission grant (temporary permission).
 */
export interface PermissionGrant {
  id: string;
  toolName: string;
  argPattern?: Record<string, unknown>;
  grantedBy: 'user' | 'system' | 'inferred';
  expiresAt?: Date;
  usageCount?: number;
  maxUsages?: number;
  reason?: string;
}

/**
 * Policy evaluation result.
 */
export interface PolicyEvaluation {
  policy: PolicyLevel;
  reason: string;
  intent?: IntentClassification;
  grantUsed?: PermissionGrant;
  requiresApproval: boolean;
}

/**
 * Execution policy events.
 */
export type PolicyEvent =
  | { type: 'policy.evaluated'; tool: string; result: PolicyEvaluation }
  | { type: 'intent.classified'; tool: string; intent: IntentClassification }
  | { type: 'grant.created'; grant: PermissionGrant }
  | { type: 'grant.used'; grant: PermissionGrant }
  | { type: 'grant.expired'; grantId: string }
  | { type: 'tool.blocked'; tool: string; reason: string }
  | { type: 'tool.prompted'; tool: string };

export type PolicyEventListener = (event: PolicyEvent) => void;

// =============================================================================
// EXECUTION POLICY MANAGER
// =============================================================================

/**
 * ExecutionPolicyManager handles tool access control and intent classification.
 */
export class ExecutionPolicyManager {
  private config: ExecutionPolicyConfig;
  private grants = new Map<string, PermissionGrant>();
  private listeners: PolicyEventListener[] = [];
  private grantIdCounter = 0;

  constructor(config: Partial<ExecutionPolicyConfig> = {}) {
    this.config = {
      defaultPolicy: config.defaultPolicy ?? 'prompt',
      toolPolicies: config.toolPolicies ?? {},
      intentAware: config.intentAware ?? true,
      intentConfidenceThreshold: config.intentConfidenceThreshold ?? 0.7,
    };
  }

  /**
   * Evaluate policy for a tool call.
   */
  evaluate(
    toolCall: ToolCall,
    context: PolicyContext
  ): PolicyEvaluation {
    // Check for active grant first
    const grant = this.findGrant(toolCall);
    if (grant) {
      this.useGrant(grant);
      return {
        policy: 'allow',
        reason: `Allowed by grant: ${grant.reason || 'permission granted'}`,
        grantUsed: grant,
        requiresApproval: false,
      };
    }

    // Get base policy for tool
    const toolPolicy = this.config.toolPolicies[toolCall.name];
    let policy = toolPolicy?.policy ?? this.config.defaultPolicy;
    let reason = toolPolicy?.reason ?? 'Default policy';

    // Check conditions
    if (toolPolicy?.conditions) {
      for (const condition of toolPolicy.conditions) {
        if (this.matchesCondition(toolCall, context, condition)) {
          policy = condition.policy;
          reason = condition.reason || `Condition matched`;
          break;
        }
      }
    }

    // Classify intent if enabled
    let intent: IntentClassification | undefined;
    if (this.config.intentAware && policy === 'prompt') {
      intent = this.classifyIntent(toolCall, context);
      this.emit({ type: 'intent.classified', tool: toolCall.name, intent });

      // Adjust policy based on intent
      if (intent.type === 'deliberate' && intent.confidence >= this.config.intentConfidenceThreshold!) {
        policy = 'allow';
        reason = `Intent: deliberate (confidence: ${(intent.confidence * 100).toFixed(0)}%)`;
      }
    }

    const result: PolicyEvaluation = {
      policy,
      reason,
      intent,
      requiresApproval: policy === 'prompt',
    };

    this.emit({ type: 'policy.evaluated', tool: toolCall.name, result });

    if (policy === 'forbidden') {
      this.emit({ type: 'tool.blocked', tool: toolCall.name, reason });
    } else if (policy === 'prompt') {
      this.emit({ type: 'tool.prompted', tool: toolCall.name });
    }

    return result;
  }

  /**
   * Create a permission grant.
   */
  createGrant(options: Omit<PermissionGrant, 'id'>): PermissionGrant {
    const grant: PermissionGrant = {
      id: `grant_${++this.grantIdCounter}`,
      ...options,
    };

    this.grants.set(grant.id, grant);
    this.emit({ type: 'grant.created', grant });

    return grant;
  }

  /**
   * Revoke a grant.
   */
  revokeGrant(grantId: string): boolean {
    const existed = this.grants.delete(grantId);
    if (existed) {
      this.emit({ type: 'grant.expired', grantId });
    }
    return existed;
  }

  /**
   * Get active grants.
   */
  getActiveGrants(): PermissionGrant[] {
    this.cleanupExpiredGrants();
    return Array.from(this.grants.values());
  }

  /**
   * Subscribe to events.
   */
  on(listener: PolicyEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  /**
   * Update tool policy.
   */
  setToolPolicy(toolName: string, policy: ToolPolicy): void {
    this.config.toolPolicies[toolName] = policy;
  }

  /**
   * Get current config.
   */
  getConfig(): ExecutionPolicyConfig {
    return { ...this.config };
  }

  // -------------------------------------------------------------------------
  // PRIVATE METHODS
  // -------------------------------------------------------------------------

  private emit(event: PolicyEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }

  private findGrant(toolCall: ToolCall): PermissionGrant | undefined {
    this.cleanupExpiredGrants();

    for (const grant of this.grants.values()) {
      if (grant.toolName !== toolCall.name) continue;

      // Check arg pattern if specified
      if (grant.argPattern) {
        if (!this.matchesArgPattern(toolCall.arguments, grant.argPattern)) {
          continue;
        }
      }

      // Check usage limit
      if (grant.maxUsages !== undefined && (grant.usageCount ?? 0) >= grant.maxUsages) {
        continue;
      }

      return grant;
    }

    return undefined;
  }

  private useGrant(grant: PermissionGrant): void {
    grant.usageCount = (grant.usageCount ?? 0) + 1;
    this.emit({ type: 'grant.used', grant });

    // Check if grant should be removed
    if (grant.maxUsages !== undefined && grant.usageCount >= grant.maxUsages) {
      this.grants.delete(grant.id);
      this.emit({ type: 'grant.expired', grantId: grant.id });
    }
  }

  private cleanupExpiredGrants(): void {
    const now = new Date();
    for (const [id, grant] of this.grants) {
      if (grant.expiresAt && grant.expiresAt < now) {
        this.grants.delete(id);
        this.emit({ type: 'grant.expired', grantId: id });
      }
    }
  }

  private matchesCondition(
    toolCall: ToolCall,
    context: PolicyContext,
    condition: PolicyCondition
  ): boolean {
    // Check argument pattern
    if (condition.argMatch) {
      for (const [key, pattern] of Object.entries(condition.argMatch)) {
        const value = toolCall.arguments[key];
        if (value === undefined) return false;

        const stringValue = String(value);
        if (typeof pattern === 'string') {
          if (!stringValue.includes(pattern)) return false;
        } else if (pattern instanceof RegExp) {
          if (!pattern.test(stringValue)) return false;
        }
      }
    }

    // Check context condition
    if (condition.contextMatch) {
      if (!condition.contextMatch(context)) return false;
    }

    return true;
  }

  private matchesArgPattern(
    args: Record<string, unknown>,
    pattern: Record<string, unknown>
  ): boolean {
    for (const [key, value] of Object.entries(pattern)) {
      const argValue = args[key];
      if (argValue !== value) return false;
    }
    return true;
  }

  private classifyIntent(
    toolCall: ToolCall,
    context: PolicyContext
  ): IntentClassification {
    const evidence: string[] = [];
    let score = 0;

    // Check if tool name appears in recent user message
    const recentUserMessage = context.currentMessage || this.getLastUserMessage(context);
    if (recentUserMessage) {
      const normalizedTool = toolCall.name.toLowerCase().replace(/_/g, ' ');
      const normalizedMessage = recentUserMessage.toLowerCase();

      if (normalizedMessage.includes(normalizedTool) ||
          normalizedMessage.includes(toolCall.name.toLowerCase())) {
        score += 0.4;
        evidence.push('Tool name mentioned in user message');
      }

      // Check for imperative verbs suggesting intent
      const imperatives = ['please', 'can you', 'could you', 'i need', 'i want', 'do', 'run', 'execute'];
      if (imperatives.some(imp => normalizedMessage.includes(imp))) {
        score += 0.2;
        evidence.push('Imperative language detected');
      }
    }

    // Check if this tool was used before in conversation
    const previousToolCalls = context.previousToolCalls || [];
    if (previousToolCalls.some(tc => tc.name === toolCall.name)) {
      score += 0.2;
      evidence.push('Tool used previously in session');
    }

    // Check conversation flow
    if (context.messages.length >= 2) {
      const recentMessages = context.messages.slice(-3);
      const mentionsAction = recentMessages.some(m =>
        m.content.toLowerCase().includes(toolCall.name.toLowerCase())
      );
      if (mentionsAction) {
        score += 0.2;
        evidence.push('Tool discussed in recent messages');
      }
    }

    // Determine intent type
    let type: IntentType;
    if (score >= 0.6) {
      type = 'deliberate';
    } else if (score >= 0.3) {
      type = 'inferred';
    } else {
      type = 'accidental';
    }

    return {
      type,
      confidence: Math.min(1, score),
      evidence,
    };
  }

  private getLastUserMessage(context: PolicyContext): string | undefined {
    for (let i = context.messages.length - 1; i >= 0; i--) {
      if (context.messages[i].role === 'user') {
        return context.messages[i].content;
      }
    }
    return undefined;
  }
}

// =============================================================================
// FACTORY
// =============================================================================

/**
 * Create an execution policy manager.
 */
export function createExecutionPolicyManager(
  config?: Partial<ExecutionPolicyConfig>
): ExecutionPolicyManager {
  return new ExecutionPolicyManager(config);
}

// =============================================================================
// PRESET POLICIES
// =============================================================================

/**
 * Strict policy preset - minimal auto-allow.
 */
export const STRICT_POLICY: ExecutionPolicyConfig = {
  defaultPolicy: 'prompt',
  intentAware: true,
  intentConfidenceThreshold: 0.9,
  toolPolicies: {
    read_file: { policy: 'allow', reason: 'Read-only operation' },
    list_directory: { policy: 'allow', reason: 'Read-only operation' },
    search: { policy: 'allow', reason: 'Read-only operation' },
    write_file: { policy: 'prompt', reason: 'Modifies filesystem' },
    delete_file: { policy: 'forbidden', reason: 'Destructive operation' },
    bash: {
      policy: 'prompt',
      conditions: [
        { argMatch: { command: /^ls\s/ }, policy: 'allow', reason: 'Safe read command' },
        { argMatch: { command: /^rm\s/ }, policy: 'forbidden', reason: 'Destructive command' },
        { argMatch: { command: /^sudo\s/ }, policy: 'forbidden', reason: 'Elevated privileges' },
      ],
    },
  },
};

/**
 * Balanced policy preset - reasonable defaults.
 */
export const BALANCED_POLICY: ExecutionPolicyConfig = {
  defaultPolicy: 'prompt',
  intentAware: true,
  intentConfidenceThreshold: 0.7,
  toolPolicies: {
    read_file: { policy: 'allow' },
    list_directory: { policy: 'allow' },
    search: { policy: 'allow' },
    write_file: { policy: 'prompt' },
    delete_file: { policy: 'prompt' },
    bash: {
      policy: 'prompt',
      conditions: [
        { argMatch: { command: /^(ls|pwd|echo|cat|head|tail|grep)\s/ }, policy: 'allow' },
        { argMatch: { command: /^rm\s+-rf\s+\// }, policy: 'forbidden' },
      ],
    },
  },
};

/**
 * Permissive policy preset - trust the agent.
 */
export const PERMISSIVE_POLICY: ExecutionPolicyConfig = {
  defaultPolicy: 'allow',
  intentAware: false,
  toolPolicies: {
    bash: {
      policy: 'allow',
      conditions: [
        { argMatch: { command: /^rm\s+-rf\s+\// }, policy: 'forbidden' },
        { argMatch: { command: /^sudo\s/ }, policy: 'prompt' },
      ],
    },
    delete_file: { policy: 'prompt' },
  },
};
