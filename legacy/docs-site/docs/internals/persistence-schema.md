---
sidebar_position: 1
title: "Persistence Schema"
---

# Persistence Schema

Attocode uses SQLite for session persistence, stored at `.agent/sessions/sessions.db`. The schema is managed through an embedded migration system.

## Core Tables

### sessions

Stores session metadata and cost tracking.

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | UUID |
| `name` | TEXT | Session name |
| `created_at` | TEXT | ISO timestamp |
| `last_active_at` | TEXT | Last activity timestamp |
| `message_count` | INTEGER | Total messages |
| `token_count` | INTEGER | Total tokens used |
| `summary` | TEXT | Session summary |
| `prompt_tokens` | INTEGER | Total prompt tokens |
| `completion_tokens` | INTEGER | Total completion tokens |
| `cost_usd` | REAL | Total cost in USD |
| `parent_session_id` | TEXT | Parent session (for subagents) |
| `session_type` | TEXT | `main`, `subagent`, `branch`, `fork` |

### entries

Chronological log of session events.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `session_id` | TEXT FK | References sessions |
| `timestamp` | TEXT | ISO timestamp |
| `type` | TEXT | Entry type (message, tool_call, etc.) |
| `data` | TEXT | JSON-encoded entry data |
| `is_summary` | INTEGER | Whether this is a compaction summary |

### checkpoints

Periodic state snapshots for session resume.

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | Checkpoint UUID |
| `session_id` | TEXT FK | References sessions |
| `state_json` | TEXT | Full serialized state (messages, etc.) |
| `created_at` | TEXT | ISO timestamp |
| `description` | TEXT | Optional checkpoint label |

### tool_calls

Individual tool execution records.

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | Tool call ID |
| `session_id` | TEXT FK | References sessions |
| `name` | TEXT | Tool name |
| `arguments` | TEXT | JSON-encoded arguments |
| `status` | TEXT | `pending`, `completed`, `failed` |
| `result` | TEXT | Tool output |
| `error` | TEXT | Error message if failed |
| `duration_ms` | INTEGER | Execution time |

## Feature Tables

### goals

Persists agent objectives outside of context window (used by goal recitation).

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | Goal UUID |
| `session_id` | TEXT FK | References sessions |
| `goal_text` | TEXT | Goal description |
| `status` | TEXT | `active`, `completed`, `abandoned` |
| `priority` | INTEGER | Priority level |
| `parent_goal_id` | TEXT FK | Sub-goal hierarchy |
| `progress_current` / `progress_total` | INTEGER | Completion tracking |

### junctures

Records critical decisions made during a session.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `session_id` | TEXT FK | References sessions |
| `goal_id` | TEXT FK | Related goal |
| `type` | TEXT | Juncture type |
| `description` | TEXT | What was decided |
| `outcome` | TEXT | Result of the decision |
| `importance` | INTEGER | Importance level (1-5) |

### worker_results

Stores subagent and swarm worker results.

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | Worker result UUID |
| `session_id` | TEXT FK | References sessions |
| `worker_id` | TEXT | Worker/agent instance ID |
| `task_description` | TEXT | What the worker did |
| `status` | TEXT | `pending`, `completed`, `failed` |
| `summary` | TEXT | Result summary |
| `full_output` | TEXT | Complete output |
| `artifacts` | TEXT | JSON-encoded artifact references |

### Other Tables

- **usage_logs**: Per-request cost tracking (model, tokens, cost, timestamp)
- **file_changes**: File modification history for undo support (before/after content, diffs)
- **compaction_history**: Context compaction records (tokens before/after, references)
- **pending_plans**: Plans awaiting user approval in plan mode
- **dead_letters**: Failed operations queued for retry
- **remembered_permissions**: User permission decisions (pattern, scope for prefix matching)

## Migration System

Migrations are embedded as TypeScript objects in `src/persistence/schema.ts`. Each migration has a version number, name, and idempotent SQL statements.

```typescript
const MIGRATIONS: Migration[] = [
  { version: 1, name: 'initial', sql: '...' },
  { version: 2, name: 'add_costs', sql: '...' },
  // ...
];
```

Applied with `applyMigrations(db)`. The system uses a `schema_versions` table to track which migrations have been applied. Feature detection (`detectFeatures()`) checks which tables exist without requiring specific migration versions.

## Session Lifecycle

1. **Create**: `createSession(name)` inserts a new session row
2. **Run**: Messages and tool calls are logged to `entries` and `tool_calls`
3. **Checkpoint**: Periodic state snapshots saved to `checkpoints`
4. **Save**: Final metrics and summary updated on session row
5. **Resume**: Load last checkpoint, reconstruct messages, continue from where left off
