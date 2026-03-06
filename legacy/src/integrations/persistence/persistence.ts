/**
 * Persistence Utilities
 *
 * Debug logging and checkpoint management for session persistence.
 */

import type { SQLiteStore } from './sqlite-store.js';
import type { SessionStore } from './session-store.js';
import { logger } from '../utilities/logger.js';

// Session store type that works with both SQLite and JSONL
export type AnySessionStore = SQLiteStore | SessionStore;

// =============================================================================
// DEBUG LOGGER FOR PERSISTENCE OPERATIONS
// =============================================================================

/**
 * Debug logger for persistence operations.
 * Enabled via --debug flag. Shows data flow at each layer boundary.
 * In TUI mode, logs are buffered instead of printed to avoid interfering with Ink.
 */
export class PersistenceDebugger {
  private enabled = false;
  private tuiMode = false;
  private buffer: string[] = [];

  enable(): void {
    this.enabled = true;
    this.log('Persistence debug mode ENABLED');
  }

  enableTUIMode(): void {
    this.tuiMode = true;
  }

  isEnabled(): boolean {
    return this.enabled;
  }

  getBuffer(): string[] {
    const logs = [...this.buffer];
    this.buffer = [];
    return logs;
  }

  log(message: string, data?: unknown): void {
    if (!this.enabled) return;
    const timestamp = new Date().toISOString().split('T')[1].slice(0, 12);
    const logLine = `[${timestamp}] ${message}`;
    const dataLine =
      data !== undefined
        ? `    -> ${JSON.stringify(data, null, 2).split('\n').join('\n    ')}`
        : '';

    if (this.tuiMode) {
      // Buffer logs in TUI mode to avoid console interference
      this.buffer.push(logLine);
      if (dataLine) this.buffer.push(dataLine);
    } else {
      logger.debug(logLine);
      if (dataLine) logger.debug(dataLine);
    }
  }

  error(message: string, err: unknown): void {
    if (!this.enabled) return;
    const timestamp = new Date().toISOString().split('T')[1].slice(0, 12);
    const errLine = `[${timestamp}] ERROR: ${message}`;
    let details = '';
    if (err instanceof Error) {
      details = `    -> ${err.message}`;
      if (err.stack) {
        details += `\n    -> Stack: ${err.stack.split('\n').slice(1, 3).join(' -> ')}`;
      }
    } else {
      details = `    -> ${String(err)}`;
    }

    if (this.tuiMode) {
      this.buffer.push(errLine);
      this.buffer.push(details);
    } else {
      logger.error(errLine);
      logger.error(details);
    }
  }

  storeType(store: AnySessionStore): string {
    if ('saveCheckpoint' in store && typeof store.saveCheckpoint === 'function') {
      return 'SQLiteStore';
    }
    return 'JSONLStore';
  }
}

// Global debug instance - enabled via --debug flag
export const persistenceDebug = new PersistenceDebugger();

// =============================================================================
// CHECKPOINT DATA
// =============================================================================

/**
 * Checkpoint data structure for full state restoration.
 */
export interface CheckpointData {
  id: string;
  label?: string;
  messages: unknown[];
  iteration: number;
  metrics?: unknown;
  plan?: unknown;
  memoryContext?: string[];
}

/**
 * Save checkpoint to session store (works with both SQLite and JSONL).
 * Now includes plan and memoryContext for full state restoration.
 */
