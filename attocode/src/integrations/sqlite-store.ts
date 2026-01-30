/**
 * SQLite Session Store
 *
 * Alternative backend for session persistence using SQLite.
 * Provides better query performance and ACID guarantees.
 *
 * @example
 * ```typescript
 * const store = await createSQLiteStore({ dbPath: '.agent/sessions.db' });
 * await store.createSession('My Session');
 * await store.appendMessage({ role: 'user', content: 'Hello' });
 * ```
 */

import Database from 'better-sqlite3';
import { join, dirname } from 'node:path';
import { mkdir } from 'node:fs/promises';
import { existsSync, readFileSync } from 'node:fs';
import type { Message, ToolCall } from '../types.js';
import type {
  SessionEntry,
  SessionEntryType,
  SessionEvent,
  SessionEventListener,
  SessionStoreConfig,
} from './session-store.js';
import {
  applyMigrations,
  getMigrationStatus,
  detectFeatures,
  type SchemaFeatures,
} from '../persistence/schema.js';
import type { PendingPlan, ProposedChange } from './pending-plan.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * SQLite store configuration.
 */
export interface SQLiteStoreConfig extends SessionStoreConfig {
  /** Path to SQLite database file */
  dbPath?: string;
  /** Enable WAL mode for better concurrency (default: true) */
  walMode?: boolean;
}

/**
 * Usage log entry for tracking API costs.
 */
export interface UsageLog {
  /** Session ID this usage belongs to */
  sessionId: string;
  /** Model ID used for the request */
  modelId: string;
  /** Number of prompt tokens used */
  promptTokens: number;
  /** Number of completion tokens generated */
  completionTokens: number;
  /** Cost in USD for this request */
  costUsd: number;
  /** ISO timestamp of when the usage occurred */
  timestamp: string;
}

/**
 * Session types for hierarchy management.
 */
export type SessionType = 'main' | 'subagent' | 'branch' | 'fork';

/**
 * Session metadata with cost tracking and hierarchy support.
 */
export interface SessionMetadata {
  id: string;
  name?: string;
  createdAt: string;
  lastActiveAt: string;
  messageCount: number;
  tokenCount: number;
  summary?: string;
  /** Parent session ID for child sessions */
  parentSessionId?: string;
  /** Type of session */
  sessionType?: SessionType;
  /** Total prompt tokens used */
  promptTokens?: number;
  /** Total completion tokens generated */
  completionTokens?: number;
  /** Total cost in USD */
  costUsd?: number;
}

/**
 * Goal status types.
 */
export type GoalStatus = 'active' | 'completed' | 'abandoned';

/**
 * Goal for tracking agent objectives.
 * Goals persist outside of context and survive compaction.
 */
export interface Goal {
  id: string;
  sessionId: string;
  goalText: string;
  status: GoalStatus;
  priority: number;        // 1=highest, 3=lowest
  parentGoalId?: string;   // for sub-goals
  progressCurrent: number;
  progressTotal?: number;
  createdAt: string;
  updatedAt: string;
  completedAt?: string;
  metadata?: string;       // JSON for extensibility
}

/**
 * Juncture type - key moments in agent execution.
 */
export type JunctureType = 'decision' | 'failure' | 'breakthrough' | 'pivot';

/**
 * Critical juncture - captures key decisions, failures, breakthroughs.
 */
export interface Juncture {
  id: number;
  sessionId: string;
  goalId?: string;
  type: JunctureType;
  description: string;
  outcome?: string;
  importance: number;      // 1=critical, 2=significant, 3=minor
  context?: string;        // JSON
  createdAt: string;
}

/**
 * Worker result status types.
 */
export type WorkerResultStatus = 'pending' | 'success' | 'error';

/**
 * Worker result - stores full output outside main context.
 * Main agent only sees reference + summary.
 */
export interface WorkerResult {
  id: string;
  sessionId: string;
  workerId: string;
  taskDescription: string;
  modelUsed?: string;
  status: WorkerResultStatus;
  summary?: string;           // Brief summary for context injection
  fullOutput?: string;        // Complete output stored here (not in context)
  artifacts?: string;         // JSON: files modified, code generated
  metrics?: string;           // JSON: tokens, duration, tool_calls
  error?: string;
  createdAt: string;
  completedAt?: string;
}

/**
 * Worker result reference - lightweight pointer to stored result.
 * This is what gets injected into context instead of full output.
 */
export interface WorkerResultRef {
  id: string;
  workerId: string;
  taskDescription: string;
  status: WorkerResultStatus;
  summary?: string;
  modelUsed?: string;
  /** Hint: Use store.getWorkerResult(id) to retrieve full output */
  retrievalHint: string;
}

/**
 * Session manifest - complete snapshot for handoff.
 * Contains all information needed for another agent/human to pick up work.
 */
export interface SessionManifest {
  version: string;
  exportedAt: string;
  session: {
    id: string;
    name?: string;
    createdAt: string;
    lastActiveAt: string;
    summary?: string;
  };
  state: {
    messageCount: number;
    toolCallCount: number;
    compactionCount: number;
    tokenCount?: number;
    costUsd?: number;
  };
  goals: {
    active: Array<{
      id: string;
      text: string;
      priority: number;
      progress?: string;
    }>;
    completed: Array<{
      id: string;
      text: string;
      completedAt?: string;
    }>;
  };
  keyMoments: Array<{
    type: string;
    description: string;
    outcome?: string;
    createdAt: string;
  }>;
  workerResults: Array<{
    id: string;
    task: string;
    status: string;
    summary?: string;
    model?: string;
  }>;
  resumption: {
    currentSessionId: string;
    canResume: boolean;
    hint: string;
  };
}

// =============================================================================
// SQLITE STORE
// =============================================================================

/**
 * SQLite-backed session store.
 */
export class SQLiteStore {
  private db: Database.Database;
  private config: Required<SQLiteStoreConfig>;
  private currentSessionId: string | null = null;
  private listeners: SessionEventListener[] = [];

  /** Available schema features (detected after migration) */
  private features: SchemaFeatures = {
    core: false,
    costs: false,
    hierarchy: false,
    compaction: false,
    fileChanges: false,
    goals: false,
    workerResults: false,
    pendingPlans: false,
    deadLetterQueue: false,
    rememberedPermissions: false,
  };

