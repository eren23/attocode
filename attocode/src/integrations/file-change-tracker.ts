/**
 * File Change Tracker
 *
 * Tracks file changes for undo capability in agent sessions.
 * Provides before/after content capture, diff generation, and undo functionality.
 *
 * @example
 * ```typescript
 * import Database from 'better-sqlite3';
 * import { FileChangeTracker } from './file-change-tracker.js';
 *
 * const db = new Database('sessions.db');
 * const tracker = new FileChangeTracker(db, 'session-123');
 *
 * // Record a file change
 * const changeId = await tracker.recordChange({
 *   filePath: '/path/to/file.ts',
 *   operation: 'edit',
 *   contentBefore: 'old content',
 *   contentAfter: 'new content',
 *   turnNumber: 1,
 * });
 *
 * // Undo the change
 * const result = await tracker.undoChange(changeId);
 * ```
 */

import Database from 'better-sqlite3';
import { writeFile, readFile, unlink } from 'node:fs/promises';
import { existsSync } from 'node:fs';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Configuration for FileChangeTracker.
 */
export interface FileChangeTrackerConfig {
  /** Whether tracking is enabled (default: true) */
  enabled?: boolean;
  /** Maximum bytes for full content storage (default: 50KB). Above this, store diff only. */
  maxFullContentBytes?: number;
}

/**
 * Represents a file change record.
 */
export interface FileChange {
  /** Unique change ID */
  id: number;
  /** Session this change belongs to */
  sessionId: string;
  /** Turn number when change occurred */
  turnNumber: number;
  /** Path to the changed file */
  filePath: string;
  /** Type of operation */
  operation: 'create' | 'write' | 'edit' | 'delete';
  /** Content before the change (null for creates) */
  contentBefore: string | null;
  /** Content after the change (null for deletes) */
  contentAfter: string | null;
  /** Unified diff (when using diff storage mode) */
  diffUnified: string | null;
  /** How content is stored */
  storageMode: 'full' | 'diff';
  /** Bytes before change */
  bytesBefore: number;
  /** Bytes after change */
  bytesAfter: number;
  /** Whether this change has been undone */
  isUndone: boolean;
  /** ID of the change that undid this one */
  undoChangeId: number | null;
  /** Tool call ID that made this change */
  toolCallId: string | null;
  /** ISO timestamp of when change was recorded */
  createdAt: string;
}

/**
 * Result of an undo operation.
 */
export interface UndoResult {
  /** Whether the undo succeeded */
  success: boolean;
  /** Path to the affected file */
  filePath: string;
  /** Human-readable message */
  message: string;
  /** Change ID that was undone (if successful) */
  changeId?: number;
}

/**
 * Summary of changes in a session.
 */
export interface ChangeSummary {
  /** Total number of changes */
  totalChanges: number;
  /** Number of active (non-undone) changes */
  activeChanges: number;
  /** Number of undone changes */
  undoneChanges: number;
  /** Files that were modified */
  filesModified: string[];
  /** Changes by operation type */
  byOperation: {
    create: number;
    write: number;
    edit: number;
    delete: number;
  };
}

// =============================================================================
// DIFF UTILITIES
// =============================================================================

/**
 * Generate a simple unified diff between two strings.
 * This is a basic implementation - for production, consider using a proper diff library.
 */
