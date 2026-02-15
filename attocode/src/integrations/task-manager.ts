/**
 * Task Manager - Claude Code-style Task System
 *
 * Provides persistent task tracking with DAG-based dependencies.
 * Tasks can be used to coordinate work across subagents and
 * track progress on multi-step implementations.
 *
 * Features:
 * - Task creation with subject, description, and activeForm
 * - Status workflow: pending → in_progress → completed
 * - Dependency management (blockedBy, blocks)
 * - Hydration pattern for session persistence
 * - Event emission for TUI updates
 */

import { EventEmitter } from 'events';

// =============================================================================
// TYPES
// =============================================================================

export type TaskStatus = 'pending' | 'in_progress' | 'completed' | 'deleted';

export interface Task {
  /** Unique task identifier */
  id: string;
  /** Brief title in imperative form (e.g., "Fix authentication bug") */
  subject: string;
  /** Detailed requirements and context */
  description: string;
  /** Present continuous form shown in spinner (e.g., "Fixing authentication bug") */
  activeForm: string;
  /** Current status */
  status: TaskStatus;
  /** Agent ID that owns this task */
  owner?: string;
  /** Last heartbeat for the in-progress lease */
  leaseHeartbeatAt?: number;
  /** Task IDs that must complete before this task can start */
  blockedBy: string[];
  /** Task IDs that are waiting on this task to complete */
  blocks: string[];
  /** Arbitrary metadata */
  metadata: Record<string, unknown>;
  /** Creation timestamp */
  createdAt: number;
  /** Last update timestamp */
  updatedAt: number;
}

export interface CreateTaskOptions {
  subject: string;
  description: string;
  activeForm?: string;
  metadata?: Record<string, unknown>;
}

export interface UpdateTaskOptions {
  subject?: string;
  description?: string;
  activeForm?: string;
  status?: TaskStatus;
  owner?: string;
  addBlockedBy?: string[];
  addBlocks?: string[];
  metadata?: Record<string, unknown>;
}

export interface TaskSummary {
  id: string;
  subject: string;
  status: TaskStatus;
  owner?: string;
  blockedBy: string[];
}

export interface ReconcileStaleInProgressOptions {
  /** Mark in-progress tasks stale after this many ms (default: 5 minutes) */
  staleAfterMs?: number;
  /** Override clock for deterministic tests */
  now?: number;
  /** Optional reason stored in task metadata for observability */
  reason?: string;
  /** Owners currently active in-process and therefore exempt from recovery */
  activeOwners?: string[];
}

export interface ReconcileResult {
  reconciled: number;
  taskIds: string[];
}

// =============================================================================
// TASK MANAGER
// =============================================================================

export class TaskManager extends EventEmitter {
  private tasks = new Map<string, Task>();
  private nextId = 1;
  private static readonly DEFAULT_STALE_AFTER_MS = 5 * 60 * 1000;

  /**
   * Normalize ownership invariants:
   * only in_progress tasks may retain owner/lease metadata.
   */
  private normalizeTaskOwnershipInvariants(): void {
    for (const task of this.tasks.values()) {
      if (task.status !== 'in_progress') {
        delete task.owner;
        delete task.leaseHeartbeatAt;
      }
    }
  }

  constructor() {
    super();
  }

  // ---------------------------------------------------------------------------
  // Core Operations
  // ---------------------------------------------------------------------------

  /**
   * Create a new task.
   */
  create(options: CreateTaskOptions): Task {
    const id = `task-${this.nextId++}`;
    const now = Date.now();

    const task: Task = {
      id,
      subject: options.subject,
      description: options.description,
      activeForm: options.activeForm || `Working on ${options.subject.toLowerCase()}`,
      status: 'pending',
      blockedBy: [],
      blocks: [],
      metadata: options.metadata || {},
      createdAt: now,
      updatedAt: now,
    };

    this.tasks.set(id, task);
    this.emit('task.created', { task });
    return task;
  }

