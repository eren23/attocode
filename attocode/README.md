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

### 1. Install globally

```bash
# Clone the repo
git clone https://github.com/eren23/attocode.git
cd attocode

# Install dependencies
npm install

# Build
npm run build

# Install globally
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
  "features": {
    "memory": true,
    "planning": true,
    "sandbox": true
  }
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
```

## Uninstall

```bash
# Remove global link
npm unlink -g attocode

# Remove config (optional)
rm -rf ~/.config/attocode
rm -rf ~/.local/share/attocode
rm -rf ~/.local/state/attocode
rm -rf ~/.cache/attocode
```