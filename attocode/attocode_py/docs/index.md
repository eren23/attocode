# Attocode

Production AI coding agent built in Python. Features a Textual-based TUI, multi-agent swarm orchestration, intelligent budget management, and a safety sandbox system.

## Highlights

- **Interactive TUI** --- Rich terminal interface with live tool status, streaming, plan/task panels, and keyboard shortcuts
- **Swarm mode** --- Multi-agent orchestration with dependency-aware wave scheduling and parallel workers
- **Budget management** --- Token-based economics with doom-loop detection and phase tracking
- **Safety sandbox** --- Platform-aware command isolation (Seatbelt on macOS, Landlock on Linux, Docker, or allowlist fallback)
- **Session persistence** --- SQLite-backed sessions, checkpoints, goals, and permission grants
- **Multi-provider** --- Anthropic, OpenRouter, and OpenAI adapters
- **Skills & agents** --- Extensible skill and agent system with project-level and user-level customization
- **MCP support** --- Connect external tools via the Model Context Protocol

## Quick Start

```bash
# Install
pip install -e ".[dev]"

# Set your API key
export ANTHROPIC_API_KEY="sk-ant-..."

# Interactive TUI
attocode

# Single-turn
attocode "List all Python files in this project"

# Swarm mode
attocode --swarm "Build a REST API with tests"
```

## Project Stats

| Metric | Count |
|--------|-------|
| Source files | 318 |
| Source lines | ~75,000 |
| Test files | 120+ |
| Total tests | 3,370+ |

## Next Steps

- [Getting Started](getting-started.md) --- Installation and first run
- [CLI Reference](cli-reference.md) --- All flags and slash commands
- [Architecture](ARCHITECTURE.md) --- Module relationships and data flow
