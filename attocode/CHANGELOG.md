# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-01-27

### Added
- "Always Allow" option (`[A]`) in TUI approval dialog - auto-approves matching commands for the session
- TUI permission approval system with safety fallbacks
- Architecture diagrams in CLAUDE.md documentation

### Changed
- Tool call display now shows full arguments in expanded view (Alt+T)

## [0.1.0] - 2026-01-27

### Added
- **Core Agent** - ProductionAgent with multi-provider support (Anthropic, OpenRouter, OpenAI)
- **TUI Mode** - Terminal UI built with Ink/React featuring:
  - Static message rendering for flicker-free display
  - Command palette (Ctrl+P)
  - Tool call visualization with expand/collapse (Alt+T)
  - Approval dialogs for dangerous operations
- **REPL Mode** - Legacy readline interface for simpler environments
- **Session Persistence** - SQLite-based storage with JSONL fallback
- **Context Management**:
  - Auto-compaction at configurable thresholds
  - Reversible compaction with retrieval references
  - Goal recitation for long-running tasks
- **MCP Integration** - Model Context Protocol for external tools
- **Tool System**:
  - Built-in tools: file operations, bash, search
  - Permission system with danger levels (safe, moderate, dangerous, critical)
  - Custom permission checkers
- **Planning & Reflection** - Task decomposition and self-evaluation
- **Thread Management** - Fork, switch, and merge conversation branches
- **Checkpoints** - Save and restore agent state
- **File Change Tracking** - Full undo capability for file modifications

### Security
- Permission-based tool execution with user approval
- Sandbox execution for bash commands (macOS Seatbelt)
- Dangerous operation blocking in strict mode

[Unreleased]: https://github.com/eren23/attocode/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/eren23/attocode/releases/tag/v0.1.0