function generateUnifiedDiff(before: string, after: string, filePath: string): string {
  const beforeLines = before.split('\n');
  const afterLines = after.split('\n');

  const header = [
    `--- a/${filePath}`,
    `+++ b/${filePath}`,
  ];

  // Simple line-by-line diff (not optimal but functional)
  const hunks: string[] = [];
  let i = 0;
  let j = 0;

  while (i < beforeLines.length || j < afterLines.length) {
    // Find next difference
    const startI = i;
    const startJ = j;

    // Skip matching lines
    while (i < beforeLines.length && j < afterLines.length && beforeLines[i] === afterLines[j]) {
      i++;
      j++;
    }

    // If we've found a difference or reached the end
    if (i < beforeLines.length || j < afterLines.length) {
      // Determine the hunk boundaries
      const contextBefore = Math.max(0, i - 3);
      const hunkStart = contextBefore + 1;

      // Find the extent of the difference
      const diffStartI = i;
      const diffStartJ = j;

      // Advance through differing lines
      while (i < beforeLines.length || j < afterLines.length) {
        if (i < beforeLines.length && j < afterLines.length && beforeLines[i] === afterLines[j]) {
          // Found a match - check if it's the end of the diff section
          let matchCount = 0;
          let tempI = i;
          let tempJ = j;
          while (tempI < beforeLines.length && tempJ < afterLines.length &&
                 beforeLines[tempI] === afterLines[tempJ] && matchCount < 3) {
            matchCount++;
            tempI++;
            tempJ++;
          }
          if (matchCount >= 3) {
            break;
          }
        }
        if (i < beforeLines.length) i++;
        if (j < afterLines.length) j++;
      }

      // Build the hunk
      const hunkLines: string[] = [];
      const beforeCount = i - contextBefore;
      const afterCount = j - (startJ + (contextBefore - startI));

      hunkLines.push(`@@ -${hunkStart},${beforeCount} +${hunkStart},${afterCount} @@`);

      // Add context before
      for (let k = contextBefore; k < diffStartI; k++) {
        hunkLines.push(` ${beforeLines[k]}`);
      }

      // Add removed lines
      for (let k = diffStartI; k < i; k++) {
        if (k < beforeLines.length) {
          hunkLines.push(`-${beforeLines[k]}`);
        }
      }

      // Add added lines
      for (let k = diffStartJ; k < j; k++) {
        if (k < afterLines.length) {
          hunkLines.push(`+${afterLines[k]}`);
        }
      }

      hunks.push(hunkLines.join('\n'));
    }
  }

  return [...header, ...hunks].join('\n');
}

/**
 * Apply a unified diff to restore original content.
 * Returns the original content before the diff was applied.
 */
function applyReverseDiff(currentContent: string, diff: string): string {
  // Parse diff hunks
  const lines = diff.split('\n');
  const resultLines = currentContent.split('\n');

  let lineIndex = 0;
  let i = 0;

  // Skip header lines
  while (i < lines.length && !lines[i].startsWith('@@')) {
    i++;
  }

  while (i < lines.length) {
    const line = lines[i];

    if (line.startsWith('@@')) {
      // Parse hunk header: @@ -start,count +start,count @@
      const match = line.match(/@@ -(\d+),?\d* \+(\d+),?\d* @@/);
      if (match) {
        lineIndex = parseInt(match[2], 10) - 1;
      }
      i++;
      continue;
    }

    if (line.startsWith('+')) {
      // This was an addition - remove it to reverse
      if (lineIndex < resultLines.length && resultLines[lineIndex] === line.slice(1)) {
        resultLines.splice(lineIndex, 1);
      }
      i++;
      continue;
    }

    if (line.startsWith('-')) {
      // This was a removal - add it back to reverse
      resultLines.splice(lineIndex, 0, line.slice(1));
      lineIndex++;
      i++;
      continue;
    }

    if (line.startsWith(' ')) {
      // Context line
      lineIndex++;
      i++;
      continue;
    }

    i++;
  }

  return resultLines.join('\n');
}

// =============================================================================
// FILE CHANGE TRACKER
// =============================================================================

/**
 * Tracks file changes for undo capability.
 */
export class FileChangeTracker {
  private db: Database.Database;
  private sessionId: string;
  private config: Required<FileChangeTrackerConfig>;
  private stmts!: {
    insertChange: Database.Statement;
    getChange: Database.Statement;
    getChanges: Database.Statement;
    getFileChanges: Database.Statement;
    getLastFileChange: Database.Statement;
    getTurnChanges: Database.Statement;
    markUndone: Database.Statement;
    getSessionSummary: Database.Statement;
  };

  constructor(db: Database.Database, sessionId: string, config?: FileChangeTrackerConfig) {
    this.db = db;
    this.sessionId = sessionId;
    this.config = {
      enabled: config?.enabled ?? true,
      maxFullContentBytes: config?.maxFullContentBytes ?? 50 * 1024, // 50KB
    };

    this.prepareStatements();
  }

