/**
 * Lesson 21: Approval Workflow
 *
 * Manages approval queues and processing.
 * Handles pending actions and policy enforcement.
 */

import type {
  ApprovalWorkflow,
  ApprovalRequest,
  PendingAction,
  ApprovalResult,
  ApprovalStatus,
  ApprovalPolicy,
  ApprovalPattern,
  RiskAssessment,
  RiskLevel,
  ActionType,
  ActionData,
  ActionContext,
  HILEvent,
  HILEventListener,
} from './types.js';
import { generateId, DEFAULT_POLICY } from './types.js';

// =============================================================================
// RISK ASSESSOR
// =============================================================================

/**
 * Risk assessment rules.
 */
interface RiskRule {
  name: string;
  weight: number;
  assess: (action: PendingAction) => number; // 0-1 contribution
}

/**
 * Default risk assessment rules.
 */
const DEFAULT_RISK_RULES: RiskRule[] = [
  {
    name: 'file_deletion',
    weight: 30,
    assess: (action) => {
      if (action.type === 'file_delete') {
        const data = action.data as { type: 'file_delete'; recursive: boolean };
        return data.recursive ? 1.0 : 0.5;
      }
      return 0;
    },
  },
  {
    name: 'system_command',
    weight: 25,
    assess: (action) => {
      if (action.type === 'command_execute') {
        const data = action.data as { type: 'command_execute'; command: string };
        const dangerous = ['rm', 'sudo', 'chmod', 'chown', 'mkfs', 'dd'];
        return dangerous.some((cmd) => data.command.includes(cmd)) ? 1.0 : 0.3;
      }
      return 0;
    },
  },
  {
    name: 'database_modification',
    weight: 20,
    assess: (action) => {
      if (action.type === 'database_modify') {
        const data = action.data as { type: 'database_modify'; query: string };
        const dangerous = ['DELETE', 'DROP', 'TRUNCATE', 'ALTER'];
        return dangerous.some((kw) => data.query.toUpperCase().includes(kw))
          ? 1.0
          : 0.4;
      }
      return 0;
    },
  },
  {
    name: 'deployment',
    weight: 25,
    assess: (action) => {
      if (action.type === 'deployment') {
        const data = action.data as { type: 'deployment'; environment: string };
        return data.environment === 'production' ? 1.0 : 0.3;
      }
      return 0;
    },
  },
  {
    name: 'user_data',
    weight: 15,
    assess: (action) => {
      return action.type === 'user_data_access' ? 0.6 : 0;
    },
  },
];

/**
 * Assess risk for an action.
 */
export function assessRisk(
  action: PendingAction,
  rules: RiskRule[] = DEFAULT_RISK_RULES
): RiskAssessment {
  let totalScore = 0;
  const factors: { name: string; weight: number; description: string }[] = [];

  for (const rule of rules) {
    const contribution = rule.assess(action);
    if (contribution > 0) {
      totalScore += rule.weight * contribution;
      factors.push({
        name: rule.name,
        weight: rule.weight * contribution,
        description: `${rule.name}: ${(contribution * 100).toFixed(0)}% match`,
      });
    }
  }

  // Normalize to 0-100
  const score = Math.min(100, totalScore);

  // Determine level
  let level: RiskLevel;
  if (score < 10) level = 'none';
  else if (score < 30) level = 'low';
  else if (score < 50) level = 'medium';
  else if (score < 80) level = 'high';
  else level = 'critical';

  // Determine recommendation
  let recommendation: 'auto_approve' | 'require_approval' | 'block';
  if (level === 'none' || level === 'low') {
    recommendation = 'auto_approve';
  } else if (level === 'critical') {
    recommendation = 'block';
  } else {
    recommendation = 'require_approval';
  }

  return { level, score, factors, recommendation };
}

// =============================================================================
// PATTERN MATCHER
// =============================================================================

/**
 * Check if an action matches a pattern.
 */
