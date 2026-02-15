# Attocode

A production-ready AI coding agent for your terminal.

## Features

- **Multi-provider support** - Anthropic, OpenRouter, OpenAI
- **Memory system** - Remembers context across sessions
- **Planning & Reflection** - Breaks down complex tasks
- **File change tracking** - Full undo capability
- **Context compaction** - Never runs out of context in long sessions
- **Session persistence** - Resume where you left off
- **Sandbox execution** - Safe command execution
- **MCP integration** - Connect external tools

## Quick Start

### 1. Install

**From npm (recommended):**

```bash
npm install -g attocode
```

**Or build from source:**

```bash
git clone https://github.com/eren23/attocode.git
cd attocode
npm install
npm run build
npm link
```

Now `attocode` is available everywhere in your terminal.

### 2. Set up your API key

```bash
# Option A: Anthropic (recommended)
export ANTHROPIC_API_KEY="sk-ant-..."

# Option B: OpenRouter (100+ models)
export OPENROUTER_API_KEY="sk-or-..."

# Option C: OpenAI
export OPENAI_API_KEY="sk-..."
```

Add to your `~/.bashrc` or `~/.zshrc` to persist.

### 3. Run the setup wizard

```bash
attocode init
```

This creates your config at `~/.config/attocode/config.json`.

### 4. Start coding

```bash
attocode
```

## Usage

### Interactive mode (default)

```bash
attocode
```

### Single task

```bash
attocode "List all TypeScript files and explain the project structure"
```

### With specific model

```bash
attocode -m anthropic/claude-opus-4 "Review this code for security issues"
```

## Commands

Once in the REPL:

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/status` | Show session metrics |
| `/checkpoint` | Save current state |
| `/restore` | Restore a checkpoint |
| `/undo` | Undo last file change |
| `/history` | Show file change history |
| `/compact` | Compact context (for long sessions) |
| `/save` | Save session |
| `/load` | Load a previous session |
| `/exit` | Exit attocode |

## Skills & Agents

Extend attocode with custom skills and agents:

```bash
# Initialize project directory
/init

# Create a custom skill
/skills new code-review

# Create a custom agent
/agents new domain-expert

# List available skills/agents
/skills
/agents

# Spawn an agent
/spawn researcher "Find all API endpoints"
```

**Directory structure:**
```
.attocode/              # Project-level
├── skills/             # Custom skills
└── agents/             # Custom agents

~/.attocode/            # User-level (shared across projects)
├── skills/
└── agents/
```

See [docs/skills-and-agents-guide.md](docs/skills-and-agents-guide.md) for the complete guide.

## MCP Servers

Connect external tools via the [Model Context Protocol](https://modelcontextprotocol.io/).

### Configuration Files

MCP servers are configured in JSON files. Attocode loads configs in order (later overrides earlier):

| Location | Scope | Priority |
|----------|-------|----------|
| `~/.config/attocode/mcp.json` | User-level (all projects) | Lower |
| `.mcp.json` | Project-level (this project) | Higher |

### Setup

**1. Create a config file:**

```bash
# User-level (shared across all projects)
mkdir -p ~/.config/attocode
touch ~/.config/attocode/mcp.json

