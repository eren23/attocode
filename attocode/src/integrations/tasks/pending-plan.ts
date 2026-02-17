/**
 * Pending Plan Manager
 *
 * Manages plans that are awaiting user approval before execution.
 * Used in "plan mode" where write operations are intercepted and queued
 * as proposed changes rather than being executed immediately.
 *
 * @example
 * ```typescript
 * const planManager = createPendingPlanManager();
 *
 * // In plan mode, intercept a write operation
 * planManager.addProposedChange({
 *   tool: 'write_file',
 *   args: { path: 'src/main.ts', content: '...' },
 *   reason: 'Create entry point for the application',
 * });
 *
 * // User approves the plan
 * const changes = planManager.approve();
 * for (const change of changes) {
 *   await executeTool(change.tool, change.args);
 * }
 * ```
 */

// =============================================================================
// TYPES
// =============================================================================

/**
 * Status of a pending plan.
 */
export type PlanStatus = 'pending' | 'approved' | 'rejected' | 'partially_approved';

/**
 * A proposed change that will be executed if the plan is approved.
 */
export interface ProposedChange {
  /** Unique ID for this change */
  id: string;

  /** The tool that would be called */
  tool: string;

  /** Arguments for the tool call */
  args: Record<string, unknown>;

  /** LLM's explanation of why this change is needed */
  reason: string;

  /** Order in which this change should be executed */
  order: number;

  /** Timestamp when this change was proposed */
  proposedAt: string;

  /** Optional: The tool call ID from the LLM response */
  toolCallId?: string;
}

/**
 * A pending plan awaiting user approval.
 */
export interface PendingPlan {
  /** Unique plan ID */
  id: string;

  /** The original task/prompt that led to this plan */
  task: string;

  /** When the plan was created */
  createdAt: string;

  /** When the plan was last updated */
  updatedAt: string;

  /** The proposed changes in execution order */
  proposedChanges: ProposedChange[];

  /** Summary of exploration done before proposing changes */
  explorationSummary: string;

  /** Current status of the plan */
  status: PlanStatus;

  /** Session ID this plan belongs to */
  sessionId?: string;
}

/**
 * Result of approving a plan.
 */
export interface PlanApprovalResult {
  /** Changes to execute */
  changes: ProposedChange[];

  /** Number of changes skipped (if partial approval) */
  skippedCount: number;
}

/**
 * Event types emitted by the plan manager.
 */
export type PendingPlanEvent =
  | { type: 'plan.created'; plan: PendingPlan }
  | { type: 'plan.change.added'; change: ProposedChange; planId: string }
  | { type: 'plan.approved'; planId: string; changeCount: number }
  | { type: 'plan.rejected'; planId: string }
  | { type: 'plan.cleared'; planId: string };

export type PendingPlanEventListener = (event: PendingPlanEvent) => void;

// =============================================================================
// PENDING PLAN MANAGER
// =============================================================================

/**
 * Manages pending plans that await user approval.
 */
export class PendingPlanManager {
  private currentPlan: PendingPlan | null = null;
  private changeCounter = 0;
  private eventListeners: Set<PendingPlanEventListener> = new Set();

