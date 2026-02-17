---
sidebar_position: 3
title: Modes
---

# Modes

Attocode operates in one of four modes that control tool access, permission levels, and agent behavior. Modes are managed by the `ModeManager` class in `src/modes.ts`.

## Available Modes

### Build Mode (default)

The default mode with full access to all tools.

- **Icon:** Hammer
- **Color:** Green
- All tools available (read, write, bash, MCP, subagents)
- No write approval required
- The agent can create, edit, and delete files and run shell commands autonomously
- Permission checks still apply (approval dialog for dangerous operations)

### Plan Mode

An exploration-first mode where write operations are intercepted and queued for user approval.

- **Icon:** Clipboard
- **Color:** Blue
- All tools are technically available, but writes are intercepted
- Write operations (`write_file`, `edit_file`, `delete_file`, `bash` with side effects) are queued as proposed changes instead of being executed
- Read-only bash commands (`ls`, `cat`, `grep`, `find`, `git status`, etc.) pass through immediately
- MCP tools with write semantics are also intercepted (pattern-matched on action verbs like `create`, `update`, `delete`)
- Subagents inherit plan mode from their parent and queue their writes into the parent's pending plan
- See [Plan Mode](./plan-mode.md) for the full approval workflow

### Review Mode

A read-only mode focused on code review and analysis.

- **Icon:** Magnifying glass
- **Color:** Yellow
- Only read-only tools available: `read_file`, `list_files`, `search_files`, `search_content`, `bash` (read-only subset), `git_log`, `git_diff`, LSP queries
- Cannot modify files or run commands with side effects
- System prompt steers the agent toward code quality, bug detection, security analysis, and best practices

### Debug Mode

A diagnostic mode with access to read operations plus test execution.

- **Icon:** Bug
- **Color:** Magenta
- Read-only tools plus `run_tests` and `execute_code`
- System prompt encourages systematic debugging: reproduce, isolate, fix
- Useful for investigating failing tests or runtime errors without accidentally modifying production code

## Switching Modes

There are several ways to change the active mode:

```
/mode plan        # Switch to plan mode
/mode build       # Switch back to build mode
/plan             # Toggle plan mode on/off
/mode             # Show current mode and all available modes
```

The `ModeManager.cycleMode()` method cycles through all four modes in order: build, plan, review, debug.

## How Mode Filtering Works

The `ModeManager` maintains the set of all registered tool names. When a tool call arrives:

1. Check if the current mode allows the tool (build mode allows everything; other modes use an explicit whitelist).
2. If the tool is not in the mode's `availableTools` list, the call is blocked and a `mode.tool.filtered` event is emitted.
3. In plan mode specifically, allowed tools are further checked: if the tool is a write tool, the call is intercepted and queued rather than blocked.

### Write Tool Detection

The system uses two strategies to identify write operations:

- **Static list:** `write_file`, `edit_file`, `delete_file`, `bash`, `run_tests`, `execute_code`
- **MCP pattern matching:** Tools prefixed with `mcp_` are tested against regex patterns that match action verbs (`create`, `write`, `update`, `delete`, `push`, `commit`, etc.)

For bash commands specifically, a separate analysis determines if the command is read-only. An allowlist of safe commands (`ls`, `cat`, `head`, `tail`, `find`, `grep`, `rg`, `git log`, `git diff`, etc.) passes through. Everything else is intercepted.

## Mode-Aware System Prompts

Each mode injects additional instructions into the system prompt. This guides the LLM's behavior even when tool filtering alone would not be sufficient. For example, review mode's prompt addition tells the agent to focus on code quality and provide actionable feedback, while plan mode's prompt explains the queuing mechanics in detail so the LLM does not attempt to verify changes that have not been applied yet.

## Mode Events

The mode system emits events that other components can listen to:

| Event | Trigger |
|-------|---------|
| `mode.changed` | Mode switches from one to another |
| `mode.tool.filtered` | A tool call was blocked by mode restrictions |
| `mode.write.intercepted` | A write operation was queued in plan mode |

The TUI listens to `mode.changed` events to update the status bar indicator.

## Subagent Mode Inheritance

When a subagent is spawned, it inherits the parent agent's current mode. This means:

- In plan mode, subagent writes are queued into the parent's pending plan
- In review mode, subagents cannot write files
- In build mode, subagents have full access (subject to their own permission checks)

The `spawn_agent` tool itself is not considered a write operation, so subagents can always be spawned regardless of mode. Only the subagent's actual write operations are subject to mode filtering.
