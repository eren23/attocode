/**
 * Session Repository
 *
 * Session CRUD operations, entries, checkpoints, cost tracking,
 * session hierarchy, pending plans, remembered permissions, migration,
 * and session manifest export.
 *
 * Extracted from sqlite-store.ts as part of Phase 3c restructuring.
 */

import Database from 'better-sqlite3';
import { join } from 'node:path';
import { existsSync, readFileSync } from 'node:fs';
import type { Message, ToolCall } from '../../types.js';
import { logger } from '../utilities/logger.js';
import type {
  SessionEntry,
  SessionEntryType,
} from './session-store.js';
import type { PendingPlan, ProposedChange } from '../tasks/pending-plan.js';
import type {
  SessionMetadata,
  SessionManifest,
  UsageLog,
  SessionType,
  SQLiteStoreDeps,
} from './sqlite-store.js';

// =============================================================================
// SESSION CRUD
// =============================================================================

/**
 * Create a new session.
 */
export function createSession(
  deps: SQLiteStoreDeps,
  name?: string
): string {
  const id = `session-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
  const now = new Date().toISOString();

  deps.stmts.insertSession.run({
    id,
    name: name || null,
    workspacePath: process.cwd(),
    workspaceFingerprint: null,
    createdAt: now,
    lastActiveAt: now,
    messageCount: 0,
    tokenCount: 0,
  });

  deps.setCurrentSessionId(id);

  // Prune old sessions
  pruneOldSessions(deps);

  deps.emit({ type: 'session.created', sessionId: id });
  return id;
}

/**
 * Append an entry to the current session.
 */
export function appendEntry(
  deps: SQLiteStoreDeps,
  entry: Omit<SessionEntry, 'timestamp'>
): void {
  if (!deps.getCurrentSessionId()) {
    createSession(deps);
  }

  const sessionId = deps.getCurrentSessionId()!;
  const timestamp = new Date().toISOString();

  deps.stmts.insertEntry.run({
    sessionId,
    timestamp,
    type: entry.type,
    data: JSON.stringify(entry.data),
  });

  // Update session metadata
  if (entry.type === 'message') {
    const msg = entry.data as Message;

    // Set summary from first user message (for session picker display)
    if (msg.role === 'user' && typeof msg.content === 'string') {
      // Only set if no summary yet
      const session = deps.stmts.getSession.get(sessionId) as SessionMetadata | undefined;
      if (session && !session.summary) {
        // Extract first line or first ~50 chars as summary
        const firstLine = msg.content.split('\n')[0].trim();
        const summary = firstLine.length > 60 ? firstLine.slice(0, 57) + '...' : firstLine;
        deps.db.prepare(`UPDATE sessions SET summary = ? WHERE id = ?`).run(summary, sessionId);
      }
    }

    deps.db.prepare(`
      UPDATE sessions SET
        last_active_at = ?,
        message_count = message_count + 1
      WHERE id = ?
    `).run(timestamp, sessionId);
  } else {
    deps.db.prepare(`
      UPDATE sessions SET last_active_at = ? WHERE id = ?
    `).run(timestamp, sessionId);
  }

  deps.emit({ type: 'entry.appended', sessionId, entryType: entry.type });
}

/**
 * Append a message to the current session.
 */
export function appendMessage(deps: SQLiteStoreDeps, message: Message): void {
  appendEntry(deps, { type: 'message', data: message });
}

/**
 * Append a tool call to the current session.
 */
export function appendToolCall(deps: SQLiteStoreDeps, toolCall: ToolCall): void {
  appendEntry(deps, { type: 'tool_call', data: toolCall });

  // Also insert into tool_calls table for fast lookup
  if ('id' in toolCall && toolCall.id) {
    deps.stmts.insertToolCall.run({
      id: toolCall.id,
      sessionId: deps.getCurrentSessionId(),
      name: toolCall.name,
      arguments: JSON.stringify(toolCall.arguments),
      status: 'pending',
      createdAt: new Date().toISOString(),
    });
  }
}

/**
 * Append a tool result to the current session.
 */
export function appendToolResult(deps: SQLiteStoreDeps, callId: string, result: unknown): void {
  appendEntry(deps, { type: 'tool_result', data: { callId, result } });

  // Update tool_calls table
  deps.stmts.updateToolCall.run({
    id: callId,
    status: 'success',
    result: JSON.stringify(result),
    error: null,
    durationMs: null,
    completedAt: new Date().toISOString(),
  });
}

/**
 * Append a compaction summary.
 */
export function appendCompaction(deps: SQLiteStoreDeps, summary: string, compactedCount: number): void {
  appendEntry(deps, {
    type: 'compaction',
    data: { summary, compactedCount, compactedAt: new Date().toISOString() },
  });
}

/**
 * Load a session by ID.
 */
export function loadSession(deps: SQLiteStoreDeps, sessionId: string): SessionEntry[] {
  const rows = deps.stmts.getEntries.all(sessionId) as Array<{
    timestamp: string;
    type: string;
    data: string;
  }>;

  const entries: SessionEntry[] = rows.map(row => ({
    timestamp: row.timestamp,
    type: row.type as SessionEntryType,
    data: JSON.parse(row.data),
  }));

  deps.setCurrentSessionId(sessionId);
  deps.emit({ type: 'session.loaded', sessionId, entryCount: entries.length });

  return entries;
}

/**
 * Reconstruct messages from session entries.
 */
export function loadSessionMessages(deps: SQLiteStoreDeps, sessionId: string): Message[] {
  const entries = loadSession(deps, sessionId);
  const messages: Message[] = [];

  for (const entry of entries) {
    if (entry.type === 'message') {
      messages.push(entry.data as Message);
    } else if (entry.type === 'compaction') {
      const compaction = entry.data as { summary: string };
      messages.push({
        role: 'system',
        content: `[Previous conversation summary]\n${compaction.summary}`,
      });
    }
  }

  return messages;
}

/**
 * Delete a session.
 */
export function deleteSession(deps: SQLiteStoreDeps, sessionId: string): void {
  deps.stmts.deleteSession.run(sessionId);

  if (deps.getCurrentSessionId() === sessionId) {
    deps.setCurrentSessionId(null);
  }

  deps.emit({ type: 'session.deleted', sessionId });
}

/**
 * List all sessions.
 */
export function listSessions(deps: SQLiteStoreDeps): SessionMetadata[] {
  const sessions = deps.stmts.listSessions.all() as SessionMetadata[];

  // Check checkpoints for sessions with 0 message count
  for (const session of sessions) {
    if (session.messageCount === 0) {
      const checkpoint = loadLatestCheckpoint(deps, session.id);
      if (checkpoint?.state?.messages && Array.isArray(checkpoint.state.messages)) {
        session.messageCount = checkpoint.state.messages.length;
      }
    }
  }

  return sessions;
}

/**
 * Get the most recent session.
 */
export function getRecentSession(deps: SQLiteStoreDeps): SessionMetadata | null {
  const sessions = listSessions(deps);
  return sessions[0] || null;
}

/**
 * Get session metadata by ID.
 */
export function getSessionMetadata(deps: SQLiteStoreDeps, sessionId: string): SessionMetadata | undefined {
  return deps.stmts.getSession.get(sessionId) as SessionMetadata | undefined;
}

/**
 * Update session metadata.
 */
export function updateSessionMetadata(
  deps: SQLiteStoreDeps,
  sessionId: string,
  updates: Partial<Pick<SessionMetadata, 'name' | 'summary' | 'tokenCount'>>
): void {
  deps.stmts.updateSession.run({
    id: sessionId,
    name: updates.name || null,
    lastActiveAt: null,
    messageCount: null,
    tokenCount: updates.tokenCount || null,
    summary: updates.summary || null,
  });
}

// =============================================================================
// CHECKPOINTS
// =============================================================================

/**
 * Save a checkpoint for state restoration.
 */
export function saveCheckpoint(
  deps: SQLiteStoreDeps,
  state: Record<string, unknown>,
  description?: string
): string {
  if (!deps.getCurrentSessionId()) {
    createSession(deps);
  }

  const id = `ckpt-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
  const sessionId = deps.getCurrentSessionId()!;

  deps.stmts.insertCheckpoint.run({
    id,
    sessionId,
    stateJson: JSON.stringify(state),
    createdAt: new Date().toISOString(),
    description: description || null,
  });

  // Update message_count in sessions table to match checkpoint
  if (state.messages && Array.isArray(state.messages)) {
    deps.db.prepare(`
      UPDATE sessions SET message_count = ? WHERE id = ?
    `).run(state.messages.length, sessionId);
  }

  return id;
}

