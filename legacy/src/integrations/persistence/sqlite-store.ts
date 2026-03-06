/**
 * SQLite Session Store
 *
 * Alternative backend for session persistence using SQLite.
 * Provides better query performance and ACID guarantees.
 *
 * Implementation is split across repository modules:
 * - session-repository.ts: Session CRUD, checkpoints, costs, hierarchy, plans, permissions, manifest
 * - goal-repository.ts: Goals + junctures
 * - worker-repository.ts: Worker results + artifacts
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
import { existsSync, mkdirSync } from 'node:fs';
import type { Message, ToolCall } from '../../types.js';
import type {
  SessionEntry,
  SessionEvent,
  SessionEventListener,
  SessionStoreConfig,
} from './session-store.js';
import {
  applyMigrations,
  getMigrationStatus,
  detectFeatures,
  type SchemaFeatures,
} from '../../persistence/schema.js';
import type { PendingPlan } from '../tasks/pending-plan.js';

// Repository modules (extracted implementation)
import * as sessionRepo from './session-repository.js';
import * as goalRepo from './goal-repository.js';
import * as workerRepo from './worker-repository.js';
import * as codebaseRepo from './codebase-repository.js';

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
  workspacePath?: string;
  workspaceFingerprint?: string;
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
  priority: number; // 1=highest, 3=lowest
  parentGoalId?: string; // for sub-goals
  progressCurrent: number;
  progressTotal?: number;
  createdAt: string;
  updatedAt: string;
  completedAt?: string;
  metadata?: string; // JSON for extensibility
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
  importance: number; // 1=critical, 2=significant, 3=minor
  context?: string; // JSON
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
  summary?: string; // Brief summary for context injection
  fullOutput?: string; // Complete output stored here (not in context)
  artifacts?: string; // JSON: files modified, code generated
  metrics?: string; // JSON: tokens, duration, tool_calls
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

/**
 * Dependency interface exposed to repository modules.
 * Provides access to the DB handle, prepared statements, features,
 * and shared helpers without exposing the full SQLiteStore class.
 */
export interface SQLiteStoreDeps {
  /** The underlying better-sqlite3 database instance */
  db: Database.Database;
  /** Prepared SQL statements */
  stmts: PreparedStatements;
  /** Detected schema features */
  features: SchemaFeatures;
  /** Store configuration */
  config: Required<SQLiteStoreConfig>;
  /** Get the current session ID */
  getCurrentSessionId(): string | null;
  /** Set the current session ID (null to clear) */
  setCurrentSessionId(sessionId: string | null): void;
  /** Emit an event to listeners */
  emit(event: SessionEvent): void;
  /** Ensure a session exists (creates one if needed) */
  ensureSession(): void;
}

/**
 * Prepared SQL statements for the SQLite store.
 */
