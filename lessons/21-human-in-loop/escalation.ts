/**
 * Lesson 21: Escalation
 *
 * Handles escalation of approval requests based on
 * policies and triggers.
 *
 * USER CONTRIBUTION OPPORTUNITY:
 * The escalation rule matching can be customized.
 * Consider implementing:
 * - Time-based escalation (business hours)
 * - Workload-based escalation
 * - Skill-based routing
 */

import type {
  PendingAction,
  EscalationRule,
  EscalationTrigger,
  NotificationMethod,
  RiskLevel,
  HILEvent,
  HILEventListener,
} from './types.js';

// =============================================================================
// ESCALATION MANAGER
// =============================================================================

/**
 * Manages escalation rules and triggers.
 */
export class EscalationManager {
  private rules: EscalationRule[] = [];
  private listeners: Set<HILEventListener> = new Set();
  private escalationHistory: Map<string, Date[]> = new Map();

  constructor(rules: EscalationRule[] = []) {
    this.rules = rules.sort((a, b) => a.priority - b.priority);
  }

  /**
   * Add an escalation rule.
   */
  addRule(rule: EscalationRule): void {
    this.rules.push(rule);
    this.rules.sort((a, b) => a.priority - b.priority);
  }

  /**
   * Remove an escalation rule.
   */
  removeRule(name: string): boolean {
    const index = this.rules.findIndex((r) => r.name === name);
    if (index !== -1) {
      this.rules.splice(index, 1);
      return true;
    }
    return false;
  }

  /**
   * Check if an action should be escalated.
   */
  shouldEscalate(action: PendingAction): EscalationRule | null {
    for (const rule of this.rules) {
      if (this.matchesTrigger(action, rule.trigger)) {
        return rule;
      }
    }
    return null;
  }

  /**
   * Escalate an action.
   */
  async escalate(action: PendingAction, rule: EscalationRule): Promise<void> {
    // Record escalation
    this.recordEscalation(action.id);

    // Send notification
    await this.notify(action, rule);

    // Emit event
    this.emit({
      type: 'approval.escalated',
      action,
      escalateTo: rule.escalateTo,
    });
  }

  /**
   * Check if a trigger matches.
   */
  private matchesTrigger(action: PendingAction, trigger: EscalationTrigger): boolean {
    switch (trigger.type) {
      case 'timeout': {
        const age = Date.now() - action.requestedAt.getTime();
        return age >= trigger.durationMs;
      }

      case 'risk_level': {
        const levels: RiskLevel[] = ['none', 'low', 'medium', 'high', 'critical'];
        const actionLevel = levels.indexOf(action.risk.level);
        const minLevel = levels.indexOf(trigger.minLevel);
        return actionLevel >= minLevel;
      }

      case 'action_type': {
        return trigger.types.includes(action.type);
      }

      case 'repeated_rejection': {
        const history = this.escalationHistory.get(action.context.requestor) || [];
        const recentRejections = history.filter(
          (date) => Date.now() - date.getTime() < trigger.windowMs
        );
        return recentRejections.length >= trigger.count;
      }

      case 'custom': {
        return trigger.condition(action);
      }

      default:
        return false;
    }
  }

  /**
   * Send notification.
   */
  private async notify(
    action: PendingAction,
    rule: EscalationRule
  ): Promise<void> {
    const method = rule.notificationMethod;
    const message = this.formatNotification(action, rule);

    switch (method.type) {
      case 'console':
        console.log(`[ESCALATION] ${message}`);
        break;

      case 'email':
        // In production, would send actual email
        console.log(`[EMAIL to ${method.address}] ${message}`);
        break;

      case 'slack':
        // In production, would post to Slack
        console.log(`[SLACK to ${method.channel}] ${message}`);
        break;

      case 'webhook':
        // In production, would POST to webhook
        console.log(`[WEBHOOK to ${method.url}] ${message}`);
        break;

      case 'callback':
        method.handler(action);
        break;
    }
  }

  /**
   * Format notification message.
   */
  private formatNotification(action: PendingAction, rule: EscalationRule): string {
    return [
      `Action requires attention: ${action.description}`,
      `Type: ${action.type}`,
      `Risk: ${action.risk.level} (score: ${action.risk.score})`,
      `Escalated to: ${rule.escalateTo}`,
      `Reason: ${rule.name}`,
    ].join('\n');
  }

  /**
   * Record escalation for rate limiting.
   */
  private recordEscalation(actionId: string): void {
    const history = this.escalationHistory.get(actionId) || [];
    history.push(new Date());
    this.escalationHistory.set(actionId, history);

    // Clean up old history
    this.cleanupHistory();
  }

  /**
   * Clean up old escalation history.
   */
  private cleanupHistory(): void {
    const maxAge = 24 * 60 * 60 * 1000; // 24 hours
    const now = Date.now();

    for (const [id, dates] of this.escalationHistory) {
      const filtered = dates.filter((d) => now - d.getTime() < maxAge);
      if (filtered.length === 0) {
        this.escalationHistory.delete(id);
      } else {
        this.escalationHistory.set(id, filtered);
      }
    }
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
        console.error('Escalation listener error:', err);
      }
    }
  }
}