  // Prepared statements for performance
  // Goal-related statements are optional (only prepared if feature is available)
  private stmts!: {
    // Core statements (always available)
    insertSession: Database.Statement;
    updateSession: Database.Statement;
    deleteSession: Database.Statement;
    getSession: Database.Statement;
    listSessions: Database.Statement;
    insertEntry: Database.Statement;
    getEntries: Database.Statement;
    insertToolCall: Database.Statement;
    updateToolCall: Database.Statement;
    insertCheckpoint: Database.Statement;
    getLatestCheckpoint: Database.Statement;
    // Cost tracking statements
    insertUsageLog: Database.Statement;
    updateSessionCosts: Database.Statement;
    getSessionUsage: Database.Statement;
    // Session hierarchy statements
    insertChildSession: Database.Statement;
    getChildSessions: Database.Statement;
    getSessionTree: Database.Statement;
    // Goal integrity statements (optional - only if goals feature available)
    insertGoal?: Database.Statement;
    updateGoal?: Database.Statement;
    getGoal?: Database.Statement;
    listGoals?: Database.Statement;
    listActiveGoals?: Database.Statement;
    insertJuncture?: Database.Statement;
    listJunctures?: Database.Statement;
    // Worker result statements (optional - only if workerResults feature available)
    insertWorkerResult?: Database.Statement;
    updateWorkerResult?: Database.Statement;
    getWorkerResult?: Database.Statement;
    listWorkerResults?: Database.Statement;
    listPendingWorkerResults?: Database.Statement;
    // Pending plan statements (optional - only if pendingPlans feature available)
    insertPendingPlan?: Database.Statement;
    updatePendingPlan?: Database.Statement;
    getPendingPlan?: Database.Statement;
    deletePendingPlan?: Database.Statement;
    // Remembered permissions statements (optional - only if rememberedPermissions feature available)
    insertRememberedPermission?: Database.Statement;
    getRememberedPermission?: Database.Statement;
    listRememberedPermissions?: Database.Statement;
    deleteRememberedPermission?: Database.Statement;
  };

  constructor(config: SQLiteStoreConfig = {}) {
    this.config = {
      baseDir: config.baseDir || '.agent/sessions',
      dbPath: config.dbPath || join(config.baseDir || '.agent/sessions', 'sessions.db'),
      autoSave: config.autoSave ?? true,
      maxSessions: config.maxSessions || 50,
      walMode: config.walMode ?? true,
    };

    // Initialize database
    this.db = new Database(this.config.dbPath);

    // Enable WAL mode for better concurrent access
    if (this.config.walMode) {
      this.db.pragma('journal_mode = WAL');
    }

    // Enable foreign keys
    this.db.pragma('foreign_keys = ON');
  }

  /**
   * Initialize the store (create tables, prepare statements).
   */
  async initialize(): Promise<void> {
    // Ensure directory exists
    const dbDir = dirname(this.config.dbPath);
    if (!existsSync(dbDir)) {
      await mkdir(dbDir, { recursive: true });
    }

    // Apply embedded migrations (no file I/O needed)
    const isDebug = process.env.DEBUG || process.argv.includes('--debug');
    if (isDebug) {
      const status = getMigrationStatus(this.db);
      process.stderr.write(
        `[DEBUG] [SQLite] DB version: ${status.currentVersion}, latest: ${status.latestVersion}, pending: ${status.pendingCount}\n`
      );
    }

    const result = applyMigrations(this.db);

    if (isDebug && result.applied > 0) {
      process.stderr.write(
        `[DEBUG] [SQLite] Applied ${result.applied} migrations: ${result.appliedMigrations.join(', ')}\n`
      );
    }

    // Detect available features after migrations
    this.features = detectFeatures(this.db);

    if (isDebug) {
      const enabled = Object.entries(this.features)
        .filter(([, v]) => v)
        .map(([k]) => k);
      process.stderr.write(`[DEBUG] [SQLite] Features: ${enabled.join(', ')}\n`);
    }

    // Prepare statements for available features
    this.prepareStatements();
  }

