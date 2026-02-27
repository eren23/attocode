# Attocode

Production AI coding agent built in Python. Features a Textual-based TUI, multi-agent swarm orchestration, intelligent budget management, and a safety sandbox system.

## Features

- **Interactive TUI** --- Rich terminal interface with live tool status, streaming, plan/task panels, and keyboard shortcuts (powered by [Textual](https://textual.textualize.io/))
- **Single-turn mode** --- Run one-shot prompts from the command line for scripting and automation
- **Swarm mode** --- Multi-agent orchestration with a standalone Python hybrid coordinator (`attoswarm`) and heterogeneous backends
- **Budget management** --- Token-based economics with doom-loop detection, phase tracking, and budget extension dialogs
- **Safety sandbox** --- Platform-aware command isolation (Seatbelt on macOS, Landlock on Linux, Docker, or allowlist fallback)
- **Session persistence** --- SQLite-backed sessions, checkpoints, goals, audit logs, and permission grants that persist across prompts
- **MCP support** --- Connect external tools via the Model Context Protocol
- **Multi-provider** --- Anthropic, OpenRouter, and OpenAI adapters
- **Skills & agents** --- Extensible skill and agent system with project-level and user-level customization

## Requirements

- Python 3.12+
- An API key for at least one LLM provider (e.g. `ANTHROPIC_API_KEY`)

## Installation

### Development install

```bash
git clone https://github.com/eren23/attocode.git
cd attocode/attocode_py

python -m venv .venv
source .venv/bin/activate   # or .venv/Scripts/activate on Windows

pip install -e ".[dev]"
```

### Global install with pipx (recommended for end users)

```bash
# From a local checkout
pipx install ./attocode_py

# Or directly from git
pipx install "attocode @ git+https://github.com/eren23/attocode.git#subdirectory=attocode_py"
```

### Global install with pip (user-site)

```bash
pip install --user ./attocode_py
```

### Optional provider extras

```bash
pip install -e ".[anthropic]"    # Anthropic SDK (recommended)
pip install -e ".[openai]"      # OpenAI SDK
pip install -e ".[tree-sitter]"  # AST parsing for code analysis
pip install -e ".[dev]"         # Development tools (pytest, mypy, ruff)
```

Set your API key:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
# Or for OpenRouter:
export OPENROUTER_API_KEY="sk-or-..."
```

## Quick Start

**Single-turn** --- ask a question and get one response:

```bash
attocode "List all Python files in this project"
```

**Interactive TUI** --- launch the full terminal interface:

```bash
attocode
```

**Swarm mode** --- decompose a task across multiple parallel agents:

```bash
attocode --swarm "Build a REST API for a todo app with tests"
```

**Hybrid swarm mode (recommended)** --- process-boundary orchestration via `attoswarm`:

```bash
attocode --swarm .attocode/swarm.yaml --hybrid "Build a REST API for a todo app with tests"
# or directly
attoswarm run .attocode/swarm.yaml "Build a REST API for a todo app with tests"
```

Run the standalone dashboard for a run directory:

```bash
attoswarm tui .agent/hybrid-swarm
```

## Running from Anywhere

The `attocode` command always operates on **the current working directory** --- it reads `.attocode/config.json` from where you run it, so the install location doesn't matter.

**pipx (recommended):** Already on `PATH` after `pipx install` --- works from any directory with no extra setup.

**Activate the venv:**

```bash
source /absolute/path/to/attocode_py/.venv/bin/activate
attocode "your prompt"
```

**Shell alias:** Add to `~/.bashrc`, `~/.zshrc`, or `~/.config/fish/config.fish`:

```bash
# bash / zsh
alias attocode="/absolute/path/to/attocode_py/.venv/bin/attocode"

# fish
alias attocode /absolute/path/to/attocode_py/.venv/bin/attocode
```

**Symlink:**

```bash
ln -s /absolute/path/to/attocode_py/.venv/bin/attocode ~/.local/bin/attocode
```

## CLI Reference

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

The TUI provides ~48 slash commands. Type `/help` in the TUI to see the full list. Here are the most commonly used:

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

Session data (goals, audit logs, permissions, checkpoints) is stored in SQLite and persists across prompts within the same TUI session.

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

Track high-level objectives across prompts:

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

## Swarm Mode

Swarm mode decomposes complex tasks into subtasks, schedules them in dependency-aware waves, and dispatches them to parallel worker agents. In hybrid mode (`--hybrid`), orchestration is handled by the standalone Python `attoswarm` package over a filesystem protocol, with workers running as subprocesses.

See [docs/swarm-guide.md](docs/swarm-guide.md) for a detailed walkthrough with examples.
For day-to-day hybrid execution and observability, see [docs/hybrid-swarm-operations.md](docs/hybrid-swarm-operations.md).

For a complete example project using hybrid swarm orchestration, see [attocodepy_swarmtester_3](https://github.com/eren23/attocodepy_swarmtester_3).

Quick setup:

```bash
# Copy the example config
cp .attocode/swarm.yaml.example .attocode/swarm.yaml

# Run swarm mode
attocode --swarm "Build a REST API for a todo app with tests"
```

## Configuration

Attocode reads configuration from a hierarchy of locations:

```
~/.attocode/              # User-level (global defaults)
  config.json
  rules.md
  skills/
  agents/

.attocode/                # Project-level (overrides user-level)
  config.json
  swarm.yaml
  rules.md
  skills/
  agents/
```

**Priority:** built-in defaults < `~/.attocode/` < `.attocode/`

### Key config options (`config.json`)

```json
{
  "model": "claude-sonnet-4-20250514",
  "provider": "anthropic",
  "max_tokens": 8192,
  "temperature": 0.0,
  "max_iterations": 25,
  "sandbox": { "mode": "auto" }
}
```

### Swarm config (`swarm.yaml`)

See [`.attocode/swarm.yaml.example`](.attocode/swarm.yaml.example) for a fully annotated template.

## Architecture

```
src/attocode/
  types/           Type definitions (messages, agent, config)
  agent/           Core agent orchestrator and builders
  core/            Execution loop, subagent spawner, tool executor
  providers/       LLM provider adapters (Anthropic, OpenRouter, OpenAI)
  tools/           Built-in tool implementations (file ops, bash, search)
  integrations/    Feature modules organized by domain:
    budget/          Economics, budget pools, doom-loop detection
    context/         Context engineering, compaction, codebase analysis
    safety/          Policy engine, sandbox (seatbelt/landlock/docker)
    persistence/     SQLite session store, checkpoints, goals
    agents/          Shared blackboard, delegation protocol
    tasks/           Task decomposition, planning, verification
    skills/          Skill loading and execution
    mcp/             MCP client and tool integration
    quality/         Learning store, self-improvement, health checks
    utilities/       Hooks, rules, routing, logging, retry
    swarm/           Multi-agent orchestrator (18 modules, 10k+ lines)
    streaming/       Streaming and PTY shell
    lsp/             Language server protocol integration
  tricks/          Context engineering techniques
  tracing/         Trace collector, event types, cache boundary tracking
  tui/             Textual TUI (app, widgets, dialogs, bridges, styles)
```

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=attocode --cov-report=term-missing

# Run a specific test file
pytest tests/unit/tui/test_swarm_panel.py -v

# Linting and type checking
ruff check src/ tests/
mypy src/
```

## Project Stats

| Metric | Count |
|--------|-------|
| Source files | 318 |
| Source lines | ~75,000 |
| Test files | 116 |
| Test lines | ~29,300 |
| Total tests | 2,778+ |

## TODO

### Incremental codebase context updates

The codebase context system (`integrations/context/`) currently does a full `os.walk` + re-parse on every `discover_files()` call and caches `_repo_map` / `_dep_graph` with no invalidation. When the agent edits or creates files mid-session, the cached data goes stale silently — symbols, dep graph, and importance scores all reflect the state at discovery time.

What's needed:

- **Hook into tool results.** After `write_file`, `edit_file`, or `bash` (when it creates/deletes files), mark affected entries in `_files` as dirty instead of re-walking the entire tree.
- **Mtime-based staleness.** Store `mtime` per `FileInfo`. On the next `get_repo_map()` / `select_context()`, stat only dirty files and re-parse them. The `CodeAnalyzer` content-hash cache already handles re-analysis correctly — the gap is that nothing triggers it.
- **Incremental dep graph.** When a file changes, remove its old edges from `DependencyGraph.forward`/`.reverse`, re-parse its imports, and add new edges. No need to rebuild the entire graph.
- **Invalidate `_repo_map` on any file mutation.** The tree text and language stats are cheap to regenerate, so just nulling `_repo_map` is fine.
- **New/deleted file handling.** `discover_files()` is the only way to pick up new files or notice deletions. A lightweight incremental scan (check parent dirs of changed paths) would avoid full re-walks.

The `CodeAnalyzer._cache` (djb2 content hash) already does per-file invalidation correctly — the problem is one layer up in `CodebaseContextManager` which has no change-awareness at all.

## Documentation

- [Architecture](docs/ARCHITECTURE.md) --- Module relationships and data flow
- [Providers](docs/PROVIDERS.md) --- LLM provider adapter reference
- [Sandbox](docs/SANDBOX.md) --- Platform-aware command isolation
- [Budget](docs/BUDGET.md) --- Token economics and doom-loop detection
- [MCP](docs/MCP.md) --- Model Context Protocol integration
- [Testing](docs/TESTING.md) --- Test patterns and conventions
- [Contributing](CONTRIBUTING.md) --- How to contribute

## License

See [LICENSE](LICENSE) for details.