  /**
   * Update an existing task.
   */
  update(taskIdRaw: string, updates: UpdateTaskOptions): Task | undefined {
    // Support both "1" and "task-1" formats
    const taskId = taskIdRaw.startsWith('task-') ? taskIdRaw : `task-${taskIdRaw}`;
    const task = this.tasks.get(taskId);
    if (!task) return undefined;

    // Handle deletion
    if (updates.status === 'deleted') {
      // Remove this task from all blockedBy references
      for (const t of this.tasks.values()) {
        t.blockedBy = t.blockedBy.filter(id => id !== taskId);
        t.blocks = t.blocks.filter(id => id !== taskId);
      }
      this.tasks.delete(taskId);
      this.emit('task.deleted', { taskId });
      return { ...task, status: 'deleted' };
    }

    // Update basic fields
    if (updates.subject !== undefined) task.subject = updates.subject;
    if (updates.description !== undefined) task.description = updates.description;
    if (updates.activeForm !== undefined) task.activeForm = updates.activeForm;
    if (updates.status !== undefined) {
      task.status = updates.status;
      if (updates.status === 'in_progress') {
        task.leaseHeartbeatAt = Date.now();
      } else {
        delete task.leaseHeartbeatAt;
        if (updates.owner === undefined) {
          delete task.owner;
        }
      }
    }
    if (updates.owner !== undefined) {
      task.owner = updates.owner;
    }

    // Add dependencies
    if (updates.addBlockedBy) {
      for (const blockerIdRaw of updates.addBlockedBy) {
        // Normalize task ID - support both "1" and "task-1" formats
        const blockerId = blockerIdRaw.startsWith('task-') ? blockerIdRaw : `task-${blockerIdRaw}`;
        if (!task.blockedBy.includes(blockerId)) {
          task.blockedBy.push(blockerId);
          // Update the blocker's blocks array
          const blocker = this.tasks.get(blockerId);
          if (blocker && !blocker.blocks.includes(taskId)) {
            blocker.blocks.push(taskId);
          }
        }
      }
    }

    if (updates.addBlocks) {
      for (const blockedIdRaw of updates.addBlocks) {
        const blockedId = blockedIdRaw.startsWith('task-') ? blockedIdRaw : `task-${blockedIdRaw}`;
        if (!task.blocks.includes(blockedId)) {
          task.blocks.push(blockedId);
          // Update the blocked task's blockedBy array
          const blocked = this.tasks.get(blockedId);
          if (blocked && !blocked.blockedBy.includes(taskId)) {
            blocked.blockedBy.push(taskId);
          }
        }
      }
    }

    // Merge metadata
    if (updates.metadata) {
      for (const [key, value] of Object.entries(updates.metadata)) {
        if (value === null) {
          delete task.metadata[key];
        } else {
          task.metadata[key] = value;
        }
      }
    }

    task.updatedAt = Date.now();
    this.emit('task.updated', { task });
    return task;
  }

  /**
   * Get a task by ID.
   */
  get(taskId: string): Task | undefined {
    // Support both "1" and "task-1" formats
    const normalizedId = taskId.startsWith('task-') ? taskId : `task-${taskId}`;
    return this.tasks.get(normalizedId);
  }

  /**
   * List all tasks (excluding deleted).
   */
  list(): Task[] {
    this.normalizeTaskOwnershipInvariants();
    return Array.from(this.tasks.values())
      .filter(t => t.status !== 'deleted')
      .sort((a, b) => {
        // Sort by status (in_progress first, then pending, then completed)
        const statusOrder: Record<TaskStatus, number> = { in_progress: 0, pending: 1, completed: 2, deleted: 3 };
        const statusDiff = statusOrder[a.status] - statusOrder[b.status];
        if (statusDiff !== 0) return statusDiff;
        // Then by ID (earlier tasks first)
        return parseInt(a.id.replace('task-', '')) - parseInt(b.id.replace('task-', ''));
      });
  }

  /**
   * Get task summaries for display.
   */
  listSummaries(): TaskSummary[] {
    return this.list().map(t => ({
      id: t.id,
      subject: t.subject,
      status: t.status,
      owner: t.owner,
      blockedBy: this.getOpenBlockers(t.id),
    }));
  }

  // ---------------------------------------------------------------------------
  // Dependency Management
  // ---------------------------------------------------------------------------

  /**
   * Check if a task is blocked (has uncompleted blockers).
   */
  isBlocked(taskId: string): boolean {
    const task = this.get(taskId);
    if (!task) return false;
    return this.getOpenBlockers(taskId).length > 0;
  }

  /**
   * Get open (non-completed) blockers for a task.
   */
  getOpenBlockers(taskId: string): string[] {
    const task = this.get(taskId);
    if (!task) return [];
    return task.blockedBy.filter(blockerId => {
      const blocker = this.tasks.get(blockerId);
      return blocker && blocker.status !== 'completed';
    });
  }

  /**
   * Get tasks that are available to work on.
   * Available = pending, not blocked.
   * Ownership is only authoritative while in_progress.
   */
  getAvailableTasks(): Task[] {
    this.normalizeTaskOwnershipInvariants();
    return this.list().filter(t =>
      t.status === 'pending' &&
      !this.isBlocked(t.id)
    );
  }

  /**
   * Claim a task for an agent.
   */
  claim(taskId: string, owner: string): Task | undefined {
    return this.update(taskId, { owner, status: 'in_progress' });
  }

  /**
   * Refresh lease heartbeat for an in-progress task.
   */
  heartbeat(taskIdRaw: string, owner?: string): Task | undefined {
    const taskId = taskIdRaw.startsWith('task-') ? taskIdRaw : `task-${taskIdRaw}`;
    const task = this.tasks.get(taskId);
    if (!task || task.status !== 'in_progress') return undefined;
    if (owner && task.owner && owner !== task.owner) return undefined;
    const now = Date.now();
    task.leaseHeartbeatAt = now;
    task.updatedAt = now;
    this.emit('task.updated', { task });
    return task;
  }

