/**
 * Dead Letter Queue
 *
 * Persists failed operations for later retry or manual intervention.
 * Integrates with SQLite store for durability across sessions.
 *
 * @example
 * ```typescript
 * const dlq = createDeadLetterQueue(db);
 *
 * // On failure, add to DLQ
 * await dlq.add({
 *   operation: 'tool:bash',
 *   args: { command: 'npm install' },
 *   error: new Error('ETIMEDOUT'),
 *   sessionId: 'session-123',
 * });
 *
 * // At session start, drain pending items
 * const pending = await dlq.getPending();
 * for (const item of pending) {
 *   const success = await retry(item);
 *   if (success) await dlq.resolve(item.id);
 * }
 * ```
 */

import type Database from 'better-sqlite3';
import { randomUUID } from 'node:crypto';
import { ErrorCategory, categorizeError, type AgentError } from '../../errors/index.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Status of a dead letter item.
 */
export type DeadLetterStatus = 'pending' | 'retrying' | 'resolved' | 'abandoned';

/**
 * A failed operation stored in the dead letter queue.
 */
export interface DeadLetterItem {
  /** Unique ID */
  id: string;

  /** Session ID (if associated with a session) */
  sessionId?: string;

  /** Operation type (e.g., 'tool:bash', 'mcp:playwright:click') */
  operation: string;

  /** Operation arguments (serialized JSON) */
  args: string;

  /** Error message */
  error: string;

  /** Error category for recovery decisions */
  category: ErrorCategory;

  /** Number of retry attempts made */
  attempts: number;

  /** Maximum retry attempts before abandoning */
  maxAttempts: number;

  /** Timestamp of last retry attempt */
  lastAttempt: Date;

  /** Timestamp for next retry (if scheduled) */
  nextRetry?: Date;

  /** Additional metadata */
  metadata?: Record<string, unknown>;

  /** Current status */
  status: DeadLetterStatus;

  /** When the item was created */
  createdAt: Date;

  /** When the item was resolved (if resolved) */
  resolvedAt?: Date;
}

/**
 * Input for adding a dead letter.
 */
export interface AddDeadLetterInput {
  /** Operation type */
  operation: string;

  /** Operation arguments */
  args: unknown;

  /** Error that caused the failure */
  error: Error | AgentError;

  /** Associated session ID */
  sessionId?: string;

  /** Maximum retry attempts (default: 3) */
  maxAttempts?: number;

  /** Additional metadata */
  metadata?: Record<string, unknown>;
}

/**
 * Options for querying the dead letter queue.
 */
export interface DeadLetterQueryOptions {
  /** Filter by status */
  status?: DeadLetterStatus;

  /** Filter by operation type */
  operation?: string;

  /** Filter by session ID */
  sessionId?: string;

  /** Only items ready for retry (nextRetry <= now) */
  readyForRetry?: boolean;

  /** Limit number of results */
  limit?: number;

  /** Order by field */
  orderBy?: 'createdAt' | 'lastAttempt' | 'nextRetry';
}

/**
 * Dead letter queue statistics.
 */
export interface DeadLetterStats {
  total: number;
  pending: number;
  retrying: number;
  resolved: number;
  abandoned: number;
  byOperation: Record<string, number>;
  byCategory: Record<string, number>;
}

/**
 * Dead letter queue event types.
 */
export type DeadLetterEvent =
  | { type: 'item.added'; item: DeadLetterItem }
  | { type: 'item.retrying'; item: DeadLetterItem }
  | { type: 'item.resolved'; item: DeadLetterItem }
  | { type: 'item.abandoned'; item: DeadLetterItem }
  | { type: 'item.deleted'; id: string };

export type DeadLetterEventListener = (event: DeadLetterEvent) => void;

// =============================================================================
// DEAD LETTER QUEUE IMPLEMENTATION
// =============================================================================

/**
 * Dead letter queue backed by SQLite.
 */
