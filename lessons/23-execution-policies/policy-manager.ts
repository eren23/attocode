/**
 * Lesson 23: Policy Manager
 *
 * Manages execution policies for tool calls, including:
 * - Policy configuration and lookup
 * - Permission grant management
 * - Event emission for auditing
 */

import type {
  ExecutionPolicyConfig,
  ToolPolicy,
  PolicyLevel,
  PermissionGrant,
  PermissionStore,
  PermissionGrantor,
  ToolCallInfo,
  PolicyEvent,
  PolicyEventListener,
} from './types.js';
import { DEFAULT_POLICY_CONFIG, POLICY_PRESETS } from './types.js';

// =============================================================================
// PERMISSION STORE IMPLEMENTATION
// =============================================================================

/**
 * In-memory implementation of permission store.
 */
export class InMemoryPermissionStore implements PermissionStore {
  private grants: Map<string, PermissionGrant> = new Map();

  add(grant: PermissionGrant): void {
    this.grants.set(grant.id, grant);
  }

  hasGrant(tool: string, args: Record<string, unknown>): PermissionGrant | null {
    for (const grant of this.grants.values()) {
      // Check if grant is for this tool
      if (grant.tool !== tool) continue;

      // Check if grant is expired
      if (grant.expiresAt && grant.expiresAt < new Date()) {
        continue;
      }

      // Check if grant has remaining uses
      if (grant.maxUses !== undefined && grant.usedCount >= grant.maxUses) {
        continue;
      }

      // Check if args match (if specific args are required)
      if (grant.allowedArgs) {
        const argsMatch = Object.entries(grant.allowedArgs).every(
          ([key, value]) => args[key] === value
        );
        if (!argsMatch) continue;
      }

      return grant;
    }
    return null;
  }

  useGrant(grantId: string): boolean {
    const grant = this.grants.get(grantId);
    if (!grant) return false;

    grant.usedCount++;
    return true;
  }

  revoke(grantId: string): void {
    this.grants.delete(grantId);
  }

  clearExpired(): number {
    const now = new Date();
    let cleared = 0;

    for (const [id, grant] of this.grants) {
      const expired = grant.expiresAt && grant.expiresAt < now;
      const exhausted = grant.maxUses !== undefined && grant.usedCount >= grant.maxUses;

      if (expired || exhausted) {
        this.grants.delete(id);
        cleared++;
      }
    }

    return cleared;
  }

  getActive(): PermissionGrant[] {
    const now = new Date();
    return Array.from(this.grants.values()).filter(grant => {
      if (grant.expiresAt && grant.expiresAt < now) return false;
      if (grant.maxUses !== undefined && grant.usedCount >= grant.maxUses) return false;
      return true;
    });
  }
}

// =============================================================================
// POLICY MANAGER
// =============================================================================

/**
 * Manages execution policies and permissions.
 */
export class PolicyManager {
  private config: ExecutionPolicyConfig;
  private permissionStore: PermissionStore;
  private eventListeners: Set<PolicyEventListener> = new Set();
  private grantCounter = 0;

  constructor(
    config: Partial<ExecutionPolicyConfig> = {},
    permissionStore?: PermissionStore
  ) {
    this.config = { ...DEFAULT_POLICY_CONFIG, ...config };
    this.permissionStore = permissionStore || new InMemoryPermissionStore();
  }

  // ===========================================================================
  // POLICY CONFIGURATION
  // ===========================================================================

  /**
   * Get the policy for a specific tool.
   */
  getToolPolicy(toolName: string): ToolPolicy {
    const policy = this.config.toolPolicies[toolName];
    if (policy) return policy;

    // Return default policy wrapped as ToolPolicy
    return {
      policy: this.config.defaultPolicy,
      riskLevel: 'medium',
      reason: 'Default policy',
    };
  }

  /**
   * Set policy for a tool.
   */
  setToolPolicy(toolName: string, policy: ToolPolicy): void {
    this.config.toolPolicies[toolName] = policy;
  }

  /**
   * Apply a preset policy to a tool.
   */
  applyPreset(
    toolName: string,
    preset: keyof typeof POLICY_PRESETS
  ): void {
    this.config.toolPolicies[toolName] = {
      ...POLICY_PRESETS[preset],
    };
  }

  /**
   * Remove policy for a tool (falls back to default).
   */
  removeToolPolicy(toolName: string): void {
    delete this.config.toolPolicies[toolName];
  }

  /**
   * Get all configured tool policies.
   */
  getAllPolicies(): Record<string, ToolPolicy> {
    return { ...this.config.toolPolicies };
  }

