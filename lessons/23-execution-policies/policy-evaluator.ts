/**
 * Lesson 23: Policy Evaluator
 *
 * Combines policy management with intent classification to make
 * context-aware execution decisions.
 *
 * This is the main integration point that evaluates tool calls
 * against policies, conditions, grants, and intent.
 */

import type {
  ExecutionPolicyConfig,
  PolicyCondition,
  ArgMatchPattern,
  ArgPatternMatcher,
  ToolCallInfo,
  EvaluationContext,
  PolicyDecision,
  PolicySuggestion,
  PolicyEvaluator as IPolicyEvaluator,
  PolicyEvent,
  PolicyEventListener,
  AuditEntry,
  AuditEventType,
  ToolCallRecord,
  Message,
  SessionInfo,
} from './types.js';
import { DEFAULT_POLICY_CONFIG } from './types.js';
import { PolicyManager } from './policy-manager.js';
import { IntentClassifier } from './intent-classifier.js';

// =============================================================================
// POLICY EVALUATOR
// =============================================================================

/**
 * Comprehensive policy evaluator that combines:
 * - Policy rules and conditions
 * - Permission grants
 * - Intent classification
 * - Audit logging
 */
export class PolicyEvaluator implements IPolicyEvaluator {
  private config: ExecutionPolicyConfig;
  private policyManager: PolicyManager;
  private intentClassifier: IntentClassifier;
  private eventListeners: Set<PolicyEventListener> = new Set();
  private auditLog: AuditEntry[] = [];
  private auditCounter = 0;
  private toolHistory: ToolCallRecord[] = [];

  constructor(
    config: Partial<ExecutionPolicyConfig> = {},
    options: {
      policyManager?: PolicyManager;
      intentClassifier?: IntentClassifier;
    } = {}
  ) {
    this.config = { ...DEFAULT_POLICY_CONFIG, ...config };
    this.policyManager = options.policyManager || new PolicyManager(config);
    this.intentClassifier = options.intentClassifier || new IntentClassifier();
  }

  // ===========================================================================
  // MAIN EVALUATION
  // ===========================================================================