export class DeadLetterQueue {
  private listeners = new Set<DeadLetterEventListener>();
  private stmts?: {
    insert: Database.Statement;
    update: Database.Statement;
    get: Database.Statement;
    delete: Database.Statement;
    list: Database.Statement;
    stats: Database.Statement;
  };

  constructor(private db: Database.Database) {
    this.prepareStatements();
  }

  private prepareStatements(): void {
    // Check if table exists
    const tableExists = this.db
      .prepare("SELECT name FROM sqlite_master WHERE type='table' AND name='dead_letters'")
      .get();

    if (!tableExists) {
      return; // Table not yet created - will be available after migration
    }

    this.stmts = {
      insert: this.db.prepare(`
        INSERT INTO dead_letters (
          id, session_id, operation, args, error, category,
          attempts, max_attempts, last_attempt, next_retry,
          metadata, status, created_at
        ) VALUES (
          @id, @sessionId, @operation, @args, @error, @category,
          @attempts, @maxAttempts, @lastAttempt, @nextRetry,
          @metadata, @status, @createdAt
        )
      `),
      update: this.db.prepare(`
        UPDATE dead_letters SET
          attempts = @attempts,
          last_attempt = @lastAttempt,
          next_retry = @nextRetry,
          status = @status,
          resolved_at = @resolvedAt
        WHERE id = @id
      `),
      get: this.db.prepare('SELECT * FROM dead_letters WHERE id = ?'),
      delete: this.db.prepare('DELETE FROM dead_letters WHERE id = ?'),
      list: this.db.prepare('SELECT * FROM dead_letters ORDER BY created_at DESC'),
      stats: this.db.prepare(`
        SELECT
          status,
          operation,
          category,
          COUNT(*) as count
        FROM dead_letters
        GROUP BY status, operation, category
      `),
    };
  }

  /**
   * Check if DLQ is available (table exists).
   */
  isAvailable(): boolean {
    return this.stmts !== undefined;
  }

  /**
   * Add a failed operation to the dead letter queue.
   */
  async add(input: AddDeadLetterInput): Promise<DeadLetterItem> {
    if (!this.stmts) {
      throw new Error('Dead letter queue not available - migration required');
    }

    const { category } =
      input.error instanceof Error
        ? categorizeError(input.error)
        : { category: ErrorCategory.INTERNAL };

    const item: DeadLetterItem = {
      id: randomUUID(),
      sessionId: input.sessionId,
      operation: input.operation,
      args: JSON.stringify(input.args),
      error: input.error.message,
      category,
      attempts: 1,
      maxAttempts: input.maxAttempts ?? 3,
      lastAttempt: new Date(),
      nextRetry: this.calculateNextRetry(1, category),
      metadata: input.metadata,
      status: 'pending',
      createdAt: new Date(),
    };

    this.stmts.insert.run({
      id: item.id,
      sessionId: item.sessionId ?? null,
      operation: item.operation,
      args: item.args,
      error: item.error,
      category: item.category,
      attempts: item.attempts,
      maxAttempts: item.maxAttempts,
      lastAttempt: item.lastAttempt.toISOString(),
      nextRetry: item.nextRetry?.toISOString() ?? null,
      metadata: item.metadata ? JSON.stringify(item.metadata) : null,
      status: item.status,
      createdAt: item.createdAt.toISOString(),
    });

    this.emit({ type: 'item.added', item });
    return item;
  }

  /**
   * Get a dead letter item by ID.
   */
  get(id: string): DeadLetterItem | null {
    if (!this.stmts) return null;

    const row = this.stmts.get.get(id) as Record<string, unknown> | undefined;
    return row ? this.rowToItem(row) : null;
  }