  /**
   * Prepare SQL statements for reuse.
   */
  private prepareStatements(): void {
    this.stmts = {
      insertSession: this.db.prepare(`
        INSERT INTO sessions (id, name, created_at, last_active_at, message_count, token_count)
        VALUES (@id, @name, @createdAt, @lastActiveAt, @messageCount, @tokenCount)
      `),

      updateSession: this.db.prepare(`
        UPDATE sessions SET
          name = COALESCE(@name, name),
          last_active_at = COALESCE(@lastActiveAt, last_active_at),
          message_count = COALESCE(@messageCount, message_count),
          token_count = COALESCE(@tokenCount, token_count),
          summary = COALESCE(@summary, summary)
        WHERE id = @id
      `),

      deleteSession: this.db.prepare(`DELETE FROM sessions WHERE id = ?`),

      getSession: this.db.prepare(`
        SELECT id, name, created_at as createdAt,
               COALESCE(last_active_at, created_at) as lastActiveAt,
               message_count as messageCount, token_count as tokenCount, summary,
               parent_session_id as parentSessionId, session_type as sessionType,
               prompt_tokens as promptTokens, completion_tokens as completionTokens,
               cost_usd as costUsd
        FROM sessions WHERE id = ?
      `),

      listSessions: this.db.prepare(`
        SELECT id, name, created_at as createdAt,
               COALESCE(last_active_at, created_at) as lastActiveAt,
               message_count as messageCount, token_count as tokenCount, summary,
               parent_session_id as parentSessionId, session_type as sessionType,
               prompt_tokens as promptTokens, completion_tokens as completionTokens,
               cost_usd as costUsd
        FROM sessions ORDER BY COALESCE(last_active_at, created_at) DESC
      `),

      insertEntry: this.db.prepare(`
        INSERT INTO entries (session_id, timestamp, type, data)
        VALUES (@sessionId, @timestamp, @type, @data)
      `),

      getEntries: this.db.prepare(`
        SELECT timestamp, type, data FROM entries
        WHERE session_id = ? ORDER BY id ASC
      `),

      insertToolCall: this.db.prepare(`
        INSERT INTO tool_calls (id, session_id, name, arguments, status, created_at)
        VALUES (@id, @sessionId, @name, @arguments, @status, @createdAt)
      `),

      updateToolCall: this.db.prepare(`
        UPDATE tool_calls SET
          status = @status,
          result = @result,
          error = @error,
          duration_ms = @durationMs,
          completed_at = @completedAt
        WHERE id = @id
      `),

      insertCheckpoint: this.db.prepare(`
        INSERT INTO checkpoints (id, session_id, state_json, created_at, description)
        VALUES (@id, @sessionId, @stateJson, @createdAt, @description)
      `),

      getLatestCheckpoint: this.db.prepare(`
        SELECT id, session_id as sessionId, state_json as stateJson,
               created_at as createdAt, description
        FROM checkpoints WHERE session_id = ?
        ORDER BY created_at DESC, rowid DESC LIMIT 1
      `),

      // Cost tracking statements
      insertUsageLog: this.db.prepare(`
        INSERT INTO usage_logs (session_id, model_id, prompt_tokens, completion_tokens, cost_usd, timestamp)
        VALUES (@sessionId, @modelId, @promptTokens, @completionTokens, @costUsd, @timestamp)
      `),

      updateSessionCosts: this.db.prepare(`
        UPDATE sessions SET
          prompt_tokens = COALESCE(prompt_tokens, 0) + @promptTokens,
          completion_tokens = COALESCE(completion_tokens, 0) + @completionTokens,
          cost_usd = COALESCE(cost_usd, 0) + @costUsd
        WHERE id = @sessionId
      `),

      getSessionUsage: this.db.prepare(`
        SELECT
          COALESCE(SUM(prompt_tokens), 0) as promptTokens,
          COALESCE(SUM(completion_tokens), 0) as completionTokens,
          COALESCE(SUM(cost_usd), 0) as costUsd
        FROM usage_logs WHERE session_id = ?
      `),

      // Session hierarchy statements
      insertChildSession: this.db.prepare(`
        INSERT INTO sessions (id, name, created_at, last_active_at, message_count, token_count, parent_session_id, session_type)
        VALUES (@id, @name, @createdAt, @lastActiveAt, @messageCount, @tokenCount, @parentSessionId, @sessionType)
      `),

      getChildSessions: this.db.prepare(`
        SELECT id, name, created_at as createdAt, last_active_at as lastActiveAt,
               message_count as messageCount, token_count as tokenCount, summary,
               parent_session_id as parentSessionId, session_type as sessionType,
               prompt_tokens as promptTokens, completion_tokens as completionTokens,
               cost_usd as costUsd
        FROM sessions WHERE parent_session_id = ?
        ORDER BY created_at ASC
      `),

      getSessionTree: this.db.prepare(`
        WITH RECURSIVE session_tree AS (
          SELECT id, name, created_at as createdAt, last_active_at as lastActiveAt,
                 message_count as messageCount, token_count as tokenCount, summary,
                 parent_session_id as parentSessionId, session_type as sessionType,
                 prompt_tokens as promptTokens, completion_tokens as completionTokens,
                 cost_usd as costUsd, 0 as depth
          FROM sessions WHERE id = ?
          UNION ALL
          SELECT s.id, s.name, s.created_at, s.last_active_at,
                 s.message_count, s.token_count, s.summary,
                 s.parent_session_id, s.session_type,
                 s.prompt_tokens, s.completion_tokens,
                 s.cost_usd, st.depth + 1
          FROM sessions s
          INNER JOIN session_tree st ON s.parent_session_id = st.id
        )
        SELECT * FROM session_tree ORDER BY depth, createdAt ASC
      `),
    };

    // Goal integrity statements - only prepare if feature is available
    if (this.features.goals) {
      this.stmts.insertGoal = this.db.prepare(`
        INSERT INTO goals (id, session_id, goal_text, status, priority, parent_goal_id,
                          progress_current, progress_total, created_at, updated_at, metadata)
        VALUES (@id, @sessionId, @goalText, @status, @priority, @parentGoalId,
                @progressCurrent, @progressTotal, @createdAt, @updatedAt, @metadata)
      `);

      this.stmts.updateGoal = this.db.prepare(`
        UPDATE goals SET
          goal_text = COALESCE(@goalText, goal_text),
          status = COALESCE(@status, status),
          priority = COALESCE(@priority, priority),
          progress_current = COALESCE(@progressCurrent, progress_current),
          progress_total = COALESCE(@progressTotal, progress_total),
          updated_at = @updatedAt,
          completed_at = @completedAt,
          metadata = COALESCE(@metadata, metadata)
        WHERE id = @id
      `);

      this.stmts.getGoal = this.db.prepare(`
        SELECT id, session_id as sessionId, goal_text as goalText, status, priority,
               parent_goal_id as parentGoalId, progress_current as progressCurrent,
               progress_total as progressTotal, created_at as createdAt,
               updated_at as updatedAt, completed_at as completedAt, metadata
        FROM goals WHERE id = ?
      `);

      this.stmts.listGoals = this.db.prepare(`
        SELECT id, session_id as sessionId, goal_text as goalText, status, priority,
               parent_goal_id as parentGoalId, progress_current as progressCurrent,
               progress_total as progressTotal, created_at as createdAt,
               updated_at as updatedAt, completed_at as completedAt, metadata
        FROM goals WHERE session_id = ? ORDER BY priority ASC, created_at ASC
      `);

      this.stmts.listActiveGoals = this.db.prepare(`
        SELECT id, session_id as sessionId, goal_text as goalText, status, priority,
               parent_goal_id as parentGoalId, progress_current as progressCurrent,
               progress_total as progressTotal, created_at as createdAt,
               updated_at as updatedAt, completed_at as completedAt, metadata
        FROM goals WHERE session_id = ? AND status = 'active'
        ORDER BY priority ASC, created_at ASC
      `);

      this.stmts.insertJuncture = this.db.prepare(`
        INSERT INTO junctures (session_id, goal_id, type, description, outcome,
                               importance, context, created_at)
        VALUES (@sessionId, @goalId, @type, @description, @outcome,
                @importance, @context, @createdAt)
      `);

      this.stmts.listJunctures = this.db.prepare(`
        SELECT id, session_id as sessionId, goal_id as goalId, type, description,
               outcome, importance, context, created_at as createdAt
        FROM junctures WHERE session_id = ? ORDER BY created_at DESC
      `);
    }

    // Worker result statements - only prepare if feature is available
    if (this.features.workerResults) {
      this.stmts.insertWorkerResult = this.db.prepare(`
        INSERT INTO worker_results (id, session_id, worker_id, task_description, model_used,
                                    status, summary, full_output, artifacts, metrics, error,
                                    created_at, completed_at)
        VALUES (@id, @sessionId, @workerId, @taskDescription, @modelUsed,
                @status, @summary, @fullOutput, @artifacts, @metrics, @error,
                @createdAt, @completedAt)
      `);

      this.stmts.updateWorkerResult = this.db.prepare(`
        UPDATE worker_results SET
          status = COALESCE(@status, status),
          summary = COALESCE(@summary, summary),
          full_output = COALESCE(@fullOutput, full_output),
          artifacts = COALESCE(@artifacts, artifacts),
          metrics = COALESCE(@metrics, metrics),
          error = @error,
          completed_at = @completedAt
        WHERE id = @id
      `);

      this.stmts.getWorkerResult = this.db.prepare(`
        SELECT id, session_id as sessionId, worker_id as workerId,
               task_description as taskDescription, model_used as modelUsed,
               status, summary, full_output as fullOutput, artifacts, metrics,
               error, created_at as createdAt, completed_at as completedAt
        FROM worker_results WHERE id = ?
      `);

      this.stmts.listWorkerResults = this.db.prepare(`
        SELECT id, session_id as sessionId, worker_id as workerId,
               task_description as taskDescription, model_used as modelUsed,
               status, summary, full_output as fullOutput, artifacts, metrics,
               error, created_at as createdAt, completed_at as completedAt
        FROM worker_results WHERE session_id = ?
        ORDER BY created_at DESC
      `);

      this.stmts.listPendingWorkerResults = this.db.prepare(`
        SELECT id, session_id as sessionId, worker_id as workerId,
               task_description as taskDescription, model_used as modelUsed,
               status, summary, created_at as createdAt
        FROM worker_results WHERE session_id = ? AND status = 'pending'
        ORDER BY created_at ASC
      `);
    }

    // Pending plan statements (optional - only if pendingPlans feature available)
    if (this.features.pendingPlans) {
      this.stmts.insertPendingPlan = this.db.prepare(`
        INSERT INTO pending_plans (id, session_id, task, proposed_changes, exploration_summary, status, created_at, updated_at)
        VALUES (@id, @sessionId, @task, @proposedChanges, @explorationSummary, @status, @createdAt, @updatedAt)
      `);

      this.stmts.updatePendingPlan = this.db.prepare(`
        UPDATE pending_plans SET
          proposed_changes = @proposedChanges,
          exploration_summary = @explorationSummary,
          status = @status,
          updated_at = @updatedAt
        WHERE id = @id
      `);

      this.stmts.getPendingPlan = this.db.prepare(`
        SELECT id, session_id as sessionId, task, proposed_changes as proposedChanges,
               exploration_summary as explorationSummary, status, created_at as createdAt, updated_at as updatedAt
        FROM pending_plans WHERE session_id = ? AND status = 'pending'
        ORDER BY created_at DESC LIMIT 1
      `);

      this.stmts.deletePendingPlan = this.db.prepare(`
        DELETE FROM pending_plans WHERE id = ?
      `);
    }

    // Remembered permissions statements (optional - only if feature available)
    if (this.features.rememberedPermissions) {
      this.stmts.insertRememberedPermission = this.db.prepare(`
        INSERT OR REPLACE INTO remembered_permissions (tool_name, pattern, decision, created_at)
        VALUES (@toolName, @pattern, @decision, @createdAt)
      `);

      this.stmts.getRememberedPermission = this.db.prepare(`
        SELECT tool_name as toolName, pattern, decision, created_at as createdAt
        FROM remembered_permissions
        WHERE tool_name = ? AND (pattern = ? OR pattern IS NULL)
        ORDER BY pattern IS NULL ASC
        LIMIT 1
      `);

      this.stmts.listRememberedPermissions = this.db.prepare(`
        SELECT tool_name as toolName, pattern, decision, created_at as createdAt
        FROM remembered_permissions
        ORDER BY tool_name, pattern
      `);

      this.stmts.deleteRememberedPermission = this.db.prepare(`
        DELETE FROM remembered_permissions WHERE tool_name = ? AND (pattern = ? OR (? IS NULL AND pattern IS NULL))
      `);
    }
  }

