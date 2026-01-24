-- Migration: 003_add_session_hierarchy
-- Description: Add session hierarchy support for parent/child sessions
-- Created: 2026

-- Add parent session reference and session type to sessions
-- parent_session_id: Links child sessions to their parent
-- session_type: 'main', 'subagent', 'branch', etc.
--
-- NOTE: SQLite's ALTER TABLE does not support adding foreign key constraints.
-- The parent-child relationship is enforced at the application level.
-- Enable PRAGMA foreign_keys = ON before INSERT/UPDATE to validate references.
ALTER TABLE sessions ADD COLUMN parent_session_id TEXT;
ALTER TABLE sessions ADD COLUMN session_type TEXT DEFAULT 'main';
ALTER TABLE sessions ADD COLUMN summary_message_id INTEGER;

-- Add is_summary flag to entries for marking summary messages
ALTER TABLE entries ADD COLUMN is_summary INTEGER DEFAULT 0;

-- Index for finding child sessions
CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_session_id);

-- Index for finding sessions by type
CREATE INDEX IF NOT EXISTS idx_sessions_type ON sessions(session_type);

-- Index for finding summary entries
CREATE INDEX IF NOT EXISTS idx_entries_summary ON entries(session_id, is_summary) WHERE is_summary = 1;