# Or project-level (this project only)
touch .mcp.json
```

**2. Add server configurations:**

```json
{
  "servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@anthropic/mcp-server-filesystem", "/path/to/allowed/dir"]
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@anthropic/mcp-server-github"],
      "env": {
        "GITHUB_TOKEN": "${GITHUB_TOKEN}"
      }
    },
    "sqlite": {
      "command": "npx",
      "args": ["-y", "@anthropic/mcp-server-sqlite", "~/database.db"]
    }
  }
}
```

**3. Verify with commands:**

```bash
/mcp              # List connected servers
/mcp tools        # List available MCP tools
/mcp search <q>   # Search and load tools
```

### Environment Variables

Use `${VAR_NAME}` syntax to reference environment variables in configs:

```json
{
  "servers": {
    "postgres": {
      "command": "npx",
      "args": ["-y", "@anthropic/mcp-server-postgres"],
      "env": {
        "DATABASE_URL": "${DATABASE_URL}"
      }
    }
  }
}
```

### Popular MCP Servers

| Server | Package | Description |
|--------|---------|-------------|
| Filesystem | `@anthropic/mcp-server-filesystem` | Read/write files in allowed directories |
| GitHub | `@anthropic/mcp-server-github` | GitHub API integration |
| SQLite | `@anthropic/mcp-server-sqlite` | Query SQLite databases |
| Postgres | `@anthropic/mcp-server-postgres` | Query PostgreSQL databases |
| Brave Search | `@anthropic/mcp-server-brave-search` | Web search via Brave |
| Puppeteer | `@anthropic/mcp-server-puppeteer` | Browser automation |

Find more at [MCP Servers Directory](https://github.com/modelcontextprotocol/servers).

## Configuration

Config file: `~/.config/attocode/config.json`

```json
{
  "providers": {
    "default": "openrouter"
  },
  "model": "anthropic/claude-sonnet-4",
  "maxIterations": 50,
  "timeout": 300000,
  "memory": { "enabled": true },
  "planning": { "enabled": true },
  "sandbox": { "enabled": true },
  "resilience": {
    "incompleteActionAutoLoop": true,
    "maxIncompleteAutoLoops": 2,
    "autoLoopPromptStyle": "strict",
    "taskLeaseStaleMs": 300000
  },
  "hooks": {
    "enabled": true,
    "shell": {
      "enabled": false,
      "defaultTimeoutMs": 5000,
      "envAllowlist": ["SLACK_WEBHOOK_URL"],
      "commands": [
        {
          "id": "notify-on-complete",
          "event": "run.after",
          "command": "node",
          "args": ["./scripts/hook-notify.js"],
          "timeoutMs": 3000
        }
      ]
    }
  }
}
```

### Behavior Tuning (Incomplete Recovery)

These settings control what happens when the model replies with "I'll do X" but has not executed the action yet:

- `resilience.incompleteActionAutoLoop`: Automatically retry incomplete runs in TUI.
- `resilience.maxIncompleteAutoLoops`: Maximum retry runs before terminal `[INCOMPLETE]`.
- `resilience.autoLoopPromptStyle`: Guidance style for retries (`strict` or `concise`).
- `resilience.taskLeaseStaleMs`: Requeue stale `in_progress` tasks to `pending` at run boundaries.

For swarm runs, `resilience.dispatchLeaseStaleMs` in swarm config controls stale `dispatched` task recovery back to `ready`.

### Branch Change Highlights

- Added bounded incomplete-action recovery (`future_intent` / `incomplete_action`) in TUI.
- Added run-boundary stale task lease recovery in core task manager.
- Added stale dispatched-task recovery in swarm queue/orchestrator.
- Added lifecycle shell-hook coverage for completion/recovery/run phases.

### Lifecycle Hooks (Trigger External Automations)

You can trigger scripts on lifecycle events (for notifications, logging, CI checks, policy alerts).

Common lifecycle events:
- `run.before`, `run.after`
- `iteration.before`, `iteration.after`
- `completion.before`, `completion.after`
- `recovery.before`, `recovery.after`
- `llm.before`, `llm.after`
- `tool.before`, `tool.after`

Shell hooks receive JSON on stdin:

```json
{
  "event": "run.after",
  "payload": { "...": "event-specific data" }
}
```

## File Locations (XDG compliant)

| Purpose | Location |
|---------|----------|
| Config | `~/.config/attocode/config.json` |
| Sessions DB | `~/.local/share/attocode/sessions.db` |
| History | `~/.local/state/attocode/history` |
| Cache | `~/.cache/attocode/` |

## CLI Options

```
attocode [COMMAND] [OPTIONS] [TASK]

Commands:
  init                    Interactive setup wizard

