/**
 * File Change Tracker Tests
 *
 * Tests for file change tracking and undo functionality,
 * including TOCTOU race condition prevention.
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import Database from 'better-sqlite3';
import { mkdtemp, rm, writeFile, readFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  FileChangeTracker,
  createFileChangeTracker,
} from '../../src/integrations/file-change-tracker.js';

describe('FileChangeTracker', () => {
  let db: Database.Database;
  let tempDir: string;
  let tracker: FileChangeTracker;
  const sessionId = 'test-session-123';

  beforeEach(async () => {
    // Create temp directory for test files
    tempDir = await mkdtemp(join(tmpdir(), 'fct-test-'));

    // Create in-memory database
    db = new Database(':memory:');

    // Create the required table
    db.exec(`
      CREATE TABLE IF NOT EXISTS file_changes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        entry_id TEXT,
        tool_call_id TEXT,
        turn_number INTEGER NOT NULL,
        file_path TEXT NOT NULL,
        operation TEXT NOT NULL,
        content_before TEXT,
        content_after TEXT,
        diff_unified TEXT,
        storage_mode TEXT NOT NULL DEFAULT 'full',
        bytes_before INTEGER DEFAULT 0,
        bytes_after INTEGER DEFAULT 0,
        is_undone INTEGER DEFAULT 0,
        undo_change_id INTEGER,
        created_at TEXT NOT NULL
      )
    `);

    tracker = createFileChangeTracker(db, sessionId);
  });

  afterEach(async () => {
    db.close();
    await rm(tempDir, { recursive: true, force: true });
  });

  describe('recording changes', () => {
    it('should record a file creation', async () => {
      const filePath = join(tempDir, 'new-file.txt');
      await writeFile(filePath, 'Hello World');

      const changeId = await tracker.recordChange({
        filePath,
        operation: 'create',
        contentAfter: 'Hello World',
        turnNumber: 1,
      });

      expect(changeId).toBeGreaterThan(0);
    });

    it('should record a file edit', async () => {
      const filePath = join(tempDir, 'edit-file.txt');
      await writeFile(filePath, 'Original content');

      const changeId = await tracker.recordChange({
        filePath,
        operation: 'edit',
        contentBefore: 'Original content',
        contentAfter: 'Modified content',
        turnNumber: 1,
      });

      expect(changeId).toBeGreaterThan(0);
    });

    it('should record a file deletion', async () => {
      const filePath = join(tempDir, 'delete-file.txt');
      await writeFile(filePath, 'Content to delete');

      const changeId = await tracker.recordChange({
        filePath,
        operation: 'delete',
        contentBefore: 'Content to delete',
        turnNumber: 1,
      });

      expect(changeId).toBeGreaterThan(0);
    });

    it('should return -1 when tracking is disabled', async () => {
      const disabledTracker = createFileChangeTracker(db, sessionId, { enabled: false });

      const changeId = await disabledTracker.recordChange({
        filePath: '/some/file',
        operation: 'create',
        turnNumber: 1,
      });

      expect(changeId).toBe(-1);
    });

    it('should use diff storage for large files', async () => {
      const filePath = join(tempDir, 'large-file.txt');
      const largeContent = 'x'.repeat(60 * 1024); // 60KB
      await writeFile(filePath, largeContent);

      const changeId = await tracker.recordChange({
        filePath,
        operation: 'edit',
        contentBefore: largeContent,
        contentAfter: largeContent + ' modified',
        turnNumber: 1,
      });

      expect(changeId).toBeGreaterThan(0);

      // Verify storage mode is diff
      const changes = tracker.getChanges();
      const change = changes.find(c => c.id === changeId);
      expect(change?.storageMode).toBe('diff');
    });
  });

  describe('undoing changes', () => {
    it('should undo a file creation by deleting the file', async () => {
      const filePath = join(tempDir, 'undo-create.txt');
      await writeFile(filePath, 'Created content');

      const changeId = await tracker.recordChange({
        filePath,
        operation: 'create',
        contentAfter: 'Created content',
        turnNumber: 1,
      });

      const result = await tracker.undoChange(changeId);

      expect(result.success).toBe(true);
      expect(existsSync(filePath)).toBe(false);
    });

    it('should undo a file edit by restoring previous content', async () => {
      const filePath = join(tempDir, 'undo-edit.txt');
      await writeFile(filePath, 'Modified content');

      const changeId = await tracker.recordChange({
        filePath,
        operation: 'edit',
        contentBefore: 'Original content',
        contentAfter: 'Modified content',
        turnNumber: 1,
      });

      const result = await tracker.undoChange(changeId);

      expect(result.success).toBe(true);
      const content = await readFile(filePath, 'utf-8');
      expect(content).toBe('Original content');
    });

    it('should undo a file deletion by recreating the file', async () => {
      const filePath = join(tempDir, 'undo-delete.txt');
      // File is already deleted, we just recorded the deletion

      const changeId = await tracker.recordChange({
        filePath,
        operation: 'delete',
        contentBefore: 'Deleted content',
        turnNumber: 1,
      });

      const result = await tracker.undoChange(changeId);

      expect(result.success).toBe(true);
      const content = await readFile(filePath, 'utf-8');
      expect(content).toBe('Deleted content');
    });

    it('should fail to undo non-existent change', async () => {
      const result = await tracker.undoChange(99999);

      expect(result.success).toBe(false);
      expect(result.message).toContain('not found');
    });

    it('should fail to undo already undone change', async () => {
      const filePath = join(tempDir, 'double-undo.txt');
      await writeFile(filePath, 'Content');

      const changeId = await tracker.recordChange({
        filePath,
        operation: 'create',
        contentAfter: 'Content',
        turnNumber: 1,
      });

      // First undo
      const result1 = await tracker.undoChange(changeId);
      expect(result1.success).toBe(true);

      // Second undo should fail
      const result2 = await tracker.undoChange(changeId);
      expect(result2.success).toBe(false);
      expect(result2.message).toContain('already undone');
    });
  });

  describe('TOCTOU race condition prevention', () => {
    it('should prevent double-undo race condition', async () => {
      const filePath = join(tempDir, 'race-test.txt');
      await writeFile(filePath, 'Original content');

      const changeId = await tracker.recordChange({
        filePath,
        operation: 'edit',
        contentBefore: 'Original content',
        contentAfter: 'Modified content',
        turnNumber: 1,
      });

      // Attempt concurrent undos
      const results = await Promise.all([
        tracker.undoChange(changeId),
        tracker.undoChange(changeId),
        tracker.undoChange(changeId),
      ]);

      // Exactly ONE should succeed
      const successes = results.filter(r => r.success);
      const failures = results.filter(r => !r.success);

      expect(successes.length).toBe(1);
      expect(failures.length).toBe(2);

      // Failures should have appropriate error messages
      for (const failure of failures) {
        expect(
          failure.message.includes('already undone') ||
          failure.message.includes('Concurrent modification')
        ).toBe(true);
      }
    });

    it('should handle rapid sequential undos correctly', async () => {
      const filePath = join(tempDir, 'sequential-test.txt');
      await writeFile(filePath, 'Content');

      const changeId = await tracker.recordChange({
        filePath,
        operation: 'create',
        contentAfter: 'Content',
        turnNumber: 1,
      });

      // Rapid sequential calls (not quite concurrent but fast)
      const result1 = await tracker.undoChange(changeId);
      const result2 = await tracker.undoChange(changeId);

      expect(result1.success).toBe(true);
      expect(result2.success).toBe(false);
    });

    it('should rollback on file operation failure', async () => {
      // Create a change for a file in a non-existent directory
      // When we try to undo, the file write will fail
      const nonExistentPath = join(tempDir, 'does', 'not', 'exist', 'file.txt');

      const changeId = await tracker.recordChange({
        filePath: nonExistentPath,
        operation: 'delete',
        contentBefore: 'Content to restore',
        turnNumber: 1,
      });

      const result = await tracker.undoChange(changeId);

      // Should fail because the directory doesn't exist
      expect(result.success).toBe(false);

      // The change should NOT be marked as undone (rollback occurred)
      const changes = tracker.getChanges();
      const change = changes.find(c => c.id === changeId);
      expect(change?.isUndone).toBe(false);
    });
  });

  describe('undo last change', () => {
    it('should undo the most recent change for a file', async () => {
      const filePath = join(tempDir, 'last-change.txt');
      await writeFile(filePath, 'Version 3');

      // Record multiple changes
      await tracker.recordChange({
        filePath,
        operation: 'edit',
        contentBefore: 'Version 1',
        contentAfter: 'Version 2',
        turnNumber: 1,
      });

      await tracker.recordChange({
        filePath,
        operation: 'edit',
        contentBefore: 'Version 2',
        contentAfter: 'Version 3',
        turnNumber: 2,
      });

      const result = await tracker.undoLastChange(filePath);

      expect(result.success).toBe(true);
      const content = await readFile(filePath, 'utf-8');
      expect(content).toBe('Version 2');
    });

    it('should fail when no undoable changes exist', async () => {
      const result = await tracker.undoLastChange('/nonexistent/file.txt');

      expect(result.success).toBe(false);
      expect(result.message).toContain('No undoable changes');
    });
  });

  describe('undo turn', () => {
    it('should undo all changes in a turn', async () => {
      const file1 = join(tempDir, 'turn-file1.txt');
      const file2 = join(tempDir, 'turn-file2.txt');

      await writeFile(file1, 'File 1 modified');
      await writeFile(file2, 'File 2 modified');

      // Record changes in turn 5
      await tracker.recordChange({
        filePath: file1,
        operation: 'edit',
        contentBefore: 'File 1 original',
        contentAfter: 'File 1 modified',
        turnNumber: 5,
      });

      await tracker.recordChange({
        filePath: file2,
        operation: 'edit',
        contentBefore: 'File 2 original',
        contentAfter: 'File 2 modified',
        turnNumber: 5,
      });

      const results = await tracker.undoTurn(5);

      expect(results.length).toBe(2);
      expect(results.every(r => r.success)).toBe(true);

      const content1 = await readFile(file1, 'utf-8');
      const content2 = await readFile(file2, 'utf-8');

      expect(content1).toBe('File 1 original');
      expect(content2).toBe('File 2 original');
    });
  });

  describe('file history', () => {
    it('should retrieve all changes for a file', async () => {
      const filePath = join(tempDir, 'history-file.txt');

      await tracker.recordChange({
        filePath,
        operation: 'create',
        contentAfter: 'v1',
        turnNumber: 1,
      });

      await tracker.recordChange({
        filePath,
        operation: 'edit',
        contentBefore: 'v1',
        contentAfter: 'v2',
        turnNumber: 2,
      });

      const history = tracker.getFileHistory(filePath);

      expect(history.length).toBe(2);
      expect(history[0].operation).toBe('create');
      expect(history[1].operation).toBe('edit');
    });
  });

  describe('session summary', () => {
    it('should provide accurate session summary', async () => {
      const file1 = join(tempDir, 'summary1.txt');
      const file2 = join(tempDir, 'summary2.txt');

      await writeFile(file1, 'Content');
      await writeFile(file2, 'Content');

      await tracker.recordChange({
        filePath: file1,
        operation: 'create',
        contentAfter: 'Content',
        turnNumber: 1,
      });

      await tracker.recordChange({
        filePath: file1,
        operation: 'edit',
        contentBefore: 'Content',
        contentAfter: 'Modified',
        turnNumber: 2,
      });

      await tracker.recordChange({
        filePath: file2,
        operation: 'delete',
        contentBefore: 'Content',
        turnNumber: 3,
      });

      const summary = tracker.getSessionChangeSummary();

      expect(summary.totalChanges).toBe(3);
      expect(summary.activeChanges).toBe(3);
      expect(summary.undoneChanges).toBe(0);
      expect(summary.filesModified.length).toBe(2);
      expect(summary.byOperation.create).toBe(1);
      expect(summary.byOperation.edit).toBe(1);
      expect(summary.byOperation.delete).toBe(1);
    });

    it('should update summary after undo', async () => {
      const filePath = join(tempDir, 'summary-undo.txt');
      await writeFile(filePath, 'Content');

      const changeId = await tracker.recordChange({
        filePath,
        operation: 'create',
        contentAfter: 'Content',
        turnNumber: 1,
      });

      await tracker.undoChange(changeId);

      const summary = tracker.getSessionChangeSummary();

      expect(summary.totalChanges).toBe(1);
      expect(summary.activeChanges).toBe(0);
      expect(summary.undoneChanges).toBe(1);
    });
  });

  describe('getChanges', () => {
    it('should return all changes', async () => {
      await tracker.recordChange({
        filePath: join(tempDir, 'file1.txt'),
        operation: 'create',
        contentAfter: 'Content 1',
        turnNumber: 1,
      });

      await tracker.recordChange({
        filePath: join(tempDir, 'file2.txt'),
        operation: 'create',
        contentAfter: 'Content 2',
        turnNumber: 1,
      });

      const changes = tracker.getChanges();
      expect(changes.length).toBe(2);
    });

    it('should filter by file path', async () => {
      const targetPath = join(tempDir, 'target.txt');

      await tracker.recordChange({
        filePath: targetPath,
        operation: 'create',
        contentAfter: 'Content',
        turnNumber: 1,
      });

      await tracker.recordChange({
        filePath: join(tempDir, 'other.txt'),
        operation: 'create',
        contentAfter: 'Other',
        turnNumber: 1,
      });

      const changes = tracker.getChanges({ filePath: targetPath });
      expect(changes.length).toBe(1);
      expect(changes[0].filePath).toBe(targetPath);
    });
  });
});
