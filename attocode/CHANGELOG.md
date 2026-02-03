# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.6] - 2026-02-03

### Fixed
- **Subagent iteration tracking** - Parent agents now pass their iteration count to subagents via `setParentIterations()`, preventing subagents from consuming excessive iterations when parent already used many
- **Budget check accuracy** - All iteration limit checks now use `getTotalIterations()` which accounts for parent iterations in the subagent hierarchy
- **Error message clarity** - Iteration limit errors now show parent context (e.g., "5 + 40 parent = 45" instead of just "5")

### Already Implemented (Found During Exploration)
- Duplicate spawn prevention with 60-second dedup window
- Subagent pending plan merging to parent
- Exploration summary merging
- Enhanced plan mode system prompt with critical rules
- Shared blackboard for parallel subagent coordination
- `spawn_agents_parallel` tool for parallel execution

## [0.1.5] - 2026-02-01

### Fixed
- **SWE-bench Eval Working Directory** - Agent now runs in correct task workspace
  - Was running in attocode/ instead of `/tmp/swe-bench-workspace/<instance>`
  - Caused all file edits to go to wrong location
- **Cost Calculation** - Fixed $0.0000 cost display in eval runner
  - Added metrics config (was missing `collectCosts: true`)
  - Initialize OpenRouter pricing cache before running tasks
- **Trace Dashboard Iterations** - Fixed all events showing "Iteration #1"
  - Parser now correctly detects iteration boundaries on LLM request cycles

### Changed
- **Model-Aware Pricing** - Replaced hardcoded Claude pricing throughout
  - `trace-collector.ts` now uses OpenRouter pricing API
  - Dashboard `token-analyzer.ts` has 20+ model pricing (Claude, GPT, GLM, Gemini, etc.)
  - Default fallback uses Gemini Flash tier (~$0.075/M) instead of Claude Sonnet (~$3/M)

## [0.1.4] - 2026-01-30

### Added
- **Trace Mode** - Comprehensive system observability
  - Captures full session execution including "thinking" blocks
  - JSONL-based storage in `.traces/` for easy analysis
  - Integrated `trace-dashboard` for visualizing agent decisions

### Changed
- **Trace Dashboard Consolidation** - Merged `trace-viewer` library into `trace-dashboard`
  - Library code now lives in `tools/trace-dashboard/src/lib/`
  - Simplified dependency structure with no more path aliases
  - Dashboard is now the sole interface for trace analysis

### Fixed
- `/trace compare` command now points to dashboard URL instead of removed CLI

## [0.1.3] - 2026-01-29

### Added
- **Unified .attocode/ Directory** - Standardized configuration structure
  - `~/.attocode/` for user-level skills and agents
  - `.attocode/` in project root for project-specific customizations
  - Automatic priority hierarchy: built-in < user < project
- **Skills Management** - New commands for skill discovery and creation
  - `/skills` - List all available skills with locations
  - `/skills new <name>` - Create skill scaffold
  - `/skills info <name>` - Show detailed skill information
  - `/skill <name>` - Execute a skill
- **Agents Management** - New commands for agent management
  - `/agents` - List all available agents with models
  - `/agents new <name>` - Create agent scaffold
  - `/agents info <name>` - Show detailed agent info
- `/init` command - Initialize `.attocode/` directory structure
- **Capabilities Registry** - Unified discovery for skills, agents, and commands
- **Decision Transparency Events** - Model routing and tool execution events for TUI
- **Context Health Events** - Token usage tracking with estimated remaining exchanges

### Fixed
- **Subagent Cancellation** - ESC now properly stops subagents via linked cancellation tokens
- **MCP Tools in Subagents** - Subagents can now use MCP tools through:
  - `toolResolver` callback for lazy-loading MCP tools
  - `mcpToolSummaries` in system prompt for tool awareness
  - Automatic MCP tool inclusion in `filterToolsForAgent()`

### Documentation
- New `docs/skills-and-agents-guide.md` - Guide for creating custom skills and agents

## [0.1.2] - 2026-01-28

### Added
- **Interactive Planning** - Step-by-step collaborative planning with user approval gates
  - Plan creation, modification, and execution workflows
  - Plan step dependencies and status tracking
  - TUI integration for plan display
- **Learning Store** - Session-to-session learning from successes and failures
  - Pattern extraction from outcomes
  - Contextual learning retrieval for similar tasks
  - SQLite persistence for learning data
- **LLM Resilience** - Production-grade provider reliability
  - Circuit breaker pattern with configurable thresholds
  - Fallback chain for multi-provider redundancy
  - Automatic retry with exponential backoff
  - Health monitoring and recovery
- **Recursive Context** - Context engineering for complex hierarchical tasks
  - Nested context management with parent-child relationships
  - Automatic context inheritance and scoping
- **Subagent Event Context** - Enhanced subagent spawning with event propagation
- **Context Token Metrics** - Track token usage across context operations

### Documentation
- New `docs/architecture.md` - Comprehensive architecture overview with diagrams
- New `docs/extending.md` - Guide for extending attocode with custom providers, tools, and tricks

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

[Unreleased]: https://github.com/eren23/attocode/compare/v0.1.6...HEAD
[0.1.6]: https://github.com/eren23/attocode/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/eren23/attocode/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/eren23/attocode/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/eren23/attocode/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/eren23/attocode/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/eren23/attocode/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/eren23/attocode/releases/tag/v0.1.0
