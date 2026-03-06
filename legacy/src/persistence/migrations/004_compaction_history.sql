-- Migration: 004_compaction_history
-- Description: Tracks context compaction events for session continuity
-- Created: 2026

-- Compaction history table
-- Stores detailed records of context compaction events including:
-- - summary: The compacted summary text
-- - references_json: JSON array of preserved reference identifiers
-- - tokens_before/after: Token counts for measuring compression ratio
-- - messages_compacted: Number of messages that were compacted
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

-- Index for querying compaction history by session
CREATE INDEX IF NOT EXISTS idx_compaction_history_session
  ON compaction_history(session_id);