  /**
   * Start a new pending plan.
   * Clears any existing plan.
   */
  startPlan(task: string, sessionId?: string): PendingPlan {
    const now = new Date().toISOString();
    const plan: PendingPlan = {
      id: `plan-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      task,
      createdAt: now,
      updatedAt: now,
      proposedChanges: [],
      explorationSummary: '',
      status: 'pending',
      sessionId,
    };

    this.currentPlan = plan;
    this.changeCounter = 0;
    this.emit({ type: 'plan.created', plan });

    return plan;
  }

  /**
   * Add a proposed change to the current plan.
   * Returns the created change, or null if no plan is active.
   */
  addProposedChange(
    tool: string,
    args: Record<string, unknown>,
    reason: string,
    toolCallId?: string,
  ): ProposedChange | null {
    if (!this.currentPlan) {
      return null;
    }

    const change: ProposedChange = {
      id: `change-${++this.changeCounter}`,
      tool,
      args,
      reason,
      order: this.currentPlan.proposedChanges.length + 1,
      proposedAt: new Date().toISOString(),
      toolCallId,
    };

    this.currentPlan.proposedChanges.push(change);
    this.currentPlan.updatedAt = new Date().toISOString();
    this.emit({ type: 'plan.change.added', change, planId: this.currentPlan.id });

    return change;
  }

  /**
   * Set the exploration summary for the current plan.
   * Can be called multiple times - will append to existing summary.
   *
   * @param summary - The exploration content to add
   * @param append - If true, appends to existing summary (default: false, replaces)
   */
  setExplorationSummary(summary: string, append = false): void {
    if (this.currentPlan) {
      if (append && this.currentPlan.explorationSummary) {
        // Avoid duplicates by checking if this content is already included
        if (!this.currentPlan.explorationSummary.includes(summary.slice(0, 100))) {
          this.currentPlan.explorationSummary += '\n\n' + summary;
        }
      } else {
        this.currentPlan.explorationSummary = summary;
      }
      this.currentPlan.updatedAt = new Date().toISOString();
    }
  }

  /**
   * Append exploration findings to the current plan.
   * Useful for capturing incremental exploration during planning.
   */
  appendExplorationFinding(finding: string): void {
    this.setExplorationSummary(finding, true);
  }

  /**
   * Get the current pending plan.
   */
  getPendingPlan(): PendingPlan | null {
    return this.currentPlan;
  }

  /**
   * Check if there's an active pending plan.
   */
  hasPendingPlan(): boolean {
    return this.currentPlan !== null && this.currentPlan.status === 'pending';
  }

  /**
   * Get the number of proposed changes.
   */
  getChangeCount(): number {
    return this.currentPlan?.proposedChanges.length ?? 0;
  }

  /**
   * Approve the pending plan.
   * @param count - If provided, only approve the first N changes
   * @returns The changes to execute
   */
  approve(count?: number): PlanApprovalResult {
    if (!this.currentPlan) {
      return { changes: [], skippedCount: 0 };
    }

    const allChanges = this.currentPlan.proposedChanges;
    const approvedChanges = count !== undefined ? allChanges.slice(0, count) : allChanges;
    const skippedCount = allChanges.length - approvedChanges.length;

    this.currentPlan.status = skippedCount > 0 ? 'partially_approved' : 'approved';
    this.currentPlan.updatedAt = new Date().toISOString();

    this.emit({
      type: 'plan.approved',
      planId: this.currentPlan.id,
      changeCount: approvedChanges.length,
    });

    // Clear the plan after approval
    const result = { changes: approvedChanges, skippedCount };
    this.currentPlan = null;

    return result;
  }

  /**
   * Reject the pending plan.
   * Clears all proposed changes.
   */
  reject(): void {
    if (!this.currentPlan) {
      return;
    }

    this.currentPlan.status = 'rejected';
    this.currentPlan.updatedAt = new Date().toISOString();

    this.emit({ type: 'plan.rejected', planId: this.currentPlan.id });
    this.currentPlan = null;
  }

  /**
   * Clear the current plan without changing status.
   */
  clear(): void {
    if (this.currentPlan) {
      this.emit({ type: 'plan.cleared', planId: this.currentPlan.id });
      this.currentPlan = null;
    }
  }

  /**
   * Restore a plan from storage.
   */
  restorePlan(plan: PendingPlan): void {
    this.currentPlan = plan;
    this.changeCounter = plan.proposedChanges.length;
  }

  /**
   * Format the pending plan for display.
   */
  formatPlan(): string {
    if (!this.currentPlan) {
      return 'No pending plan.';
    }

    const lines: string[] = [
      `━━━ PENDING PLAN ━━━`,
      ``,
      `Task: "${this.currentPlan.task}"`,
      `Status: ${this.currentPlan.status}`,
      `Created: ${this.currentPlan.createdAt}`,
      '',
    ];

    // Show exploration summary if available
    if (this.currentPlan.explorationSummary) {
      lines.push('📋 Exploration Summary:');
      lines.push(this.currentPlan.explorationSummary);
      lines.push('');
    }

    if (this.currentPlan.proposedChanges.length === 0) {
      lines.push('No proposed changes yet.');
    } else {
      // Extract overall approach from first change's reason (often shared across spawn_agent calls)
      const firstReason = this.currentPlan.proposedChanges[0]?.reason || '';
      const allSameReason = this.currentPlan.proposedChanges.every((c) => c.reason === firstReason);

      if (allSameReason && firstReason && this.currentPlan.proposedChanges.length > 1) {
        lines.push('🎯 Overall Approach:');
        lines.push(`   ${firstReason}`);
        lines.push('');
      }

      lines.push(`📝 Proposed Actions (${this.currentPlan.proposedChanges.length}):`);
      lines.push('');

      for (const change of this.currentPlan.proposedChanges) {
        // Format based on tool type
        if (change.tool === 'write_file' || change.tool === 'edit_file') {
          const path = change.args.path || change.args.file_path || '(no path specified)';
          lines.push(`${change.order}. [${change.tool}] ${path}`);
          if (!allSameReason) {
            lines.push(`   └─ ${change.reason}`);
          }
        } else if (change.tool === 'bash') {
          const cmd = String(change.args.command || '').slice(0, 80);
          lines.push(`${change.order}. [bash] ${cmd}${cmd.length >= 80 ? '...' : ''}`);
          if (!allSameReason) {
            lines.push(`   └─ ${change.reason}`);
          }
        } else if (change.tool === 'spawn_agent') {
          // For spawn_agent, the task IS the plan - show it prominently
          const agentType = change.args.agent || change.args.type || 'subagent';
          const task = String(change.args.task || change.args.prompt || '');

          lines.push(`${change.order}. [${agentType}]`);

          // Show the full task, properly formatted with line breaks
          const taskLines = task.split(/\n/).filter((l) => l.trim());
          if (taskLines.length <= 3) {
            // Short task - show inline
            for (const taskLine of taskLines) {
              lines.push(`   ${taskLine.trim()}`);
            }
          } else {
            // Longer task - show first few lines and indicate more
            for (let i = 0; i < Math.min(4, taskLines.length); i++) {
              const line = taskLines[i].trim();
              if (line.length > 100) {
                lines.push(`   ${line.slice(0, 97)}...`);
              } else {
                lines.push(`   ${line}`);
              }
            }
            if (taskLines.length > 4) {
              lines.push(`   ... (${taskLines.length - 4} more lines)`);
            }
          }

          if (!allSameReason) {
            lines.push(`   └─ ${change.reason}`);
          }
        } else {
          // Generic tool
          lines.push(`${change.order}. [${change.tool}]`);
          const argsStr = JSON.stringify(change.args);
          if (argsStr.length > 100) {
            lines.push(`   Args: ${argsStr.slice(0, 97)}...`);
          } else {
            lines.push(`   Args: ${argsStr}`);
          }
          if (!allSameReason) {
            lines.push(`   └─ ${change.reason}`);
          }
        }
        lines.push('');
      }
    }

    lines.push('━━━━━━━━━━━━━━━━━━━━━━━');
    lines.push('Commands: /approve, /reject, /show-plan');

    return lines.join('\n');
  }

  /**
   * Synthesize a coherent plan summary.
   * This creates a well-structured executive summary from the proposed changes.
   *
   * @param llmProvider - Optional LLM provider for AI-generated synthesis.
   *                      If not provided, uses structured template formatting.
   * @returns A coherent plan summary string
   */
  async synthesizePlan(llmProvider?: {
    chat(
      messages: Array<{ role: 'user' | 'assistant' | 'system'; content: string }>,
    ): Promise<{ content: string }>;
  }): Promise<string> {
    if (!this.currentPlan) {
      return 'No pending plan.';
    }

    const plan = this.currentPlan;
    const changes = plan.proposedChanges;

    // If LLM provider is available, use it for intelligent synthesis
    if (llmProvider && changes.length > 0) {
      try {
        const changesDescription = changes
          .map((c) => {
            const target =
              c.tool === 'spawn_agent'
                ? `Delegate to subagent: ${String(c.args.agent || c.args.type || 'subagent')}`
                : c.tool === 'bash'
                  ? `Execute: ${String(c.args.command || '').slice(0, 100)}`
                  : `${c.tool}: ${String(c.args.path || c.args.file_path || JSON.stringify(c.args)).slice(0, 100)}`;
            return `${c.order}. [${c.tool}] ${target}\n   Reason: ${c.reason}`;
          })
          .join('\n\n');

        const prompt = `Analyze this plan and provide a concise executive summary.

Task: ${plan.task}
${plan.explorationSummary ? `\nExploration findings:\n${plan.explorationSummary.slice(0, 1000)}` : ''}

Proposed Changes:
${changesDescription}

Provide:
1. A 2-3 sentence executive summary explaining what this plan accomplishes
2. Key files/components that will be affected
3. Any dependencies between the changes (what must happen first)
4. Brief verification steps after completion

Keep it concise and actionable. Focus on the "why" not just the "what".`;

        const response = await llmProvider.chat([{ role: 'user', content: prompt }]);

        if (response.content && response.content.length > 50) {
          return response.content;
        }
      } catch {
        // Fall through to template-based synthesis
      }
    }

    // Template-based synthesis (no LLM or LLM failed)
    const lines: string[] = [];

    // Executive summary based on change types
    const fileChanges = changes.filter((c) => ['write_file', 'edit_file'].includes(c.tool));
    const bashCommands = changes.filter((c) => c.tool === 'bash');
    const subagentTasks = changes.filter((c) => c.tool === 'spawn_agent');

    lines.push('## Executive Summary');
    lines.push('');

    if (subagentTasks.length > 0) {
      lines.push(`This plan delegates ${subagentTasks.length} task(s) to specialized subagents.`);
    }
    if (fileChanges.length > 0) {
      const uniqueFiles = new Set(
        fileChanges.map((c) => String(c.args.path || c.args.file_path || '')),
      );
      lines.push(`${fileChanges.length} file operation(s) across ${uniqueFiles.size} file(s).`);
    }
    if (bashCommands.length > 0) {
      lines.push(`${bashCommands.length} shell command(s) to execute.`);
    }
    lines.push('');

    // Exploration context if available
    if (plan.explorationSummary && plan.explorationSummary.length > 0) {
      lines.push('## Context from Exploration');
      // Take first 500 chars or first paragraph
      const summary = plan.explorationSummary.split('\n\n')[0].slice(0, 500);
      lines.push(summary + (plan.explorationSummary.length > 500 ? '...' : ''));
      lines.push('');
    }

    // Key targets
    if (fileChanges.length > 0) {
      lines.push('## Files Affected');
      const uniqueFiles = [
        ...new Set(fileChanges.map((c) => String(c.args.path || c.args.file_path || 'unknown'))),
      ];
      for (const file of uniqueFiles.slice(0, 10)) {
        lines.push(`- ${file}`);
      }
      if (uniqueFiles.length > 10) {
        lines.push(`... and ${uniqueFiles.length - 10} more`);
      }
      lines.push('');
    }

    // Dependencies (simple sequential assumption)
    if (changes.length > 1) {
      lines.push('## Execution Order');
      lines.push('Changes will be executed sequentially in the order shown.');
      lines.push('');
    }

    // Verification suggestion
    lines.push('## Verification');
    if (bashCommands.some((c) => String(c.args.command || '').includes('test'))) {
      lines.push('- Tests are included in this plan');
    } else {
      lines.push('- Consider running tests after approval: `npm test` or relevant test command');
    }
    if (fileChanges.length > 0) {
      lines.push('- Review changed files after execution');
    }

    return lines.join('\n');
  }

  /**
   * Subscribe to plan events.
   */
  subscribe(listener: PendingPlanEventListener): () => void {
    this.eventListeners.add(listener);
    return () => this.eventListeners.delete(listener);
  }

  // Internal

  private emit(event: PendingPlanEvent): void {
    for (const listener of this.eventListeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }
}

// =============================================================================
// FACTORY
// =============================================================================

/**
 * Create a new pending plan manager.
 */
export function createPendingPlanManager(): PendingPlanManager {
  return new PendingPlanManager();
}

/**
 * Format a plan for compact display (e.g., in status bar).
 */
export function formatPlanStatus(plan: PendingPlan | null): string {
  if (!plan) {
    return '';
  }

  const count = plan.proposedChanges.length;
  return `${count} change${count === 1 ? '' : 's'} pending`;
}
