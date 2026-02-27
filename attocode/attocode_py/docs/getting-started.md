# Getting Started

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

### Optional provider extras

```bash
pip install -e ".[anthropic]"    # Anthropic SDK (recommended)
pip install -e ".[openai]"      # OpenAI SDK
pip install -e ".[tree-sitter]"  # AST parsing for code analysis
```

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

**pipx (recommended):** Already on `PATH` after `pipx install` --- works from any directory with no extra setup.

**Shell alias:** Add to `~/.bashrc`, `~/.zshrc`, or `~/.config/fish/config.fish`:

```bash
# bash / zsh
alias attocode="/absolute/path/to/attocode_py/.venv/bin/attocode"

# fish
alias attocode /absolute/path/to/attocode_py/.venv/bin/attocode
```

## Next Steps

- [CLI Reference](cli-reference.md) --- All flags and slash commands
- [Architecture](ARCHITECTURE.md) --- How the codebase is organized
- [Swarm Mode](swarm-guide.md) --- Detailed swarm walkthrough