  /**
   * Prepare SQL statements for reuse.
   */
  private prepareStatements(): void {
    this.stmts = {
      insertChange: this.db.prepare(`
        INSERT INTO file_changes (
          session_id, entry_id, tool_call_id, turn_number, file_path,
          operation, content_before, content_after, diff_unified,
          storage_mode, bytes_before, bytes_after, is_undone,
          undo_change_id, created_at
        )
        VALUES (
          @sessionId, @entryId, @toolCallId, @turnNumber, @filePath,
          @operation, @contentBefore, @contentAfter, @diffUnified,
          @storageMode, @bytesBefore, @bytesAfter, @isUndone,
          @undoChangeId, @createdAt
        )
      `),

      getChange: this.db.prepare(`
        SELECT
          id, session_id as sessionId, turn_number as turnNumber,
          file_path as filePath, operation, content_before as contentBefore,
          content_after as contentAfter, diff_unified as diffUnified,
          storage_mode as storageMode, bytes_before as bytesBefore,
          bytes_after as bytesAfter, is_undone as isUndone,
          undo_change_id as undoChangeId, tool_call_id as toolCallId,
          created_at as createdAt
        FROM file_changes
        WHERE id = ? AND session_id = ?
      `),

      getChanges: this.db.prepare(`
        SELECT
          id, session_id as sessionId, turn_number as turnNumber,
          file_path as filePath, operation, content_before as contentBefore,
          content_after as contentAfter, diff_unified as diffUnified,
          storage_mode as storageMode, bytes_before as bytesBefore,
          bytes_after as bytesAfter, is_undone as isUndone,
          undo_change_id as undoChangeId, tool_call_id as toolCallId,
          created_at as createdAt
        FROM file_changes
        WHERE session_id = ?
        ORDER BY id ASC
      `),

      getFileChanges: this.db.prepare(`
        SELECT
          id, session_id as sessionId, turn_number as turnNumber,
          file_path as filePath, operation, content_before as contentBefore,
          content_after as contentAfter, diff_unified as diffUnified,
          storage_mode as storageMode, bytes_before as bytesBefore,
          bytes_after as bytesAfter, is_undone as isUndone,
          undo_change_id as undoChangeId, tool_call_id as toolCallId,
          created_at as createdAt
        FROM file_changes
        WHERE session_id = ? AND file_path = ?
        ORDER BY id ASC
      `),

      getLastFileChange: this.db.prepare(`
        SELECT
          id, session_id as sessionId, turn_number as turnNumber,
          file_path as filePath, operation, content_before as contentBefore,
          content_after as contentAfter, diff_unified as diffUnified,
          storage_mode as storageMode, bytes_before as bytesBefore,
          bytes_after as bytesAfter, is_undone as isUndone,
          undo_change_id as undoChangeId, tool_call_id as toolCallId,
          created_at as createdAt
        FROM file_changes
        WHERE session_id = ? AND file_path = ? AND is_undone = 0
        ORDER BY id DESC
        LIMIT 1
      `),

      getTurnChanges: this.db.prepare(`
        SELECT
          id, session_id as sessionId, turn_number as turnNumber,
          file_path as filePath, operation, content_before as contentBefore,
          content_after as contentAfter, diff_unified as diffUnified,
          storage_mode as storageMode, bytes_before as bytesBefore,
          bytes_after as bytesAfter, is_undone as isUndone,
          undo_change_id as undoChangeId, tool_call_id as toolCallId,
          created_at as createdAt
        FROM file_changes
        WHERE session_id = ? AND turn_number = ? AND is_undone = 0
        ORDER BY id DESC
      `),

      markUndone: this.db.prepare(`
        UPDATE file_changes
        SET is_undone = 1, undo_change_id = ?
        WHERE id = ? AND session_id = ?
      `),

      getSessionSummary: this.db.prepare(`
        SELECT
          COUNT(*) as totalChanges,
          SUM(CASE WHEN is_undone = 0 THEN 1 ELSE 0 END) as activeChanges,
          SUM(CASE WHEN is_undone = 1 THEN 1 ELSE 0 END) as undoneChanges,
          SUM(CASE WHEN operation = 'create' AND is_undone = 0 THEN 1 ELSE 0 END) as createCount,
          SUM(CASE WHEN operation = 'write' AND is_undone = 0 THEN 1 ELSE 0 END) as writeCount,
          SUM(CASE WHEN operation = 'edit' AND is_undone = 0 THEN 1 ELSE 0 END) as editCount,
          SUM(CASE WHEN operation = 'delete' AND is_undone = 0 THEN 1 ELSE 0 END) as deleteCount
        FROM file_changes
        WHERE session_id = ?
      `),
    };
  }