  /**
   * Evaluate a tool call against all policies and context.
   */
  async evaluate(
    toolCall: ToolCallInfo,
    context: EvaluationContext
  ): Promise<PolicyDecision> {
    // Step 1: Check for existing permission grant
    const grant = this.policyManager.hasActiveGrant(toolCall.name, toolCall.args);
    if (grant) {
      const decision: PolicyDecision = {
        allowed: true,
        policy: 'allow',
        reason: `Permission granted: ${grant.reason || 'Active grant exists'}`,
        usedGrant: grant,
        promptRequired: false,
        riskLevel: this.policyManager.getRiskLevel(toolCall.name),
      };

      this.recordDecision(toolCall, decision, context);
      return decision;
    }

    // Step 2: Get base policy
    const toolPolicy = this.policyManager.getToolPolicy(toolCall.name);

    // Step 3: Check conditions to potentially override base policy
    const effectivePolicy = await this.evaluateConditions(
      toolCall,
      toolPolicy.conditions || [],
      context
    );

    // Step 4: Handle forbidden policy
    if (effectivePolicy.policy === 'forbidden') {
      const decision: PolicyDecision = {
        allowed: false,
        policy: 'forbidden',
        reason: effectivePolicy.reason || 'Tool is forbidden by policy',
        matchedCondition: effectivePolicy.matchedCondition,
        promptRequired: false,
        riskLevel: toolPolicy.riskLevel || 'critical',
        suggestions: this.generateSuggestions(toolCall, 'forbidden'),
      };

      this.recordDecision(toolCall, decision, context);
      return decision;
    }

    // Step 5: Handle allow policy
    if (effectivePolicy.policy === 'allow') {
      const decision: PolicyDecision = {
        allowed: true,
        policy: 'allow',
        reason: effectivePolicy.reason || 'Tool is allowed by policy',
        matchedCondition: effectivePolicy.matchedCondition,
        promptRequired: false,
        riskLevel: toolPolicy.riskLevel || 'low',
      };

      this.recordDecision(toolCall, decision, context);
      return decision;
    }

    // Step 6: Handle prompt policy with intent classification
    if (this.config.intentAware) {
      const intent = await this.intentClassifier.classify(
        toolCall,
        context.conversation
      );

      this.emit({ type: 'intent.classified', toolCall, intent });

      // High-confidence deliberate intent can auto-allow
      if (
        intent.type === 'deliberate' &&
        intent.confidence >= (this.config.intentThreshold || 0.8)
      ) {
        // Grant one-time permission based on intent
        const intentGrant = this.policyManager.grantFromIntent(
          toolCall.name,
          `intent_${Date.now()}`,
          {
            allowedArgs: toolCall.args,
            maxUses: 1,
            reason: 'Deliberate intent detected',
          }
        );

        const decision: PolicyDecision = {
          allowed: true,
          policy: 'prompt',
          reason: `Deliberate intent detected (confidence: ${(intent.confidence * 100).toFixed(0)}%)`,
          intent,
          usedGrant: intentGrant,
          promptRequired: false,
          riskLevel: toolPolicy.riskLevel || 'medium',
        };

        this.recordDecision(toolCall, decision, context);
        return decision;
      }

      // Accidental intent should block with explanation
      if (
        intent.type === 'accidental' ||
        intent.confidence < (this.config.intentThreshold || 0.8) * 0.5
      ) {
        const decision: PolicyDecision = {
          allowed: false,
          policy: 'prompt',
          reason: `Tool call appears unintentional (confidence: ${(intent.confidence * 100).toFixed(0)}%)`,
          intent,
          promptRequired: true,
          riskLevel: toolPolicy.riskLevel || 'medium',
          suggestions: this.generateSuggestions(toolCall, 'accidental'),
        };

        this.recordDecision(toolCall, decision, context);
        return decision;
      }

      // Uncertain intent requires prompt
      const decision: PolicyDecision = {
        allowed: false,
        policy: 'prompt',
        reason: 'User confirmation required',
        intent,
        promptRequired: true,
        riskLevel: toolPolicy.riskLevel || 'medium',
      };

      this.recordDecision(toolCall, decision, context);
      return decision;
    }

    // Step 7: Standard prompt policy (no intent classification)
    const decision: PolicyDecision = {
      allowed: false,
      policy: 'prompt',
      reason: effectivePolicy.reason || 'User confirmation required',
      matchedCondition: effectivePolicy.matchedCondition,
      promptRequired: true,
      riskLevel: toolPolicy.riskLevel || 'medium',
    };

    this.recordDecision(toolCall, decision, context);
    return decision;
  }

  // ===========================================================================
  // CONDITION EVALUATION
  // ===========================================================================

  /**
   * Evaluate conditions to find applicable policy override.
   */
  private async evaluateConditions(
    toolCall: ToolCallInfo,
    conditions: PolicyCondition[],
    context: EvaluationContext
  ): Promise<{
    policy: 'allow' | 'prompt' | 'forbidden';
    reason?: string;
    matchedCondition?: PolicyCondition;
  }> {
    for (const condition of conditions) {
      const matches = await this.matchesCondition(toolCall, condition, context);
      if (matches) {
        return {
          policy: condition.policy,
          reason: condition.reason,
          matchedCondition: condition,
        };
      }
    }

    // No condition matched, return base policy
    const basePolicy = this.policyManager.getToolPolicy(toolCall.name);
    return { policy: basePolicy.policy, reason: basePolicy.reason };
  }

  /**
   * Check if a tool call matches a specific condition.
   */
  private async matchesCondition(
    toolCall: ToolCallInfo,
    condition: PolicyCondition,
    context: EvaluationContext
  ): Promise<boolean> {
    // Check argument patterns
    if (condition.argMatch) {
      if (!this.matchesArgPattern(toolCall.args, condition.argMatch)) {
        return false;
      }
    }

    // Check context conditions
    if (condition.context) {
      if (!this.matchesContext(condition.context, context)) {
        return false;
      }
    }

    return true;
  }