  /**
   * Get pending items ready for retry.
   */
  getPending(options: DeadLetterQueryOptions = {}): DeadLetterItem[] {
    if (!this.stmts) return [];

    const conditions: string[] = ["status = 'pending'"];
    const params: Record<string, unknown> = {};

    if (options.operation) {
      conditions.push('operation = @operation');
      params.operation = options.operation;
    }

    if (options.sessionId) {
      conditions.push('session_id = @sessionId');
      params.sessionId = options.sessionId;
    }

    if (options.readyForRetry === true) {
      conditions.push('(next_retry IS NULL OR next_retry <= @now)');
      params.now = new Date().toISOString();
    }

    const orderBy = options.orderBy ?? 'createdAt';
    const orderCol =
      orderBy === 'createdAt'
        ? 'created_at'
        : orderBy === 'lastAttempt'
          ? 'last_attempt'
          : 'next_retry';

    const limit = options.limit ?? 100;

    const sql = `
      SELECT * FROM dead_letters
      WHERE ${conditions.join(' AND ')}
      ORDER BY ${orderCol} ASC
      LIMIT ${limit}
    `;

    const rows = this.db.prepare(sql).all(params) as Record<string, unknown>[];
    return rows.map((row) => this.rowToItem(row));
  }

  /**
   * Query dead letters with filters.
   */
  query(options: DeadLetterQueryOptions = {}): DeadLetterItem[] {
    if (!this.stmts) return [];

    const conditions: string[] = [];
    const params: Record<string, unknown> = {};

    if (options.status) {
      conditions.push('status = @status');
      params.status = options.status;
    }

    if (options.operation) {
      conditions.push('operation = @operation');
      params.operation = options.operation;
    }

    if (options.sessionId) {
      conditions.push('session_id = @sessionId');
      params.sessionId = options.sessionId;
    }

    if (options.readyForRetry) {
      conditions.push("status = 'pending' AND (next_retry IS NULL OR next_retry <= @now)");
      params.now = new Date().toISOString();
    }

    const orderBy = options.orderBy ?? 'createdAt';
    const orderCol =
      orderBy === 'createdAt'
        ? 'created_at'
        : orderBy === 'lastAttempt'
          ? 'last_attempt'
          : 'next_retry';

    const limit = options.limit ?? 100;

    const whereClause = conditions.length > 0 ? `WHERE ${conditions.join(' AND ')}` : '';
    const sql = `
      SELECT * FROM dead_letters
      ${whereClause}
      ORDER BY ${orderCol} DESC
      LIMIT ${limit}
    `;

    const rows = this.db.prepare(sql).all(params) as Record<string, unknown>[];
    return rows.map((row) => this.rowToItem(row));
  }

  /**
   * Mark an item as being retried.
   */
  markRetrying(id: string): void {
    if (!this.stmts) return;

    const item = this.get(id);
    if (!item) return;

    const now = new Date();
    this.stmts.update.run({
      id,
      attempts: item.attempts + 1,
      lastAttempt: now.toISOString(),
      nextRetry: this.calculateNextRetry(item.attempts + 1, item.category)?.toISOString() ?? null,
      status: 'retrying',
      resolvedAt: null,
    });

    this.emit({ type: 'item.retrying', item: { ...item, status: 'retrying' } });
  }

  /**
   * Mark an item as resolved (successful retry).
   */
  resolve(id: string): void {
    if (!this.stmts) return;

    const item = this.get(id);
    if (!item) return;

    const now = new Date();
    this.stmts.update.run({
      id,
      attempts: item.attempts,
      lastAttempt: item.lastAttempt.toISOString(),
      nextRetry: null,
      status: 'resolved',
      resolvedAt: now.toISOString(),
    });

    this.emit({ type: 'item.resolved', item: { ...item, status: 'resolved', resolvedAt: now } });
  }

  /**
   * Mark an item as abandoned (max retries exceeded or non-recoverable).
   */
  abandon(id: string): void {
    if (!this.stmts) return;

    const item = this.get(id);
    if (!item) return;

    this.stmts.update.run({
      id,
      attempts: item.attempts,
      lastAttempt: item.lastAttempt.toISOString(),
      nextRetry: null,
      status: 'abandoned',
      resolvedAt: new Date().toISOString(),
    });

    this.emit({ type: 'item.abandoned', item: { ...item, status: 'abandoned' } });
  }

