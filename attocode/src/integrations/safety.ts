/**
 * Lesson 23: Safety Integration
 *
 * Integrates sandboxing (Lesson 20) and human-in-the-loop (Lesson 21)
 * into the production agent. Provides execution safety and approval workflows.
 */

import { resolve, isAbsolute, dirname } from 'node:path';
import { realpathSync, existsSync, lstatSync } from 'node:fs';
import type {
  SandboxConfig,
  PolicyEngineConfig,
  HumanInLoopConfig,
  ToolCall,
  ToolResult,
  ApprovalRequest,
} from '../types.js';
import {
  evaluateBashCommandByProfile,
  isToolAllowedByProfile,
  resolvePolicyProfile,
} from './policy-engine.js';
import { stripCdPrefix } from './bash-policy.js';
import { logger } from './logger.js';

// =============================================================================
// SANDBOX MANAGER
// =============================================================================

/**
 * Manages sandboxed execution of tools.
 */
export class SandboxManager {
  private config: SandboxConfig;
  private policyEngineConfig?: PolicyEngineConfig;

  constructor(config: SandboxConfig, policyEngineConfig?: PolicyEngineConfig | false) {
    this.config = config;
    this.policyEngineConfig = policyEngineConfig || undefined;
  }

  /**
   * Check if a command is allowed.
   */
  isCommandAllowed(command: string): { allowed: boolean; reason?: string } {
    const { profile } = resolvePolicyProfile({
      policyEngine: this.policyEngineConfig,
      sandboxConfig: this.config,
    });

    const policyDecision = evaluateBashCommandByProfile(command, profile);
    if (!policyDecision.allowed) {
      return { allowed: false, reason: policyDecision.reason };
    }

    // Check blocked patterns first
    for (const blocked of this.config.blockedCommands || []) {
      if (command.includes(blocked)) {
        return { allowed: false, reason: `Blocked pattern: ${blocked}` };
      }
    }

    // Check allowed commands
    const allowedCommands = this.config.allowedCommands || [];
    const effective = stripCdPrefix(command);
    const commandBase = effective.split(' ')[0];

    if (allowedCommands.length > 0 && !allowedCommands.includes(commandBase)) {
      const suggestions = allowedCommands.slice(0, 10).join(', ');
      return {
        allowed: false,
        reason: `Command '${commandBase}' is not in the sandbox allowlist. Use built-in tools (read_file, write_file, edit_file, glob, grep) instead, or use bash with an allowed command: ${suggestions}...`,
      };
    }

    return { allowed: true };
  }

  /**
   * Check if a path is allowed.
   * Resolves relative paths against cwd before comparison.
   * Uses realpath to resolve symlinks and prevent symlink escape attacks.
   */
  isPathAllowed(path: string): boolean {
    const allowedPaths = this.config.allowedPaths || ['.'];

    // Resolve the path, handling symlinks for security
    let resolvedPath: string;
    try {
      const absolutePath = isAbsolute(path) ? path : resolve(process.cwd(), path);

      // If path exists, use realpath to resolve symlinks
      if (existsSync(absolutePath)) {
        resolvedPath = realpathSync(absolutePath);
      } else {
        // Special case: broken symlink exists as a link entry but target is missing.
        // Deny to fail closed and avoid symlink-escape bypasses.
        try {
          const stat = lstatSync(absolutePath);
          if (stat.isSymbolicLink()) {
            return false;
          }
        } catch {
          // No direct entry - continue with parent-directory check.
        }

        // Path doesn't exist yet - recursively check that parent is allowed
        const parentDir = dirname(absolutePath);
        if (parentDir === absolutePath) {
          return false; // Root reached without match
        }
        return this.isPathAllowed(parentDir);
      }
    } catch {
      // realpath failed (broken symlink, permission denied, etc.)
      // Fail closed - deny access
      return false;
    }

    for (const allowed of allowedPaths) {
      let resolvedAllowed: string;
      try {
        const absoluteAllowed = isAbsolute(allowed) ? allowed : resolve(process.cwd(), allowed);
        // Use realpath if allowed path exists, otherwise just the absolute path
        resolvedAllowed = existsSync(absoluteAllowed)
          ? realpathSync(absoluteAllowed)
          : absoluteAllowed;
      } catch {
        continue; // Skip invalid allowed paths
      }

      // Check if resolved target is within resolved allowed path
      if (resolvedPath === resolvedAllowed || resolvedPath.startsWith(resolvedAllowed + '/')) {
        return true;
      }
    }

    return false;
  }

