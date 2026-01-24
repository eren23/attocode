-- Migration: 005_file_changes
-- Description: Tracks file changes for undo capability
-- Created: 2026

-- File changes table
-- Stores detailed records of file operations for undo/redo capability:
-- - operation: create, write, edit, or delete
-- - content_before/after: Full content snapshots or null if using diff
-- - diff_unified: Unified diff format for large files
-- - storage_mode: 'full' or 'diff' indicating how content is stored
-- - is_undone: Whether this change has been reverted
-- - undo_change_id: ID of the change that undid this one (if applicable)
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

-- Index for querying changes by session and file path
CREATE INDEX IF NOT EXISTS idx_file_changes_session_path
  ON file_changes(session_id, file_path);

-- Index for querying changes by session and turn number
CREATE INDEX IF NOT EXISTS idx_file_changes_session_turn
  ON file_changes(session_id, turn_number);
