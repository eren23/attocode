---
sidebar_position: 5
title: Sessions
---

# Sessions

Attocode persists all conversation state to a SQLite database, enabling save/load, checkpoints, forking, and crash recovery. The persistence layer lives in `src/integrations/persistence/` and is split across several repository modules.

## Storage Backend

Sessions are stored in a SQLite database at `.agent/sessions.db` (configurable via `SQLiteStoreConfig.dbPath`). The database uses WAL mode by default for better concurrency when subagents write simultaneously.

The implementation is split across repository modules:
- `session-repository.ts` -- Session CRUD, checkpoints, costs, hierarchy, plans, permissions, manifest
- `goal-repository.ts` -- Goals and junctures
- `worker-repository.ts` -- Worker results and artifacts
- `codebase-repository.ts` -- Codebase context data

## Session Metadata

Each session tracks:

```typescript
interface SessionMetadata {
  id: string;
  name?: string;
  workspacePath?: string;
  createdAt: string;
  lastActiveAt: string;
  messageCount: number;
  tokenCount: number;
  summary?: string;
  parentSessionId?: string;     // For forks and subagent sessions
  sessionType?: SessionType;    // 'main' | 'subagent' | 'branch' | 'fork'
  promptTokens?: number;
  completionTokens?: number;
  estimatedCost?: number;
}
```

## Basic Commands

| Command | Description |
|---------|-------------|
| `/save` | Save current session state |
| `/load <id>` | Load a session by ID |
| `/sessions` | List all saved sessions with timestamps and metrics |
| `/resume` | Resume the most recent session |

## Auto-Checkpoints

Attocode automatically creates checkpoints every 5 turns. Each checkpoint captures:

- **Messages** -- The full conversation history at that point
- **Iteration count** -- How many agent turns have elapsed
- **Metrics** -- Token counts, cost, tool call counts
- **Plan state** -- Any pending plan from plan mode
- **Memory context** -- Compacted context and memory references

Auto-checkpoints enable crash recovery: if the process terminates unexpectedly, `/resume` restores from the most recent checkpoint.

## Manual Checkpoints

```
/checkpoint "before refactoring auth module"
/checkpoints                    # list all checkpoints
/restore <checkpoint-id>        # restore to a specific checkpoint
/rollback                       # undo the last step (rollback 1)
/rollback 3                     # undo the last 3 steps
```

Checkpoints are stored in the `checkpoints` table with a label, timestamp, and the serialized agent state.

## Session Forking

Forking creates a new session that branches from the current conversation state:

```
/fork "experiment-with-redis"
```

This creates a new session with:
- A copy of the current messages and state
- `parentSessionId` pointing to the original session
- `sessionType` set to `'fork'`

You can work on the fork independently, and later switch back to the original session.

## Thread Management

Threads allow parallel conversation branches within a session:

```
/threads          # list all threads
/switch <id>      # switch to a different thread
```

The `ThreadManager` tracks active threads and their checkpoint history, making it possible to jump between different lines of exploration.

## Session Hierarchy

Sessions form a tree structure through `parentSessionId`:

```
main-session
├── fork-1 (forked at checkpoint 5)
│   └── subagent-task-a
├── fork-2 (forked at checkpoint 8)
└── subagent-task-b
```

Subagent sessions are automatically created when `spawn_agent` is called. They have `sessionType: 'subagent'` and track their own token usage and cost independently.

## Cost Tracking

Every LLM call logs a usage record:

```typescript
interface UsageLog {
  sessionId: string;
  modelId: string;
  promptTokens: number;
  completionTokens: number;
  costUsd: number;
  timestamp: string;
}
```

The `/status` command aggregates these logs to show total cost for the current session. Cost data persists across resumes.

## Resume Picker

On startup, if previous sessions exist, the TUI displays a resume picker:

- **Quick select** -- Shows the most recent session with a Y/N prompt
- **Full browser** -- Lists all sessions sorted by last activity, with ID, name, message count, and cost

## File Change Tracking

The session API includes file change tracking for undo support:

- `trackFileChange()` records each file operation (create, write, edit, delete) with before/after content
- `undoLastFileChange(path)` reverts the last change to a specific file
- `undoCurrentTurn()` reverts all changes from the current agent turn

Changes are associated with turn numbers and tool call IDs for precise rollback.

## Dead Letter Queue

The `DeadLetterQueue` tracks operations that failed during a session (tool execution errors, permission denials, timeout failures). On resume, the agent can review the dead letter queue to retry or skip failed operations:

```typescript
interface DeadLetterEntry {
  tool: string;
  args: Record<string, unknown>;
  error: string;
  timestamp: string;
  retryCount: number;
}
```

## Persistence Debug Mode

Enable detailed persistence logging with `--debug`:

```bash
npx tsx src/main.ts --debug
```

This activates `PersistenceDebugger`, which logs data flow at each layer boundary (save, load, checkpoint, restore). In TUI mode, debug logs are buffered to avoid interfering with Ink rendering and displayed in the debug panel (`Alt+D`).

## Source Files

| File | Purpose |
|------|---------|
| `src/integrations/persistence/sqlite-store.ts` | SQLiteStore class, config, metadata types |
| `src/integrations/persistence/session-repository.ts` | Session CRUD, checkpoints, costs |
| `src/integrations/persistence/goal-repository.ts` | Goal tracking |
| `src/integrations/persistence/worker-repository.ts` | Worker/subagent results |
| `src/integrations/persistence/persistence.ts` | PersistenceDebugger, checkpoint utilities |
| `src/integrations/persistence/session-store.ts` | SessionStore interface |
| `src/agent/session-api.ts` | File change tracking, undo operations |