  /**
   * Return an item to pending status after a failed retry.
   */
  returnToPending(id: string): void {
    if (!this.stmts) return;

    const item = this.get(id);
    if (!item) return;

    // Check if max attempts reached
    if (item.attempts >= item.maxAttempts) {
      this.abandon(id);
      return;
    }

    const now = new Date();
    this.stmts.update.run({
      id,
      attempts: item.attempts,
      lastAttempt: now.toISOString(),
      nextRetry: this.calculateNextRetry(item.attempts, item.category)?.toISOString() ?? null,
      status: 'pending',
      resolvedAt: null,
    });
  }

  /**
   * Delete an item from the queue.
   */
  delete(id: string): void {
    if (!this.stmts) return;

    this.stmts.delete.run(id);
    this.emit({ type: 'item.deleted', id });
  }

  /**
   * Get queue statistics.
   */
  getStats(): DeadLetterStats {
    if (!this.stmts) {
      return {
        total: 0,
        pending: 0,
        retrying: 0,
        resolved: 0,
        abandoned: 0,
        byOperation: {},
        byCategory: {},
      };
    }

    const rows = this.stmts.stats.all() as Array<{
      status: string;
      operation: string;
      category: string;
      count: number;
    }>;

    const stats: DeadLetterStats = {
      total: 0,
      pending: 0,
      retrying: 0,
      resolved: 0,
      abandoned: 0,
      byOperation: {},
      byCategory: {},
    };

    for (const row of rows) {
      const count = row.count;
      stats.total += count;

      // Count by status
      if (row.status === 'pending') stats.pending += count;
      else if (row.status === 'retrying') stats.retrying += count;
      else if (row.status === 'resolved') stats.resolved += count;
      else if (row.status === 'abandoned') stats.abandoned += count;

      // Count by operation
      stats.byOperation[row.operation] = (stats.byOperation[row.operation] || 0) + count;

      // Count by category
      stats.byCategory[row.category] = (stats.byCategory[row.category] || 0) + count;
    }

    return stats;
  }

  /**
   * Cleanup old resolved/abandoned items.
   */
  cleanup(olderThanDays: number = 7): number {
    if (!this.stmts) return 0;

    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - olderThanDays);

    const result = this.db
      .prepare(
        `
      DELETE FROM dead_letters
      WHERE status IN ('resolved', 'abandoned')
        AND resolved_at < ?
    `,
      )
      .run(cutoff.toISOString());