/**
 * Load the latest checkpoint for a session.
 */
export function loadLatestCheckpoint(
  deps: SQLiteStoreDeps,
  sessionId: string
): { id: string; state: Record<string, unknown>; createdAt: string; description?: string } | null {
  const row = deps.stmts.getLatestCheckpoint.get(sessionId) as {
    id: string;
    stateJson: string;
    createdAt: string;
    description: string | null;
  } | undefined;

  if (!row) return null;

  return {
    id: row.id,
    state: JSON.parse(row.stateJson),
    createdAt: row.createdAt,
    description: row.description ?? undefined,
  };
}

/**
 * Query entries with SQL (advanced usage).
 */
export function query<T = unknown>(deps: SQLiteStoreDeps, sql: string, params: unknown[] = []): T[] {
  return deps.db.prepare(sql).all(...params) as T[];
}

/**
 * Get database statistics.
 */
export function getStats(deps: SQLiteStoreDeps): {
  sessionCount: number;
  entryCount: number;
  toolCallCount: number;
  checkpointCount: number;
  dbSizeBytes: number;
} {
  const sessionCount = (deps.db.prepare('SELECT COUNT(*) as count FROM sessions').get() as { count: number }).count;
  const entryCount = (deps.db.prepare('SELECT COUNT(*) as count FROM entries').get() as { count: number }).count;
  const toolCallCount = (deps.db.prepare('SELECT COUNT(*) as count FROM tool_calls').get() as { count: number }).count;
  const checkpointCount = (deps.db.prepare('SELECT COUNT(*) as count FROM checkpoints').get() as { count: number }).count;
  const dbSizeBytes = (deps.db.prepare('SELECT page_count * page_size as size FROM pragma_page_count(), pragma_page_size()').get() as { size: number }).size;

  return { sessionCount, entryCount, toolCallCount, checkpointCount, dbSizeBytes };
}