  /**
   * Update the configuration.
   */
  updateConfig(updates: Partial<ExecutionPolicyConfig>): void {
    this.config = { ...this.config, ...updates };
  }

  /**
   * Get current configuration.
   */
  getConfig(): ExecutionPolicyConfig {
    return { ...this.config };
  }

  // ===========================================================================
  // POLICY LOOKUP
  // ===========================================================================

  /**
   * Get the base policy level for a tool (before conditions).
   */
  getBasePolicyLevel(toolName: string): PolicyLevel {
    return this.getToolPolicy(toolName).policy;
  }

  /**
   * Check if a tool is generally allowed (may still have conditions).
   */
  isToolAllowed(toolName: string): boolean {
    const policy = this.getToolPolicy(toolName);
    return policy.policy === 'allow';
  }

  /**
   * Check if a tool is forbidden (regardless of conditions).
   */
  isToolForbidden(toolName: string): boolean {
    const policy = this.getToolPolicy(toolName);
    return policy.policy === 'forbidden';
  }

  /**
   * Check if a tool requires prompting.
   */
  requiresPrompt(toolName: string): boolean {
    const policy = this.getToolPolicy(toolName);
    return policy.policy === 'prompt';
  }

  /**
   * Get risk level for a tool.
   */
  getRiskLevel(toolName: string): 'low' | 'medium' | 'high' | 'critical' {
    const policy = this.getToolPolicy(toolName);
    return policy.riskLevel || 'medium';
  }

  // ===========================================================================
  // PERMISSION GRANTS
  // ===========================================================================

  /**
   * Grant permission for a tool call.
   */
  grantPermission(
    tool: string,
    grantor: PermissionGrantor,
    options: {
      allowedArgs?: Record<string, unknown>;
      expiresIn?: number; // milliseconds
      maxUses?: number;
      reason?: string;
    } = {}
  ): PermissionGrant {
    const grant: PermissionGrant = {
      id: `grant_${++this.grantCounter}_${Date.now()}`,
      tool,
      allowedArgs: options.allowedArgs,
      grantedBy: grantor,
      grantedAt: new Date(),
      expiresAt: options.expiresIn
        ? new Date(Date.now() + options.expiresIn)
        : undefined,
      maxUses: options.maxUses,
      usedCount: 0,
      reason: options.reason,
    };

    this.permissionStore.add(grant);
    this.emit({ type: 'permission.granted', grant });

    return grant;
  }

  /**
   * Grant permission from user interaction.
   */
  grantFromUser(
    tool: string,
    userId: string,
    options: {
      allowedArgs?: Record<string, unknown>;
      expiresIn?: number;
      maxUses?: number;
      reason?: string;
    } = {}
  ): PermissionGrant {
    return this.grantPermission(tool, {
      type: 'user',
      id: userId,
      name: 'User',
    }, options);
  }

  /**
   * Grant permission from system/policy.
   */
  grantFromSystem(
    tool: string,
    policyName: string,
    options: {
      allowedArgs?: Record<string, unknown>;
      expiresIn?: number;
      maxUses?: number;
      reason?: string;
    } = {}
  ): PermissionGrant {
    return this.grantPermission(tool, {
      type: 'policy',
      id: policyName,
      name: policyName,
    }, options);
  }

  /**
   * Grant permission based on intent classification.
   */
  grantFromIntent(
    tool: string,
    intentId: string,
    options: {
      allowedArgs?: Record<string, unknown>;
      maxUses?: number;
      reason?: string;
    } = {}
  ): PermissionGrant {
    // Intent-based grants should be one-time by default
    return this.grantPermission(tool, {
      type: 'intent',
      id: intentId,
      name: 'Intent Classification',
    }, {
      ...options,
      maxUses: options.maxUses ?? 1,
    });
  }

  /**
   * Check if there's an active grant for a tool call.
   */
  hasActiveGrant(tool: string, args: Record<string, unknown>): PermissionGrant | null {
    return this.permissionStore.hasGrant(tool, args);
  }

  /**
   * Use a grant (marks it as used).
   */
  useGrant(grantId: string): boolean {
    return this.permissionStore.useGrant(grantId);
  }

  /**
   * Revoke a specific grant.
   */
  revokeGrant(grantId: string): void {
    this.permissionStore.revoke(grantId);
  }

  /**
   * Revoke all grants for a tool.
   */
  revokeToolGrants(tool: string): void {
    const grants = this.permissionStore.getActive();
    for (const grant of grants) {
      if (grant.tool === tool) {
        this.permissionStore.revoke(grant.id);
      }
    }
  }

