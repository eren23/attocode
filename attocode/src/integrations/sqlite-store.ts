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
  SessionMetadata,
  SessionEntry,
  SessionEntryType,
  SessionEvent,
  SessionEventListener,
  SessionStoreConfig,
} from './session-store.js';

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

// =============================================================================
// SCHEMA
// =============================================================================

const SCHEMA = `
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

-- Session entries table (messages, tool calls, checkpoints, etc.)
CREATE TABLE IF NOT EXISTS entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  timestamp TEXT NOT NULL,
  type TEXT NOT NULL,
  data TEXT NOT NULL,
  FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

-- Tool calls table (for fast tool lookup)
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

-- Checkpoints table (for state restoration)
CREATE TABLE IF NOT EXISTS checkpoints (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  state_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  description TEXT,
  FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_entries_session ON entries(session_id);
CREATE INDEX IF NOT EXISTS idx_entries_session_type ON entries(session_id, type);
CREATE INDEX IF NOT EXISTS idx_tool_calls_session ON tool_calls(session_id);
CREATE INDEX IF NOT EXISTS idx_checkpoints_session ON checkpoints(session_id);
`;

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

  // Prepared statements for performance
  private stmts!: {
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

    // Create tables
    this.db.exec(SCHEMA);

    // Prepare statements
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
        SELECT id, name, created_at as createdAt, last_active_at as lastActiveAt,
               message_count as messageCount, token_count as tokenCount, summary
        FROM sessions WHERE id = ?
      `),

      listSessions: this.db.prepare(`
        SELECT id, name, created_at as createdAt, last_active_at as lastActiveAt,
               message_count as messageCount, token_count as tokenCount, summary
        FROM sessions ORDER BY last_active_at DESC
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
    };
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