export function matchesPattern(
  action: PendingAction,
  pattern: ApprovalPattern
): boolean {
  // Check action type
  if (pattern.actionType && action.type !== pattern.actionType) {
    return false;
  }

  // Check path pattern
  if (pattern.pathPattern) {
    const path = getPathFromAction(action);
    if (path && !matchGlob(path, pattern.pathPattern)) {
      return false;
    }
  }

  // Check command pattern
  if (pattern.commandPattern && action.type === 'command_execute') {
    const data = action.data as { type: 'command_execute'; command: string };
    const regex = new RegExp(pattern.commandPattern);
    if (!regex.test(data.command)) {
      return false;
    }
  }

  // Custom matcher
  if (pattern.matcher && !pattern.matcher(action)) {
    return false;
  }

  return true;
}

/**
 * Extract path from action if applicable.
 */
function getPathFromAction(action: PendingAction): string | null {
  switch (action.data.type) {
    case 'file_write':
    case 'file_delete':
      return (action.data as { path: string }).path;
    default:
      return null;
  }
}

/**
 * Simple glob matching.
 */
function matchGlob(path: string, pattern: string): boolean {
  const regex = pattern
    .replace(/\./g, '\\.')
    .replace(/\*/g, '.*')
    .replace(/\?/g, '.');
  return new RegExp(`^${regex}$`).test(path);
}

// =============================================================================
// APPROVAL QUEUE
// =============================================================================

/**
 * Manages the queue of pending approvals.
 */
export class ApprovalQueue implements ApprovalWorkflow {
  private pending: Map<string, PendingAction> = new Map();
  private policy: ApprovalPolicy;
  private listeners: Set<HILEventListener> = new Set();
  private timers: Map<string, NodeJS.Timeout> = new Map();

  constructor(policy: ApprovalPolicy = DEFAULT_POLICY) {
    this.policy = policy;
  }

  /**
   * Request approval for an action.
   */
  async requestApproval(request: ApprovalRequest): Promise<PendingAction> {
    const action = request.action;

    // Assess risk if not already done
    if (!action.risk) {
      action.risk = assessRisk(action);
    }

    // Apply policy
    const status = await this.applyPolicy(action);
    action.status = status;

    // If not auto-decided, add to queue
    if (status === 'pending') {
      this.pending.set(action.id, action);
      this.emit({ type: 'approval.requested', action });

      // Set timeout
      const timeout = action.timeout || this.policy.defaultTimeout;
      const timer = setTimeout(() => {
        this.expireAction(action.id);
      }, timeout);
      this.timers.set(action.id, timer);
    }

    return action;
  }

  /**
   * Process a pending action.
   */
  async processAction(actionId: string, result: ApprovalResult): Promise<void> {
    const action = this.pending.get(actionId);
    if (!action) {
      throw new Error(`Action ${actionId} not found`);
    }

    // Clear timeout
    const timer = this.timers.get(actionId);
    if (timer) {
      clearTimeout(timer);
      this.timers.delete(actionId);
    }

    // Update action
    action.status = result.decision === 'approved' ? 'approved' : 'rejected';
    action.result = result;

    // Remove from pending
    this.pending.delete(actionId);

    // Emit event
    this.emit({ type: 'approval.decided', action, result });
  }

  /**
   * Get all pending actions.
   */
  getPendingActions(): PendingAction[] {
    return Array.from(this.pending.values());
  }

  /**
   * Get action by ID.
   */
  getAction(actionId: string): PendingAction | undefined {
    return this.pending.get(actionId);
  }

  /**
   * Cancel a pending action.
   */
  async cancelAction(actionId: string, reason: string): Promise<void> {
    const action = this.pending.get(actionId);
    if (action) {
      action.status = 'rejected';
      action.result = {
        decision: 'rejected',
        decidedBy: 'system',
        decidedAt: new Date(),
        reason: `Cancelled: ${reason}`,
      };

      // Clear timeout
      const timer = this.timers.get(actionId);
      if (timer) {
        clearTimeout(timer);
        this.timers.delete(actionId);
      }

      this.pending.delete(actionId);
    }
  }