  /**
   * Get all active grants.
   */
  getActiveGrants(): PermissionGrant[] {
    return this.permissionStore.getActive();
  }

  /**
   * Clean up expired grants.
   */
  cleanupGrants(): number {
    return this.permissionStore.clearExpired();
  }

  // ===========================================================================
  // QUICK CHECKS
  // ===========================================================================

  /**
   * Quick check if a tool call can proceed (has grant or is allowed).
   */
  canProceed(toolCall: ToolCallInfo): boolean {
    // Check for active grant first
    const grant = this.hasActiveGrant(toolCall.name, toolCall.args);
    if (grant) return true;

    // Check base policy
    const policy = this.getToolPolicy(toolCall.name);
    return policy.policy === 'allow';
  }

  /**
   * Quick check that returns the reason for the decision.
   */
  quickCheck(toolCall: ToolCallInfo): {
    allowed: boolean;
    reason: string;
    grant?: PermissionGrant;
  } {
    // Check for active grant
    const grant = this.hasActiveGrant(toolCall.name, toolCall.args);
    if (grant) {
      return {
        allowed: true,
        reason: `Permission granted: ${grant.reason || 'Active grant exists'}`,
        grant,
      };
    }

    // Check base policy
    const policy = this.getToolPolicy(toolCall.name);

    switch (policy.policy) {
      case 'allow':
        return {
          allowed: true,
          reason: policy.reason || 'Tool is allowed by policy',
        };

      case 'prompt':
        return {
          allowed: false,
          reason: policy.reason || 'Tool requires user approval',
        };

      case 'forbidden':
        return {
          allowed: false,
          reason: policy.reason || 'Tool is forbidden by policy',
        };
    }
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
  // BULK OPERATIONS
  // ===========================================================================

  /**
   * Configure multiple tool policies at once.
   */
  configurePolicies(policies: Record<string, ToolPolicy>): void {
    for (const [tool, policy] of Object.entries(policies)) {
      this.config.toolPolicies[tool] = policy;
    }
  }

  /**
   * Reset all policies to defaults.
   */
  resetPolicies(): void {
    this.config.toolPolicies = {};
  }

  /**
   * Export current configuration for persistence.
   */
  exportConfig(): string {
    return JSON.stringify(this.config, null, 2);
  }

  /**
   * Import configuration from JSON.
   */
  importConfig(json: string): void {
    const config = JSON.parse(json) as ExecutionPolicyConfig;
    this.config = { ...DEFAULT_POLICY_CONFIG, ...config };
  }
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create a policy manager with common presets.
 */
export function createPolicyManager(
  options: {
    defaultPolicy?: PolicyLevel;
    readOnlyTools?: string[];
    writeTools?: string[];
    destructiveTools?: string[];
    shellTools?: string[];
  } = {}
): PolicyManager {
  const config: Partial<ExecutionPolicyConfig> = {
    defaultPolicy: options.defaultPolicy || 'prompt',
    toolPolicies: {},
  };

  // Apply presets to tool categories
  for (const tool of options.readOnlyTools || []) {
    config.toolPolicies![tool] = { ...POLICY_PRESETS.readOnly };
  }
  for (const tool of options.writeTools || []) {
    config.toolPolicies![tool] = { ...POLICY_PRESETS.write };
  }
  for (const tool of options.destructiveTools || []) {
    config.toolPolicies![tool] = { ...POLICY_PRESETS.destructive };
  }
  for (const tool of options.shellTools || []) {
    config.toolPolicies![tool] = { ...POLICY_PRESETS.shell };
  }

  return new PolicyManager(config);
}

/**
 * Create a permissive policy manager (mostly allow).
 */
export function createPermissiveManager(
  forbiddenTools: string[] = []
): PolicyManager {
  const config: Partial<ExecutionPolicyConfig> = {
    defaultPolicy: 'allow',
    toolPolicies: {},
  };

  for (const tool of forbiddenTools) {
    config.toolPolicies![tool] = { ...POLICY_PRESETS.destructive };
  }

  return new PolicyManager(config);
}

/**
 * Create a restrictive policy manager (mostly prompt/forbidden).
 */
export function createRestrictiveManager(
  allowedTools: string[] = []
): PolicyManager {
  const config: Partial<ExecutionPolicyConfig> = {
    defaultPolicy: 'forbidden',
    toolPolicies: {},
  };

  for (const tool of allowedTools) {
    config.toolPolicies![tool] = { ...POLICY_PRESETS.readOnly };
  }

  return new PolicyManager(config);
}
