# Attocode

Production AI coding agent built in Python. Features a Textual-based TUI, multi-agent swarm orchestration, intelligent budget management, and a safety sandbox system.

**[Documentation](https://eren23.github.io/attocode/)** | **[PyPI](https://pypi.org/project/attocode/)**

## Features

- **Interactive TUI** --- Rich terminal interface with live tool status, streaming, plan/task panels, and keyboard shortcuts (powered by [Textual](https://textual.textualize.io/))
- **Single-turn mode** --- Run one-shot prompts from the command line for scripting and automation
- **Swarm mode** --- Multi-agent orchestration with a standalone Python hybrid coordinator (`attoswarm`) and heterogeneous backends
- **Budget management** --- Token-based economics with doom-loop detection, phase tracking, and budget extension dialogs
- **Safety sandbox** --- Platform-aware command isolation (Seatbelt on macOS, Landlock on Linux, Docker, or allowlist fallback)
- **Session persistence** --- SQLite-backed sessions, checkpoints, goals, audit logs, and permission grants that persist across prompts
- **MCP support** --- Connect external tools via the Model Context Protocol
- **Multi-provider** --- Anthropic, OpenRouter, OpenAI, Azure, and ZAI adapters
- **Research campaigns** --- Multi-experiment research workflows with dedicated worktrees, hypothesis tracking, and persistent campaign state
- **Skills & agents** --- Extensible skill and agent system with project-level and user-level customization

## Requirements

- Python 3.12+
- An API key for at least one LLM provider (e.g. `ANTHROPIC_API_KEY`)

## Installation

### Development install (recommended)

```bash
git clone https://github.com/eren23/attocode.git
cd attocode

uv sync --all-extras          # creates .venv, installs everything
```

### Global install (recommended for end users)

```bash
cd attocode
uv tool install --force . --with anthropic --with openai
```

This installs three commands globally: `attocode`, `attocodepy`, and `attoswarm`.

### Optional provider extras

```bash
uv sync --extra anthropic     # Anthropic SDK (recommended)
uv sync --extra openai        # OpenAI SDK
uv sync --extra tree-sitter   # AST parsing for code analysis
uv sync --extra semantic      # Semantic search embeddings (sentence-transformers)
uv sync --extra dev           # Development tools (pytest, mypy, ruff)
uv sync --all-extras          # All of the above
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

**Hybrid swarm mode** --- process-boundary orchestration via `attoswarm`:

```bash
attocode swarm start .attocode/swarm.hybrid.yaml "Build a REST API for a todo app with tests"
```

**Research campaign** --- run structured multi-experiment research:

```bash
attocode research start "Evaluate caching strategies for the query layer"
```

## Swarm Command Chooser

Use these commands based on the scenario:

```bash
# New standalone swarm
attocode swarm start .attocode/swarm.hybrid.yaml "$(cat tasks/goal.md)"

# Follow-up / phase-2 swarm based on a previous swarm result
attocode swarm continue .agent/hybrid-swarm/demo-1 --config .attocode/swarm.hybrid.yaml "$(cat tasks/goal-phase2.md)"

# Resume the exact same run
attoswarm resume .agent/hybrid-swarm/demo-1

# Reattach the dashboard
attocode swarm monitor .agent/hybrid-swarm/demo-1
```

Important distinction:

- `start` = new standalone run
- `continue` = new child run from previous swarm output
- `resume` = same run dir, same persisted goal

Use `--tasks-file` only with structured decomposition files such as
`tasks.yaml` or `tasks.md`, not with high-level goal docs like `goal.md`.

## CLI Reference

| Flag | Short | Description |
|------|-------|-------------|
| `PROMPT` | | Positional --- run single-turn with this prompt |
| `--model` | `-m` | LLM model to use |
| `--provider` | | LLM provider (`anthropic`, `openrouter`, `openai`, `azure`, `zai`) |
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
| `--record` | | Record session for visual replay |
| `--debug` | | Enable debug logging |
| `--non-interactive` | | Run in non-interactive mode |
| `--version` | | Show version and exit |

## Architecture

```
src/attocode/
  types/           Type definitions (messages, agent, config)
  agent/           Core agent orchestrator and builders
  core/            Execution loop, subagent spawner, tool executor
  providers/       LLM provider adapters (Anthropic, OpenRouter, OpenAI, Azure, ZAI)
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
    swarm/           Multi-agent orchestrator (20 modules, 10k+ lines)
    streaming/       Streaming and PTY shell
    lsp/             Language server protocol integration
  tricks/          Context engineering techniques
  tracing/         Trace collector, event types, cache boundary tracking
  tui/             Textual TUI (app, widgets, dialogs, bridges, styles)
```

## Lessons

The [`lessons/`](lessons/) directory contains a **26-lesson course** teaching you to build production-ready AI coding agents from scratch. The lessons use TypeScript and cover everything from the core agent loop to multi-agent coordination.

```bash
cd lessons
npm install
npm run lesson:1
```

The lessons are also available on the [documentation site](https://eren23.github.io/attocode/lessons/).

## Legacy TypeScript Version

The [`legacy/`](legacy/) directory contains the original TypeScript implementation of Attocode (v0.2.6). The Python version is the active implementation and has surpassed the TypeScript version in features. See [`legacy/PORTING_REPORT.md`](legacy/PORTING_REPORT.md) for a detailed feature comparison.

## Testing

```bash
uv run pytest tests/unit/ -x -q          # Quick unit tests
uv run pytest tests/ --cov=src/attocode  # With coverage
uv run ruff check src/ tests/            # Linting
```

## Documentation

Full documentation is available at **[eren23.github.io/attocode](https://eren23.github.io/attocode/)**.

- [Architecture](docs/ARCHITECTURE.md) --- Module relationships and data flow
- [Providers](docs/PROVIDERS.md) --- LLM provider adapter reference
- [Sandbox](docs/SANDBOX.md) --- Platform-aware command isolation
- [Budget](docs/BUDGET.md) --- Token economics and doom-loop detection
- [MCP](docs/MCP.md) --- Model Context Protocol integration
- [Swarm Guide](docs/swarm-guide.md) --- Multi-agent orchestration
- [Hybrid Swarm](docs/hybrid-swarm-operations.md) --- Start vs continue vs resume, monitor/detach flows, and runbook
- [Research Campaigns](docs/research-guide.md) --- Multi-experiment research workflows with dedicated worktrees
- [Contributing](CONTRIBUTING.md) --- How to contribute

## License

See [LICENSE](LICENSE) for details.