export interface PreparedStatements {
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
    codebaseAnalysis: false,
  };

  // Prepared statements for performance
  private stmts!: PreparedStatements;

  constructor(config: SQLiteStoreConfig = {}) {
    this.config = {
      baseDir: config.baseDir || '.agent/sessions',
      dbPath: config.dbPath || join(config.baseDir || '.agent/sessions', 'sessions.db'),
      autoSave: config.autoSave ?? true,
      maxSessions: config.maxSessions || 50,
      walMode: config.walMode ?? true,
    };

    // Ensure directory exists BEFORE opening database
    // (better-sqlite3 requires the parent directory to exist)
    const dbDir = dirname(this.config.dbPath);
    if (!existsSync(dbDir)) {
      mkdirSync(dbDir, { recursive: true });
    }

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
   * Get the deps object for repository modules.
   */
  private get deps(): SQLiteStoreDeps {
    return {
      db: this.db,
      stmts: this.stmts,
      features: this.features,
      config: this.config,
      getCurrentSessionId: () => this.currentSessionId,
      setCurrentSessionId: (id: string | null) => {
        this.currentSessionId = id;
      },
      emit: (event: SessionEvent) => this.emit(event),
      ensureSession: () => {
        this.createSession();
      },
    };
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
        `[DEBUG] [SQLite] DB version: ${status.currentVersion}, latest: ${status.latestVersion}, pending: ${status.pendingCount}\n`,
      );
    }

    const result = applyMigrations(this.db);

    if (isDebug && result.applied > 0) {
      process.stderr.write(
        `[DEBUG] [SQLite] Applied ${result.applied} migrations: ${result.appliedMigrations.join(', ')}\n`,
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
        INSERT INTO sessions (id, name, workspace_path, workspace_fingerprint, created_at, last_active_at, message_count, token_count)
        VALUES (@id, @name, @workspacePath, @workspaceFingerprint, @createdAt, @lastActiveAt, @messageCount, @tokenCount)
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
               workspace_path as workspacePath, workspace_fingerprint as workspaceFingerprint,
               COALESCE(last_active_at, created_at) as lastActiveAt,
               message_count as messageCount, token_count as tokenCount, summary,
               parent_session_id as parentSessionId, session_type as sessionType,
               prompt_tokens as promptTokens, completion_tokens as completionTokens,
               cost_usd as costUsd
        FROM sessions WHERE id = ?
      `),

      listSessions: this.db.prepare(`
        SELECT id, name, created_at as createdAt,
               workspace_path as workspacePath, workspace_fingerprint as workspaceFingerprint,
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
        INSERT INTO sessions (id, name, workspace_path, workspace_fingerprint, created_at, last_active_at, message_count, token_count, parent_session_id, session_type)
        VALUES (@id, @name, @workspacePath, @workspaceFingerprint, @createdAt, @lastActiveAt, @messageCount, @tokenCount, @parentSessionId, @sessionType)
      `),

      getChildSessions: this.db.prepare(`
        SELECT id, name, created_at as createdAt, last_active_at as lastActiveAt,
               workspace_path as workspacePath, workspace_fingerprint as workspaceFingerprint,
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
                 workspace_path as workspacePath, workspace_fingerprint as workspaceFingerprint,
                 message_count as messageCount, token_count as tokenCount, summary,
                 parent_session_id as parentSessionId, session_type as sessionType,
                 prompt_tokens as promptTokens, completion_tokens as completionTokens,
                 cost_usd as costUsd, 0 as depth
          FROM sessions WHERE id = ?
          UNION ALL
          SELECT s.id, s.name, s.created_at, s.last_active_at,
                 s.workspace_path, s.workspace_fingerprint,
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
  // SESSION MANAGEMENT (delegates to session-repository.ts)
  // ===========================================================================

  createSession(name?: string): string {
    return sessionRepo.createSession(this.deps, name);
  }

  getCurrentSessionId(): string | null {
    return this.currentSessionId;
  }

  setCurrentSessionId(sessionId: string): void {
    this.currentSessionId = sessionId;
  }

  appendEntry(entry: Omit<SessionEntry, 'timestamp'>): void {
    sessionRepo.appendEntry(this.deps, entry);
  }

  appendMessage(message: Message): void {
    sessionRepo.appendMessage(this.deps, message);
  }

  appendToolCall(toolCall: ToolCall): void {
    sessionRepo.appendToolCall(this.deps, toolCall);
  }

  appendToolResult(callId: string, result: unknown): void {
    sessionRepo.appendToolResult(this.deps, callId, result);
  }

  appendCompaction(summary: string, compactedCount: number): void {
    sessionRepo.appendCompaction(this.deps, summary, compactedCount);
  }

  loadSession(sessionId: string): SessionEntry[] {
    return sessionRepo.loadSession(this.deps, sessionId);
  }

  loadSessionMessages(sessionId: string): Message[] {
    return sessionRepo.loadSessionMessages(this.deps, sessionId);
  }

  deleteSession(sessionId: string): void {
    sessionRepo.deleteSession(this.deps, sessionId);
  }

  listSessions(): SessionMetadata[] {
    return sessionRepo.listSessions(this.deps);
  }

  getRecentSession(): SessionMetadata | null {
    return sessionRepo.getRecentSession(this.deps);
  }

  getSessionMetadata(sessionId: string): SessionMetadata | undefined {
    return sessionRepo.getSessionMetadata(this.deps, sessionId);
  }

  updateSessionMetadata(
    sessionId: string,
    updates: Partial<Pick<SessionMetadata, 'name' | 'summary' | 'tokenCount'>>,
  ): void {
    sessionRepo.updateSessionMetadata(this.deps, sessionId, updates);
  }

  // ===========================================================================
  // SQLITE-SPECIFIC FEATURES (delegates to session-repository.ts)
  // ===========================================================================

  saveCheckpoint(state: Record<string, unknown>, description?: string): string {
    return sessionRepo.saveCheckpoint(this.deps, state, description);
  }

  loadLatestCheckpoint(sessionId: string): {
    id: string;
    state: Record<string, unknown>;
    createdAt: string;
    description?: string;
  } | null {
    return sessionRepo.loadLatestCheckpoint(this.deps, sessionId);
  }

  query<T = unknown>(sql: string, params: unknown[] = []): T[] {
    return sessionRepo.query<T>(this.deps, sql, params);
  }

  getStats(): {
    sessionCount: number;
    entryCount: number;
    toolCallCount: number;
    checkpointCount: number;
    dbSizeBytes: number;
  } {
    return sessionRepo.getStats(this.deps);
  }

  getDatabase(): Database.Database {
    return this.db;
  }

  // ===========================================================================
  // COST TRACKING (delegates to session-repository.ts)
  // ===========================================================================

  logUsage(usage: UsageLog): void {
    sessionRepo.logUsage(this.deps, usage);
  }

  getSessionUsage(sessionId: string): {
    promptTokens: number;
    completionTokens: number;
    costUsd: number;
  } {
    return sessionRepo.getSessionUsage(this.deps, sessionId);
  }

  // ===========================================================================
  // SESSION HIERARCHY (delegates to session-repository.ts)
  // ===========================================================================

  createChildSession(parentId: string, name?: string, type: SessionType = 'subagent'): string {
    return sessionRepo.createChildSession(this.deps, parentId, name, type);
  }

  getChildSessions(parentId: string): SessionMetadata[] {
    return sessionRepo.getChildSessions(this.deps, parentId);
  }

  getSessionTree(rootId: string): SessionMetadata[] {
    return sessionRepo.getSessionTree(this.deps, rootId);
  }

  // ===========================================================================
  // GOAL INTEGRITY (delegates to goal-repository.ts)
  // ===========================================================================

  hasGoalsFeature(): boolean {
    return this.features.goals;
  }

  createGoal(
    goalText: string,
    options: {
      priority?: number;
      parentGoalId?: string;
      progressTotal?: number;
      metadata?: Record<string, unknown>;
    } = {},
  ): string | undefined {
    return goalRepo.createGoal(this.deps, goalText, options);
  }

  updateGoal(
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
    goalRepo.updateGoal(this.deps, goalId, updates);
  }

  completeGoal(goalId: string): void {
    goalRepo.completeGoal(this.deps, goalId);
  }

  getGoal(goalId: string): Goal | undefined {
    return goalRepo.getGoal(this.deps, goalId);
  }

  listGoals(sessionId?: string): Goal[] {
    return goalRepo.listGoals(this.deps, sessionId);
  }

  listActiveGoals(sessionId?: string): Goal[] {
    return goalRepo.listActiveGoals(this.deps, sessionId);
  }

  getGoalsSummary(sessionId?: string): string {
    return goalRepo.getGoalsSummary(this.deps, sessionId);
  }

  logJuncture(
    type: JunctureType,
    description: string,
    options: {
      goalId?: string;
      outcome?: string;
      importance?: number;
      context?: Record<string, unknown>;
    } = {},
  ): number {
    return goalRepo.logJuncture(this.deps, type, description, options);
  }

  listJunctures(sessionId?: string, limit?: number): Juncture[] {
    return goalRepo.listJunctures(this.deps, sessionId, limit);
  }

  getJuncturesSummary(sessionId?: string, limit: number = 5): string {
    return goalRepo.getJuncturesSummary(this.deps, sessionId, limit);
  }

  // ===========================================================================
  // WORKER RESULTS (delegates to worker-repository.ts)
  // ===========================================================================

  hasWorkerResultsFeature(): boolean {
    return this.features.workerResults;
  }

  createWorkerResult(
    workerId: string,
    taskDescription: string,
    modelUsed?: string,
  ): string | undefined {
    return workerRepo.createWorkerResult(this.deps, workerId, taskDescription, modelUsed);
  }

  completeWorkerResult(
    resultId: string,
    output: {
      fullOutput: string;
      summary?: string;
      artifacts?: Record<string, unknown>[];
      metrics?: { tokens?: number; duration?: number; toolCalls?: number };
    },
  ): WorkerResultRef | undefined {
    return workerRepo.completeWorkerResult(this.deps, resultId, output);
  }

  failWorkerResult(resultId: string, error: string): void {
    workerRepo.failWorkerResult(this.deps, resultId, error);
  }

  getWorkerResult(resultId: string): WorkerResult | undefined {
    return workerRepo.getWorkerResult(this.deps, resultId);
  }

  getWorkerResultRef(resultId: string): WorkerResultRef | undefined {
    return workerRepo.getWorkerResultRef(this.deps, resultId);
  }

  listWorkerResults(sessionId?: string): WorkerResult[] {
    return workerRepo.listWorkerResults(this.deps, sessionId);
  }

  listPendingWorkerResults(sessionId?: string): WorkerResult[] {
    return workerRepo.listPendingWorkerResults(this.deps, sessionId);
  }

  getWorkerResultsSummary(sessionId?: string): string {
    return workerRepo.getWorkerResultsSummary(this.deps, sessionId);
  }

  // ===========================================================================
  // PENDING PLANS (delegates to session-repository.ts)
  // ===========================================================================

  hasPendingPlansFeature(): boolean {
    return this.features.pendingPlans;
  }

  savePendingPlan(plan: PendingPlan, sessionId?: string): void {
    sessionRepo.savePendingPlan(this.deps, plan, sessionId);
  }

  getPendingPlan(sessionId?: string): PendingPlan | null {
    return sessionRepo.getPendingPlan(this.deps, sessionId);
  }

  updatePlanStatus(planId: string, status: 'approved' | 'rejected' | 'partially_approved'): void {
    sessionRepo.updatePlanStatus(this.deps, planId, status);
  }

  deletePendingPlan(planId: string): void {
    sessionRepo.deletePendingPlan(this.deps, planId);
  }

  // ===========================================================================
  // SESSION MANIFEST (delegates to session-repository.ts)
  // ===========================================================================

  exportSessionManifest(sessionId?: string): SessionManifest | undefined {
    return sessionRepo.exportSessionManifest(this.deps, this.manifestCallbacks, sessionId);
  }

  exportSessionMarkdown(sessionId?: string): string {
    return sessionRepo.exportSessionMarkdown(this.deps, this.manifestCallbacks, sessionId);
  }

  /** Callbacks for manifest export (bridges to goal/worker repositories). */
  private get manifestCallbacks(): sessionRepo.ManifestCallbacks {
    return {
      listGoals: (sid?: string) => this.listGoals(sid),
      listJunctures: (sid?: string, limit?: number) => this.listJunctures(sid, limit),
      listWorkerResults: (sid?: string) => this.listWorkerResults(sid),
    };
  }

  // ===========================================================================
  // MIGRATION (delegates to session-repository.ts)
  // ===========================================================================

  async migrateFromJSONL(jsonlDir: string): Promise<{ migrated: number; failed: number }> {
    return sessionRepo.migrateFromJSONL(this.deps, jsonlDir);
  }

  // ===========================================================================
  // REMEMBERED PERMISSIONS (delegates to session-repository.ts)
  // ===========================================================================

  hasRememberedPermissionsFeature(): boolean {
    return this.features.rememberedPermissions;
  }

  rememberPermission(toolName: string, decision: 'always' | 'never', pattern?: string): void {
    sessionRepo.rememberPermission(this.deps, toolName, decision, pattern);
  }

  getRememberedPermission(
    toolName: string,
    pattern?: string,
  ): { decision: 'always' | 'never'; pattern?: string } | undefined {
    return sessionRepo.getRememberedPermission(this.deps, toolName, pattern);
  }

  listRememberedPermissions(): Array<{
    toolName: string;
    pattern?: string;
    decision: 'always' | 'never';
    createdAt: string;
  }> {
    return sessionRepo.listRememberedPermissions(this.deps);
  }

  forgetPermission(toolName: string, pattern?: string): void {
    sessionRepo.forgetPermission(this.deps, toolName, pattern);
  }

  clearRememberedPermissions(toolName?: string): void {
    sessionRepo.clearRememberedPermissions(this.deps, toolName);
  }

  // ===========================================================================
  // LIFECYCLE
  // ===========================================================================

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

  // ===========================================================================
  // CODEBASE ANALYSIS PERSISTENCE
  // ===========================================================================

  /**
   * Save codebase analysis to SQLite for warm startup next session.
   */
  saveCodebaseAnalysis(
    root: string,
    chunks: Iterable<{
      filePath: string;
      content: string;
      symbolDetails: Array<{ name: string; kind: string; exported: boolean; line: number }>;
      dependencies: string[];
      importance: number;
      type: string;
      tokenCount: number;
    }>,
    dependencyGraph: Map<string, Set<string>>,
  ): void {
    codebaseRepo.saveCodebaseAnalysis(this.deps, root, chunks, dependencyGraph);
  }

  /**
   * Load persisted codebase analysis from SQLite.
   */
  loadCodebaseAnalysis(root: string): codebaseRepo.SavedCodebaseAnalysis | null {
    return codebaseRepo.loadCodebaseAnalysis(this.deps, root);
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
