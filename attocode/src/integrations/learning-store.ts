/**
 * Learning Store Integration
 *
 * Provides cross-session persistence for failure patterns and learnings.
 * Extends the failure-evidence system with long-term memory.
 *
 * Features:
 * - SQLite persistence for learnings
 * - Pattern extraction from failures
 * - User validation workflow
 * - Retrieval of relevant learnings for new sessions
 *
 * @example
 * ```typescript
 * const store = createLearningStore({
 *   dbPath: '.agent/learnings.db',
 *   requireValidation: true,
 * });
 *
 * // Connect failure tracker to store
 * store.connectFailureTracker(tracker);
 *
 * // Learnings are auto-extracted and proposed
 * store.on((event) => {
 *   if (event.type === 'learning.proposed') {
 *     // Ask user to validate
 *     const approved = await askUser(event.learning.description);
 *     if (approved) {
 *       store.validateLearning(event.learning.id, true);
 *     }
 *   }
 * });
 *
 * // Retrieve relevant learnings for context
 * const learnings = store.retrieveRelevant('file operations', 5);
 * ```
 */

import { mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
import Database from 'better-sqlite3';
import {
  type FailureTracker,
  type Failure,
  type FailurePattern,
  type FailureCategory,
} from '../tricks/failure-evidence.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Status of a learning.
 */
export type LearningStatus =
  | 'proposed'   // Automatically extracted, pending validation
  | 'validated'  // User confirmed as accurate
  | 'rejected'   // User marked as inaccurate
  | 'archived';  // No longer relevant

/**
 * Type of learning.
 */
export type LearningType =
  | 'pattern'       // Extracted from failure patterns
  | 'workaround'    // Successful workaround for a failure
  | 'antipattern'   // Thing to avoid
  | 'best_practice' // Positive pattern
  | 'gotcha';       // Non-obvious issue to watch for

/**
 * A learning record.
 */
export interface Learning {
  /** Unique ID */
  id: string;

  /** When created */
  createdAt: string;

  /** When last updated */
  updatedAt: string;

  /** Learning type */
  type: LearningType;

  /** Current status */
  status: LearningStatus;

  /** Short description */
  description: string;

  /** Detailed explanation */
  details?: string;

  /** Related categories */
  categories: FailureCategory[];

  /** Related actions/tools */
  actions: string[];

  /** Keywords for retrieval */
  keywords: string[];

  /** How often this learning was applied */
  applyCount: number;

  /** How often it helped */
  helpCount: number;

  /** Confidence score (0-1) */
  confidence: number;

  /** Original failure IDs that led to this learning */
  sourceFailureIds: string[];

  /** User notes */
  userNotes?: string;
}

/**
 * Input for proposing a learning.
 */
export interface LearningProposal {
  /** Learning type */
  type: LearningType;

  /** Short description */
  description: string;

  /** Detailed explanation */
  details?: string;

  /** Related categories */
  categories?: FailureCategory[];

  /** Related actions */
  actions?: string[];

  /** Keywords for retrieval */
  keywords?: string[];

  /** Source failures */
  sourceFailures?: Failure[];

  /** Initial confidence */
  confidence?: number;
}

/**
 * Configuration for learning store.
 */
export interface LearningStoreConfig {
  /** Path to SQLite database */
  dbPath?: string;

  /** Whether to require user validation */
  requireValidation?: boolean;

  /** Minimum confidence to auto-validate */
  autoValidateThreshold?: number;

  /** Max learnings to keep */
  maxLearnings?: number;

  /** Whether to use in-memory database (for testing) */
  inMemory?: boolean;
}

/**
 * Events emitted by learning store.
 */
export type LearningStoreEvent =
  | { type: 'learning.proposed'; learning: Learning }
  | { type: 'learning.validated'; learningId: string }
  | { type: 'learning.rejected'; learningId: string; reason?: string }
  | { type: 'learning.applied'; learningId: string; context: string }
  | { type: 'learning.helped'; learningId: string }
  | { type: 'pattern.extracted'; pattern: FailurePattern; learning: Learning };

export type LearningStoreEventListener = (event: LearningStoreEvent) => void;

// =============================================================================
// DATABASE SCHEMA
// =============================================================================

const SCHEMA = `
  CREATE TABLE IF NOT EXISTS learnings (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    description TEXT NOT NULL,
    details TEXT,
    categories TEXT NOT NULL,
    actions TEXT NOT NULL,
    keywords TEXT NOT NULL,
    apply_count INTEGER DEFAULT 0,
    help_count INTEGER DEFAULT 0,
    confidence REAL DEFAULT 0.5,
    source_failure_ids TEXT NOT NULL,
    user_notes TEXT
  );

  CREATE INDEX IF NOT EXISTS idx_learnings_status ON learnings(status);
  CREATE INDEX IF NOT EXISTS idx_learnings_type ON learnings(type);
  CREATE INDEX IF NOT EXISTS idx_learnings_confidence ON learnings(confidence);

  CREATE VIRTUAL TABLE IF NOT EXISTS learnings_fts USING fts5(
    id,
    description,
    details,
    keywords,
    actions,
    content=learnings,
    content_rowid=rowid
  );

  CREATE TRIGGER IF NOT EXISTS learnings_ai AFTER INSERT ON learnings BEGIN
    INSERT INTO learnings_fts(id, description, details, keywords, actions)
    VALUES (NEW.id, NEW.description, NEW.details, NEW.keywords, NEW.actions);
  END;

  CREATE TRIGGER IF NOT EXISTS learnings_ad AFTER DELETE ON learnings BEGIN
    INSERT INTO learnings_fts(learnings_fts, id, description, details, keywords, actions)
    VALUES ('delete', OLD.id, OLD.description, OLD.details, OLD.keywords, OLD.actions);
  END;

  CREATE TRIGGER IF NOT EXISTS learnings_au AFTER UPDATE ON learnings BEGIN
    INSERT INTO learnings_fts(learnings_fts, id, description, details, keywords, actions)
    VALUES ('delete', OLD.id, OLD.description, OLD.details, OLD.keywords, OLD.actions);
    INSERT INTO learnings_fts(id, description, details, keywords, actions)
    VALUES (NEW.id, NEW.description, NEW.details, NEW.keywords, NEW.actions);
  END;
`;

// =============================================================================
// LEARNING STORE
// =============================================================================

/**
 * Manages persistent storage and retrieval of learnings.
 */
export class LearningStore {
  private config: Required<LearningStoreConfig>;
  private db: Database.Database;
  private listeners: LearningStoreEventListener[] = [];
  private failureTrackerUnsubscribe?: () => void;

  constructor(config: LearningStoreConfig = {}) {
    this.config = {
      dbPath: config.dbPath ?? '.agent/learnings.db',
      requireValidation: config.requireValidation ?? true,
      autoValidateThreshold: config.autoValidateThreshold ?? 0.9,
      maxLearnings: config.maxLearnings ?? 500,
      inMemory: config.inMemory ?? false,
    };

    // Ensure parent directory exists
    if (!this.config.inMemory) {
      mkdirSync(dirname(this.config.dbPath), { recursive: true });
    }

    // Initialize database
    this.db = new Database(this.config.inMemory ? ':memory:' : this.config.dbPath);
    this.initializeSchema();
  }

  /**
   * Initialize the database schema.
   */
  private initializeSchema(): void {
    // Execute schema statements one at a time to handle SQLite limitations
    const statements = SCHEMA.split(';').filter(s => s.trim());
    for (const stmt of statements) {
      try {
        this.db.prepare(stmt + ';').run();
      } catch {
        // Some statements may fail if already exists, which is fine
      }
    }
  }

  /**
   * Connect a failure tracker to automatically extract learnings.
   */
  connectFailureTracker(tracker: FailureTracker): () => void {
    this.failureTrackerUnsubscribe = tracker.on((event) => {
      if (event.type === 'pattern.detected') {
        this.extractLearningFromPattern(event.pattern);
      }
    });

    return () => {
      if (this.failureTrackerUnsubscribe) {
        this.failureTrackerUnsubscribe();
        this.failureTrackerUnsubscribe = undefined;
      }
    };
  }

  /**
   * Propose a new learning.
   */
  proposeLearning(proposal: LearningProposal): Learning {
    const learning: Learning = {
      id: `learn-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      type: proposal.type,
      status: this.shouldAutoValidate(proposal.confidence ?? 0.5) ? 'validated' : 'proposed',
      description: proposal.description,
      details: proposal.details,
      categories: proposal.categories || [],
      actions: proposal.actions || [],
      keywords: proposal.keywords || this.extractKeywords(proposal.description),
      applyCount: 0,
      helpCount: 0,
      confidence: proposal.confidence ?? 0.5,
      sourceFailureIds: proposal.sourceFailures?.map((f) => f.id) || [],
    };

    this.saveLearning(learning);

    if (learning.status === 'proposed') {
      this.emit({ type: 'learning.proposed', learning });
    }

    return learning;
  }

  /**
   * Validate a proposed learning.
   */
  validateLearning(learningId: string, approved: boolean, reason?: string): boolean {
    const learning = this.getLearning(learningId);
    if (!learning) return false;

    if (approved) {
      learning.status = 'validated';
      learning.updatedAt = new Date().toISOString();
      this.saveLearning(learning);
      this.emit({ type: 'learning.validated', learningId });
    } else {
      learning.status = 'rejected';
      learning.userNotes = reason;
      learning.updatedAt = new Date().toISOString();
      this.saveLearning(learning);
      this.emit({ type: 'learning.rejected', learningId, reason });
    }

    return true;
  }

  /**
   * Record that a learning was applied.
   */
  recordApply(learningId: string, context: string): boolean {
    const learning = this.getLearning(learningId);
    if (!learning) return false;

    learning.applyCount++;
    learning.updatedAt = new Date().toISOString();
    this.saveLearning(learning);

    this.emit({ type: 'learning.applied', learningId, context });
    return true;
  }

  /**
   * Record that a learning helped.
   */
  recordHelped(learningId: string): boolean {
    const learning = this.getLearning(learningId);
    if (!learning) return false;

    learning.helpCount++;
    // Increase confidence when learning helps
    learning.confidence = Math.min(1, learning.confidence + 0.05);
    learning.updatedAt = new Date().toISOString();
    this.saveLearning(learning);

    this.emit({ type: 'learning.helped', learningId });
    return true;
  }

  /**
   * Get a learning by ID.
   */
  getLearning(id: string): Learning | null {
    const row = this.db.prepare('SELECT * FROM learnings WHERE id = ?').get(id) as LearningRow | undefined;
    if (!row) return null;
    return this.rowToLearning(row);
  }

  /**
   * Get all validated learnings.
   */
  getValidatedLearnings(): Learning[] {
    const rows = this.db
      .prepare('SELECT * FROM learnings WHERE status = ? ORDER BY confidence DESC')
      .all('validated') as LearningRow[];
    return rows.map((r) => this.rowToLearning(r));
  }

  /**
   * Get proposed learnings awaiting validation.
   */
  getPendingLearnings(): Learning[] {
    const rows = this.db
      .prepare('SELECT * FROM learnings WHERE status = ? ORDER BY created_at DESC')
      .all('proposed') as LearningRow[];
    return rows.map((r) => this.rowToLearning(r));
  }

  /**
   * Retrieve learnings relevant to a query.
   */
  retrieveRelevant(query: string, limit: number = 10): Learning[] {
    // Use FTS for search
    try {
      const rows = this.db
        .prepare(
          `SELECT learnings.* FROM learnings_fts
           JOIN learnings ON learnings_fts.id = learnings.id
           WHERE learnings_fts MATCH ?
           AND learnings.status = 'validated'
           ORDER BY rank
           LIMIT ?`
        )
        .all(this.sanitizeFtsQuery(query), limit) as LearningRow[];

      return rows.map((r) => this.rowToLearning(r));
    } catch {
      // FTS query failed, fall back to LIKE search
      return this.retrieveByKeyword(query, limit);
    }
  }

  /**
   * Retrieve learnings by keyword (fallback).
   */
  private retrieveByKeyword(keyword: string, limit: number): Learning[] {
    const rows = this.db
      .prepare(
        `SELECT * FROM learnings
         WHERE status = 'validated'
         AND (description LIKE ? OR details LIKE ? OR keywords LIKE ?)
         ORDER BY confidence DESC
         LIMIT ?`
      )
      .all(`%${keyword}%`, `%${keyword}%`, `%${keyword}%`, limit) as LearningRow[];

    return rows.map((r) => this.rowToLearning(r));
  }

  /**
   * Retrieve learnings by category.
   */
  retrieveByCategory(category: FailureCategory, limit: number = 10): Learning[] {
    const rows = this.db
      .prepare(
        `SELECT * FROM learnings
         WHERE status = 'validated'
         AND categories LIKE ?
         ORDER BY confidence DESC, help_count DESC
         LIMIT ?`
      )
      .all(`%${category}%`, limit) as LearningRow[];

    return rows.map((r) => this.rowToLearning(r));
  }

  /**
   * Retrieve learnings by action.
   */
  retrieveByAction(action: string, limit: number = 10): Learning[] {
    const rows = this.db
      .prepare(
        `SELECT * FROM learnings
         WHERE status = 'validated'
         AND actions LIKE ?
         ORDER BY confidence DESC, help_count DESC
         LIMIT ?`
      )
      .all(`%${action}%`, limit) as LearningRow[];

    return rows.map((r) => this.rowToLearning(r));
  }

  /**
   * Get learning context formatted for LLM inclusion.
   */
  getLearningContext(options: {
    query?: string;
    categories?: FailureCategory[];
    actions?: string[];
    maxLearnings?: number;
  } = {}): string {
    const {
      query,
      categories = [],
      actions = [],
      maxLearnings = 5,
    } = options;

    let learnings: Learning[] = [];

    // Search by query
    if (query) {
      learnings = this.retrieveRelevant(query, maxLearnings);
    }

    // Add by categories
    for (const cat of categories) {
      const catLearnings = this.retrieveByCategory(cat, 2);
      learnings.push(...catLearnings);
    }

    // Add by actions
    for (const action of actions) {
      const actionLearnings = this.retrieveByAction(action, 2);
      learnings.push(...actionLearnings);
    }

    // Deduplicate and limit
    const seen = new Set<string>();
    learnings = learnings.filter((l) => {
      if (seen.has(l.id)) return false;
      seen.add(l.id);
      return true;
    }).slice(0, maxLearnings);

    if (learnings.length === 0) {
      return '';
    }

    return formatLearningsContext(learnings);
  }

  /**
   * Archive a learning.
   */
  archiveLearning(learningId: string): boolean {
    const learning = this.getLearning(learningId);
    if (!learning) return false;

    learning.status = 'archived';
    learning.updatedAt = new Date().toISOString();
    this.saveLearning(learning);

    return true;
  }

  /**
   * Delete a learning.
   */
  deleteLearning(learningId: string): boolean {
    const result = this.db.prepare('DELETE FROM learnings WHERE id = ?').run(learningId);
    return result.changes > 0;
  }

  /**
   * Get learning statistics.
   */
  getStats(): {
    total: number;
    byStatus: Record<LearningStatus, number>;
    byType: Record<LearningType, number>;
    topApplied: Array<{ id: string; description: string; applyCount: number }>;
    topHelpful: Array<{ id: string; description: string; helpCount: number }>;
  } {
    const total = (this.db.prepare('SELECT COUNT(*) as count FROM learnings').get() as { count: number }).count;

    const byStatus: Record<LearningStatus, number> = {
      proposed: 0,
      validated: 0,
      rejected: 0,
      archived: 0,
    };

    const statusRows = this.db.prepare('SELECT status, COUNT(*) as count FROM learnings GROUP BY status').all() as Array<{ status: LearningStatus; count: number }>;
    for (const row of statusRows) {
      byStatus[row.status] = row.count;
    }

    const byType: Record<LearningType, number> = {
      pattern: 0,
      workaround: 0,
      antipattern: 0,
      best_practice: 0,
      gotcha: 0,
    };

    const typeRows = this.db.prepare('SELECT type, COUNT(*) as count FROM learnings GROUP BY type').all() as Array<{ type: LearningType; count: number }>;
    for (const row of typeRows) {
      byType[row.type] = row.count;
    }

    const topApplied = this.db
      .prepare('SELECT id, description, apply_count FROM learnings ORDER BY apply_count DESC LIMIT 5')
      .all() as Array<{ id: string; description: string; apply_count: number }>;

    const topHelpful = this.db
      .prepare('SELECT id, description, help_count FROM learnings ORDER BY help_count DESC LIMIT 5')
      .all() as Array<{ id: string; description: string; help_count: number }>;

    return {
      total,
      byStatus,
      byType,
      topApplied: topApplied.map((r) => ({ id: r.id, description: r.description, applyCount: r.apply_count })),
      topHelpful: topHelpful.map((r) => ({ id: r.id, description: r.description, helpCount: r.help_count })),
    };
  }

  /**
   * Subscribe to events.
   */
  on(listener: LearningStoreEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  /**
   * Close the database connection.
   */
  close(): void {
    if (this.failureTrackerUnsubscribe) {
      this.failureTrackerUnsubscribe();
    }
    this.db.close();
  }

  // Internal methods

  private shouldAutoValidate(confidence: number): boolean {
    return !this.config.requireValidation || confidence >= this.config.autoValidateThreshold;
  }

  private extractLearningFromPattern(pattern: FailurePattern): Learning {
    const learning = this.proposeLearning({
      type: pattern.type === 'repeated_action' ? 'antipattern' : 'pattern',
      description: pattern.description,
      details: pattern.suggestion,
      keywords: pattern.description.split(/\s+/).filter((w) => w.length > 3),
      confidence: pattern.confidence,
    });

    this.emit({ type: 'pattern.extracted', pattern, learning });

    return learning;
  }

  private extractKeywords(text: string): string[] {
    // Simple keyword extraction - remove common words and short words
    const stopWords = new Set([
      'the', 'a', 'an', 'and', 'or', 'but', 'is', 'are', 'was', 'were',
      'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did',
      'to', 'at', 'by', 'for', 'with', 'about', 'against', 'between',
      'into', 'through', 'during', 'before', 'after', 'above', 'below',
      'from', 'up', 'down', 'in', 'out', 'on', 'off', 'over', 'under',
      'again', 'further', 'then', 'once', 'here', 'there', 'when', 'where',
      'why', 'how', 'all', 'each', 'few', 'more', 'most', 'other', 'some',
      'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than',
      'too', 'very', 'can', 'will', 'just', 'should', 'now',
    ]);

    return text
      .toLowerCase()
      .split(/\W+/)
      .filter((word) => word.length > 3 && !stopWords.has(word))
      .slice(0, 10);
  }

  private sanitizeFtsQuery(query: string): string {
    // Escape special FTS5 characters
    return query
      .replace(/['"]/g, '')
      .replace(/[^\w\s]/g, ' ')
      .trim()
      .split(/\s+/)
      .filter((w) => w.length > 0)
      .join(' OR ');
  }

  private saveLearning(learning: Learning): void {
    const stmt = this.db.prepare(`
      INSERT OR REPLACE INTO learnings (
        id, created_at, updated_at, type, status, description, details,
        categories, actions, keywords, apply_count, help_count, confidence,
        source_failure_ids, user_notes
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);

    stmt.run(
      learning.id,
      learning.createdAt,
      learning.updatedAt,
      learning.type,
      learning.status,
      learning.description,
      learning.details || null,
      JSON.stringify(learning.categories),
      JSON.stringify(learning.actions),
      JSON.stringify(learning.keywords),
      learning.applyCount,
      learning.helpCount,
      learning.confidence,
      JSON.stringify(learning.sourceFailureIds),
      learning.userNotes || null
    );

    // Enforce max learnings
    const count = (this.db.prepare('SELECT COUNT(*) as count FROM learnings').get() as { count: number }).count;
    if (count > this.config.maxLearnings) {
      // Delete oldest rejected or archived first, then lowest confidence
      this.db.prepare(`
        DELETE FROM learnings WHERE id IN (
          SELECT id FROM learnings
          WHERE status IN ('rejected', 'archived')
          ORDER BY updated_at ASC
          LIMIT ?
        )
      `).run(count - this.config.maxLearnings);

      // If still over limit, delete lowest confidence
      const remainingCount = (this.db.prepare('SELECT COUNT(*) as count FROM learnings').get() as { count: number }).count;
      if (remainingCount > this.config.maxLearnings) {
        this.db.prepare(`
          DELETE FROM learnings WHERE id IN (
            SELECT id FROM learnings
            ORDER BY confidence ASC, apply_count ASC
            LIMIT ?
          )
        `).run(remainingCount - this.config.maxLearnings);
      }
    }
  }

  private rowToLearning(row: LearningRow): Learning {
    return {
      id: row.id,
      createdAt: row.created_at,
      updatedAt: row.updated_at,
      type: row.type as LearningType,
      status: row.status as LearningStatus,
      description: row.description,
      details: row.details || undefined,
      categories: JSON.parse(row.categories) as FailureCategory[],
      actions: JSON.parse(row.actions) as string[],
      keywords: JSON.parse(row.keywords) as string[],
      applyCount: row.apply_count,
      helpCount: row.help_count,
      confidence: row.confidence,
      sourceFailureIds: JSON.parse(row.source_failure_ids) as string[],
      userNotes: row.user_notes || undefined,
    };
  }

  private emit(event: LearningStoreEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }
}

// Internal row type for database
interface LearningRow {
  id: string;
  created_at: string;
  updated_at: string;
  type: string;
  status: string;
  description: string;
  details: string | null;
  categories: string;
  actions: string;
  keywords: string;
  apply_count: number;
  help_count: number;
  confidence: number;
  source_failure_ids: string;
  user_notes: string | null;
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create a learning store.
 *
 * @example
 * ```typescript
 * const store = createLearningStore({
 *   dbPath: '.agent/learnings.db',
 *   requireValidation: true,
 * });
 *
 * // Propose a learning manually
 * store.proposeLearning({
 *   type: 'gotcha',
 *   description: 'Always check file exists before reading',
 *   actions: ['read_file'],
 *   categories: ['not_found'],
 * });
 *
 * // Retrieve relevant learnings
 * const learnings = store.retrieveRelevant('file permissions');
 * ```
 */
export function createLearningStore(
  config: LearningStoreConfig = {}
): LearningStore {
  return new LearningStore(config);
}

/**
 * Create an in-memory learning store (for testing).
 */
export function createInMemoryLearningStore(
  config: Omit<LearningStoreConfig, 'dbPath' | 'inMemory'> = {}
): LearningStore {
  return new LearningStore({
    ...config,
    inMemory: true,
  });
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Format learnings as context for LLM.
 */
export function formatLearningsContext(learnings: Learning[]): string {
  if (learnings.length === 0) return '';

  const lines = [
    '[Learnings from Previous Sessions]',
    '',
  ];

  for (const l of learnings) {
    const typeIcon = {
      pattern: '📊',
      workaround: '💡',
      antipattern: '⚠️',
      best_practice: '✅',
      gotcha: '🔍',
    }[l.type];

    lines.push(`${typeIcon} **${l.description}**`);

    if (l.details) {
      lines.push(`   ${l.details}`);
    }

    if (l.actions.length > 0) {
      lines.push(`   Actions: ${l.actions.join(', ')}`);
    }

    lines.push('');
  }

  return lines.join('\n');
}

/**
 * Format learning stats for display.
 */
export function formatLearningStats(stats: ReturnType<LearningStore['getStats']>): string {
  const lines = [
    'Learning Statistics:',
    `  Total: ${stats.total}`,
    '',
    '  By Status:',
  ];

  for (const [status, count] of Object.entries(stats.byStatus)) {
    if (count > 0) {
      lines.push(`    ${status}: ${count}`);
    }
  }

  lines.push('');
  lines.push('  By Type:');

  for (const [type, count] of Object.entries(stats.byType)) {
    if (count > 0) {
      lines.push(`    ${type}: ${count}`);
    }
  }

  if (stats.topApplied.length > 0) {
    lines.push('');
    lines.push('  Most Applied:');
    for (const l of stats.topApplied) {
      if (l.applyCount > 0) {
        lines.push(`    ${l.description.slice(0, 50)}... (${l.applyCount})`);
      }
    }
  }

  if (stats.topHelpful.length > 0) {
    lines.push('');
    lines.push('  Most Helpful:');
    for (const l of stats.topHelpful) {
      if (l.helpCount > 0) {
        lines.push(`    ${l.description.slice(0, 50)}... (${l.helpCount})`);
      }
    }
  }

  return lines.join('\n');
}