  // ===========================================================================
  // SESSION MANAGEMENT (compatible with SessionStore interface)
  // ===========================================================================

  /**
   * Create a new session.
   */
  createSession(name?: string): string {
    const id = `session-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
    const now = new Date().toISOString();

    this.stmts.insertSession.run({
      id,
      name: name || null,
      createdAt: now,
      lastActiveAt: now,
      messageCount: 0,
      tokenCount: 0,
    });

    this.currentSessionId = id;

    // Prune old sessions
    this.pruneOldSessions();

    this.emit({ type: 'session.created', sessionId: id });
    return id;
  }

  /**
   * Get current session ID.
   */
  getCurrentSessionId(): string | null {
    return this.currentSessionId;
  }

  /**
   * Set current session ID.
   */
  setCurrentSessionId(sessionId: string): void {
    this.currentSessionId = sessionId;
  }

  /**
   * Append an entry to the current session.
   */
  appendEntry(entry: Omit<SessionEntry, 'timestamp'>): void {
    if (!this.currentSessionId) {
      this.createSession();
    }

    const timestamp = new Date().toISOString();

    this.stmts.insertEntry.run({
      sessionId: this.currentSessionId,
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
        const session = this.stmts.getSession.get(this.currentSessionId) as SessionMetadata | undefined;
        if (session && !session.summary) {
          // Extract first line or first ~50 chars as summary
          const firstLine = msg.content.split('\n')[0].trim();
          const summary = firstLine.length > 60 ? firstLine.slice(0, 57) + '...' : firstLine;
          this.db.prepare(`UPDATE sessions SET summary = ? WHERE id = ?`).run(summary, this.currentSessionId);
        }
      }

      this.db.prepare(`
        UPDATE sessions SET
          last_active_at = ?,
          message_count = message_count + 1
        WHERE id = ?
      `).run(timestamp, this.currentSessionId);
    } else {
      this.db.prepare(`
        UPDATE sessions SET last_active_at = ? WHERE id = ?
      `).run(timestamp, this.currentSessionId);
    }

    this.emit({ type: 'entry.appended', sessionId: this.currentSessionId!, entryType: entry.type });
  }

  /**
   * Append a message to the current session.
   */
  appendMessage(message: Message): void {
    this.appendEntry({ type: 'message', data: message });
  }

  /**
   * Append a tool call to the current session.
   */
  appendToolCall(toolCall: ToolCall): void {
    this.appendEntry({ type: 'tool_call', data: toolCall });

    // Also insert into tool_calls table for fast lookup
    if ('id' in toolCall && toolCall.id) {
      this.stmts.insertToolCall.run({
        id: toolCall.id,
        sessionId: this.currentSessionId,
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
  appendToolResult(callId: string, result: unknown): void {
    this.appendEntry({ type: 'tool_result', data: { callId, result } });

    // Update tool_calls table
    this.stmts.updateToolCall.run({
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
  appendCompaction(summary: string, compactedCount: number): void {
    this.appendEntry({
      type: 'compaction',
      data: { summary, compactedCount, compactedAt: new Date().toISOString() },
    });
  }

  /**
   * Load a session by ID.
   */
  loadSession(sessionId: string): SessionEntry[] {
    const rows = this.stmts.getEntries.all(sessionId) as Array<{
      timestamp: string;
      type: string;
      data: string;
    }>;

    const entries: SessionEntry[] = rows.map(row => ({
      timestamp: row.timestamp,
      type: row.type as SessionEntryType,
      data: JSON.parse(row.data),
    }));

    this.currentSessionId = sessionId;
    this.emit({ type: 'session.loaded', sessionId, entryCount: entries.length });

    return entries;
  }

  /**
   * Reconstruct messages from session entries.
   */
  loadSessionMessages(sessionId: string): Message[] {
    const entries = this.loadSession(sessionId);
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
  deleteSession(sessionId: string): void {
    this.stmts.deleteSession.run(sessionId);

    if (this.currentSessionId === sessionId) {
      this.currentSessionId = null;
    }

    this.emit({ type: 'session.deleted', sessionId });
  }

  /**
   * List all sessions.
   */
  listSessions(): SessionMetadata[] {
    return this.stmts.listSessions.all() as SessionMetadata[];
  }

  /**
   * Get the most recent session.
   */
  getRecentSession(): SessionMetadata | null {
    const sessions = this.listSessions();
    return sessions[0] || null;
  }

  /**
   * Get session metadata by ID.
   */
  getSessionMetadata(sessionId: string): SessionMetadata | undefined {
    return this.stmts.getSession.get(sessionId) as SessionMetadata | undefined;
  }

  /**
   * Update session metadata.
   */
  updateSessionMetadata(
    sessionId: string,
    updates: Partial<Pick<SessionMetadata, 'name' | 'summary' | 'tokenCount'>>
  ): void {
    this.stmts.updateSession.run({
      id: sessionId,
      name: updates.name || null,
      lastActiveAt: null,
      messageCount: null,
      tokenCount: updates.tokenCount || null,
      summary: updates.summary || null,
    });
  }

  // ===========================================================================
  // SQLITE-SPECIFIC FEATURES
  // ===========================================================================

  /**
   * Save a checkpoint for state restoration.
   */
  saveCheckpoint(state: Record<string, unknown>, description?: string): string {
    if (!this.currentSessionId) {
      this.createSession();
    }

    const id = `ckpt-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;

    this.stmts.insertCheckpoint.run({
      id,
      sessionId: this.currentSessionId,
      stateJson: JSON.stringify(state),
      createdAt: new Date().toISOString(),
      description: description || null,
    });

    return id;
  }