  /**
   * Get resource limits.
   */
  getResourceLimits(): NonNullable<SandboxConfig['resourceLimits']> {
    return this.config.resourceLimits || {
      maxCpuSeconds: 30,
      maxMemoryMB: 512,
      maxOutputBytes: 1024 * 1024,
      timeout: 60000,
    };
  }

  /**
   * Wrap execution with resource limits.
   */
  async executeWithLimits<T>(
    fn: () => Promise<T>,
    timeout?: number
  ): Promise<T> {
    const limits = this.getResourceLimits();
    const timeoutMs = timeout || limits.timeout;

    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(new Error(`Execution timeout: ${timeoutMs}ms`));
      }, timeoutMs);

      fn()
        .then((result) => {
          clearTimeout(timer);
          resolve(result);
        })
        .catch((err) => {
          clearTimeout(timer);
          reject(err);
        });
    });
  }

  /**
   * Validate tool call against sandbox rules.
   */
  validateToolCall(toolCall: ToolCall): { valid: boolean; reason?: string } {
    const args = toolCall.arguments as Record<string, unknown>;
    const { profile } = resolvePolicyProfile({
      policyEngine: this.policyEngineConfig,
      sandboxConfig: this.config,
    });

    const toolDecision = isToolAllowedByProfile(toolCall.name, profile);
    if (!toolDecision.allowed) {
      return { valid: false, reason: toolDecision.reason };
    }

    // Check for command execution tools
    if (toolCall.name === 'bash' || toolCall.name === 'shell' || toolCall.name === 'execute') {
      const command = String(args.command || args.cmd || '');
      const result = this.isCommandAllowed(command);
      return { valid: result.allowed, reason: result.reason };
    }

    // Check for file operation tools
    if (toolCall.name === 'read_file' || toolCall.name === 'write_file' || toolCall.name === 'edit_file') {
      const path = String(args.path || args.file || args.file_path || '');
      if (!this.isPathAllowed(path)) {
        return { valid: false, reason: `Path not allowed: ${path}` };
      }
    }

    return { valid: true };
  }
}

// =============================================================================
// HUMAN-IN-LOOP MANAGER
// =============================================================================

/**
 * Manages human approval workflows.
 */
export class HumanInLoopManager {
  private config: HumanInLoopConfig;
  private auditLog: AuditEntry[] = [];
  private pendingApprovals: Map<string, PendingApproval> = new Map();
  private approvalScope: ApprovalScope | null = null;

  // Audit log limits to prevent unbounded memory growth
  private readonly maxAuditEntries = 10000;
  private readonly auditTrimSize = 5000; // Keep this many when trimming

  constructor(config: HumanInLoopConfig) {
    this.config = config;
  }

  /**
   * Set an approval scope for pre-approved operations.
   * Used by subagents to reduce approval interruptions.
   */
  setApprovalScope(scope: ApprovalScope): void {
    this.approvalScope = scope;
  }

  /**
   * Check if a tool call is pre-approved by the current scope.
   */
  private isPreApproved(toolCall: ToolCall): boolean {
    if (!this.approvalScope) return false;

    const toolName = toolCall.name.toLowerCase();

    // Check require-approval list first (highest priority) — exact match only
    if (this.approvalScope.requireApproval?.some(t => toolName === t.toLowerCase())) {
      return false;
    }

    // Check auto-approve list — exact match only
    if (this.approvalScope.autoApprove?.some(t => toolName === t.toLowerCase())) {
      return true;
    }

    // Check scoped approval (tool + path match)
    if (this.approvalScope.scopedApprove?.[toolCall.name]) {
      const scope = this.approvalScope.scopedApprove[toolCall.name];
      const args = toolCall.arguments as Record<string, unknown>;
      const filePath = String(args.path || args.file_path || '');

      if (filePath && scope.paths.some(p => {
        // Directory-aware path matching
        const dir = p.endsWith('/**') ? p.slice(0, -3) : p;
        // Ensure directory boundary: "src/" matches "src/foo.ts" but not "src-backup/foo.ts"
        // If dir already ends with '/', use as-is; otherwise check exact match or '/' boundary
        if (dir.endsWith('/')) {
          return filePath.startsWith(dir);
        }
        return filePath === dir || filePath.startsWith(dir + '/');
      })) {
        return true;
      }
    }

    return false;
  }