  /**
   * Match tool arguments against a pattern.
   */
  private matchesArgPattern(
    args: Record<string, unknown>,
    pattern: ArgMatchPattern
  ): boolean {
    for (const [argName, matchValue] of Object.entries(pattern)) {
      const argValue = args[argName];

      // Handle regex pattern
      if (matchValue instanceof RegExp) {
        if (typeof argValue !== 'string' || !matchValue.test(argValue)) {
          return false;
        }
        continue;
      }

      // Handle advanced pattern matcher
      if (typeof matchValue === 'object' && matchValue !== null) {
        if (!this.matchesAdvancedPattern(argValue, matchValue as ArgPatternMatcher)) {
          return false;
        }
        continue;
      }

      // Handle string with regex syntax
      if (typeof matchValue === 'string' && matchValue.startsWith('/')) {
        try {
          const regexMatch = matchValue.match(/^\/(.+)\/([gimsuy]*)$/);
          if (regexMatch) {
            const regex = new RegExp(regexMatch[1], regexMatch[2]);
            if (typeof argValue !== 'string' || !regex.test(argValue)) {
              return false;
            }
            continue;
          }
        } catch {
          // Not a valid regex, treat as literal
        }
      }

      // Direct value comparison
      if (argValue !== matchValue) {
        return false;
      }
    }

    return true;
  }

  /**
   * Match against advanced pattern matcher.
   */
  private matchesAdvancedPattern(
    value: unknown,
    matcher: ArgPatternMatcher
  ): boolean {
    const strValue = String(value);

    if (matcher.contains && !strValue.includes(matcher.contains)) {
      return false;
    }

    if (matcher.startsWith && !strValue.startsWith(matcher.startsWith)) {
      return false;
    }

    if (matcher.endsWith && !strValue.endsWith(matcher.endsWith)) {
      return false;
    }

    if (matcher.pattern) {
      const regex = new RegExp(matcher.pattern);
      if (!regex.test(strValue)) {
        return false;
      }
    }

    if (matcher.oneOf && !matcher.oneOf.includes(value as string | number)) {
      return false;
    }

    if (matcher.notOneOf && matcher.notOneOf.includes(value as string | number)) {
      return false;
    }

    if (matcher.range) {
      const numValue = Number(value);
      if (isNaN(numValue)) return false;
      if (matcher.range.min !== undefined && numValue < matcher.range.min) {
        return false;
      }
      if (matcher.range.max !== undefined && numValue > matcher.range.max) {
        return false;
      }
    }

    return true;
  }

  /**
   * Match context conditions.
   */
  private matchesContext(
    contextCondition: NonNullable<PolicyCondition['context']>,
    context: EvaluationContext
  ): boolean {
    if (
      contextCondition.sessionState &&
      context.session.state !== contextCondition.sessionState
    ) {
      return false;
    }

    if (
      contextCondition.userRole &&
      context.session.user?.role !== contextCondition.userRole
    ) {
      return false;
    }

    if (contextCondition.safeHistoryDepth) {
      const recentCalls = this.toolHistory.slice(-contextCondition.safeHistoryDepth);
      const allSafe = recentCalls.every(
        call => call.decision.allowed && call.decision.riskLevel === 'low'
      );
      if (!allSafe) {
        return false;
      }
    }

    if (
      contextCondition.minIntentConfidence &&
      context.intent &&
      context.intent.confidence < contextCondition.minIntentConfidence
    ) {
      return false;
    }

    if (contextCondition.custom && !contextCondition.custom(context)) {
      return false;
    }

    return true;
  }

  // ===========================================================================
  // SUGGESTIONS
  // ===========================================================================

  /**
   * Generate suggestions for blocked tool calls.
   */
  private generateSuggestions(
    toolCall: ToolCallInfo,
    blockReason: 'forbidden' | 'accidental'
  ): PolicySuggestion[] {
    const suggestions: PolicySuggestion[] = [];

    if (blockReason === 'forbidden') {
      // Suggest safer alternatives
      const alternatives = this.findAlternatives(toolCall.name);
      for (const alt of alternatives) {
        suggestions.push({
          type: 'use_alternative',
          description: `Consider using ${alt} instead`,
          alternativeTool: alt,
        });
      }
    }

    if (blockReason === 'accidental') {
      suggestions.push({
        type: 'add_safeguard',
        description: 'Verify this action was intended by the user',
      });
    }

    // Suggest argument modifications for dangerous patterns
    const safeArgs = this.suggestSafeArgs(toolCall);
    if (safeArgs) {
      suggestions.push({
        type: 'modify_args',
        description: 'Use safer argument values',
        modifiedArgs: safeArgs,
      });
    }

    return suggestions;
  }