  /**
   * Load the latest checkpoint for a session.
   */
  loadLatestCheckpoint(sessionId: string): { id: string; state: Record<string, unknown>; createdAt: string; description?: string } | null {
    const row = this.stmts.getLatestCheckpoint.get(sessionId) as {
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
  query<T = unknown>(sql: string, params: unknown[] = []): T[] {
    return this.db.prepare(sql).all(...params) as T[];
  }

  /**
   * Get database statistics.
   */
  getStats(): {
    sessionCount: number;
    entryCount: number;
    toolCallCount: number;
    checkpointCount: number;
    dbSizeBytes: number;
  } {
    const sessionCount = (this.db.prepare('SELECT COUNT(*) as count FROM sessions').get() as { count: number }).count;
    const entryCount = (this.db.prepare('SELECT COUNT(*) as count FROM entries').get() as { count: number }).count;
    const toolCallCount = (this.db.prepare('SELECT COUNT(*) as count FROM tool_calls').get() as { count: number }).count;
    const checkpointCount = (this.db.prepare('SELECT COUNT(*) as count FROM checkpoints').get() as { count: number }).count;
    const dbSizeBytes = (this.db.prepare('SELECT page_count * page_size as size FROM pragma_page_count(), pragma_page_size()').get() as { size: number }).size;

    return { sessionCount, entryCount, toolCallCount, checkpointCount, dbSizeBytes };
  }

  /**
   * Get the underlying database instance.
   * Useful for integrations that need direct database access (e.g., DeadLetterQueue).
   */
  getDatabase(): Database.Database {
    return this.db;
  }

  // ===========================================================================
  // COST TRACKING
  // ===========================================================================

  /**
   * Log API usage for cost tracking.
   * Inserts a usage log entry and updates session totals atomically.
   */
  logUsage(usage: UsageLog): void {
    // Use transaction to ensure atomicity of insert + update
    this.db.transaction(() => {
      // Insert into usage_logs table
      this.stmts.insertUsageLog.run({
        sessionId: usage.sessionId,
        modelId: usage.modelId,
        promptTokens: usage.promptTokens,
        completionTokens: usage.completionTokens,
        costUsd: usage.costUsd,
        timestamp: usage.timestamp,
      });

      // Update session totals
      this.stmts.updateSessionCosts.run({
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
  getSessionUsage(sessionId: string): { promptTokens: number; completionTokens: number; costUsd: number } {
    const result = this.stmts.getSessionUsage.get(sessionId) as {
      promptTokens: number;
      completionTokens: number;
      costUsd: number;
    } | undefined;

    return result || { promptTokens: 0, completionTokens: 0, costUsd: 0 };
  }

  // ===========================================================================
  // SESSION HIERARCHY
  // ===========================================================================

  /**
   * Create a child session linked to a parent.
   */
  createChildSession(parentId: string, name?: string, type: SessionType = 'subagent'): string {
    const id = `session-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
    const now = new Date().toISOString();

    this.stmts.insertChildSession.run({
      id,
      name: name || null,
      createdAt: now,
      lastActiveAt: now,
      messageCount: 0,
      tokenCount: 0,
      parentSessionId: parentId,
      sessionType: type,
    });

    this.emit({ type: 'session.created', sessionId: id });
    return id;
  }

  /**
   * Get all direct child sessions of a parent.
   */
  getChildSessions(parentId: string): SessionMetadata[] {
    return this.stmts.getChildSessions.all(parentId) as SessionMetadata[];
  }

  /**
   * Get the full session tree starting from a root session.
   * Uses a recursive CTE to traverse the hierarchy.
   */
  getSessionTree(rootId: string): SessionMetadata[] {
    const rows = this.stmts.getSessionTree.all(rootId) as Array<SessionMetadata & { depth: number }>;
    // Remove the depth field from results (used only for ordering)
    return rows.map(({ depth, ...session }) => session);
  }

  // ===========================================================================
  // GOAL INTEGRITY
  // ===========================================================================

  /**
   * Check if goals feature is available.
   */
  hasGoalsFeature(): boolean {
    return this.features.goals;
  }

  /**
   * Create a new goal for the current session.
   * Goals persist outside of context and survive compaction.
   * Returns undefined if goals feature is not available.
   */
  createGoal(
    goalText: string,
    options: {
      priority?: number;
      parentGoalId?: string;
      progressTotal?: number;
      metadata?: Record<string, unknown>;
    } = {}
  ): string | undefined {
    if (!this.features.goals || !this.stmts.insertGoal) {
      return undefined;
    }

    if (!this.currentSessionId) {
      this.createSession();
    }

    const id = `goal-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
    const now = new Date().toISOString();

    this.stmts.insertGoal.run({
      id,
      sessionId: this.currentSessionId,
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
  updateGoal(
    goalId: string,
    updates: {
      goalText?: string;
      status?: GoalStatus;
      priority?: number;
      progressCurrent?: number;
      progressTotal?: number;
      metadata?: Record<string, unknown>;
    }
  ): void {
    if (!this.features.goals || !this.stmts.updateGoal) {
      return;
    }

    const now = new Date().toISOString();

    this.stmts.updateGoal.run({
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
  completeGoal(goalId: string): void {
    this.updateGoal(goalId, { status: 'completed' });
  }

  /**
   * Get a goal by ID.
   */
  getGoal(goalId: string): Goal | undefined {
    if (!this.features.goals || !this.stmts.getGoal) {
      return undefined;
    }
    return this.stmts.getGoal.get(goalId) as Goal | undefined;
  }

  /**
   * List all goals for a session.
   */
  listGoals(sessionId?: string): Goal[] {
    if (!this.features.goals || !this.stmts.listGoals) {
      return [];
    }
    const sid = sessionId ?? this.currentSessionId;
    if (!sid) return [];
    return this.stmts.listGoals.all(sid) as Goal[];
  }

  /**
   * List active goals for a session.
   */
  listActiveGoals(sessionId?: string): Goal[] {
    if (!this.features.goals || !this.stmts.listActiveGoals) {
      return [];
    }
    const sid = sessionId ?? this.currentSessionId;
    if (!sid) return [];
    return this.stmts.listActiveGoals.all(sid) as Goal[];
  }

  /**
   * Get a summary of the current goals for context injection.
   * This is what gets recited to maintain goal awareness.
   */
  getGoalsSummary(sessionId?: string): string {
    if (!this.features.goals) {
      return 'Goals feature not available.';
    }

    const goals = this.listActiveGoals(sessionId);
    if (goals.length === 0) {
      return 'No active goals.';
    }

    const lines: string[] = ['Active Goals:'];
    for (const goal of goals) {
      const progress = goal.progressTotal
        ? ` (${goal.progressCurrent}/${goal.progressTotal})`
        : '';
      const priority = goal.priority === 1 ? ' [HIGH]' : goal.priority === 3 ? ' [low]' : '';
      lines.push(`• ${goal.goalText}${progress}${priority}`);
    }
    return lines.join('\n');
  }

  /**
   * Log a critical juncture (decision, failure, breakthrough, pivot).
   * Returns -1 if goals feature is not available.
   */
  logJuncture(
    type: JunctureType,
    description: string,
    options: {
      goalId?: string;
      outcome?: string;
      importance?: number;
      context?: Record<string, unknown>;
    } = {}
  ): number {
    if (!this.features.goals || !this.stmts.insertJuncture) {
      return -1;
    }

    if (!this.currentSessionId) {
      this.createSession();
    }

    const result = this.stmts.insertJuncture.run({
      sessionId: this.currentSessionId,
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
  listJunctures(sessionId?: string, limit?: number): Juncture[] {
    if (!this.features.goals || !this.stmts.listJunctures) {
      return [];
    }

    const sid = sessionId ?? this.currentSessionId;
    if (!sid) return [];

    const junctures = this.stmts.listJunctures.all(sid) as Juncture[];
    return limit ? junctures.slice(0, limit) : junctures;
  }

  /**
   * Get recent critical junctures for context.
   */
  getJuncturesSummary(sessionId?: string, limit: number = 5): string {
    if (!this.features.goals) {
      return '';
    }

    const junctures = this.listJunctures(sessionId, limit);
    if (junctures.length === 0) {
      return '';
    }

    const lines: string[] = ['Recent Key Moments:'];
    for (const j of junctures) {
      const icon = j.type === 'failure' ? '✗' : j.type === 'breakthrough' ? '★' :
                   j.type === 'decision' ? '→' : '↻';
      lines.push(`${icon} [${j.type}] ${j.description}`);
      if (j.outcome) {
        lines.push(`  └─ ${j.outcome}`);
      }
    }
    return lines.join('\n');
  }

  // ===========================================================================
  // WORKER RESULTS
  // ===========================================================================

  /**
   * Check if worker results feature is available.
   */
  hasWorkerResultsFeature(): boolean {
    return this.features.workerResults;
  }

  /**
   * Create a pending worker result entry.
   * Call this when spawning a worker to reserve the result slot.
   * Returns the result ID for later reference.
   */
  createWorkerResult(
    workerId: string,
    taskDescription: string,
    modelUsed?: string
  ): string | undefined {
    if (!this.features.workerResults || !this.stmts.insertWorkerResult) {
      return undefined;
    }

    if (!this.currentSessionId) {
      this.createSession();
    }

    const id = `wr-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
    const now = new Date().toISOString();

    this.stmts.insertWorkerResult.run({
      id,
      sessionId: this.currentSessionId,
      workerId,
      taskDescription,
      modelUsed: modelUsed ?? null,
      status: 'pending',
      summary: null,
      fullOutput: null,
      artifacts: null,
      metrics: null,
      error: null,
      createdAt: now,
      completedAt: null,
    });

    return id;
  }

  /**
   * Complete a worker result with output.
   * Stores full output in database, generates summary for context injection.
   */
  completeWorkerResult(
    resultId: string,
    output: {
      fullOutput: string;
      summary?: string;
      artifacts?: Record<string, unknown>[];
      metrics?: { tokens?: number; duration?: number; toolCalls?: number };
    }
  ): WorkerResultRef | undefined {
    if (!this.features.workerResults || !this.stmts.updateWorkerResult) {
      return undefined;
    }

    const now = new Date().toISOString();

    // Auto-generate summary if not provided (first 200 chars)
    const summary = output.summary ?? this.generateResultSummary(output.fullOutput);

    this.stmts.updateWorkerResult.run({
      id: resultId,
      status: 'success',
      summary,
      fullOutput: output.fullOutput,
      artifacts: output.artifacts ? JSON.stringify(output.artifacts) : null,
      metrics: output.metrics ? JSON.stringify(output.metrics) : null,
      error: null,
      completedAt: now,
    });

    // Return reference for context injection
    const result = this.getWorkerResult(resultId);
    return result ? this.toResultRef(result) : undefined;
  }

  /**
   * Mark a worker result as failed.
   */
  failWorkerResult(resultId: string, error: string): void {
    if (!this.features.workerResults || !this.stmts.updateWorkerResult) {
      return;
    }

    this.stmts.updateWorkerResult.run({
      id: resultId,
      status: 'error',
      summary: `Failed: ${error.slice(0, 100)}`,
      fullOutput: null,
      artifacts: null,
      metrics: null,
      error,
      completedAt: new Date().toISOString(),
    });
  }

  /**
   * Get a worker result by ID (includes full output).
   */
  getWorkerResult(resultId: string): WorkerResult | undefined {
    if (!this.features.workerResults || !this.stmts.getWorkerResult) {
      return undefined;
    }
    return this.stmts.getWorkerResult.get(resultId) as WorkerResult | undefined;
  }

  /**
   * Get a lightweight reference to a worker result (for context injection).
   * Does NOT include full output - that stays in database.
   */
  getWorkerResultRef(resultId: string): WorkerResultRef | undefined {
    const result = this.getWorkerResult(resultId);
    return result ? this.toResultRef(result) : undefined;
  }

  /**
   * List all worker results for a session.
   */
  listWorkerResults(sessionId?: string): WorkerResult[] {
    if (!this.features.workerResults || !this.stmts.listWorkerResults) {
      return [];
    }
    const sid = sessionId ?? this.currentSessionId;
    if (!sid) return [];
    return this.stmts.listWorkerResults.all(sid) as WorkerResult[];
  }

  /**
   * List pending worker results (workers still running).
   */
  listPendingWorkerResults(sessionId?: string): WorkerResult[] {
    if (!this.features.workerResults || !this.stmts.listPendingWorkerResults) {
      return [];
    }
    const sid = sessionId ?? this.currentSessionId;
    if (!sid) return [];
    return this.stmts.listPendingWorkerResults.all(sid) as WorkerResult[];
  }

  /**
   * Get a summary of worker results for context injection.
   * Returns lightweight references, not full outputs.
   */
  getWorkerResultsSummary(sessionId?: string): string {
    if (!this.features.workerResults) {
      return '';
    }

    const results = this.listWorkerResults(sessionId);
    if (results.length === 0) {
      return '';
    }

    const lines: string[] = ['Worker Results:'];
    for (const r of results.slice(0, 10)) {
      const status = r.status === 'success' ? '✓' : r.status === 'error' ? '✗' : '⏳';
      const task = r.taskDescription.length > 50
        ? r.taskDescription.slice(0, 47) + '...'
        : r.taskDescription;
      lines.push(`${status} [${r.id}] ${task}`);
      if (r.summary) {
        lines.push(`  └─ ${r.summary}`);
      }
    }
    if (results.length > 10) {
      lines.push(`  ... and ${results.length - 10} more`);
    }
    return lines.join('\n');
  }

  /**
   * Convert a full WorkerResult to a lightweight reference.
   */
  private toResultRef(result: WorkerResult): WorkerResultRef {
    return {
      id: result.id,
      workerId: result.workerId,
      taskDescription: result.taskDescription,
      status: result.status,
      summary: result.summary,
      modelUsed: result.modelUsed,
      retrievalHint: `Full output available: store.getWorkerResult('${result.id}')`,
    };
  }

  /**
   * Generate a brief summary from full output.
   */
  private generateResultSummary(fullOutput: string): string {
    const firstLine = fullOutput.split('\n')[0].trim();
    if (firstLine.length <= 150) {
      return firstLine;
    }
    return firstLine.slice(0, 147) + '...';
  }

  // ===========================================================================
  // PENDING PLANS (Plan Mode Support)
  // ===========================================================================

  /**
   * Check if pending plans feature is available.
   */
  hasPendingPlansFeature(): boolean {
    return this.features.pendingPlans;
  }

  /**
   * Save a pending plan to the database.
   */
  savePendingPlan(plan: PendingPlan, sessionId?: string): void {
    if (!this.features.pendingPlans || !this.stmts.insertPendingPlan) {
      return;
    }

    const sid = sessionId ?? this.currentSessionId;
    if (!sid) return;

    const now = new Date().toISOString();

    // Check if plan already exists
    const existing = this.getPendingPlan(sid);
    if (existing && existing.id === plan.id) {
      // Update existing plan
      this.stmts.updatePendingPlan?.run({
        id: plan.id,
        proposedChanges: JSON.stringify(plan.proposedChanges),
        explorationSummary: plan.explorationSummary || null,
        status: plan.status,
        updatedAt: now,
      });
    } else {
      // Delete any existing pending plan first
      if (existing) {
        this.stmts.deletePendingPlan?.run(existing.id);
      }

      // Insert new plan
      this.stmts.insertPendingPlan.run({
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
  getPendingPlan(sessionId?: string): PendingPlan | null {
    if (!this.features.pendingPlans || !this.stmts.getPendingPlan) {
      return null;
    }

    const sid = sessionId ?? this.currentSessionId;
    if (!sid) return null;

    const row = this.stmts.getPendingPlan.get(sid) as {
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
  updatePlanStatus(planId: string, status: 'approved' | 'rejected' | 'partially_approved'): void {
    if (!this.features.pendingPlans || !this.stmts.updatePendingPlan) {
      return;
    }

    const now = new Date().toISOString();

    // We need to get the plan first to preserve other fields
    // Since we update by id, we do a direct update here
    this.db.prepare(`
      UPDATE pending_plans SET status = ?, updated_at = ? WHERE id = ?
    `).run(status, now, planId);
  }

  /**
   * Delete a pending plan.
   */
  deletePendingPlan(planId: string): void {
    if (!this.features.pendingPlans || !this.stmts.deletePendingPlan) {
      return;
    }
    this.stmts.deletePendingPlan.run(planId);
  }

  // ===========================================================================
  // SESSION MANIFEST (Handoff Support)
  // ===========================================================================

  /**
   * Export a complete session manifest for handoff.
   * Contains all information needed for another agent/human to pick up the work.
   */
  exportSessionManifest(sessionId?: string): SessionManifest | undefined {
    const sid = sessionId ?? this.currentSessionId;
    if (!sid) return undefined;

    const session = this.getSessionMetadata(sid);
    if (!session) return undefined;

    // Collect all session state
    const goals = this.listGoals(sid);
    const activeGoals = goals.filter(g => g.status === 'active');
    const completedGoals = goals.filter(g => g.status === 'completed');
    const junctures = this.listJunctures(sid, 20);
    const workerResults = this.listWorkerResults(sid);
    const entries = this.loadSession(sid);

    // Count message types from entries
    let messageCount = entries.filter(e => e.type === 'message').length;
    const toolCallCount = entries.filter(e => e.type === 'tool_call').length;
    const compactionCount = entries.filter(e => e.type === 'compaction').length;

    // If no messages in entries, check the latest checkpoint (where messages are actually stored)
    if (messageCount === 0) {
      const checkpoint = this.loadLatestCheckpoint(sid);
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
   * Suitable for printing, sharing, or reviewing offline.
   */
  exportSessionMarkdown(sessionId?: string): string {
    const manifest = this.exportSessionManifest(sessionId);
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
        const icon = moment.type === 'failure' ? '❌' :
                     moment.type === 'breakthrough' ? '⭐' :
                     moment.type === 'decision' ? '→' : '↻';
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
        const status = result.status === 'success' ? '✅' :
                      result.status === 'error' ? '❌' : '⏳';
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

  // ===========================================================================
  // MIGRATION
  // ===========================================================================

  /**
   * Migrate sessions from JSONL format to SQLite.
   */
  async migrateFromJSONL(jsonlDir: string): Promise<{ migrated: number; failed: number }> {
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
          const existing = this.getSessionMetadata(meta.id);
          if (existing) {
            continue;
          }

          // Insert session metadata
          this.stmts.insertSession.run({
            id: meta.id,
            name: meta.name || null,
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
                  this.stmts.insertEntry.run({
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
          console.error(`Failed to migrate session ${meta.id}:`, err);
          failed++;
        }
      }
    } catch (err) {
      console.error('Failed to read JSONL index:', err);
    }

    return { migrated, failed };
  }

  // ===========================================================================
  // REMEMBERED PERMISSIONS
  // ===========================================================================

  /**
   * Check if remembered permissions feature is available.
   */
  hasRememberedPermissionsFeature(): boolean {
    return this.features.rememberedPermissions;
  }

  /**
   * Remember a permission decision.
   * @param toolName - The tool name (e.g., 'bash')
   * @param decision - 'always' or 'never'
   * @param pattern - Optional command pattern (for bash commands)
   */
  rememberPermission(
    toolName: string,
    decision: 'always' | 'never',
    pattern?: string
  ): void {
    if (!this.features.rememberedPermissions || !this.stmts.insertRememberedPermission) {
      return;
    }

    this.stmts.insertRememberedPermission.run({
      toolName,
      pattern: pattern ?? null,
      decision,
      createdAt: new Date().toISOString(),
    });
  }

  /**
   * Get a remembered permission decision.
   * Returns the decision if found, or undefined if no remembered decision.
   */
  getRememberedPermission(
    toolName: string,
    pattern?: string
  ): { decision: 'always' | 'never'; pattern?: string } | undefined {
    if (!this.features.rememberedPermissions || !this.stmts.getRememberedPermission) {
      return undefined;
    }

    const row = this.stmts.getRememberedPermission.get(toolName, pattern ?? null) as {
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
  listRememberedPermissions(): Array<{
    toolName: string;
    pattern?: string;
    decision: 'always' | 'never';
    createdAt: string;
  }> {
    if (!this.features.rememberedPermissions || !this.stmts.listRememberedPermissions) {
      return [];
    }

    const rows = this.stmts.listRememberedPermissions.all() as Array<{
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
  forgetPermission(toolName: string, pattern?: string): void {
    if (!this.features.rememberedPermissions || !this.stmts.deleteRememberedPermission) {
      return;
    }

    this.stmts.deleteRememberedPermission.run(toolName, pattern ?? null, pattern ?? null);
  }

  /**
   * Clear all remembered permissions for a tool or all tools.
   */
  clearRememberedPermissions(toolName?: string): void {
    if (!this.features.rememberedPermissions) {
      return;
    }

    if (toolName) {
      this.db.prepare('DELETE FROM remembered_permissions WHERE tool_name = ?').run(toolName);
    } else {
      this.db.prepare('DELETE FROM remembered_permissions').run();
    }
  }

  // ===========================================================================
  // LIFECYCLE
  // ===========================================================================

  /**
   * Prune old sessions if over limit.
   */
  private pruneOldSessions(): void {
    const sessions = this.listSessions();
    if (sessions.length > this.config.maxSessions) {
      const toDelete = sessions.slice(this.config.maxSessions);
      for (const session of toDelete) {
        this.stmts.deleteSession.run(session.id);
      }
    }
  }

  /**
   * Subscribe to events.
   */
  on(listener: SessionEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  /**
   * Emit an event.
   */
  private emit(event: SessionEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }

  /**
   * Close the database connection.
   */
  close(): void {
    this.db.close();
  }

  /**
   * Cleanup - same as close for compatibility.
   */
  async cleanup(): Promise<void> {
    this.close();
  }
}

// =============================================================================
// FACTORY
// =============================================================================

/**
 * Create and initialize a SQLite session store.
 */
export async function createSQLiteStore(config?: SQLiteStoreConfig): Promise<SQLiteStore> {
  const store = new SQLiteStore(config);
  await store.initialize();
  return store;
}