  /**
   * Determine risk level of an action.
   */
  assessRisk(toolCall: ToolCall): RiskLevel {
    const toolName = toolCall.name.toLowerCase();
    const args = toolCall.arguments as Record<string, unknown>;

    // Check always-approve list (high risk)
    for (const pattern of this.config.alwaysApprove || []) {
      if (toolName.includes(pattern.toLowerCase())) {
        return 'high';
      }
    }

    // Check never-approve list (low risk, auto-approve)
    for (const pattern of this.config.neverApprove || []) {
      if (toolName.includes(pattern.toLowerCase())) {
        return 'low';
      }
    }

    // Heuristic risk assessment
    const highRiskPatterns = ['delete', 'remove', 'drop', 'truncate', 'wipe', 'destroy'];
    for (const pattern of highRiskPatterns) {
      if (toolName.includes(pattern)) {
        return 'high';
      }
    }

    const moderateRiskPatterns = ['write', 'modify', 'update'];
    for (const pattern of moderateRiskPatterns) {
      if (toolName.includes(pattern)) {
        return 'moderate';
      }
    }

    // Check for destructive arguments
    const argsStr = JSON.stringify(args).toLowerCase();
    if (argsStr.includes('--force') || argsStr.includes('-rf') || argsStr.includes('--hard')) {
      return 'moderate';
    }

    return 'low';
  }

  /**
   * Check if action needs approval.
   */
  needsApproval(toolCall: ToolCall): boolean {
    // Check pre-approval scope first (for subagent batched approvals)
    if (this.isPreApproved(toolCall)) {
      return false;
    }

    const risk = this.assessRisk(toolCall);
    const threshold = this.config.riskThreshold || 'high';

    const riskLevels: RiskLevel[] = ['low', 'moderate', 'high'];
    const riskIndex = riskLevels.indexOf(risk);
    const thresholdIndex = riskLevels.indexOf(threshold);

    return riskIndex >= thresholdIndex;
  }

  /**
   * Request approval for an action.
   */
  async requestApproval(
    toolCall: ToolCall,
    context: string
  ): Promise<ApprovalResult> {
    const risk = this.assessRisk(toolCall);

    // Auto-approve low risk if below threshold
    if (!this.needsApproval(toolCall)) {
      this.logAction(toolCall, true, 'auto', risk);
      return { approved: true, approver: 'auto' };
    }

    // Use custom handler if provided
    if (this.config.approvalHandler) {
      const approvalRequest: ApprovalRequest = {
        id: `approval-${Date.now()}`,
        action: toolCall.name,
        tool: toolCall.name,
        args: toolCall.arguments,
        risk,
        context,
      };

      const response = await this.executeWithTimeout(
        () => this.config.approvalHandler!(approvalRequest),
        this.config.approvalTimeout || 300000
      );

      // Convert ApprovalResponse to ApprovalResult
      const result: ApprovalResult = {
        approved: response.approved,
        reason: response.reason,
        modifiedArgs: response.modifiedArgs,
        approver: 'handler',
      };

      this.logAction(toolCall, result.approved, result.approver || 'handler', risk);
      return result;
    }

    // Default: console-based approval
    return this.consoleApproval(toolCall, context, risk);
  }

  /**
   * Console-based approval (for demos).
   */
  private async consoleApproval(
    toolCall: ToolCall,
    context: string,
    risk: RiskLevel
  ): Promise<ApprovalResult> {
    logger.info('Approval required', {
      tool: toolCall.name,
      risk: risk.toUpperCase(),
      arguments: JSON.stringify(toolCall.arguments).slice(0, 47),
      context: context.slice(0, 47),
    });

    // In non-interactive mode, auto-approve for demo
    logger.debug('Demo mode: Auto-approving');
    this.logAction(toolCall, true, 'demo', risk);
    return { approved: true, approver: 'demo' };
  }

  /**
   * Execute with timeout.
   */
  private async executeWithTimeout<T>(
    fn: () => Promise<T>,
    timeout: number
  ): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(new Error('Approval timeout'));
      }, timeout);

      fn()
        .then((result) => {
          clearTimeout(timer);
          resolve(result);
        })
        .catch((err) => {
          clearTimeout(timer);
          reject(err);
        });
    });
  }

  /**
   * Log an action to audit trail.
   * Trims the log when it exceeds maxAuditEntries to prevent unbounded growth.
   */
  private logAction(
    toolCall: ToolCall,
    approved: boolean,
    approver: string,
    risk: RiskLevel
  ): void {
    if (!this.config.auditLog) return;

    const entry: AuditEntry = {
      timestamp: new Date(),
      action: toolCall.name,
      args: toolCall.arguments,
      approved,
      approver,
      risk,
    };

    this.auditLog.push(entry);

    // Trim if exceeded max size - keep most recent entries
    if (this.auditLog.length > this.maxAuditEntries) {
      this.auditLog = this.auditLog.slice(-this.auditTrimSize);
    }
  }

  /**
   * Get audit log.
   */
  getAuditLog(): AuditEntry[] {
    return [...this.auditLog];
  }

  /**
   * Get audit summary.
   */
  getAuditSummary(): AuditSummary {
    const total = this.auditLog.length;
    const approved = this.auditLog.filter((e) => e.approved).length;
    const denied = total - approved;
    const byRisk = {
      low: this.auditLog.filter((e) => e.risk === 'low').length,
      medium: this.auditLog.filter((e) => e.risk === 'moderate').length,
      high: this.auditLog.filter((e) => e.risk === 'high').length,
    };

    return { total, approved, denied, byRisk };
  }

  /**
   * Clear audit log.
   */
  clearAuditLog(): void {
    this.auditLog = [];
  }
}