// =============================================================================
// COST TRACKING
// =============================================================================

/**
 * Log API usage for cost tracking.
 * Inserts a usage log entry and updates session totals atomically.
 */
export function logUsage(deps: SQLiteStoreDeps, usage: UsageLog): void {
  // Use transaction to ensure atomicity of insert + update
  deps.db.transaction(() => {
    // Insert into usage_logs table
    deps.stmts.insertUsageLog.run({
      sessionId: usage.sessionId,
      modelId: usage.modelId,
      promptTokens: usage.promptTokens,
      completionTokens: usage.completionTokens,
      costUsd: usage.costUsd,
      timestamp: usage.timestamp,
    });

    // Update session totals
    deps.stmts.updateSessionCosts.run({
      sessionId: usage.sessionId,
      promptTokens: usage.promptTokens,
      completionTokens: usage.completionTokens,
      costUsd: usage.costUsd,
    });
  })();
}

/**
 * Get aggregated usage for a session.
 */
export function getSessionUsage(deps: SQLiteStoreDeps, sessionId: string): { promptTokens: number; completionTokens: number; costUsd: number } {
  const result = deps.stmts.getSessionUsage.get(sessionId) as {
    promptTokens: number;
    completionTokens: number;
    costUsd: number;
  } | undefined;

  return result || { promptTokens: 0, completionTokens: 0, costUsd: 0 };
}

// =============================================================================
// SESSION HIERARCHY
// =============================================================================

/**
 * Create a child session linked to a parent.
 */
