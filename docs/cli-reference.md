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

## Swarm CLI (`attocode swarm` / `attoswarm`)

For hybrid swarm operations, prefer `attocode swarm ...` as the user-facing
entrypoint. `attoswarm` is the underlying engine CLI.

### Core Commands

| Command | Purpose |
|---------|---------|
| `attocode swarm start <config> "<goal>"` | Start a new standalone swarm |
| `attocode swarm continue <run-dir> --config <config> "<goal>"` | Start a new child swarm from previous swarm output |
| `attoswarm resume <run-dir>` | Resume the exact same run directory |
| `attocode swarm monitor <run-dir>` | Open the dashboard for an existing run |
| `attocode swarm inspect <run-dir>` | Inspect recent state/events without opening TUI |
| `attoswarm quick "<goal>"` | Run a no-config swarm with defaults |

### Scenario Examples

```bash
# New standalone swarm from inline goal text
attocode swarm start .attocode/swarm.hybrid.yaml "Implement a tiny feature and tests"

# New standalone swarm from a high-level goal file
attocode swarm start .attocode/swarm.hybrid.yaml "$(cat tasks/goal.md)"

# New child swarm (phase 2 / follow-up)
attocode swarm continue .agent/hybrid-swarm/demo-1 --config .attocode/swarm.hybrid.yaml "$(cat tasks/goal-phase2.md)"

# Resume the same run
attoswarm resume .agent/hybrid-swarm/demo-1

# Reattach dashboard only
attocode swarm monitor .agent/hybrid-swarm/demo-1
```

### `--tasks-file` vs Goal Files

Use high-level goal docs like `tasks/goal.md` as the positional goal text:

```bash
attocode swarm start .attocode/swarm.hybrid.yaml "$(cat tasks/goal.md)"
```

Use `--tasks-file` only for structured decomposition files like
`tasks.yaml`, `tasks.yml`, or `tasks.md`:

```bash
attocode swarm start .attocode/swarm.hybrid.yaml --tasks-file tasks/tasks.yaml "Implement the planned work"
```

### Important Behavior

- `--resume` cannot be combined with `--continue-from`.
- If you changed the goal, do not use `resume`; use `start` or `continue`.
- `--preview --no-monitor` automatically falls back to `--dry-run`.
- Closing the dashboard detaches from the run; it does not stop the coordinator.
- Shared-workspace planning failures stop the run as `planning_failed`; they are not converted into a synthetic catch-all task.
- Merge/keep finalization excludes swarm runtime artifacts from `.agent/`.

See [Hybrid Swarm](hybrid-swarm-operations.md) for the full runbook.

### Utility Commands

| Command | Purpose |
|---------|---------|
| `attoswarm quick "<goal>"` | No-config swarm with sensible defaults |
| `attoswarm doctor <config>` | Validate backend binaries and runtime readiness |
| `attoswarm init .` | Interactive config generator |
| `attoswarm inspect <run-dir>` | View run state and recent events |
| `attoswarm postmortem <run-dir>` | Post-mortem analysis of a completed run |
| `attoswarm trace <run-dir>` | Query trace data from a run |
| `attoswarm tui <run-dir>` | Reattach TUI dashboard to a running/completed swarm |

#### Quick Start (No Config)

```bash
# Simplest way to use swarm — no YAML needed
attoswarm quick "Build a REST API for user auth with tests"
attoswarm quick --budget 5 --workers 3 "Fix all failing tests"
attoswarm quick --preview "Refactor the parser module"
attoswarm quick --dry-run "Add caching layer"  # just see the decomposition
```

### Research Campaigns (`attoswarm research`)

Iterative experiment campaigns that evaluate code changes against a numeric metric.

| Command | Purpose |
|---------|---------|
| `attoswarm research start "<goal>" -e "<eval-cmd>"` | Start a new research campaign |
| `attoswarm research leaderboard --run-id <id>` | Show experiment rankings |
| `attoswarm research feed --run-id <id>` | Show findings and steering notes |
| `attoswarm research monitor --run-id <id>` | Snapshot of current campaign state |
| `attoswarm research inject <run-id> "<note>"` | Inject a steering note into a running campaign |
| `attoswarm research promote <run-id> <exp-id>` | Force-accept an experiment |
| `attoswarm research hold <run-id> <exp-id>` | Pause an experiment |
| `attoswarm research resume <run-id> <exp-id>` | Resume a paused experiment |
| `attoswarm research kill <run-id> <exp-id>` | Terminate an experiment |
| `attoswarm research compare <run-id> <exp1> <exp2>` | Compare two experiments |
| `attoswarm research reproduce --run-id <id> ...` | Reproduce a specific experiment |
| `attoswarm research import-patch --run-id <id> ...` | Import a patch into a campaign |
| `attoswarm research cleanup --run-dir <dir>` | Remove experiment worktrees |

#### Research Examples

```bash
# Start a research campaign (eval command extracts the last number from stdout)
attoswarm research start "Improve test pass rate" \
  -e 'uv run python -m pytest tests/ -q --tb=no 2>&1 | tail -1' \
  -t src/mymodule.py --max-experiments 10 --max-cost 5.0

# With mini-swarm mode (full decompose → implement → review per experiment)
attoswarm research start "Improve test pass rate" \
  -e 'uv run python -m pytest tests/ -q --tb=no 2>&1 | tail -1' \
  -t src/mymodule.py --max-experiments 5 --experiment-mode swarm \
  --config .attocode/swarm.hybrid.yaml --monitor

# Check results
attoswarm research leaderboard --run-id abc123 --run-dir .agent/research
attoswarm research feed --run-id abc123 --run-dir .agent/research

# Inject guidance mid-campaign
attoswarm research inject abc123 "Focus on the caching layer, not the parser"

# Clean up worktrees after campaign
attoswarm research cleanup --run-dir .agent/research
```