  /**
   * Record a file change.
   */
  async recordChange(params: {
    filePath: string;
    operation: 'create' | 'write' | 'edit' | 'delete';
    contentBefore?: string;
    contentAfter?: string;
    turnNumber: number;
    toolCallId?: string;
  }): Promise<number> {
    if (!this.config.enabled) {
      return -1;
    }

    const now = new Date().toISOString();
    const contentBefore = params.contentBefore ?? null;
    const contentAfter = params.contentAfter ?? null;
    const bytesBefore = contentBefore ? Buffer.byteLength(contentBefore, 'utf-8') : 0;
    const bytesAfter = contentAfter ? Buffer.byteLength(contentAfter, 'utf-8') : 0;

    // Determine storage mode
    let storageMode: 'full' | 'diff' = 'full';
    let diffUnified: string | null = null;
    let storedBefore = contentBefore;
    let storedAfter = contentAfter;

    // Use diff mode for large files
    const totalBytes = bytesBefore + bytesAfter;
    if (totalBytes > this.config.maxFullContentBytes && contentBefore && contentAfter) {
      storageMode = 'diff';
      diffUnified = generateUnifiedDiff(contentBefore, contentAfter, params.filePath);
      // In diff mode, we only store the after content (current state) and the diff
      // to reconstruct the before content
      storedBefore = null;
      storedAfter = contentAfter;
    }

    const result = this.stmts.insertChange.run({
      sessionId: this.sessionId,
      entryId: null,
      toolCallId: params.toolCallId ?? null,
      turnNumber: params.turnNumber,
      filePath: params.filePath,
      operation: params.operation,
      contentBefore: storedBefore,
      contentAfter: storedAfter,
      diffUnified,
      storageMode,
      bytesBefore,
      bytesAfter,
      isUndone: 0,
      undoChangeId: null,
      createdAt: now,
    });

    return result.lastInsertRowid as number;
  }

  /**
   * Undo a specific change by ID.
   */
  async undoChange(changeId: number): Promise<UndoResult> {
    const row = this.stmts.getChange.get(changeId, this.sessionId) as {
      id: number;
      sessionId: string;
      turnNumber: number;
      filePath: string;
      operation: string;
      contentBefore: string | null;
      contentAfter: string | null;
      diffUnified: string | null;
      storageMode: string;
      bytesBefore: number;
      bytesAfter: number;
      isUndone: number;
      undoChangeId: number | null;
      toolCallId: string | null;
      createdAt: string;
    } | undefined;

    if (!row) {
      return {
        success: false,
        filePath: '',
        message: `Change ${changeId} not found`,
      };
    }

    if (row.isUndone) {
      return {
        success: false,
        filePath: row.filePath,
        message: `Change ${changeId} has already been undone`,
      };
    }

    const filePath = row.filePath;

    try {
      // Determine what content to restore
      let contentToRestore: string | null = null;

      if (row.storageMode === 'full') {
        contentToRestore = row.contentBefore;
      } else if (row.storageMode === 'diff' && row.diffUnified && row.contentAfter) {
        // Reconstruct the before content from the diff
        contentToRestore = applyReverseDiff(row.contentAfter, row.diffUnified);
      }

      // Perform the undo based on operation type
      switch (row.operation) {
        case 'create':
          // Undo create = delete the file
          if (existsSync(filePath)) {
            await unlink(filePath);
          }
          break;

        case 'write':
        case 'edit':
          // Undo write/edit = restore previous content
          if (contentToRestore !== null) {
            await writeFile(filePath, contentToRestore, 'utf-8');
          } else if (row.operation === 'write') {
            // If no previous content for a write, delete the file
            if (existsSync(filePath)) {
              await unlink(filePath);
            }
          }
          break;

        case 'delete':
          // Undo delete = recreate the file with original content
          if (contentToRestore !== null) {
            await writeFile(filePath, contentToRestore, 'utf-8');
          }
          break;
      }

      // Mark as undone (no undo change id since this isn't creating a new change record)
      this.stmts.markUndone.run(null, changeId, this.sessionId);

      return {
        success: true,
        filePath,
        message: `Successfully undid ${row.operation} on ${filePath}`,
        changeId,
      };
    } catch (error) {
      return {
        success: false,
        filePath,
        message: `Failed to undo change: ${error instanceof Error ? error.message : String(error)}`,
        changeId,
      };
    }
  }

  /**
   * Undo the last change to a specific file.
   */
  async undoLastChange(filePath: string): Promise<UndoResult> {
    const row = this.stmts.getLastFileChange.get(this.sessionId, filePath) as {
      id: number;
    } | undefined;

    if (!row) {
      return {
        success: false,
        filePath,
        message: `No undoable changes found for ${filePath}`,
      };
    }

    return this.undoChange(row.id);
  }