export function createChildSession(
  deps: SQLiteStoreDeps,
  parentId: string,
  name?: string,
  type: SessionType = 'subagent'
): string {
  const id = `session-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
  const now = new Date().toISOString();

  deps.stmts.insertChildSession.run({
    id,
    name: name || null,
    workspacePath: process.cwd(),
    workspaceFingerprint: null,
    createdAt: now,
    lastActiveAt: now,
    messageCount: 0,
    tokenCount: 0,
    parentSessionId: parentId,
    sessionType: type,
  });

  deps.emit({ type: 'session.created', sessionId: id });
  return id;
}

/**
 * Get all direct child sessions of a parent.
 */
export function getChildSessions(deps: SQLiteStoreDeps, parentId: string): SessionMetadata[] {
  return deps.stmts.getChildSessions.all(parentId) as SessionMetadata[];
}

/**
 * Get the full session tree starting from a root session.
 * Uses a recursive CTE to traverse the hierarchy.
 */
export function getSessionTree(deps: SQLiteStoreDeps, rootId: string): SessionMetadata[] {
  const rows = deps.stmts.getSessionTree.all(rootId) as Array<SessionMetadata & { depth: number }>;
  // Remove the depth field from results (used only for ordering)
  return rows.map(({ depth, ...session }) => session);
}

// =============================================================================
// PENDING PLANS
// =============================================================================

/**
 * Save a pending plan to the database.
 */
export function savePendingPlan(
  deps: SQLiteStoreDeps,
  plan: PendingPlan,
  sessionId?: string
): void {
  if (!deps.features.pendingPlans || !deps.stmts.insertPendingPlan) {
    return;
  }

  const sid = sessionId ?? deps.getCurrentSessionId();
  if (!sid) return;

  const now = new Date().toISOString();

  // Check if plan already exists
  const existing = getPendingPlan(deps, sid);
  if (existing && existing.id === plan.id) {
    // Update existing plan
    deps.stmts.updatePendingPlan?.run({
      id: plan.id,
      proposedChanges: JSON.stringify(plan.proposedChanges),
      explorationSummary: plan.explorationSummary || null,
      status: plan.status,
      updatedAt: now,
    });
  } else {
    // Delete any existing pending plan first
    if (existing) {
      deps.stmts.deletePendingPlan?.run(existing.id);
    }

    // Insert new plan
    deps.stmts.insertPendingPlan.run({
      id: plan.id,
      sessionId: sid,
      task: plan.task,
      proposedChanges: JSON.stringify(plan.proposedChanges),
      explorationSummary: plan.explorationSummary || null,
      status: plan.status,
      createdAt: plan.createdAt,
      updatedAt: now,
    });
  }
}

/**
 * Get the pending plan for a session.
 * Returns the most recent pending plan, or null if none.
 */
export function getPendingPlan(deps: SQLiteStoreDeps, sessionId?: string): PendingPlan | null {
  if (!deps.features.pendingPlans || !deps.stmts.getPendingPlan) {
    return null;
  }

  const sid = sessionId ?? deps.getCurrentSessionId();
  if (!sid) return null;

  const row = deps.stmts.getPendingPlan.get(sid) as {
    id: string;
    sessionId: string;
    task: string;
    proposedChanges: string;
    explorationSummary: string | null;
    status: string;
    createdAt: string;
    updatedAt: string;
  } | undefined;

  if (!row) return null;

  return {
    id: row.id,
    task: row.task,
    createdAt: row.createdAt,
    updatedAt: row.updatedAt,
    proposedChanges: JSON.parse(row.proposedChanges) as ProposedChange[],
    explorationSummary: row.explorationSummary || '',
    status: row.status as PendingPlan['status'],
    sessionId: row.sessionId,
  };
}

/**
 * Update the status of a pending plan.
 */
export function updatePlanStatus(
  deps: SQLiteStoreDeps,
  planId: string,
  status: 'approved' | 'rejected' | 'partially_approved'
): void {
  if (!deps.features.pendingPlans || !deps.stmts.updatePendingPlan) {
    return;
  }

  const now = new Date().toISOString();

  deps.db.prepare(`
    UPDATE pending_plans SET status = ?, updated_at = ? WHERE id = ?
  `).run(status, now, planId);
}

/**
 * Delete a pending plan.
 */
export function deletePendingPlan(deps: SQLiteStoreDeps, planId: string): void {
  if (!deps.features.pendingPlans || !deps.stmts.deletePendingPlan) {
    return;
  }
  deps.stmts.deletePendingPlan.run(planId);
}

// =============================================================================
// REMEMBERED PERMISSIONS
// =============================================================================

/**
 * Remember a permission decision.
 */
export function rememberPermission(
  deps: SQLiteStoreDeps,
  toolName: string,
  decision: 'always' | 'never',
  pattern?: string
): void {
  if (!deps.features.rememberedPermissions || !deps.stmts.insertRememberedPermission) {
    return;
  }

  deps.stmts.insertRememberedPermission.run({
    toolName,
    pattern: pattern ?? null,
    decision,
    createdAt: new Date().toISOString(),
  });
}

/**
 * Get a remembered permission decision.
 */
export function getRememberedPermission(
  deps: SQLiteStoreDeps,
  toolName: string,
  pattern?: string
): { decision: 'always' | 'never'; pattern?: string } | undefined {
  if (!deps.features.rememberedPermissions || !deps.stmts.getRememberedPermission) {
    return undefined;
  }

  const row = deps.stmts.getRememberedPermission.get(toolName, pattern ?? null) as {
    toolName: string;
    pattern: string | null;
    decision: 'always' | 'never';
    createdAt: string;
  } | undefined;

  if (!row) return undefined;

  return {
    decision: row.decision,
    pattern: row.pattern ?? undefined,
  };
}

/**
 * List all remembered permission decisions.
 */
export function listRememberedPermissions(
  deps: SQLiteStoreDeps
): Array<{
  toolName: string;
  pattern?: string;
  decision: 'always' | 'never';
  createdAt: string;
}> {
  if (!deps.features.rememberedPermissions || !deps.stmts.listRememberedPermissions) {
    return [];
  }

  const rows = deps.stmts.listRememberedPermissions.all() as Array<{
    toolName: string;
    pattern: string | null;
    decision: 'always' | 'never';
    createdAt: string;
  }>;

  return rows.map(row => ({
    toolName: row.toolName,
    pattern: row.pattern ?? undefined,
    decision: row.decision,
    createdAt: row.createdAt,
  }));
}

/**
 * Remove a remembered permission decision.
 */
export function forgetPermission(deps: SQLiteStoreDeps, toolName: string, pattern?: string): void {
  if (!deps.features.rememberedPermissions || !deps.stmts.deleteRememberedPermission) {
    return;
  }

  deps.stmts.deleteRememberedPermission.run(toolName, pattern ?? null, pattern ?? null);
}

/**
 * Clear all remembered permissions for a tool or all tools.
 */
export function clearRememberedPermissions(deps: SQLiteStoreDeps, toolName?: string): void {
  if (!deps.features.rememberedPermissions) {
    return;
  }

  if (toolName) {
    deps.db.prepare('DELETE FROM remembered_permissions WHERE tool_name = ?').run(toolName);
  } else {
    deps.db.prepare('DELETE FROM remembered_permissions').run();
  }
}

// =============================================================================
// SESSION MANIFEST (Handoff Support)
// =============================================================================

/**
 * Callbacks for manifest export.
 * These are provided by the SQLiteStore class to bridge to goal/worker repositories.
 */
export interface ManifestCallbacks {
  listGoals(sessionId?: string): Array<{ id: string; goalText: string; status: string; priority: number; progressCurrent: number; progressTotal?: number; completedAt?: string }>;
  listJunctures(sessionId?: string, limit?: number): Array<{ type: string; description: string; outcome?: string; createdAt: string }>;
  listWorkerResults(sessionId?: string): Array<{ id: string; taskDescription: string; status: string; summary?: string; modelUsed?: string }>;
}

/**
 * Export a complete session manifest for handoff.
 * Contains all information needed for another agent/human to pick up the work.
 */
export function exportSessionManifest(
  deps: SQLiteStoreDeps,
  callbacks: ManifestCallbacks,
  sessionId?: string
): SessionManifest | undefined {
  const sid = sessionId ?? deps.getCurrentSessionId();
  if (!sid) return undefined;

  const session = getSessionMetadata(deps, sid);
  if (!session) return undefined;

  // Collect all session state
  const goals = callbacks.listGoals(sid);
  const activeGoals = goals.filter(g => g.status === 'active');
  const completedGoals = goals.filter(g => g.status === 'completed');
  const junctures = callbacks.listJunctures(sid, 20);
  const workerResults = callbacks.listWorkerResults(sid);
  const entries = loadSession(deps, sid);

  // Count message types from entries
  let messageCount = entries.filter(e => e.type === 'message').length;
  const toolCallCount = entries.filter(e => e.type === 'tool_call').length;
  const compactionCount = entries.filter(e => e.type === 'compaction').length;

  // If no messages in entries, check the latest checkpoint
  if (messageCount === 0) {
    const checkpoint = loadLatestCheckpoint(deps, sid);
    if (checkpoint?.state?.messages && Array.isArray(checkpoint.state.messages)) {
      messageCount = checkpoint.state.messages.length;
    }
  }

  return {
    version: '1.0',
    exportedAt: new Date().toISOString(),
    session: {
      id: session.id,
      name: session.name,
      createdAt: session.createdAt,
      lastActiveAt: session.lastActiveAt,
      summary: session.summary,
    },
    state: {
      messageCount,
      toolCallCount,
      compactionCount,
      tokenCount: session.tokenCount,
      costUsd: session.costUsd,
    },
    goals: {
      active: activeGoals.map(g => ({
        id: g.id,
        text: g.goalText,
        priority: g.priority,
        progress: g.progressTotal
          ? `${g.progressCurrent}/${g.progressTotal}`
          : undefined,
      })),
      completed: completedGoals.map(g => ({
        id: g.id,
        text: g.goalText,
        completedAt: g.completedAt,
      })),
    },
    keyMoments: junctures.map(j => ({
      type: j.type,
      description: j.description,
      outcome: j.outcome,
      createdAt: j.createdAt,
    })),
    workerResults: workerResults.map(r => ({
      id: r.id,
      task: r.taskDescription,
      status: r.status,
      summary: r.summary,
      model: r.modelUsed,
    })),
    resumption: {
      currentSessionId: sid,
      canResume: true,
      hint: 'Load this session with /load ' + sid.slice(-8),
    },
  };
}

/**
 * Export session as human-readable markdown.
 */
export function exportSessionMarkdown(
  deps: SQLiteStoreDeps,
  callbacks: ManifestCallbacks,
  sessionId?: string
): string {
  const manifest = exportSessionManifest(deps, callbacks, sessionId);
  if (!manifest) return '# Session Not Found\n';

  const lines: string[] = [];

  // Header
  lines.push(`# Session Handoff: ${manifest.session.name || manifest.session.id}`);
  lines.push('');
  lines.push(`> Exported: ${manifest.exportedAt}`);
  lines.push(`> Session ID: \`${manifest.session.id}\``);
  lines.push('');

  // Summary
  if (manifest.session.summary) {
    lines.push('## Summary');
    lines.push('');
    lines.push(manifest.session.summary);
    lines.push('');
  }

  // State
  lines.push('## Session State');
  lines.push('');
  lines.push(`- Messages: ${manifest.state.messageCount}`);
  lines.push(`- Tool Calls: ${manifest.state.toolCallCount}`);
  lines.push(`- Compactions: ${manifest.state.compactionCount}`);
  lines.push(`- Tokens: ${manifest.state.tokenCount?.toLocaleString() ?? 'N/A'}`);
  if (manifest.state.costUsd) {
    lines.push(`- Cost: $${manifest.state.costUsd.toFixed(4)}`);
  }
  lines.push('');

  // Active Goals
  if (manifest.goals.active.length > 0) {
    lines.push('## Active Goals');
    lines.push('');
    for (const goal of manifest.goals.active) {
      const priority = goal.priority === 1 ? ' **[HIGH]**' : goal.priority === 3 ? ' [low]' : '';
      const progress = goal.progress ? ` (${goal.progress})` : '';
      lines.push(`- [ ] ${goal.text}${progress}${priority}`);
    }
    lines.push('');
  }

  // Completed Goals
  if (manifest.goals.completed.length > 0) {
    lines.push('## Completed Goals');
    lines.push('');
    for (const goal of manifest.goals.completed) {
      lines.push(`- [x] ${goal.text}`);
    }
    lines.push('');
  }

  // Key Moments
  if (manifest.keyMoments.length > 0) {
    lines.push('## Key Moments');
    lines.push('');
    for (const moment of manifest.keyMoments) {
      const icon = moment.type === 'failure' ? '\u274C' :
                   moment.type === 'breakthrough' ? '\u2B50' :
                   moment.type === 'decision' ? '\u2192' : '\u21BB';
      lines.push(`### ${icon} ${moment.type.charAt(0).toUpperCase() + moment.type.slice(1)}`);
      lines.push('');
      lines.push(moment.description);
      if (moment.outcome) {
        lines.push('');
        lines.push(`**Outcome:** ${moment.outcome}`);
      }
      lines.push('');
    }
  }

  // Worker Results
  if (manifest.workerResults.length > 0) {
    lines.push('## Worker Results');
    lines.push('');
    for (const result of manifest.workerResults) {
      const status = result.status === 'success' ? '\u2705' :
                    result.status === 'error' ? '\u274C' : '\u23F3';
      lines.push(`- ${status} **${result.task}**`);
      if (result.summary) {
        lines.push(`  - ${result.summary}`);
      }
      if (result.model) {
        lines.push(`  - Model: ${result.model}`);
      }
    }
    lines.push('');
  }

  // Resumption
  lines.push('## How to Resume');
  lines.push('');
  lines.push('```bash');
  lines.push(`attocode --load ${manifest.resumption.currentSessionId}`);
  lines.push('```');
  lines.push('');
  lines.push('Or within attocode:');
  lines.push('```');
  lines.push(manifest.resumption.hint);
  lines.push('```');

  return lines.join('\n');
}