See [Research Campaigns](research-guide.md) for the full guide.

## Code Intelligence Server

The `code-intel serve` subcommand starts the MCP or HTTP server for code intelligence tools.

```bash
attocode code-intel serve [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--transport <type>` | `stdio` | Transport protocol: `stdio`, `sse`, or `http` |
| `--project <path>` | `.` | Project directory to index |
| `--host <addr>` | `127.0.0.1` | Server bind address (for `sse` and `http` transports) |
| `--port <num>` | `8080` | Server port (for `sse` and `http` transports) |

### Transport Modes

| Transport | Protocol | Use Case |
|-----------|----------|----------|
| `stdio` | MCP over stdin/stdout | AI coding assistants (Claude Code, Cursor, etc.) |
| `sse` | MCP over Server-Sent Events | Remote MCP clients |
| `http` | REST API (FastAPI) | Custom integrations, CI pipelines, multi-project |

```bash
# Default: MCP over stdio
attocode code-intel serve --project /path/to/repo

# HTTP REST API
attocode code-intel serve --transport http --project /path/to/repo

# SSE transport on custom port
attocode code-intel serve --transport sse --host 0.0.0.0 --port 9090
```

The HTTP transport serves interactive API docs at `/docs` (Swagger) and `/redoc`. See [Code Intel HTTP API](code-intel-http-api.md) for the full endpoint reference.

### `setup` — Bootstrap local dev environment

```bash
attocode code-intel setup [options]
```

| Flag | Description |
|------|-------------|
| `--reset` | Wipe Docker volumes and dev state, then re-bootstrap |
| `--skip-deps` | Skip `uv sync` (use if deps already installed) |
| `--project <path>` | Project directory (default: `.`) |

Developer convenience — bootstraps local infrastructure for contributing to attocode. Runs in two phases: infrastructure (Docker, deps, migrations) then API registration (dev user, org, repo). If the API server isn't running, Phase 1 completes and prints instructions. Re-run after starting the API to complete Phase 2.

To connect to an existing server, use `attocode code-intel connect` instead.

## Remote Connection Commands

The `code-intel` subcommand supports connecting a local project to a remote code-intel server for real-time indexing.

### `connect` — Connect to a server

```bash
# Interactive (prompts for email/password, org/repo selection)
attocode code-intel connect --server <url>

# Non-interactive with token (CI, scripts)
attocode code-intel connect --server <url> --token <token> [--repo <id>]

# Non-interactive with credentials
attocode code-intel connect --server <url> --email <email> --password <pass>
```

| Flag | Required | Description |
|------|----------|-------------|
| `--server <url>` | Yes | Server URL (e.g. `https://code.example.com`) |
| `--token <token>` | No | JWT or API key — skips interactive login |
| `--email <email>` | No | Email for register/login (skip prompt) |
| `--password <pass>` | No | Password for register/login (skip prompt) |
| `--org <slug-or-id>` | No | Organization slug or ID (skip selection) |
| `--repo <id>` | No | Repository UUID on the remote server |
| `--name <repo-name>` | No | Override auto-detected repository name |
| `--project <path>` | No | Project directory (default: `.`) |
| `--ci` | No | CI/CD mode: non-interactive, exits non-zero on error |
| `--skip-sync` | No | Skip initial file sync (CI may only register) |
| `--state-file <path>` | No | Alternative state file location for ephemeral CI runners |
| `--force` | No | Clear cached state and re-run |

The primary onboarding flow for service mode. When run without `--token`:

1. Health-checks the server
2. Registers a new account or logs in (interactive or via `--email`/`--password`)
3. Auto-detects or prompts for organization (creates one if none exist)
4. Adds the current project as a repo (or matches an existing one by `local_path`)
5. Writes `.attocode/config.toml` and `.attocode/dev-state.json`
6. Verifies authentication and repo access

When run with `--token`, behaves as before — writes config and verifies.

Saves connection config to `.attocode/config.toml` so that subsequent `notify` and `watch` commands POST to the remote server.

### CI/CD Examples

```bash
# CI pipeline: register + skip sync
attocode code-intel connect --server $SERVER --token $TOKEN --repo $REPO_ID --ci --skip-sync

# CI with ephemeral state
attocode code-intel connect --server $SERVER --token $TOKEN --ci --state-file /tmp/ci-state.json

# Force re-register (clear cached state)
attocode code-intel connect --server $SERVER --token $TOKEN --repo $REPO_ID --force
```

### `test-connection` — Verify remote connectivity

```bash
attocode code-intel test-connection [--project <path>]
```

Runs a series of checks: server reachable, auth valid, repo exists, notify endpoint works, WebSocket connection, and index stats. Reports pass/fail for each.

### `watch` — Watch filesystem and notify remote

```bash
attocode code-intel watch [--project <path>] [--debounce <ms>]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--project <path>` | `.` | Project directory to watch |
| `--debounce <ms>` | `500` | Debounce interval in milliseconds |

Uses `watchfiles` (Rust-based) to detect file changes and batch-POSTs them to the remote server's notify endpoint. Watches common code file extensions (`.py`, `.js`, `.ts`, `.go`, `.rs`, `.java`, etc.). Press `Ctrl+C` to stop.

---

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
| `/spawn [--model <model>] <task>` | Spawn a subagent for a task |

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