  /**
   * Apply policy to an action.
   */
  async applyPolicy(action: PendingAction): Promise<ApprovalStatus> {
    // Check block patterns first
    for (const pattern of this.policy.blockPatterns) {
      if (matchesPattern(action, pattern)) {
        this.emit({ type: 'policy.matched', action, pattern });
        return 'auto_rejected';
      }
    }

    // Check require patterns
    for (const pattern of this.policy.requirePatterns) {
      if (matchesPattern(action, pattern)) {
        this.emit({ type: 'policy.matched', action, pattern });
        return 'pending';
      }
    }

    // Check allow patterns
    for (const pattern of this.policy.allowPatterns) {
      if (matchesPattern(action, pattern)) {
        this.emit({ type: 'policy.matched', action, pattern });
        return 'auto_approved';
      }
    }

    // Check risk thresholds
    const riskOrder: RiskLevel[] = ['none', 'low', 'medium', 'high', 'critical'];
    const actionRiskIndex = riskOrder.indexOf(action.risk.level);
    const autoApproveIndex = riskOrder.indexOf(this.policy.autoApproveThreshold);
    const autoRejectIndex = riskOrder.indexOf(this.policy.autoRejectThreshold);

    if (actionRiskIndex <= autoApproveIndex) {
      return 'auto_approved';
    }

    if (actionRiskIndex >= autoRejectIndex) {
      return 'auto_rejected';
    }

    return 'pending';
  }

  /**
   * Handle action expiration.
   */
  private expireAction(actionId: string): void {
    const action = this.pending.get(actionId);
    if (action) {
      action.status = 'expired';
      this.pending.delete(actionId);
      this.timers.delete(actionId);
      this.emit({ type: 'approval.expired', action });
    }
  }

  /**
   * Update policy.
   */
  setPolicy(policy: ApprovalPolicy): void {
    this.policy = policy;
  }

  /**
   * Subscribe to events.
   */
  on(listener: HILEventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit(event: HILEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch (err) {
        console.error('HIL event listener error:', err);
      }
    }
  }

  /**
   * Clean up resources.
   */
  destroy(): void {
    for (const timer of this.timers.values()) {
      clearTimeout(timer);
    }
    this.timers.clear();
    this.pending.clear();
  }
}

// =============================================================================
// ACTION BUILDER
// =============================================================================

/**
 * Fluent builder for pending actions.
 */
export class ActionBuilder {
  private action: Partial<PendingAction> = {
    id: generateId(),
    requestedAt: new Date(),
    status: 'pending',
  };

  /**
   * Set action type and data.
   */
  ofType<T extends ActionData['type']>(
    type: T,
    data: Omit<Extract<ActionData, { type: T }>, 'type'>
  ): ActionBuilder {
    this.action.type = type as ActionType;
    this.action.data = { type, ...data } as ActionData;
    return this;
  }

  /**
   * Set description.
   */
  describe(description: string): ActionBuilder {
    this.action.description = description;
    return this;
  }

  /**
   * Set context.
   */
  withContext(context: ActionContext): ActionBuilder {
    this.action.context = context;
    return this;
  }

  /**
   * Set timeout.
   */
  withTimeout(timeoutMs: number): ActionBuilder {
    this.action.timeout = timeoutMs;
    return this;
  }

  /**
   * Set escalation target.
   */
  escalateTo(target: string): ActionBuilder {
    this.action.escalateTo = target;
    return this;
  }

  /**
   * Build the action.
   */
  build(): PendingAction {
    if (!this.action.type || !this.action.data) {
      throw new Error('Action type and data are required');
    }
    if (!this.action.description) {
      throw new Error('Description is required');
    }
    if (!this.action.context) {
      throw new Error('Context is required');
    }

    // Assess risk
    const partial = this.action as PendingAction;
    partial.risk = assessRisk(partial);

    return partial;
  }
}

// =============================================================================
// EXPORTS
// =============================================================================

export function createApprovalQueue(policy?: ApprovalPolicy): ApprovalQueue {
  return new ApprovalQueue(policy);
}

export function createActionBuilder(): ActionBuilder {
  return new ActionBuilder();
}
