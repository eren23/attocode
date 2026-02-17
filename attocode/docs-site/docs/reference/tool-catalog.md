---
sidebar_position: 3
title: "Tool Catalog"
---

# Tool Catalog

All built-in tools available to the agent. Tools are registered in `ToolRegistry` and described to the LLM as JSON Schema.

## File Operations

### read_file

Reads the contents of a file.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Path to the file |

**Danger level:** `safe`
**Returns:** File content with metadata (`lines`, `bytes`).

### write_file

Writes content to a file, creating it if necessary.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Path to write |
| `content` | string | Yes | File content |

**Danger level:** `moderate`
**Returns:** Confirmation with unified diff of changes.

### edit_file

Performs a targeted string replacement in a file. The `old_string` must match exactly one location in the file.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Path to edit |
| `old_string` | string | Yes | Text to find (must be unique) |
| `new_string` | string | Yes | Replacement text |

**Danger level:** `moderate`
**Returns:** Confirmation with unified diff. Fails if `old_string` is not found or matches multiple locations.

### list_files

Lists files and directories at a path.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Directory to list |
| `recursive` | boolean | No | List recursively (default: false) |

**Danger level:** `safe`
**Returns:** Formatted listing with emoji indicators. Caps at 500 entries.

## Search Tools

### grep

Searches file contents with regex patterns.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `pattern` | string | Yes | Regex pattern |
| `path` | string | No | Directory to search |
| `recursive` | boolean | No | Search recursively |

**Danger level:** `safe`
**Returns:** Matching lines with file paths and line numbers.

### glob

Finds files matching a glob pattern.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `pattern` | string | Yes | Glob pattern (e.g., `**/*.ts`) |
| `path` | string | No | Base directory |

**Danger level:** `safe`
**Returns:** List of matching file paths.

## Shell

### bash

Executes a bash command.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `command` | string | Yes | Command to execute |
| `cwd` | string | No | Working directory |
| `timeout` | number | No | Timeout in ms (default: 30000) |

**Danger level:** Dynamic -- classified per-command:
- `safe`: `ls`, `cat`, `echo`, `pwd`, `which`
- `moderate`: `npm install`, `git status`, `mkdir`
- `dangerous`: `rm -rf`, `chmod`, `sudo`

**Returns:** `{ output, exitCode }`. Output capped at 100KB. Timeout auto-corrects values under 300 (treated as seconds, multiplied by 1000).

## Undo System

### undo_file_change

Reverts the last change to a specific file.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | File to revert |

**Danger level:** `moderate`
**Returns:** Confirmation with restored content.

### show_file_history

Shows the change history for a file in the current session.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | File to inspect |

**Danger level:** `safe`
**Returns:** Chronological list of changes with timestamps and diffs.

### show_session_changes

Shows all file changes made during the current session.

**Danger level:** `safe`
**Returns:** Summary of all modified files with change counts and types.

## Task Management

### task_create

Creates a new task for tracking work.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `subject` | string | Yes | Task title |
| `description` | string | No | Task details |
| `activeForm` | boolean | No | Set as active task |

### task_update

Updates an existing task's status or metadata.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `taskId` | string | Yes | Task ID |
| `status` | string | No | New status |
| `dependencies` | string[] | No | Task dependencies |
| `metadata` | object | No | Additional metadata |

### task_get / task_list

Retrieve a specific task by ID, or list all tasks with summaries.

## Agent Spawning

### spawn_agent

Spawns a subagent for a delegated task.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `type` | string | Yes | Agent type (e.g., `researcher`) |
| `task` | string | Yes | Task description |
| `constraints` | object | No | Budget, timeout overrides |

**Returns:** `SpawnResult` with `success`, `output`, `metrics`, and optional `structured` closure report.

## MCP Tools

MCP (Model Context Protocol) tools are loaded dynamically from configured MCP servers at runtime. They appear alongside built-in tools in the registry. Use `/tools` to list all available tools including MCP tools.
