-- Migration: 002_add_costs
-- Description: Add cost tracking columns and usage logs table
-- Created: 2026

-- Add token and cost tracking columns to sessions
-- Note: SQLite ALTER TABLE only supports adding columns, not modifying existing ones
ALTER TABLE sessions ADD COLUMN prompt_tokens INTEGER DEFAULT 0;
ALTER TABLE sessions ADD COLUMN completion_tokens INTEGER DEFAULT 0;
ALTER TABLE sessions ADD COLUMN cost_usd REAL DEFAULT 0.0;

-- Usage logs table for detailed per-call tracking
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

-- Index for querying usage by session
CREATE INDEX IF NOT EXISTS idx_usage_logs_session ON usage_logs(session_id);

-- Index for querying usage by timestamp (for reporting)
CREATE INDEX IF NOT EXISTS idx_usage_logs_timestamp ON usage_logs(timestamp);
