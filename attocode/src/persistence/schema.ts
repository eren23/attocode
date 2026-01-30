/**
 * SQLite Schema Definitions
 *
 * Embeds all migrations as TypeScript code - no external SQL files needed.
 * This eliminates file path resolution issues and makes migrations part
 * of the compiled bundle.
 *
 * ## Design Principles
 *
 * 1. **Migrations as Code**: Each migration is a TypeScript object with
 *    version, name, and SQL statements. No file I/O at runtime.
 *
 * 2. **Idempotent Statements**: Use IF NOT EXISTS and handle duplicate
 *    column errors gracefully.
 *
 * 3. **Feature Detection**: Tables are grouped by feature, allowing
 *    the store to detect which features are available.
 */

import type Database from 'better-sqlite3';

// =============================================================================
// TYPES
// =============================================================================

/**
 * A schema migration definition.
 */
export interface Migration {
  /** Version number (must be unique and sequential) */
  version: number;
  /** Human-readable name */
  name: string;
  /** SQL statements to execute (semicolon-separated) */
  sql: string;
}

/**
 * Result of applying migrations.
 */
export interface MigrationResult {
  applied: number;
  currentVersion: number;
  appliedMigrations: string[];
}

// =============================================================================
// EMBEDDED MIGRATIONS
// =============================================================================

/**
 * All schema migrations, embedded as TypeScript code.
 *
 * To add a new migration:
 * 1. Add a new entry with the next version number
 * 2. Ensure SQL is idempotent (IF NOT EXISTS, etc.)
 * 3. Run tests to verify migration applies cleanly
 */