// =============================================================================
// COMBINED SAFETY MANAGER
// =============================================================================

/**
 * Combined safety manager for the production agent.
 */
export class SafetyManager {
  public sandbox: SandboxManager | null = null;
  public humanInLoop: HumanInLoopManager | null = null;

  constructor(
    sandboxConfig: SandboxConfig | false,
    hilConfig: HumanInLoopConfig | false,
    policyEngineConfig?: PolicyEngineConfig | false,
  ) {
    if (sandboxConfig && sandboxConfig.enabled !== false) {
      this.sandbox = new SandboxManager(sandboxConfig, policyEngineConfig);
    }

    if (hilConfig && hilConfig.enabled !== false) {
      this.humanInLoop = new HumanInLoopManager(hilConfig);
    }
  }

  /**
   * Validate a tool call against all safety rules.
   */
  async validateAndApprove(
    toolCall: ToolCall,
    context: string,
    options?: { skipHumanApproval?: boolean }
  ): Promise<{ allowed: boolean; reason?: string }> {
    // Sandbox validation
    if (this.sandbox) {
      const validation = this.sandbox.validateToolCall(toolCall);
      if (!validation.valid) {
        return { allowed: false, reason: validation.reason };
      }
    }

    // Human-in-loop approval
    if (this.humanInLoop) {
      if (!options?.skipHumanApproval && this.humanInLoop.needsApproval(toolCall)) {
        const result = await this.humanInLoop.requestApproval(toolCall, context);
        if (!result.approved) {
          return { allowed: false, reason: `Denied by ${result.approver}` };
        }
      }
    }

    return { allowed: true };
  }

  /**
   * Execute a tool call with safety wrapping.
   */
  async executeWithSafety<T>(
    fn: () => Promise<T>,
    toolCall: ToolCall,
    context: string
  ): Promise<T> {
    // Validate first
    const validation = await this.validateAndApprove(toolCall, context);
    if (!validation.allowed) {
      throw new Error(`Tool call blocked: ${validation.reason}`);
    }

    // Execute with sandbox limits if enabled
    if (this.sandbox) {
      return this.sandbox.executeWithLimits(fn);
    }

    return fn();
  }
}

// =============================================================================
// TYPES
// =============================================================================

/**
 * Approval scope for subagent pre-approval.
 * Allows specifying which tools and paths are pre-approved,
 * reducing interruptions during multi-agent workflows.
 */
export interface ApprovalScope {
  /** Tools that are always auto-approved (e.g., read_file, glob, grep) */
  autoApprove?: string[];
  /** Tools approved within specific path scopes */
  scopedApprove?: Record<string, { paths: string[] }>;
  /** Tools that always require approval regardless of scope */
  requireApproval?: string[];
}

/**
 * Risk levels for safety assessment.
 * Matches the risk property in ApprovalRequest from types.ts.
 */
type RiskLevel = 'low' | 'moderate' | 'high' | 'critical';

/**
 * Result of an approval request.
 * Extends ApprovalResponse with additional tracking info.
 */
interface ApprovalResult {
  approved: boolean;
  reason?: string;
  modifiedArgs?: Record<string, unknown>;
  /** Who approved the action (for audit trail) */
  approver?: string;
}

interface PendingApproval {
  id: string;
  toolCall: ToolCall;
  context: string;
  risk: RiskLevel;
  requestedAt: Date;
  resolve: (result: ApprovalResult) => void;
}

interface AuditEntry {
  timestamp: Date;
  action: string;
  args: unknown;
  approved: boolean;
  approver: string;
  risk: RiskLevel;
}

interface AuditSummary {
  total: number;
  approved: number;
  denied: number;
  byRisk: {
    low: number;
    medium: number;
    high: number;
  };
}

// =============================================================================
// FACTORY
// =============================================================================

export function createSafetyManager(
  sandboxConfig: SandboxConfig | false,
  hilConfig: HumanInLoopConfig | false,
  policyEngineConfig?: PolicyEngineConfig | false,
): SafetyManager {
  return new SafetyManager(sandboxConfig, hilConfig, policyEngineConfig);
}
