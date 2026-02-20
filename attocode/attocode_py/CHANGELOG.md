# Changelog

All notable changes to the Attocode Python agent will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-02-20

### Added

- **Core agent** — `ProductionAgent` with ReAct execution loop, tool registry, and event system
- **LLM providers** — Anthropic, OpenRouter, OpenAI, Azure, ZAI adapters with fallback chains
- **Built-in tools** — file operations (read/write/edit/glob/grep), bash executor, search, agent delegation
- **TUI** — Textual-based terminal interface with message log, streaming buffer, tool call panel, status bar, thinking panel, swarm panel, and keyboard shortcuts
- **Budget system** — execution economics, loop detection, phase tracking, dynamic budget pools, cancellation tokens
- **Context engineering** — auto-compaction, reversible compaction, KV-cache optimization, failure evidence tracking, goal recitation, serialization diversity
- **Safety** — policy engine, bash classification, sandbox system (seatbelt/landlock/docker/basic)
- **Persistence** — SQLite session store with checkpoints
- **MCP integration** — client, tool search, tool validation, config loader
- **Swarm mode** — multi-agent orchestrator with task queue, worker pool, quality gates, wave execution, recovery, event bridge
- **Tasks** — smart decomposer, dependency analyzer, interactive planning, verification gates
- **Quality** — learning store, self-improvement, auto-checkpoint, dead letter queue, health checks
- **Utilities** — hooks, rules, routing, retry, diff utils, ignore patterns, thinking strategy, complexity classifier, mode manager, file change tracker, undo
- **CLI** — Click-based with `--model`, `--provider`, `--swarm`, `--tui/--no-tui`, `--yolo`, `--trace`, `--resume` flags
- **Tracing** — JSONL execution trace writer with cache boundary detection
- **Skills & agents** — loader, executor, registry for `.attocode/` directory system
- **LSP integration** — language server protocol client
