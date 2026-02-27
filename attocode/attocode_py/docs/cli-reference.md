# CLI Reference

## Command-Line Flags

| Flag | Short | Description |
|------|-------|-------------|
| `PROMPT` | | Positional --- run single-turn with this prompt |
| `--model` | `-m` | LLM model to use |
| `--provider` | | LLM provider (`anthropic`, `openrouter`, `openai`) |
| `--permission` | `-p` | Permission mode: `strict`, `interactive`, `auto-safe`, `yolo` |
| `--yolo` | | Shorthand for `--permission yolo` (auto-approve all) |
| `--task` | `-t` | Task description (alternative to positional prompt) |
| `--max-tokens` | | Maximum response tokens |
| `--temperature` | | LLM temperature (0.0--1.0) |
| `--max-iterations` | `-i` | Maximum agent iterations |
| `--timeout` | | Request timeout in seconds |
| `--resume` | | Resume a previous session by ID |
| `--tui` / `--no-tui` | | Force TUI or plain REPL mode |
| `--theme` | | TUI theme (`dark`, `light`, `auto`) |
| `--trace` | | Save JSONL execution traces to `.attocode/traces/` |
| `--swarm` | | Enable swarm mode (optional: path to config YAML) |
| `--swarm-resume` | | Resume a previous swarm session by ID |
| `--hybrid` | | Route swarm execution to standalone `attoswarm` orchestrator |
| `--paid-only` | | Only use paid models (no free tier) |
| `--debug` | | Enable debug logging |
| `--non-interactive` | | Run in non-interactive mode |
| `--version` | | Show version and exit |

## Examples

```bash
# Interactive TUI (default)
attocode

# Single-turn with a prompt
attocode "Explain the main function in cli.py"

# Use a specific model
attocode -m claude-sonnet-4-20250514 "Fix the bug in parser.py"

# Auto-approve all tool calls
attocode --yolo "Add tests for the auth module"

# Swarm mode with config
attocode --swarm .attocode/swarm.yaml "Build a REST API"

# Resume a previous session
attocode --resume abc123

# Non-interactive single-turn
attocode --non-interactive "List all TODO comments"
```

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+C` | Exit (press twice to force quit during execution) |
| `Ctrl+L` | Clear message log |
| `Ctrl+P` | Open command palette / help |
| `Ctrl+Y` | Copy last agent response to clipboard |
| `Ctrl+T` | Toggle tool call details |
| `Ctrl+W` | Toggle swarm panel |
| `ESC` | Cancel current operation |

## Slash Commands

Type `/help` in the TUI for the full list. The most commonly used commands are organized by category below.

### Core

| Command | Description |
|---------|-------------|
| `/help` | Show all available commands |
| `/status` | Show agent status and metrics |
| `/budget` | Show budget usage details |
| `/extend [amount]` | Request budget extension |
| `/model [name]` | Show or switch the LLM model |
| `/compact` | Force context compaction |
| `/save` | Save current session checkpoint |
| `/clear` | Clear message log |
| `/quit` | Exit the application |

### Session Persistence

| Command | Description |
|---------|-------------|
| `/sessions` | List recent sessions |
| `/load <id>` | Load a previous session |
| `/resume [id]` | Resume most recent (or specific) session |
| `/checkpoint` | Create a named checkpoint |
| `/checkpoints [id]` | List checkpoints for a session |
| `/reset` | Reset conversation (clear messages & metrics) |
| `/handoff [fmt]` | Export session handoff summary |

### Goals

| Command | Description |
|---------|-------------|
| `/goals` | List current goals |
| `/goals add "..."` | Add a new goal |
| `/goals done <n>` | Mark goal N as complete |
| `/goals all` | Show all goals including completed |

### Debug & Audit

| Command | Description |
|---------|-------------|
| `/audit` | Show recent tool call audit log |
| `/grants` | Show remembered permission grants |
| `/trace [subcmd]` | Trace inspection (summary/analyze/issues/export) |
| `/undo [path]` | Undo last file change (or specific file) |
| `/diff` | Show file changes made in this session |
| `/context [breakdown]` | Show context window token details |

### Skills & Agents

| Command | Description |
|---------|-------------|
| `/skills` | List available skills |
| `/skills info <name>` | Show detailed skill info |
| `/skills new <name>` | Create a new skill scaffold |
| `/agents` | List available agents |
| `/agents info <name>` | Show detailed agent info |
| `/spawn <task>` | Spawn a subagent for a task |

### MCP (Model Context Protocol)

| Command | Description |
|---------|-------------|
| `/mcp` | List connected MCP servers |
| `/mcp tools` | Show tools from MCP servers |
| `/mcp connect <cmd>` | Connect a new MCP server |
| `/mcp disconnect <name>` | Disconnect an MCP server |

### Configuration

| Command | Description |
|---------|-------------|
| `/init` | Initialize `.attocode/` directory structure |
| `/config` | Show current config (provider, model, key) |
| `/config provider <name>` | Switch provider (persists globally) |
| `/config model <name>` | Switch model (persists globally) |
| `/config api-key` | Re-enter API key (TUI dialog) |
| `/setup` | Run the first-time setup wizard |
| `/theme [name]` | Show or switch theme |

## Permission Modes

| Mode | Behavior |
|------|----------|
| `strict` | Prompt for every tool call |
| `interactive` | Auto-allow safe tools (read, glob, grep), prompt for writes |
| `auto-safe` | Auto-allow safe tools, auto-approve writes in project dir |
| `yolo` | Auto-approve everything (use with caution) |

Safe tools that are auto-allowed in `interactive` and `auto-safe` modes: `read_file`, `glob`, `grep`, `list_directory`, `codebase_overview`.