// =============================================================================
// ESCALATION RULE BUILDER
// =============================================================================

/**
 * Fluent builder for escalation rules.
 */
export class EscalationRuleBuilder {
  private rule: Partial<EscalationRule> = {
    priority: 50,
  };

  /**
   * Set rule name.
   */
  name(name: string): EscalationRuleBuilder {
    this.rule.name = name;
    return this;
  }

  /**
   * Set timeout trigger.
   */
  afterTimeout(durationMs: number): EscalationRuleBuilder {
    this.rule.trigger = { type: 'timeout', durationMs };
    return this;
  }

  /**
   * Set risk level trigger.
   */
  whenRiskAtLeast(level: RiskLevel): EscalationRuleBuilder {
    this.rule.trigger = { type: 'risk_level', minLevel: level };
    return this;
  }

  /**
   * Set action type trigger.
   */
  forActionTypes(types: PendingAction['type'][]): EscalationRuleBuilder {
    this.rule.trigger = { type: 'action_type', types };
    return this;
  }

  /**
   * Set repeated rejection trigger.
   */
  afterRepeatedRejections(count: number, windowMs: number): EscalationRuleBuilder {
    this.rule.trigger = { type: 'repeated_rejection', count, windowMs };
    return this;
  }

  /**
   * Set custom trigger.
   */
  whenCustom(condition: (action: PendingAction) => boolean): EscalationRuleBuilder {
    this.rule.trigger = { type: 'custom', condition };
    return this;
  }

  /**
   * Set escalation target.
   */
  escalateTo(target: string): EscalationRuleBuilder {
    this.rule.escalateTo = target;
    return this;
  }

  /**
   * Set notification method to console.
   */
  notifyConsole(): EscalationRuleBuilder {
    this.rule.notificationMethod = { type: 'console' };
    return this;
  }

  /**
   * Set notification method to email.
   */
  notifyEmail(address: string): EscalationRuleBuilder {
    this.rule.notificationMethod = { type: 'email', address };
    return this;
  }

  /**
   * Set notification method to Slack.
   */
  notifySlack(channel: string, webhook?: string): EscalationRuleBuilder {
    this.rule.notificationMethod = { type: 'slack', channel, webhook };
    return this;
  }

  /**
   * Set notification method to webhook.
   */
  notifyWebhook(url: string): EscalationRuleBuilder {
    this.rule.notificationMethod = { type: 'webhook', url };
    return this;
  }

  /**
   * Set notification method to callback.
   */
  notifyCallback(handler: (action: PendingAction) => void): EscalationRuleBuilder {
    this.rule.notificationMethod = { type: 'callback', handler };
    return this;
  }

  /**
   * Set priority.
   */
  withPriority(priority: number): EscalationRuleBuilder {
    this.rule.priority = priority;
    return this;
  }

  /**
   * Build the rule.
   */
  build(): EscalationRule {
    if (!this.rule.name) {
      throw new Error('Rule name is required');
    }
    if (!this.rule.trigger) {
      throw new Error('Trigger is required');
    }
    if (!this.rule.escalateTo) {
      throw new Error('Escalation target is required');
    }
    if (!this.rule.notificationMethod) {
      this.rule.notificationMethod = { type: 'console' };
    }

    return this.rule as EscalationRule;
  }
}

// =============================================================================
// EXPORTS
// =============================================================================

export function createEscalationManager(
  rules?: EscalationRule[]
): EscalationManager {
  return new EscalationManager(rules);
}

export function createEscalationRuleBuilder(): EscalationRuleBuilder {
  return new EscalationRuleBuilder();
}

// =============================================================================
// COMMON ESCALATION RULES
// =============================================================================

/**
 * Pre-built common escalation rules.
 */
export const COMMON_ESCALATION_RULES = {
  /**
   * Escalate high-risk actions to security team.
   */
  highRiskToSecurity: new EscalationRuleBuilder()
    .name('high-risk-security')
    .whenRiskAtLeast('high')
    .escalateTo('security-team')
    .notifySlack('#security-alerts')
    .withPriority(10)
    .build(),

  /**
   * Escalate deployments to ops team.
   */
  deploymentsToOps: new EscalationRuleBuilder()
    .name('deployments-ops')
    .forActionTypes(['deployment'])
    .escalateTo('ops-team')
    .notifySlack('#deployments')
    .withPriority(20)
    .build(),

  /**
   * Escalate stale requests after 5 minutes.
   */
  staleRequestsToManager: new EscalationRuleBuilder()
    .name('stale-requests')
    .afterTimeout(5 * 60 * 1000)
    .escalateTo('manager')
    .notifyEmail('manager@example.com')
    .withPriority(30)
    .build(),

  /**
   * Escalate repeated rejections.
   */
  repeatedRejectionsToAdmin: new EscalationRuleBuilder()
    .name('repeated-rejections')
    .afterRepeatedRejections(3, 60 * 60 * 1000)
    .escalateTo('admin')
    .notifyConsole()
    .withPriority(40)
    .build(),
};