// =============================================================================
// MIGRATION
// =============================================================================

/**
 * Migrate sessions from JSONL format to SQLite.
 */
export async function migrateFromJSONL(
  deps: SQLiteStoreDeps,
  jsonlDir: string
): Promise<{ migrated: number; failed: number }> {
  const indexPath = join(jsonlDir, 'index.json');
  let migrated = 0;
  let failed = 0;

  if (!existsSync(indexPath)) {
    return { migrated: 0, failed: 0 };
  }

  try {
    const indexContent = readFileSync(indexPath, 'utf-8');
    const index = JSON.parse(indexContent) as { sessions: SessionMetadata[] };

    for (const meta of index.sessions) {
      try {
        // Check if already migrated
        const existing = getSessionMetadata(deps, meta.id);
        if (existing) {
          continue;
        }

        // Insert session metadata
        deps.stmts.insertSession.run({
          id: meta.id,
          name: meta.name || null,
          workspacePath: (meta as SessionMetadata).workspacePath || null,
          workspaceFingerprint: (meta as SessionMetadata).workspaceFingerprint || null,
          createdAt: meta.createdAt,
          lastActiveAt: meta.lastActiveAt,
          messageCount: meta.messageCount,
          tokenCount: meta.tokenCount,
        });

        // Load and migrate entries
        const sessionPath = join(jsonlDir, `${meta.id}.jsonl`);
        if (existsSync(sessionPath)) {
          const content = readFileSync(sessionPath, 'utf-8');
          for (const line of content.split('\n')) {
            if (line.trim()) {
              try {
                const entry = JSON.parse(line) as SessionEntry;
                deps.stmts.insertEntry.run({
                  sessionId: meta.id,
                  timestamp: entry.timestamp,
                  type: entry.type,
                  data: JSON.stringify(entry.data),
                });
              } catch {
                // Skip corrupted lines
              }
            }
          }
        }

        migrated++;
      } catch (err) {
        logger.error(`Failed to migrate session ${meta.id}:`, { error: err });
        failed++;
      }
    }
  } catch (err) {
    logger.error('Failed to read JSONL index:', { error: err });
  }

  return { migrated, failed };
}

// =============================================================================
// LIFECYCLE HELPERS
// =============================================================================

/**
 * Prune old sessions if over limit.
 */
export function pruneOldSessions(deps: SQLiteStoreDeps): void {
  const sessions = listSessions(deps);
  if (sessions.length > deps.config.maxSessions) {
    const toDelete = sessions.slice(deps.config.maxSessions);
    for (const session of toDelete) {
      deps.stmts.deleteSession.run(session.id);
    }
  }
}
