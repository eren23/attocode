---
sidebar_position: 2
title: Commands
---

# Commands

Attocode provides 70+ slash commands organized by category. All commands are handled by a central dispatcher in `src/commands/handler.ts` that works identically in both TUI and REPL modes. Commands are mode-agnostic -- they use a `CommandContext.output` interface so the same logic drives both interfaces.

## General

| Command | Aliases | Description |
|---------|---------|-------------|
| `/help` | `/h`, `/?` | Show the full help reference |
| `/status` | | Show session stats, token usage, goals, and cost |
| `/clear` | | Clear the screen |
| `/reset` | | Reset agent state and clear conversation |
| `/quit` | `/exit`, `/q` | Exit Attocode |

## Agent Modes

| Command | Description |
|---------|-------------|
| `/mode` | Show current mode and list available modes |
| `/mode <name>` | Switch to a mode: `build`, `plan`, `review`, `debug` |
| `/plan` | Toggle plan mode on/off |

## Plan Approval

These commands are active when using plan mode:

| Command | Description |
|---------|-------------|
| `/show-plan` | Display all pending proposed changes |
| `/approve` | Approve and execute all pending changes |
| `/approve <n>` | Approve and execute only the first `n` changes |
| `/reject` | Reject and discard all pending changes |

## Sessions and Persistence

| Command | Description |
|---------|-------------|
| `/save` | Save current session to disk |
| `/load <id>` | Load a previous session by ID |
| `/sessions` | List all saved sessions with timestamps |
| `/resume` | Resume the most recent session (auto-loads last checkpoint) |

## Context Management

| Command | Description |
|---------|-------------|
| `/context` | Show context window usage (tokens used vs. available) |
| `/context breakdown` | Detailed token breakdown by category |
| `/compact` | Summarize and compress context to free tokens |
| `/compact status` | Check whether compaction is recommended |

## Checkpoints and Threads

| Command | Aliases | Description |
|---------|---------|-------------|
| `/checkpoint [label]` | `/cp` | Create a named checkpoint |
| `/checkpoints` | `/cps` | List all checkpoints |
| `/restore <id>` | | Restore conversation to a checkpoint |
| `/rollback [n]` | `/rb` | Rollback `n` steps (default: 1) |
| `/fork <name>` | | Fork conversation into a new thread |
| `/threads` | | List all conversation threads |
| `/switch <id>` | | Switch to a different thread |

## Reasoning Modes

| Command | Description |
|---------|-------------|
| `/react <task>` | Run with ReAct (Reason + Act) reasoning pattern |
| `/team <task>` | Run with multi-agent team coordination |

## Subagents

| Command | Description |
|---------|-------------|
| `/agents` | List all available agents with descriptions |
| `/spawn <agent> <task>` | Spawn a specific agent to handle a task |
| `/find <query>` | Find agents by keyword search |
| `/suggest <task>` | AI-powered agent suggestion for a task |
| `/auto <task>` | Auto-route a task to the best agent |

## MCP Integration

| Command | Description |
|---------|-------------|
| `/mcp` | List MCP servers and connection status |
| `/mcp connect <name>` | Connect to an MCP server |
| `/mcp disconnect <name>` | Disconnect from a server |
| `/mcp tools` | List all available MCP tools |
| `/mcp search <query>` | Search and lazy-load MCP tools |
| `/mcp stats` | Show MCP context usage statistics |

## Budget and Economics

| Command | Description |
|---------|-------------|
| `/budget` | Show token/cost budget and current usage |
| `/extend <type> <n>` | Extend a budget limit (e.g., `/extend tokens 50000`) |

## Permissions and Security

| Command | Description |
|---------|-------------|
| `/grants` | Show active permission grants (always-allow patterns) |
| `/audit` | Show the security audit log |

## Skills and Agents

| Command | Description |
|---------|-------------|
| `/skills` | List all skills with usage hints |
| `/skills new <name>` | Create a new skill scaffold in `.attocode/skills/` |
| `/skills info <name>` | Show detailed information about a skill |
| `/skills enable <name>` | Activate a skill |
| `/skills disable <name>` | Deactivate a skill |
| `/agents` | List all available agents |
| `/agents new <name>` | Create a new agent scaffold in `.attocode/agents/` |
| `/agents info <name>` | Show detailed information about an agent |

## Initialization

| Command | Description |
|---------|-------------|
| `/init` | Initialize the `.attocode/` directory structure in the current project |

## Trace Analysis

| Command | Description |
|---------|-------------|
| `/trace` | Show current session trace summary |
| `/trace --analyze` | Run efficiency analysis on the trace |
| `/trace issues` | List detected inefficiencies |
| `/trace fixes` | List pending improvements |
| `/trace export` | Export trace as JSON for external analysis |

## Capabilities and Debugging

| Command | Description |
|---------|-------------|
| `/powers` | Show all agent capabilities |
| `/powers <type>` | List by type: `tools`, `skills`, `agents`, `mcp`, `commands` |
| `/powers search <q>` | Search capabilities by keyword |
| `/sandbox` | Show available sandbox modes |
| `/shell` | Show PTY shell integration info |
| `/lsp` | Show LSP integration status |
| `/tui` | Show TUI features and capabilities |
| `/theme [name]` | Show or switch the current theme |

## Skill Invocation

Skills marked as `invokable` in their YAML frontmatter register as slash commands automatically. For example, a skill named `review` becomes `/review`. Arguments are parsed from the command line:

```
/review --file src/main.ts --focus security
```

The command handler checks for skill invocations before processing built-in commands, so skill names can shadow built-in commands if needed.