  /**
   * Requeue stale in-progress tasks back to pending.
   * Used to recover orphaned task ownership across interrupted runs.
   */
  reconcileStaleInProgress(options: ReconcileStaleInProgressOptions = {}): ReconcileResult {
    const now = options.now ?? Date.now();
    const staleAfterMs = options.staleAfterMs ?? TaskManager.DEFAULT_STALE_AFTER_MS;
    const activeOwners = new Set(options.activeOwners ?? []);
    const taskIds: string[] = [];

    for (const task of this.tasks.values()) {
      if (task.status !== 'in_progress') continue;
      if (task.owner && activeOwners.has(task.owner)) continue;

      const lastTouched = task.leaseHeartbeatAt ?? task.updatedAt ?? task.createdAt;
      if (now - lastTouched < staleAfterMs) continue;

      task.status = 'pending';
      delete task.owner;
      delete task.leaseHeartbeatAt;
      task.updatedAt = now;
      task.metadata.recoveredFromStaleInProgressAt = new Date(now).toISOString();
      if (options.reason) {
        task.metadata.recoveryReason = options.reason;
      }
      taskIds.push(task.id);
      this.emit('task.updated', { task });
      this.emit('task.recovered', { taskId: task.id, from: 'in_progress', to: 'pending', reason: options.reason });
    }

    return { reconciled: taskIds.length, taskIds };
  }

  /**
   * Complete a task.
   */
  complete(taskId: string): Task | undefined {
    return this.update(taskId, { status: 'completed' });
  }

  // ---------------------------------------------------------------------------
  // Persistence (Hydration Pattern)
  // ---------------------------------------------------------------------------

  /**
   * Export tasks to markdown for session handoff.
   */
  toMarkdown(): string {
    const tasks = this.list();
    if (tasks.length === 0) return '# Tasks\n\nNo tasks.\n';

    const lines = ['# Tasks\n'];

    for (const task of tasks) {
      const statusIcon =
        task.status === 'completed' ? '[x]' :
        task.status === 'in_progress' ? '[~]' : '[ ]';

      lines.push(`## ${statusIcon} ${task.id}: ${task.subject}`);
      lines.push('');
      lines.push(`**Status:** ${task.status}`);
      if (task.owner) lines.push(`**Owner:** ${task.owner}`);
      if (task.blockedBy.length > 0) {
        lines.push(`**Blocked by:** ${task.blockedBy.join(', ')}`);
      }
      if (task.blocks.length > 0) {
        lines.push(`**Blocks:** ${task.blocks.join(', ')}`);
      }
      lines.push('');
      lines.push('**Description:**');
      lines.push(task.description);
      lines.push('');
    }

    return lines.join('\n');
  }

  /**
   * Import tasks from markdown (hydration).
   */
  fromMarkdown(markdown: string): void {
    // Clear existing tasks
    this.tasks.clear();
    this.nextId = 1;

    // Parse markdown
    const taskRegex = /## \[(.)\] (task-\d+): (.+)\n([\s\S]*?)(?=\n## |\n# |$)/g;
    let match;

    while ((match = taskRegex.exec(markdown)) !== null) {
      const statusChar = match[1];
      const id = match[2];
      const subject = match[3].trim();
      const body = match[4];

      // Parse status
      const status: TaskStatus =
        statusChar === 'x' ? 'completed' :
        statusChar === '~' ? 'in_progress' : 'pending';

      // Parse fields from body
      const ownerMatch = body.match(/\*\*Owner:\*\* (.+)/);
      const blockedByMatch = body.match(/\*\*Blocked by:\*\* (.+)/);
      const blocksMatch = body.match(/\*\*Blocks:\*\* (.+)/);
      const descriptionMatch = body.match(/\*\*Description:\*\*\n([\s\S]*?)$/);

      const task: Task = {
        id,
        subject,
        description: descriptionMatch ? descriptionMatch[1].trim() : '',
        activeForm: `Working on ${subject.toLowerCase()}`,
        status,
        owner: ownerMatch ? ownerMatch[1].trim() : undefined,
        blockedBy: blockedByMatch ? blockedByMatch[1].split(',').map(s => s.trim()) : [],
        blocks: blocksMatch ? blocksMatch[1].split(',').map(s => s.trim()) : [],
        metadata: {},
        createdAt: Date.now(),
        updatedAt: Date.now(),
      };

      this.tasks.set(id, task);

      // Track highest ID for nextId
      const idNum = parseInt(id.replace('task-', ''));
      if (idNum >= this.nextId) {
        this.nextId = idNum + 1;
      }
    }

    this.normalizeTaskOwnershipInvariants();

    this.emit('tasks.hydrated', { count: this.tasks.size });
  }

  /**
   * Clear all tasks.
   */
  clear(): void {
    this.tasks.clear();
    this.nextId = 1;
    this.emit('tasks.cleared', {});
  }

  /**
   * Get count of tasks by status.
   */
  getCounts(): { pending: number; inProgress: number; completed: number; total: number } {
    const tasks = this.list();
    return {
      pending: tasks.filter(t => t.status === 'pending').length,
      inProgress: tasks.filter(t => t.status === 'in_progress').length,
      completed: tasks.filter(t => t.status === 'completed').length,
      total: tasks.length,
    };
  }
}

// =============================================================================
// FACTORY
// =============================================================================

export function createTaskManager(): TaskManager {
  return new TaskManager();
}