export function saveCheckpointToStore(store: AnySessionStore, checkpoint: CheckpointData): void {
  const storeType = persistenceDebug.storeType(store);
  persistenceDebug.log(`saveCheckpointToStore called`, {
    storeType,
    checkpointId: checkpoint.id,
    messageCount: checkpoint.messages?.length ?? 0,
    hasLabel: !!checkpoint.label,
    hasPlan: !!checkpoint.plan,
  });

  try {
    if ('saveCheckpoint' in store && typeof store.saveCheckpoint === 'function') {
      // SQLite store - check currentSessionId
      const sqliteStore = store as SQLiteStore;
      const currentSessionId = sqliteStore.getCurrentSessionId();
      persistenceDebug.log(`SQLite saveCheckpoint`, {
        currentSessionId,
        hasCurrentSession: !!currentSessionId,
      });

      if (!currentSessionId) {
        persistenceDebug.error(
          'SQLite store has no currentSessionId!',
          new Error('No active session'),
        );
      }

      const ckptId = store.saveCheckpoint(
        {
          id: checkpoint.id,
          label: checkpoint.label,
          messages: checkpoint.messages,
          iteration: checkpoint.iteration,
          metrics: checkpoint.metrics,
          plan: checkpoint.plan,
          memoryContext: checkpoint.memoryContext,
        },
        checkpoint.label || `auto-checkpoint-${checkpoint.id}`,
      );
      persistenceDebug.log(`SQLite checkpoint saved successfully`, { returnedId: ckptId });
    } else if ('appendEntry' in store && typeof store.appendEntry === 'function') {
      // JSONL store - use appendEntry with checkpoint type
      persistenceDebug.log(`JSONL appendEntry (checkpoint type)`);
      store.appendEntry({
        type: 'checkpoint',
        data: {
          id: checkpoint.id,
          label: checkpoint.label,
          messages: checkpoint.messages,
          iteration: checkpoint.iteration,
          metrics: checkpoint.metrics,
          plan: checkpoint.plan,
          memoryContext: checkpoint.memoryContext,
          createdAt: new Date().toISOString(),
        },
      });
      persistenceDebug.log(`JSONL checkpoint appended successfully`);
    } else {
      persistenceDebug.error('No compatible save method found on store', { storeType });
    }
  } catch (err) {
    persistenceDebug.error(`Failed to save checkpoint`, err);
    // Re-throw in debug mode so the error is visible
    if (persistenceDebug.isEnabled()) {
      throw err;
    }
  }
}

/**
 * Load session state (checkpoint or messages) for resuming.
 * Returns checkpoint data if found, or null.
 */
export async function loadSessionState(
  sessionStore: AnySessionStore,
  sessionId: string,
): Promise<CheckpointData | null> {
  persistenceDebug.log('Loading session state', { sessionId });

  // Try SQLite's loadLatestCheckpoint first
  if (
    'loadLatestCheckpoint' in sessionStore &&
    typeof sessionStore.loadLatestCheckpoint === 'function'
  ) {
    const sqliteCheckpoint = sessionStore.loadLatestCheckpoint(sessionId);
    if (sqliteCheckpoint?.state) {
      persistenceDebug.log('Loaded from SQLite checkpoint', {
        messageCount: (sqliteCheckpoint.state as any).messages?.length,
      });
      return sqliteCheckpoint.state as unknown as CheckpointData;
    }
  }

  // Fall back to entries-based lookup (for JSONL or if SQLite checkpoint not found)
  try {
    const entriesResult = sessionStore.loadSession(sessionId);
    const entries = Array.isArray(entriesResult) ? entriesResult : await entriesResult;

    // Try to find a checkpoint entry
    const checkpoint = [...entries].reverse().find((e) => e.type === 'checkpoint');
    if (checkpoint?.data) {
      persistenceDebug.log('Loaded from entries checkpoint', {
        messageCount: (checkpoint.data as any).messages?.length,
      });
      return checkpoint.data as CheckpointData;
    }

    // No checkpoint, try to load messages directly from entries
    const messages = entries
      .filter((e: { type: string }) => e.type === 'message')
      .map((e: { data: unknown }) => e.data);

    if (messages.length > 0) {
      persistenceDebug.log('Loaded messages from entries', { count: messages.length });
      return {
        id: `loaded-${sessionId}`,
        messages,
        iteration: 0,
      };
    }
  } catch (error) {
    persistenceDebug.error('Failed to load session entries', error);
  }

  return null;
}