Options:
  -h, --help              Show help
  -v, --version           Show version
  -m, --model MODEL       Model to use (e.g., anthropic/claude-sonnet-4)
  -p, --permission MODE   Permission mode: strict, interactive, auto-safe, yolo
  -i, --max-iterations N  Max agent iterations (default: 50)
  -t, --task TASK         Run single task non-interactively
  --tui                   Force TUI mode
  --legacy                Force legacy readline mode
  --trace                 Enable trace capture to .traces/
  --debug                 Enable debug logging
  --swarm [CONFIG]        Enable swarm mode (optional config path)
  --swarm-resume ID       Resume a previous swarm session
  --paid-only             Use only paid models in swarm auto-detection
  --theme THEME           UI theme: dark, light, auto
  --yolo                  Shorthand for --permission yolo
```

## Tracing & Performance Analysis

Attocode includes comprehensive tracing capabilities for understanding agent behavior, debugging issues, and optimizing performance.

### Quick Start

```bash
# Enable tracing when starting attocode
attocode --trace

# View trace summary after running commands
/trace

# Analyze efficiency issues
/trace --analyze
```

### Trace Commands

| Command | Description |
|---------|-------------|
| `/trace` | Show current session trace summary |
| `/trace --analyze` | Run efficiency analysis on trace |
| `/trace issues` | List detected inefficiencies |
| `/trace fixes` | List pending improvements |
| `/trace export [file]` | Export trace JSON for LLM analysis |

### Trace Viewer CLI

For detailed offline analysis, use the trace-viewer tool:

```bash
# Navigate to the trace viewer
cd tools/trace-viewer

# Build (first time)
npm install && npm run build

# View trace summary
npx tsx bin/trace-viewer.ts .traces/

# Timeline view
npx tsx bin/trace-viewer.ts .traces/ --view timeline

# Token flow analysis
npx tsx bin/trace-viewer.ts .traces/ --view tokens

# Generate HTML report
npx tsx bin/trace-viewer.ts .traces/ --output html

# Compare two sessions
npx tsx bin/trace-viewer.ts compare <baseline.jsonl> <comparison.jsonl>
```

See [docs/tracing-guide.md](docs/tracing-guide.md) for the complete tracing documentation.

## Architecture

Attocode follows a modular architecture:

```
┌─────────────────────────────────────────────────────┐
│                    Entry Point                       │
│                 src/main.ts (CLI + TUI)              │
└─────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│                  ProductionAgent                     │
│  ┌─────────────┐ ┌─────────────┐ ┌───────────────┐  │
│  │   Hooks     │ │   Memory    │ │   Planning    │  │
│  └─────────────┘ └─────────────┘ └───────────────┘  │
│  ┌─────────────┐ ┌─────────────┐ ┌───────────────┐  │
│  │   Safety    │ │  Economics  │ │Context Engine │  │
│  └─────────────┘ └─────────────┘ └───────────────┘  │
└─────────────────────────────────────────────────────┘
        │                  │                  │
        ▼                  ▼                  ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ LLM Providers│   │ Tool Registry│   │ Integrations │
│ - Anthropic  │   │ - File Ops   │   │ - Sessions   │
│ - OpenRouter │   │ - Bash       │   │ - MCP Client │
│ - OpenAI     │   │ - Search     │   │ - Compaction │
└──────────────┘   └──────────────┘   └──────────────┘
```

See [docs/architecture.md](docs/architecture.md) for the complete architecture documentation.

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/architecture.md) | System design and data flow |
| [API Reference](docs/api-reference.md) | Core interfaces and types |
| [Extending](docs/extending.md) | Adding providers, tools, integrations |
| [Skills & Agents](docs/skills-and-agents-guide.md) | Custom skills and agents |
| [Tracing](docs/tracing-guide.md) | Performance analysis |
| [Modes Guide](docs/modes-guide.md) | TUI, REPL, plan, subagent, and swarm modes |
| [Swarm Mode](docs/swarm/README.md) | Multi-model parallel orchestration |
| [Troubleshooting](docs/troubleshooting.md) | Common issues and solutions |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## Uninstall

```bash
# If installed from npm
npm uninstall -g attocode

# If installed from source
npm unlink -g attocode

# Remove config and data (optional)
rm -rf ~/.config/attocode
rm -rf ~/.local/share/attocode
rm -rf ~/.local/state/attocode
rm -rf ~/.cache/attocode
```
