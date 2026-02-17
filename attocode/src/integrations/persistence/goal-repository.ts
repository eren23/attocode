/**
 * Goal Repository
 *
 * Goal CRUD operations and critical juncture tracking.
 * Goals persist outside of context and survive compaction.
 *
 * Extracted from sqlite-store.ts as part of Phase 3c restructuring.
 */

import type { Goal, GoalStatus, Juncture, JunctureType, SQLiteStoreDeps } from './sqlite-store.js';

// =============================================================================
// GOAL CRUD
// =============================================================================

/**
 * Create a new goal for the current session.
 * Goals persist outside of context and survive compaction.
 * Returns undefined if goals feature is not available.
 */
export function createGoal(
  deps: SQLiteStoreDeps,
  goalText: string,
  options: {
    priority?: number;
    parentGoalId?: string;
    progressTotal?: number;
    metadata?: Record<string, unknown>;
  } = {},
): string | undefined {
  if (!deps.features.goals || !deps.stmts.insertGoal) {
    return undefined;
  }

  if (!deps.getCurrentSessionId()) {
    // Delegate session creation to the store
    deps.ensureSession();
  }

  const id = `goal-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
  const now = new Date().toISOString();

  deps.stmts.insertGoal.run({
    id,
    sessionId: deps.getCurrentSessionId(),
    goalText,
    status: 'active',
    priority: options.priority ?? 2,
    parentGoalId: options.parentGoalId ?? null,
    progressCurrent: 0,
    progressTotal: options.progressTotal ?? null,
    createdAt: now,
    updatedAt: now,
    metadata: options.metadata ? JSON.stringify(options.metadata) : null,
  });

  return id;
}

/**
 * Update a goal's status or progress.
 */
export function updateGoal(
  deps: SQLiteStoreDeps,
  goalId: string,
  updates: {
    goalText?: string;
    status?: GoalStatus;
    priority?: number;
    progressCurrent?: number;
    progressTotal?: number;
    metadata?: Record<string, unknown>;
  },
): void {
  if (!deps.features.goals || !deps.stmts.updateGoal) {
    return;
  }

  const now = new Date().toISOString();

  deps.stmts.updateGoal.run({
    id: goalId,
    goalText: updates.goalText ?? null,
    status: updates.status ?? null,
    priority: updates.priority ?? null,
    progressCurrent: updates.progressCurrent ?? null,
    progressTotal: updates.progressTotal ?? null,
    updatedAt: now,
    completedAt: updates.status === 'completed' || updates.status === 'abandoned' ? now : null,
    metadata: updates.metadata ? JSON.stringify(updates.metadata) : null,
  });
}

/**
 * Mark a goal as completed.
 */
export function completeGoal(deps: SQLiteStoreDeps, goalId: string): void {
  updateGoal(deps, goalId, { status: 'completed' });
}

/**
 * Get a goal by ID.
 */
export function getGoal(deps: SQLiteStoreDeps, goalId: string): Goal | undefined {
  if (!deps.features.goals || !deps.stmts.getGoal) {
    return undefined;
  }
  return deps.stmts.getGoal.get(goalId) as Goal | undefined;
}

/**
 * List all goals for a session.
 */
export function listGoals(deps: SQLiteStoreDeps, sessionId?: string): Goal[] {
  if (!deps.features.goals || !deps.stmts.listGoals) {
    return [];
  }
  const sid = sessionId ?? deps.getCurrentSessionId();
  if (!sid) return [];
  return deps.stmts.listGoals.all(sid) as Goal[];
}

/**
 * List active goals for a session.
 */
export function listActiveGoals(deps: SQLiteStoreDeps, sessionId?: string): Goal[] {
  if (!deps.features.goals || !deps.stmts.listActiveGoals) {
    return [];
  }
  const sid = sessionId ?? deps.getCurrentSessionId();
  if (!sid) return [];
  return deps.stmts.listActiveGoals.all(sid) as Goal[];
}

/**
 * Get a summary of the current goals for context injection.
 * This is what gets recited to maintain goal awareness.
 */
export function getGoalsSummary(deps: SQLiteStoreDeps, sessionId?: string): string {
  if (!deps.features.goals) {
    return 'Goals feature not available.';
  }

  const goals = listActiveGoals(deps, sessionId);
  if (goals.length === 0) {
    return 'No active goals.';
  }

  const lines: string[] = ['Active Goals:'];
  for (const goal of goals) {
    const progress = goal.progressTotal ? ` (${goal.progressCurrent}/${goal.progressTotal})` : '';
    const priority = goal.priority === 1 ? ' [HIGH]' : goal.priority === 3 ? ' [low]' : '';
    lines.push(`\u2022 ${goal.goalText}${progress}${priority}`);
  }
  return lines.join('\n');
}

// =============================================================================
// JUNCTURES (Critical Moments)
// =============================================================================

/**
 * Log a critical juncture (decision, failure, breakthrough, pivot).
 * Returns -1 if goals feature is not available.
 */
export function logJuncture(
  deps: SQLiteStoreDeps,
  type: JunctureType,
  description: string,
  options: {
    goalId?: string;
    outcome?: string;
    importance?: number;
    context?: Record<string, unknown>;
  } = {},
): number {
  if (!deps.features.goals || !deps.stmts.insertJuncture) {
    return -1;
  }

  if (!deps.getCurrentSessionId()) {
    deps.ensureSession();
  }

  const result = deps.stmts.insertJuncture.run({
    sessionId: deps.getCurrentSessionId(),
    goalId: options.goalId ?? null,
    type,
    description,
    outcome: options.outcome ?? null,
    importance: options.importance ?? 2,
    context: options.context ? JSON.stringify(options.context) : null,
    createdAt: new Date().toISOString(),
  });

  return Number(result.lastInsertRowid);
}

/**
 * List junctures for a session.
 */
export function listJunctures(
  deps: SQLiteStoreDeps,
  sessionId?: string,
  limit?: number,
): Juncture[] {
  if (!deps.features.goals || !deps.stmts.listJunctures) {
    return [];
  }

  const sid = sessionId ?? deps.getCurrentSessionId();
  if (!sid) return [];

  const junctures = deps.stmts.listJunctures.all(sid) as Juncture[];
  return limit ? junctures.slice(0, limit) : junctures;
}

/**
 * Get recent critical junctures for context.
 */
export function getJuncturesSummary(
  deps: SQLiteStoreDeps,
  sessionId?: string,
  limit: number = 5,
): string {
  if (!deps.features.goals) {
    return '';
  }

  const junctures = listJunctures(deps, sessionId, limit);
  if (junctures.length === 0) {
    return '';
  }

  const lines: string[] = ['Recent Key Moments:'];
  for (const j of junctures) {
    const icon =
      j.type === 'failure'
        ? '\u2717'
        : j.type === 'breakthrough'
          ? '\u2605'
          : j.type === 'decision'
            ? '\u2192'
            : '\u21BB';
    lines.push(`${icon} [${j.type}] ${j.description}`);
    if (j.outcome) {
      lines.push(`  \u2514\u2500 ${j.outcome}`);
    }
  }
  return lines.join('\n');
}