    return result.changes;
  }

  /**
   * Add an event listener.
   */
  on(listener: DeadLetterEventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit(event: DeadLetterEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }

  /**
   * Calculate next retry time based on attempts and error category.
   */
  private calculateNextRetry(attempts: number, category: ErrorCategory): Date | undefined {
    // Don't retry permanent errors
    if (category === ErrorCategory.PERMANENT || category === ErrorCategory.VALIDATION) {
      return undefined;
    }

    // Exponential backoff: 1min, 5min, 15min, 30min, 1hr
    const delays = [60, 300, 900, 1800, 3600]; // seconds
    const delaySeconds = delays[Math.min(attempts - 1, delays.length - 1)];

    const nextRetry = new Date();
    nextRetry.setSeconds(nextRetry.getSeconds() + delaySeconds);
    return nextRetry;
  }

  private rowToItem(row: Record<string, unknown>): DeadLetterItem {
    return {
      id: row.id as string,
      sessionId: row.session_id as string | undefined,
      operation: row.operation as string,
      args: row.args as string,
      error: row.error as string,
      category: row.category as ErrorCategory,
      attempts: row.attempts as number,
      maxAttempts: row.max_attempts as number,
      lastAttempt: new Date(row.last_attempt as string),
      nextRetry: row.next_retry ? new Date(row.next_retry as string) : undefined,
      metadata: row.metadata ? JSON.parse(row.metadata as string) : undefined,
      status: row.status as DeadLetterStatus,
      createdAt: new Date(row.created_at as string),
      resolvedAt: row.resolved_at ? new Date(row.resolved_at as string) : undefined,
    };
  }

  // ===========================================================================
  // RETRY LOOP
  // ===========================================================================

  private retryTimer: ReturnType<typeof setInterval> | null = null;
  private retryExecutor: ((item: DeadLetterItem) => Promise<boolean>) | null = null;

  /**
   * Register a retry executor function that will be called for each pending item.
   * The executor should attempt to re-execute the operation and return true on success.
   */
  setRetryExecutor(executor: (item: DeadLetterItem) => Promise<boolean>): void {
    this.retryExecutor = executor;
  }

  /**
   * Process all pending items that are ready for retry.
   * Returns the number of items processed (resolved + abandoned).
   */
  async processRetries(): Promise<{ resolved: number; failed: number; abandoned: number }> {
    if (!this.retryExecutor) {
      return { resolved: 0, failed: 0, abandoned: 0 };
    }

    const pending = this.getPending({ readyForRetry: true });
    let resolved = 0;
    let failed = 0;
    let abandoned = 0;

    for (const item of pending) {
      this.markRetrying(item.id);
      try {
        const success = await this.retryExecutor(item);
        if (success) {
          this.resolve(item.id);
          resolved++;
        } else {
          this.returnToPending(item.id);
          // Check if returnToPending auto-abandoned it
          const updated = this.get(item.id);
          if (updated?.status === 'abandoned') {
            abandoned++;
          } else {
            failed++;
          }
        }
      } catch {
        this.returnToPending(item.id);
        const updated = this.get(item.id);
        if (updated?.status === 'abandoned') {
          abandoned++;
        } else {
          failed++;
        }
      }
    }

    return { resolved, failed, abandoned };
  }

  /**
   * Start a periodic retry loop.
   * @param intervalMs - How often to check for retries (default: 60000ms = 1 minute)
   */
  startRetryLoop(intervalMs: number = 60000): void {
    this.stopRetryLoop();
    this.retryTimer = setInterval(async () => {
      try {
        await this.processRetries();
      } catch {
        // Silently swallow errors in the retry loop
      }
    }, intervalMs);

    // Don't block process exit
    if (this.retryTimer && typeof this.retryTimer === 'object' && 'unref' in this.retryTimer) {
      this.retryTimer.unref();
    }
  }

  /**
   * Stop the periodic retry loop.
   */
  stopRetryLoop(): void {
    if (this.retryTimer) {
      clearInterval(this.retryTimer);
      this.retryTimer = null;
    }
  }
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create a dead letter queue instance.
 */
export function createDeadLetterQueue(db: Database.Database): DeadLetterQueue {
  return new DeadLetterQueue(db);
}

// =============================================================================
// FORMATTING
// =============================================================================

/**
 * Format dead letter stats for display.
 */
export function formatDeadLetterStats(stats: DeadLetterStats): string {
  const lines: string[] = [];

  lines.push(`Dead Letter Queue Statistics`);
  lines.push(`  Total: ${stats.total}`);
  lines.push(`  Pending: ${stats.pending}`);
  lines.push(`  Retrying: ${stats.retrying}`);
  lines.push(`  Resolved: ${stats.resolved}`);
  lines.push(`  Abandoned: ${stats.abandoned}`);

  if (Object.keys(stats.byOperation).length > 0) {
    lines.push('');
    lines.push('  By Operation:');
    for (const [op, count] of Object.entries(stats.byOperation)) {
      lines.push(`    ${op}: ${count}`);
    }
  }

  if (Object.keys(stats.byCategory).length > 0) {
    lines.push('');
    lines.push('  By Category:');
    for (const [cat, count] of Object.entries(stats.byCategory)) {
      lines.push(`    ${cat}: ${count}`);
    }
  }

  return lines.join('\n');
}