  /**
   * Undo all changes in a turn.
   */
  async undoTurn(turnNumber: number): Promise<UndoResult[]> {
    const rows = this.stmts.getTurnChanges.all(this.sessionId, turnNumber) as Array<{
      id: number;
      filePath: string;
    }>;

    const results: UndoResult[] = [];

    // Undo in reverse order (last change first)
    for (const row of rows) {
      const result = await this.undoChange(row.id);
      results.push(result);
    }

    return results;
  }

  /**
   * Get all changes for a file.
   */
  getFileHistory(filePath: string): FileChange[] {
    const rows = this.stmts.getFileChanges.all(this.sessionId, filePath) as Array<{
      id: number;
      sessionId: string;
      turnNumber: number;
      filePath: string;
      operation: string;
      contentBefore: string | null;
      contentAfter: string | null;
      diffUnified: string | null;
      storageMode: string;
      bytesBefore: number;
      bytesAfter: number;
      isUndone: number;
      undoChangeId: number | null;
      toolCallId: string | null;
      createdAt: string;
    }>;

    return rows.map(row => ({
      id: row.id,
      sessionId: row.sessionId,
      turnNumber: row.turnNumber,
      filePath: row.filePath,
      operation: row.operation as 'create' | 'write' | 'edit' | 'delete',
      contentBefore: row.contentBefore,
      contentAfter: row.contentAfter,
      diffUnified: row.diffUnified,
      storageMode: row.storageMode as 'full' | 'diff',
      bytesBefore: row.bytesBefore,
      bytesAfter: row.bytesAfter,
      isUndone: row.isUndone === 1,
      undoChangeId: row.undoChangeId,
      toolCallId: row.toolCallId,
      createdAt: row.createdAt,
    }));
  }

  /**
   * Get all changes in session.
   */
  getChanges(options?: { filePath?: string }): FileChange[] {
    if (options?.filePath) {
      return this.getFileHistory(options.filePath);
    }

    const rows = this.stmts.getChanges.all(this.sessionId) as Array<{
      id: number;
      sessionId: string;
      turnNumber: number;
      filePath: string;
      operation: string;
      contentBefore: string | null;
      contentAfter: string | null;
      diffUnified: string | null;
      storageMode: string;
      bytesBefore: number;
      bytesAfter: number;
      isUndone: number;
      undoChangeId: number | null;
      toolCallId: string | null;
      createdAt: string;
    }>;

    return rows.map(row => ({
      id: row.id,
      sessionId: row.sessionId,
      turnNumber: row.turnNumber,
      filePath: row.filePath,
      operation: row.operation as 'create' | 'write' | 'edit' | 'delete',
      contentBefore: row.contentBefore,
      contentAfter: row.contentAfter,
      diffUnified: row.diffUnified,
      storageMode: row.storageMode as 'full' | 'diff',
      bytesBefore: row.bytesBefore,
      bytesAfter: row.bytesAfter,
      isUndone: row.isUndone === 1,
      undoChangeId: row.undoChangeId,
      toolCallId: row.toolCallId,
      createdAt: row.createdAt,
    }));
  }

  /**
   * Get session change summary.
   */
  getSessionChangeSummary(): ChangeSummary {
    const row = this.stmts.getSessionSummary.get(this.sessionId) as {
      totalChanges: number;
      activeChanges: number;
      undoneChanges: number;
      createCount: number;
      writeCount: number;
      editCount: number;
      deleteCount: number;
    };

    // Get unique file paths from active changes
    const changes = this.getChanges();
    const activeFiles = new Set<string>();
    for (const change of changes) {
      if (!change.isUndone) {
        activeFiles.add(change.filePath);
      }
    }

    return {
      totalChanges: row.totalChanges || 0,
      activeChanges: row.activeChanges || 0,
      undoneChanges: row.undoneChanges || 0,
      filesModified: Array.from(activeFiles),
      byOperation: {
        create: row.createCount || 0,
        write: row.writeCount || 0,
        edit: row.editCount || 0,
        delete: row.deleteCount || 0,
      },
    };
  }
}

// =============================================================================
// FACTORY
// =============================================================================

/**
 * Create a FileChangeTracker instance.
 */
export function createFileChangeTracker(
  db: Database.Database,
  sessionId: string,
  config?: FileChangeTrackerConfig
): FileChangeTracker {
  return new FileChangeTracker(db, sessionId, config);
}