export const MIGRATIONS: Migration[] = [
  {
    version: 1,
    name: 'initial',
    sql: `
      -- Sessions table
      CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        name TEXT,
        created_at TEXT NOT NULL,
        last_active_at TEXT NOT NULL,
        message_count INTEGER DEFAULT 0,
        token_count INTEGER DEFAULT 0,
        summary TEXT
      );

      -- Session entries table
      CREATE TABLE IF NOT EXISTS entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        type TEXT NOT NULL,
        data TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
      );

      -- Tool calls table
      CREATE TABLE IF NOT EXISTS tool_calls (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        name TEXT NOT NULL,
        arguments TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        result TEXT,
        error TEXT,
        duration_ms INTEGER,
        created_at TEXT NOT NULL,
        completed_at TEXT,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
      );

      -- Checkpoints table
      CREATE TABLE IF NOT EXISTS checkpoints (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        state_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        description TEXT,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
      );

      -- Core indexes
      CREATE INDEX IF NOT EXISTS idx_entries_session ON entries(session_id);
      CREATE INDEX IF NOT EXISTS idx_entries_session_type ON entries(session_id, type);
      CREATE INDEX IF NOT EXISTS idx_tool_calls_session ON tool_calls(session_id);
      CREATE INDEX IF NOT EXISTS idx_checkpoints_session ON checkpoints(session_id);
    `,
  },
  {
    version: 2,
    name: 'add_costs',
    sql: `
      -- Cost tracking columns
      ALTER TABLE sessions ADD COLUMN prompt_tokens INTEGER DEFAULT 0;
      ALTER TABLE sessions ADD COLUMN completion_tokens INTEGER DEFAULT 0;
      ALTER TABLE sessions ADD COLUMN cost_usd REAL DEFAULT 0.0;

      -- Usage logs table
      CREATE TABLE IF NOT EXISTS usage_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        model_id TEXT NOT NULL,
        prompt_tokens INTEGER NOT NULL DEFAULT 0,
        completion_tokens INTEGER NOT NULL DEFAULT 0,
        cost_usd REAL NOT NULL DEFAULT 0.0,
        timestamp TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
      );

      CREATE INDEX IF NOT EXISTS idx_usage_logs_session ON usage_logs(session_id);
      CREATE INDEX IF NOT EXISTS idx_usage_logs_timestamp ON usage_logs(timestamp);
    `,
  },
  {
    version: 3,
    name: 'add_session_hierarchy',
    sql: `
      -- Session hierarchy columns
      ALTER TABLE sessions ADD COLUMN parent_session_id TEXT;
      ALTER TABLE sessions ADD COLUMN session_type TEXT DEFAULT 'main';
      ALTER TABLE sessions ADD COLUMN summary_message_id INTEGER;

      -- Entry summary flag
      ALTER TABLE entries ADD COLUMN is_summary INTEGER DEFAULT 0;

      -- Hierarchy indexes
      CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_session_id);
      CREATE INDEX IF NOT EXISTS idx_sessions_type ON sessions(session_type);
      CREATE INDEX IF NOT EXISTS idx_entries_summary ON entries(session_id, is_summary) WHERE is_summary = 1;
    `,
  },
  {
    version: 4,
    name: 'compaction_history',
    sql: `
      CREATE TABLE IF NOT EXISTS compaction_history (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        summary TEXT NOT NULL,
        references_json TEXT NOT NULL,
        tokens_before INTEGER NOT NULL,
        tokens_after INTEGER NOT NULL,
        messages_compacted INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
      );

      CREATE INDEX IF NOT EXISTS idx_compaction_history_session ON compaction_history(session_id);
    `,
  },
  {
    version: 5,
    name: 'file_changes',
    sql: `
      CREATE TABLE IF NOT EXISTS file_changes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        entry_id INTEGER,
        tool_call_id TEXT,
        turn_number INTEGER NOT NULL,
        file_path TEXT NOT NULL,
        operation TEXT NOT NULL,
        content_before TEXT,
        content_after TEXT,
        diff_unified TEXT,
        storage_mode TEXT DEFAULT 'full',
        bytes_before INTEGER,
        bytes_after INTEGER,
        is_undone INTEGER DEFAULT 0,
        undo_change_id INTEGER,
        created_at TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
      );

      CREATE INDEX IF NOT EXISTS idx_file_changes_session_path ON file_changes(session_id, file_path);
      CREATE INDEX IF NOT EXISTS idx_file_changes_session_turn ON file_changes(session_id, turn_number);
    `,
  },
  {
    version: 6,
    name: 'goal_integrity',
    sql: `
      -- Goals table - persists objectives outside of context
      CREATE TABLE IF NOT EXISTS goals (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        goal_text TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        priority INTEGER DEFAULT 1,
        parent_goal_id TEXT,
        progress_current INTEGER DEFAULT 0,
        progress_total INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        completed_at TEXT,
        metadata TEXT,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
        FOREIGN KEY (parent_goal_id) REFERENCES goals(id) ON DELETE SET NULL
      );

      -- Critical junctures table
      CREATE TABLE IF NOT EXISTS junctures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        goal_id TEXT,
        type TEXT NOT NULL,
        description TEXT NOT NULL,
        outcome TEXT,
        importance INTEGER DEFAULT 2,
        context TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
        FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE SET NULL
      );

      -- Goal indexes
      CREATE INDEX IF NOT EXISTS idx_goals_session ON goals(session_id);
      CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(session_id, status);
      CREATE INDEX IF NOT EXISTS idx_goals_parent ON goals(parent_goal_id);
      CREATE INDEX IF NOT EXISTS idx_junctures_session ON junctures(session_id);
      CREATE INDEX IF NOT EXISTS idx_junctures_goal ON junctures(goal_id);
      CREATE INDEX IF NOT EXISTS idx_junctures_type ON junctures(session_id, type);
    `,
  },
  {
    version: 7,
    name: 'worker_results',
    sql: `
      CREATE TABLE IF NOT EXISTS worker_results (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        worker_id TEXT NOT NULL,
        task_description TEXT NOT NULL,
        model_used TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        summary TEXT,
        full_output TEXT,
        artifacts TEXT,
        metrics TEXT,
        error TEXT,
        created_at TEXT NOT NULL,
        completed_at TEXT,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
      );

      CREATE INDEX IF NOT EXISTS idx_worker_results_session ON worker_results(session_id);
      CREATE INDEX IF NOT EXISTS idx_worker_results_worker ON worker_results(worker_id);
      CREATE INDEX IF NOT EXISTS idx_worker_results_status ON worker_results(session_id, status);
    `,
  },
  {
    version: 8,
    name: 'pending_plans',
    sql: `
      -- Pending plans table - stores plans awaiting user approval (plan mode)
      CREATE TABLE IF NOT EXISTS pending_plans (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        task TEXT NOT NULL,
        proposed_changes TEXT NOT NULL,
        exploration_summary TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
      );

      CREATE INDEX IF NOT EXISTS idx_pending_plans_session ON pending_plans(session_id);
      CREATE INDEX IF NOT EXISTS idx_pending_plans_status ON pending_plans(session_id, status);
    `,
  },
  {
    version: 9,
    name: 'dead_letter_queue',
    sql: `
      -- Dead letter queue for failed operations
      CREATE TABLE IF NOT EXISTS dead_letters (
        id TEXT PRIMARY KEY,
        session_id TEXT,
        operation TEXT NOT NULL,
        args TEXT NOT NULL,
        error TEXT NOT NULL,
        category TEXT NOT NULL,
        attempts INTEGER DEFAULT 1,
        max_attempts INTEGER DEFAULT 3,
        last_attempt TEXT NOT NULL,
        next_retry TEXT,
        metadata TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        resolved_at TEXT,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL
      );

      CREATE INDEX IF NOT EXISTS idx_dead_letters_status ON dead_letters(status);
      CREATE INDEX IF NOT EXISTS idx_dead_letters_session ON dead_letters(session_id);
      CREATE INDEX IF NOT EXISTS idx_dead_letters_operation ON dead_letters(operation);
      CREATE INDEX IF NOT EXISTS idx_dead_letters_next_retry ON dead_letters(next_retry) WHERE status = 'pending';
    `,
  },
  {
    version: 10,
    name: 'remembered_permissions',
    sql: `
      -- Remembered permission decisions for persistent approval across sessions
      -- This allows "always" decisions to persist and reduces repeated prompts
      CREATE TABLE IF NOT EXISTS remembered_permissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tool_name TEXT NOT NULL,
        pattern TEXT,
        decision TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(tool_name, pattern)
      );

      CREATE INDEX IF NOT EXISTS idx_remembered_permissions_tool ON remembered_permissions(tool_name);
    `,
  },
];