  /**
   * Find safer alternative tools.
   */
  private findAlternatives(toolName: string): string[] {
    const alternativeMap: Record<string, string[]> = {
      delete_file: ['move_file', 'rename_file'],
      rm: ['mv', 'trash'],
      bash: ['safe_bash', 'sandbox_bash'],
      write_file: ['write_file_safe', 'write_with_backup'],
    };

    return alternativeMap[toolName] || [];
  }

  /**
   * Suggest safer argument modifications.
   */
  private suggestSafeArgs(
    toolCall: ToolCallInfo
  ): Record<string, unknown> | null {
    const args = { ...toolCall.args };
    let modified = false;

    // Example: suggest --dry-run for dangerous commands
    if (toolCall.name === 'bash' && typeof args.command === 'string') {
      const dangerousCommands = ['rm', 'delete', 'drop', 'truncate'];
      if (dangerousCommands.some(cmd => (args.command as string).includes(cmd))) {
        args.command = `${args.command} --dry-run`;
        modified = true;
      }
    }

    return modified ? args : null;
  }

  // ===========================================================================
  // AUDIT LOGGING
  // ===========================================================================

  /**
   * Record a policy decision for auditing.
   */
  private recordDecision(
    toolCall: ToolCallInfo,
    decision: PolicyDecision,
    context: EvaluationContext
  ): void {
    // Update tool history
    this.toolHistory.push({
      tool: toolCall.name,
      args: toolCall.args,
      decision,
      executedAt: new Date(),
    });

    // Keep history bounded
    if (this.toolHistory.length > 100) {
      this.toolHistory = this.toolHistory.slice(-100);
    }

    // Emit event
    this.emit({ type: 'policy.evaluated', toolCall, decision });

    if (decision.allowed) {
      this.emit({ type: 'tool.allowed', tool: toolCall.name, decision });
    } else {
      this.emit({ type: 'tool.blocked', tool: toolCall.name, decision });
    }

    // Add audit entry if enabled
    if (this.config.auditLog) {
      const eventType: AuditEventType = decision.allowed
        ? decision.promptRequired
          ? 'permission_prompted'
          : 'policy_evaluated'
        : 'permission_denied';

      this.addAuditEntry({
        event: eventType,
        tool: toolCall.name,
        args: toolCall.args,
        decision,
        actor: {
          type: context.session.user ? 'user' : 'system',
          id: context.session.user?.id || 'system',
        },
      });
    }
  }

  /**
   * Add an entry to the audit log.
   */
  private addAuditEntry(
    entry: Omit<AuditEntry, 'id' | 'timestamp'>
  ): void {
    const fullEntry: AuditEntry = {
      id: `audit_${++this.auditCounter}_${Date.now()}`,
      timestamp: new Date(),
      ...entry,
    };

    this.auditLog.push(fullEntry);
    this.emit({ type: 'audit.logged', entry: fullEntry });

    // Keep audit log bounded
    if (this.auditLog.length > 1000) {
      this.auditLog = this.auditLog.slice(-1000);
    }
  }

  /**
   * Get audit log entries.
   */
  getAuditLog(filter?: {
    tool?: string;
    event?: AuditEventType;
    since?: Date;
  }): AuditEntry[] {
    let entries = [...this.auditLog];

    if (filter?.tool) {
      entries = entries.filter(e => e.tool === filter.tool);
    }
    if (filter?.event) {
      entries = entries.filter(e => e.event === filter.event);
    }
    if (filter?.since) {
      entries = entries.filter(e => e.timestamp >= filter.since!);
    }

    return entries;
  }

  /**
   * Export audit log to JSON.
   */
  exportAuditLog(): string {
    return JSON.stringify(this.auditLog, null, 2);
  }

  /**
   * Clear audit log.
   */
  clearAuditLog(): void {
    this.auditLog = [];
  }

  // ===========================================================================
  // EVENTS
  // ===========================================================================

  /**
   * Subscribe to policy events.
   */
  subscribe(listener: PolicyEventListener): () => void {
    this.eventListeners.add(listener);
    return () => this.eventListeners.delete(listener);
  }

