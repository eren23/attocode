# Attocode Examples

Quick-start examples for using attocode in different modes.

## Basic Usage

### Single Non-Interactive Task

```bash
bash examples/basic-task.sh
```

Runs a one-shot task (no TUI, no interactive prompts). Useful for CI/CD or scripting.

### Swarm Research

```bash
bash examples/swarm-research.sh
```

Launches a multi-agent swarm that researches a topic in parallel. Requires a provider that supports parallel requests.

## Configuration

See `examples/config/` for sample configuration files:

- `config.json` — Project-level agent configuration
- `rules.md` — Project-level rules and guidelines

Copy these to `.attocode/` in your project root to customize behavior.

## Prerequisites

- Node.js 20+
- An API key set via `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, or `OPENAI_API_KEY`
- Build the project first: `npm run build`