// =============================================================================
// FEATURE DETECTION
// =============================================================================

/**
 * Feature flags based on which tables exist.
 */
export interface SchemaFeatures {
  /** Core tables: sessions, entries, tool_calls, checkpoints */
  core: boolean;
  /** Cost tracking: usage_logs + session columns */
  costs: boolean;
  /** Session hierarchy: parent/child relationships */
  hierarchy: boolean;
  /** Compaction history tracking */
  compaction: boolean;
  /** File change tracking for undo */
  fileChanges: boolean;
  /** Goal integrity: goals + junctures */
  goals: boolean;
  /** Worker result storage: worker_results */
  workerResults: boolean;
  /** Pending plans for plan mode: pending_plans */
  pendingPlans: boolean;
  /** Dead letter queue for failed operations */
  deadLetterQueue: boolean;
  /** Remembered permission decisions for persistent approval */
  rememberedPermissions: boolean;
}

/**
 * Check which tables exist in the database.
 */
export function detectFeatures(db: Database.Database): SchemaFeatures {
  const tableExists = (name: string): boolean => {
    const result = db
      .prepare("SELECT name FROM sqlite_master WHERE type='table' AND name=?")
      .get(name);
    return result !== undefined;
  };

  return {
    core: tableExists('sessions') && tableExists('entries'),
    costs: tableExists('usage_logs'),
    hierarchy: tableExists('sessions'), // Check column existence instead
    compaction: tableExists('compaction_history'),
    fileChanges: tableExists('file_changes'),
    goals: tableExists('goals') && tableExists('junctures'),
    workerResults: tableExists('worker_results'),
    pendingPlans: tableExists('pending_plans'),
    deadLetterQueue: tableExists('dead_letters'),
    rememberedPermissions: tableExists('remembered_permissions'),
  };
}

// =============================================================================
// MIGRATION ENGINE
// =============================================================================

/**
 * Get current schema version from database.
 */
export function getSchemaVersion(db: Database.Database): number {
  const result = db.pragma('user_version', { simple: true });
  return typeof result === 'number' ? result : 0;
}

/**
 * Set schema version in database.
 */
export function setSchemaVersion(db: Database.Database, version: number): void {
  db.pragma(`user_version = ${version}`);
}

/**
 * Strip leading comment lines from SQL statement.
 */
function stripLeadingComments(sql: string): string {
  const lines = sql.split('\n');
  let startIndex = 0;

  while (startIndex < lines.length) {
    const line = lines[startIndex].trim();
    if (line === '' || line.startsWith('--')) {
      startIndex++;
    } else {
      break;
    }
  }

  return lines.slice(startIndex).join('\n').trim();
}

/**
 * Execute migration SQL with idempotent error handling.
 */
function executeMigrationSql(db: Database.Database, sql: string): void {
  // Split by semicolons and filter empty statements
  const statements = sql
    .split(';')
    .map((s) => s.trim())
    .map((s) => stripLeadingComments(s)) // Strip leading comments before checking
    .filter((s) => s.length > 0);

  for (const statement of statements) {
    try {
      db.exec(statement);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      // Idempotent: skip duplicate column errors
      if (msg.includes('duplicate column name')) {
        continue;
      }
      throw err;
    }
  }
}

/**
 * Apply all pending migrations to the database.
 */
export function applyMigrations(db: Database.Database): MigrationResult {
  const currentVersion = getSchemaVersion(db);
  const pending = MIGRATIONS.filter((m) => m.version > currentVersion);
  const applied: string[] = [];

  for (const migration of pending) {
    try {
      executeMigrationSql(db, migration.sql);
      setSchemaVersion(db, migration.version);
      applied.push(migration.name);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      throw new Error(`Migration ${migration.version}_${migration.name} failed: ${msg}`);
    }
  }

  return {
    applied: applied.length,
    currentVersion: getSchemaVersion(db),
    appliedMigrations: applied,
  };
}

/**
 * Get migration status.
 */
export function getMigrationStatus(db: Database.Database): {
  currentVersion: number;
  latestVersion: number;
  pendingCount: number;
  pendingMigrations: Array<{ version: number; name: string }>;
} {
  const currentVersion = getSchemaVersion(db);
  const pending = MIGRATIONS.filter((m) => m.version > currentVersion);

  return {
    currentVersion,
    latestVersion: MIGRATIONS.length > 0 ? MIGRATIONS[MIGRATIONS.length - 1].version : 0,
    pendingCount: pending.length,
    pendingMigrations: pending.map((m) => ({ version: m.version, name: m.name })),
  };
}

/**
 * Check if database needs migration.
 */
export function needsMigration(db: Database.Database): boolean {
  const currentVersion = getSchemaVersion(db);
  const latestVersion = MIGRATIONS.length > 0 ? MIGRATIONS[MIGRATIONS.length - 1].version : 0;
  return currentVersion < latestVersion;
}