  /**
   * Emit an event.
   */
  private emit(event: PolicyEvent): void {
    for (const listener of this.eventListeners) {
      try {
        listener(event);
      } catch (error) {
        console.error('Policy event listener error:', error);
      }
    }
  }

  // ===========================================================================
  // CONFIGURATION
  // ===========================================================================

  /**
   * Update configuration.
   */
  updateConfig(config: Partial<ExecutionPolicyConfig>): void {
    this.config = { ...this.config, ...config };
    this.policyManager.updateConfig(config);
  }

  /**
   * Get current configuration.
   */
  getConfig(): ExecutionPolicyConfig {
    return { ...this.config };
  }

  /**
   * Get policy manager for direct access.
   */
  getPolicyManager(): PolicyManager {
    return this.policyManager;
  }

  /**
   * Get intent classifier for direct access.
   */
  getIntentClassifier(): IntentClassifier {
    return this.intentClassifier;
  }

  /**
   * Get tool call history.
   */
  getToolHistory(): ToolCallRecord[] {
    return [...this.toolHistory];
  }

  /**
   * Clear tool call history.
   */
  clearHistory(): void {
    this.toolHistory = [];
  }
}

// =============================================================================
// CONTEXT BUILDER
// =============================================================================

/**
 * Helper to build evaluation context.
 */
export class EvaluationContextBuilder {
  private context: Partial<EvaluationContext> = {
    conversation: [],
    grants: [],
    toolHistory: [],
  };

  /**
   * Set the tool call being evaluated.
   */
  toolCall(call: ToolCallInfo): this {
    this.context.toolCall = call;
    return this;
  }

  /**
   * Set conversation history.
   */
  conversation(messages: Message[]): this {
    this.context.conversation = messages;
    return this;
  }

  /**
   * Add a message to conversation.
   */
  addMessage(role: Message['role'], content: string): this {
    this.context.conversation!.push({ role, content });
    return this;
  }

  /**
   * Set session info.
   */
  session(info: SessionInfo): this {
    this.context.session = info;
    return this;
  }

  /**
   * Create a default interactive session.
   */
  interactiveSession(userId?: string): this {
    this.context.session = {
      id: `session_${Date.now()}`,
      state: 'interactive',
      user: userId ? { id: userId } : undefined,
      startedAt: new Date(),
    };
    return this;
  }

  /**
   * Set existing grants.
   */
  grants(grants: EvaluationContext['grants']): this {
    this.context.grants = grants;
    return this;
  }

  /**
   * Set tool history.
   */
  toolHistory(history: ToolCallRecord[]): this {
    this.context.toolHistory = history;
    return this;
  }

  /**
   * Set custom metadata.
   */
  metadata(data: Record<string, unknown>): this {
    this.context.metadata = data;
    return this;
  }

  /**
   * Build the context.
   */
  build(): EvaluationContext {
    if (!this.context.toolCall) {
      throw new Error('toolCall is required');
    }
    if (!this.context.session) {
      this.interactiveSession();
    }

    return this.context as EvaluationContext;
  }
}

/**
 * Start building evaluation context.
 */
export function buildContext(): EvaluationContextBuilder {
  return new EvaluationContextBuilder();
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create a policy evaluator with common defaults.
 */
export function createPolicyEvaluator(
  options: {
    defaultPolicy?: 'allow' | 'prompt' | 'forbidden';
    intentAware?: boolean;
    intentThreshold?: number;
    auditLog?: boolean;
  } = {}
): PolicyEvaluator {
  return new PolicyEvaluator({
    defaultPolicy: options.defaultPolicy || 'prompt',
    intentAware: options.intentAware ?? true,
    intentThreshold: options.intentThreshold ?? 0.8,
    auditLog: options.auditLog ?? true,
  });
}

/**
 * Create a strict policy evaluator.
 */
export function createStrictEvaluator(): PolicyEvaluator {
  return new PolicyEvaluator({
    defaultPolicy: 'forbidden',
    intentAware: true,
    intentThreshold: 0.9,
    auditLog: true,
  });
}

/**
 * Create a permissive policy evaluator.
 */
export function createPermissiveEvaluator(): PolicyEvaluator {
  return new PolicyEvaluator({
    defaultPolicy: 'allow',
    intentAware: false,
    auditLog: false,
  });
}
