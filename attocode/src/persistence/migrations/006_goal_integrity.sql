-- Migration: 006_goal_integrity
-- Description: Add goals table and critical junctures for Goal Integrity pillar
-- Created: 2026

-- Goals table - persists goals outside of context
-- Goals survive compaction, crashes, and model swaps
CREATE TABLE IF NOT EXISTS goals (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  goal_text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',  -- active, completed, abandoned
  priority INTEGER DEFAULT 1,             -- 1=highest, 3=lowest
  parent_goal_id TEXT,                    -- for sub-goals
  progress_current INTEGER DEFAULT 0,     -- current progress (e.g., 3 of 7)
  progress_total INTEGER,                 -- total items (e.g., 7)
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  completed_at TEXT,
  metadata TEXT,                          -- JSON for extensibility
  FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
  FOREIGN KEY (parent_goal_id) REFERENCES goals(id) ON DELETE SET NULL
);

-- Critical junctures table - captures key decisions, failures, breakthroughs
CREATE TABLE IF NOT EXISTS junctures (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  goal_id TEXT,                           -- optional link to related goal
  type TEXT NOT NULL,                     -- decision, failure, breakthrough, pivot
  description TEXT NOT NULL,
  outcome TEXT,                           -- what happened as a result
  importance INTEGER DEFAULT 2,           -- 1=critical, 2=significant, 3=minor
  context TEXT,                           -- JSON: relevant state at the time
  created_at TEXT NOT NULL,
  FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
  FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE SET NULL
);

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_goals_session ON goals(session_id);
CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(session_id, status);
CREATE INDEX IF NOT EXISTS idx_goals_parent ON goals(parent_goal_id);
CREATE INDEX IF NOT EXISTS idx_junctures_session ON junctures(session_id);
CREATE INDEX IF NOT EXISTS idx_junctures_goal ON junctures(goal_id);
CREATE INDEX IF NOT EXISTS idx_junctures_type ON junctures(session_id, type);
