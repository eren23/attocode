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
    toolCallId?: string
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
   */
  setExplorationSummary(summary: string): void {
    if (this.currentPlan) {
      this.currentPlan.explorationSummary = summary;
      this.currentPlan.updatedAt = new Date().toISOString();
    }
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
    const approvedChanges = count !== undefined
      ? allChanges.slice(0, count)
      : allChanges;
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
      `Plan: "${this.currentPlan.task}"`,
      `Status: ${this.currentPlan.status}`,
      `Created: ${this.currentPlan.createdAt}`,
      '',
    ];

    if (this.currentPlan.explorationSummary) {
      lines.push('Exploration Summary:');
      lines.push(this.currentPlan.explorationSummary);
      lines.push('');
    }

    if (this.currentPlan.proposedChanges.length === 0) {
      lines.push('No proposed changes yet.');
    } else {
      lines.push(`Proposed Changes (${this.currentPlan.proposedChanges.length}):`);
      lines.push('');

      for (const change of this.currentPlan.proposedChanges) {
        lines.push(`${change.order}. [${change.tool}]`);

        // Format args nicely based on tool type
        if (change.tool === 'write_file' || change.tool === 'edit_file') {
          const path = change.args.path || change.args.file_path;
          lines.push(`   File: ${path}`);
        } else if (change.tool === 'bash') {
          const cmd = String(change.args.command || '').slice(0, 60);
          lines.push(`   Command: ${cmd}${cmd.length >= 60 ? '...' : ''}`);
        } else if (change.tool === 'spawn_agent') {
          // Special formatting for spawn_agent to show agent type and task clearly
          const agentType = change.args.agent || change.args.type || 'unknown';
          const task = String(change.args.task || change.args.prompt || '');
          lines.push(`   Agent: ${agentType}`);
          // Show task with newlines replaced by spaces, truncated to 300 chars
          const flattened = task.replace(/\n+/g, ' ').replace(/\s+/g, ' ').trim();
          const truncated = flattened.length > 300 ? flattened.slice(0, 297) + '...' : flattened;
          lines.push(`   Task: ${truncated}`);
        } else {
          lines.push(`   Args: ${JSON.stringify(change.args).slice(0, 80)}...`);
        }

        lines.push(`   Reason: ${change.reason}`);
        lines.push('');
      }
    }

    lines.push('Commands: /approve, /reject, /show-plan');

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
