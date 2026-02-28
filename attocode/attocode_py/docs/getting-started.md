# Getting Started

## Requirements

- Python 3.12+
- An API key for at least one LLM provider (e.g. `ANTHROPIC_API_KEY`)

## Installation

### Development install (recommended)

```bash
git clone https://github.com/eren23/attocode.git
cd attocode/attocode_py

uv sync --all-extras          # creates .venv, installs everything
```

### Global install (recommended for end users)

```bash
cd attocode/attocode_py
uv tool install --force . --with anthropic --with openai
```

This installs three commands globally: `attocode`, `attocodepy`, and `attoswarm`. Re-run the same command to update after pulling new code.

### Optional provider extras

```bash
uv sync --extra anthropic     # Anthropic SDK (recommended)
uv sync --extra openai        # OpenAI SDK
uv sync --extra tree-sitter   # AST parsing for code analysis
```

<details>
<summary>Fallback: pip / pipx</summary>

```bash
# Dev install
python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"

# Global install with pipx (installs attocode, attocodepy, attoswarm)
pipx install --force .
```

</details>

## API Key Setup

Set your API key as an environment variable:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
# Or for OpenRouter:
export OPENROUTER_API_KEY="sk-or-..."
```

Or configure it interactively:

```bash
attocode
# Then type: /setup
```

## First Run

### Interactive TUI

Launch the full terminal interface:

```bash
attocode
```

The TUI provides:

- Live tool call status display
- Keyboard shortcuts (see [CLI Reference](cli-reference.md))
- ~48 slash commands (`/help` to list them all)
- Plan and task panels
- Budget and context monitoring

### Single-turn Mode

Ask a question and get one response:

```bash
attocode "List all Python files in this project"
```

### Swarm Mode

Decompose a complex task across multiple parallel agents:

```bash
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

Initialize a project config directory:

```bash
attocode
# Then type: /init
```

## Running from Anywhere

The `attocode` command always operates on **the current working directory** --- it reads `.attocode/config.json` from where you run it, so the install location doesn't matter.

**`uv tool install` (recommended):** Already on `PATH` after install --- `attocode`, `attocodepy`, and `attoswarm` all work from any directory.

**`uv run` (from the project directory):**

```bash
cd /path/to/attocode_py
uv run attocode "your prompt"
```

<details>
<summary>Other options: shell alias, symlink</summary>

**Shell alias:** Add to `~/.bashrc`, `~/.zshrc`, or `~/.config/fish/config.fish`:

```bash
# bash / zsh
alias attocode="/absolute/path/to/attocode_py/.venv/bin/attocode"

# fish
alias attocode /absolute/path/to/attocode_py/.venv/bin/attocode
```

</details>

## Next Steps

- [CLI Reference](cli-reference.md) --- All flags and slash commands
- [Architecture](ARCHITECTURE.md) --- How the codebase is organized
- [Swarm Mode](swarm-guide.md) --- Detailed swarm walkthrough
