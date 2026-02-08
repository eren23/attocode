# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1] - 2026-02-08

### Added
- **Parallel tool execution batching (B1)** — Read-only tools (`read_file`, `glob`, `grep`, `list_files`, `search_files`, `search_code`, `get_file_info`) are now batched and executed concurrently via `Promise.allSettled`. Non-parallelizable tools break the batch and execute sequentially. Reduces wall-clock time for multi-read tool call sequences.
- **Boolean coercion for tool parameters (B6)** — New `coerceBoolean()` schema (via `z.preprocess`) accepts string `"true"`/`"false"`, `"1"`/`"0"`, `"yes"`/`"no"` (case-insensitive, whitespace-tolerant) from weaker models that send booleans as strings.
- **`allowMcpTools` agent field (B5)** — Agent definitions can now control MCP tool access: `true` (default, all MCP tools), `false` (none), or `string[]` (specific tool names). Applied in `filterToolsForAgent()`.
- **New test suites** — 6 new/extended test files (+56 tests): `coercion.test.ts`, `anthropic-cache.test.ts`, `adapters-cache.test.ts`, `budget-pool.test.ts` additions, `agent-registry.test.ts` additions, `parallel-tool-execution.test.ts`.

### Fixed
- **B7: Double budget allocation in parallel spawns** — `spawnAgentsParallel()` previously called `reserveBatch()` to pre-allocate equal shares, then passed `constraints.maxTokens` to each `spawnAgent()`. But `getSubagentBudget()` short-circuits on `constraints.maxTokens` without touching the pool, leaving phantom reservations permanently locked. Fixed by replacing `reserveBatch` with `setMaxPerChild(equalShare)` + `resetMaxPerChild()` in a `finally` block, letting each child allocate normally from the pool at the reduced cap.
- **Agent hang on unparseable tool call arguments** — When an LLM returns tool calls with truncated/invalid JSON arguments (common with weaker models like glm-4.7), the agent would silently convert args to `{}`, execute the tool (which fails with a cryptic error), and the LLM would retry with the same broken JSON — each attempt taking 120s+ due to provider timeouts. Now: parse failures are propagated via a `parseError` field on `ToolCall`, and `executeSingleToolCall` short-circuits with a clear error message telling the LLM to retry with valid JSON, preventing the confusion-retry loop.

### Changed
- **Anthropic prompt caching headers (A1)** — Both `chat()` and `chatWithTools()` now send `anthropic-beta: prompt-caching-2024-07-31` header.
- **Structured system content passthrough (A2-A3)** — System messages with `ContentBlock[]` containing `cache_control` markers are passed through as-is to the Anthropic API (not flattened to string).
- **Cache usage extraction (A4-A5)** — Anthropic responses with `cache_creation_input_tokens` and `cache_read_input_tokens` are mapped to `cacheWriteTokens` and `cacheReadTokens` in both `chat()` and `chatWithTools()`.
- **ProviderAdapter cache passthrough** — `cacheReadTokens`, `cacheWriteTokens`, and `cost` fields forwarded from provider responses. `cachedTokens` (OpenRouter) falls back to `cacheReadTokens`.
- **Budget pool API** — Removed `reserveBatch()` method (fundamentally flawed). Added `setMaxPerChild()` / `resetMaxPerChild()` for temporary cap adjustment during parallel spawns.

## [0.2.0] - 2026-02-07

### Added

#### Swarm Mode — Multi-Model Parallel Orchestration (Major Feature)

A new execution mode where one orchestrator model decomposes tasks into subtask DAGs, dispatches them across waves of parallel cheap/free specialist worker models, validates outputs through quality gates, and synthesizes a final result.

- **SwarmOrchestrator** (`src/integrations/swarm/swarm-orchestrator.ts`) — Core orchestration loop implementing an 8-phase pipeline: decompose → plan → schedule → execute → review → verify → fix-up → synthesize. Manages wave-based parallel execution with per-wave review cycles and integration verification.
- **SwarmTaskQueue** (`src/integrations/swarm/task-queue.ts`) — Wave-based task scheduler that organizes subtasks into dependency layers. Tasks flow through `pending → ready → dispatched → completed/failed/skipped` states. Supports fix-up task injection mid-execution and cross-wave ready-task promotion.
- **SwarmWorkerPool** (`src/integrations/swarm/worker-pool.ts`) — Concurrent worker dispatch with configurable `maxConcurrency` (default: 3). Selects workers by capability matching (code, research, test, review, document) with round-robin load distribution and health-aware selection.
- **SwarmBudgetPool** (`src/integrations/swarm/swarm-budget.ts`) — Budget management splitting total tokens between orchestrator reserve (15%) and shared worker pool (85%). Per-worker token and cost caps prevent any single worker from exhausting the budget. Overrides the parent agent's budget pool so swarm workers allocate from the swarm's much larger pool.
- **SwarmQualityGate** (`src/integrations/swarm/swarm-quality-gate.ts`) — Per-task output validation by a judge model scoring 1-5. Failed outputs trigger retries. Quality gates automatically skip under rate limit pressure and on retried tasks to avoid compounding failures.
- **Model auto-detection** (`src/integrations/swarm/model-selector.ts`) — Queries OpenRouter `/api/v1/models` API, filters by tool support, context window, and cost, then assigns models to worker roles with provider-diverse selection (maximizes rate limit headroom by picking models from different providers). Falls back to hardcoded models (Mistral, Z-AI, AllenAI, Moonshot) when API is unavailable.
- **ModelHealthTracker** — Per-model health monitoring tracking successes, failures, rate limits, and average latency. Models are marked unhealthy after 2+ rate limits in 60s or >50% failure rate. Unhealthy models are deprioritized in capability matching and can trigger automatic failover to alternative models.
- **Request throttle** (`src/integrations/swarm/request-throttle.ts`) — Token bucket rate limiter with FIFO queue and minimum spacing. Two presets: `free` (2 concurrent, 0.5 req/s, 1500ms spacing) and `paid` (5 concurrent, 2.0 req/s, 200ms spacing). Features adaptive backoff (halves capacity on 429, recovers after 10s success) and proactive adjustment from rate limit response headers.
- **ThrottledProvider** — LLM provider wrapper that enforces `throttle.acquire()` before every `chat()` call. Since all subagents share the parent's provider by reference, wrapping the provider at swarm init throttles ALL downstream LLM calls across all workers.
- **Circuit breaker** — Orchestrator-level safety that pauses all dispatch after 3 rate limit errors within 30 seconds for a 15-second cooldown. Complements the per-request throttle by providing a reactive macro-level stop.
- **Hierarchy roles** — Three-tier authority separation: **Executor** (workers performing subtasks), **Manager** (reviews wave outputs, spawns fix-up tasks), **Judge** (runs quality gates, verification). Manager and judge models configurable via `hierarchy.manager` and `hierarchy.judge` in swarm.yaml.
- **Planning phase** — Orchestrator (or manager) creates acceptance criteria per subtask and an integration test plan with bash verification commands. Planning is graceful — continues without criteria if it fails.
- **Wave review** — Manager reviews all completed outputs after each wave, assesses as "good"/"needs-fixes"/"critical-issues", and can spawn fix-up tasks (`FixupTask`) that execute immediately before the next wave.
- **Integration verification** — After all waves complete, runs bash commands from the integration test plan. Failed verification triggers fix-up tasks with up to `maxVerificationRetries` (default: 2) retry cycles.
- **State persistence and resume** (`src/integrations/swarm/swarm-state-store.ts`) — Checkpoints saved after each wave containing full task states, plan, model health, orchestrator decisions, and stats. Resume with `--swarm-resume <session-id>` to continue from the last completed wave.
- **Orchestrator decision logging** — Every significant decision (planning, review, failover, circuit breaker) is logged with timestamp, phase, decision, and reasoning. Included in checkpoints and emitted as events for dashboard visibility.
- **Event system** (`src/integrations/swarm/swarm-events.ts`) — 27 typed event categories covering lifecycle, tasks, waves, quality, budget, planning, review, verification, model health, persistence, circuit breaker, and hierarchy role actions. All events forwarded to the main agent event system for TUI display and to the filesystem via `SwarmEventBridge` for dashboard consumption.
- **SwarmEventBridge** (`src/integrations/swarm/swarm-event-bridge.ts`) — Serializes swarm events to JSONL on disk, enabling the live dashboard to consume events via file polling → SSE streaming.
- **YAML config system** (`src/integrations/swarm/swarm-config-loader.ts`) — Custom YAML parser supporting nested objects, block arrays, multiline strings (`|`), and type coercion. Config search order: `.attocode/swarm.yaml` → `.attocode/swarm.yml` → `.attocode/swarm.json` → `~/.attocode/swarm.yaml`. Merge order: built-in defaults < yaml config < CLI flags.
- **Swarm budget presets** (`src/integrations/economics.ts`) — `SWARM_WORKER_BUDGET` (20K tokens, $0.05, 2 min, 15 iterations) and `SWARM_ORCHESTRATOR_BUDGET` (100K tokens, $0.25, 5 min, 50 iterations) for economics system integration.
- **Worker persona and philosophy** — Per-worker `persona` strings for role-specific behavior and a global `philosophy` string injected into every worker's system prompt for team-wide coding standards.
- **Inter-worker communication** — Shared blackboard for posting findings between workers. Dependency context aggregation (configurable `dependencyContextMaxLength`). Optional workspace file listing.
- **File conflict strategies** — Three modes for handling concurrent file modifications: `serialize`, `claim-based` (default), and `orchestrator-merges`.

#### CLI — New Flags

- **`--swarm [CONFIG]`** — Enable swarm mode. Without argument: auto-detect worker models from OpenRouter. With path: load the specified `.attocode/swarm.yaml` config file.
- **`--swarm-resume ID`** — Resume a swarm session from its last checkpoint. Implicitly enables swarm mode.
- **`--paid-only`** — Filter out free-tier models in swarm mode. Automatically switches throttle preset to `paid`.
- **`--yolo`** — Shorthand for `--permission yolo`.

#### TUI — Swarm Status Panel

- **SwarmStatusPanel** (`src/tui/components/SwarmStatusPanel.tsx`) — New TUI panel showing live swarm execution status: current phase, wave progress bar with percentage, queue stats (ready/running/done/failed/skipped), active workers table (model, task description, elapsed time), and budget gauges (tokens + cost). Auto-hides when no swarm is active.
- **Alt+W keyboard shortcut** — Toggle swarm panel visibility.
- **Swarm event messages** — All swarm events (wave start/complete, task dispatched/completed/failed, quality rejections, errors) displayed as `[SWARM]` system messages in the TUI message stream.

#### Trace Dashboard — Swarm Visualization

- **SwarmDashboardPage** (`tools/trace-dashboard/src/pages/SwarmDashboardPage.tsx`) — Full-page live swarm visualization with responsive layout. Auto-connects when a swarm starts; shows idle placeholder otherwise.
- **SwarmHistoryPage** (`tools/trace-dashboard/src/pages/SwarmHistoryPage.tsx`) — Browse and review previous swarm sessions from trace files.
- **14 dashboard components** — `SwarmHeader`, `MetricsStrip`, `WaveProgressStrip`, `TaskDAGPanel` (interactive dependency graph), `TaskNode`, `TaskInspector` (click-to-inspect task details), `WorkerTimelinePanel` (Gantt-style parallel execution), `BudgetPanel` (radial gauges), `ModelDistributionPanel`, `QualityHeatmapPanel`, `EventFeedPanel` (scrolling event log), `EventRow`, `HierarchyPanel`, `ExpandablePanel`.
- **SSE live streaming** (`tools/trace-dashboard/src/api/routes/swarm-live.ts`) — Server-Sent Events endpoint streaming swarm events in real-time.
- **Swarm watcher** (`tools/trace-dashboard/src/api/swarm-watcher.ts`) — Polls JSONL event files for new entries and feeds connected SSE clients.
- **useSwarmStream hook** (`tools/trace-dashboard/src/hooks/useSwarmStream.ts`) — React hook managing SSE connection lifecycle, state updates, reconnection, and idle detection.
- **Swarm type library** (`tools/trace-dashboard/src/lib/swarm-types.ts`) — Shared type definitions for dashboard state management.
- **Navigation** — New "Swarm" nav link in the dashboard header routing to `/swarm` and `/swarm/history`.

#### Provider Enhancements

- **Reasoning/thinking content extraction** — OpenRouter provider now extracts `reasoning` and `reasoning_content` fields from model responses (used by DeepSeek-R1, GLM-4, QwQ, and other reasoning models). Exposed as `ChatResponse.thinking` across the provider interface.
- **Thinking-only response handling** — Main agent loop now handles responses with thinking but no visible content. Gives one targeted nudge ("provide your answer based on your analysis"), then accepts thinking as content on second attempt. Prevents infinite empty-response retries with reasoning models.
- **Rate limit info extraction** — OpenRouter provider extracts `X-RateLimit-Remaining`, `X-RateLimit-Remaining-Tokens`, and `X-RateLimit-Reset` headers into `ChatResponse.rateLimitInfo`. Used by the swarm throttle for proactive adjustment.
- **Pre-flight key check** — `OpenRouterProvider.checkKeyInfo()` queries `/api/v1/key` to detect free-tier keys and low credit balances before swarm execution starts.
- **Enhanced 429 retry logic** (`src/providers/resilient-fetch.ts`) — Rate limit errors now get extra retry budget (`maxRetriesFor429`, default: +2 beyond `maxRetries`). Uses steeper exponential backoff (3^n instead of 2^n base) with ±25% jitter to give rate limit windows more recovery time.

#### Init Command

- **`attocode init` now scaffolds `swarm.yaml`** — The `/init` command creates `.attocode/swarm.yaml` with all swarm config options commented out alongside the existing `config.json` and `rules.md`.

#### Documentation

- **Comprehensive swarm guide** (`docs/swarm/`) — 8 new documentation files:
  - `README.md` — Hub page linking all guides and examples
  - `how-it-works.md` — Deep dive: normal mode vs swarm, 8-phase pipeline, wave execution, hierarchy, budget management
  - `getting-started.md` — Tutorial: first run, understanding output, when to use swarm vs normal mode, decision flowchart
  - `configuration-guide.md` — Every config option with defaults, purpose, and examples
  - `advanced/architecture-deep-dive.md` — Event system, budget pool math, circuit breaker, token bucket throttling, checkpoint format, event bridge pipeline
  - `advanced/model-selection.md` — Auto-detection flow, capability matching, health tracking, failover, hardcoded fallbacks
  - `advanced/dashboard.md` — All dashboard panels, real-time SSE architecture, commands
- **5 annotated example configs** (`docs/swarm/examples/`):
  - `minimal.yaml` — Zero-config auto-detection
  - `free-tier.yaml` — Conservative rate limits, persistence
  - `paid-fast.yaml` — Max parallelism, generous budget
  - `quality-focused.yaml` — Strict hierarchy with manager + judge
  - `resume-friendly.yaml` — Checkpointing for long-running tasks

#### Tests

- **9 new test files** with comprehensive swarm coverage:
  - `tests/swarm/config-loader.test.ts` — YAML parsing, nested objects, arrays, multiline strings, config merge
  - `tests/swarm/model-selector.test.ts` — Auto-detection, capability matching, provider diversity
  - `tests/swarm/model-failover.test.ts` — Health tracking, failover selection, unhealthy model handling
  - `tests/swarm/request-throttle.test.ts` — Token bucket, FIFO ordering, adaptive backoff, recovery
  - `tests/swarm/swarm-budget.test.ts` — Budget pool split, per-worker caps, capacity checks
  - `tests/swarm/task-queue.test.ts` — Wave scheduling, task lifecycle, fix-up injection, checkpoint/restore
  - `tests/swarm/types.test.ts` — Type conversions, defaults, capability mapping
  - `tests/swarm/state-persistence.test.ts` — Checkpoint save/load, resume flow
  - `tests/swarm/worker-prompts.test.ts` — Philosophy injection, persona layering, tool filtering
- **OpenRouter provider tests** — New tests for reasoning content extraction (`reasoning`/`reasoning_content` fields), null content handling, rate limit info extraction from headers, and `chatWithTools` reasoning support.

### Changed

- **Provider types** (`src/providers/types.ts`) — `ChatResponse` interface extended with `thinking?: string` for reasoning content and `rateLimitInfo?: { remainingRequests, remainingTokens, resetSeconds }` for rate limit headers. `content` field in OpenRouter response type widened from `string` to `string | null` to handle thinking-only responses.
- **ProviderAdapter** (`src/adapters.ts`) — Now passes through `thinking` field from provider responses to the production agent.
- **Agent types** (`src/types.ts`) — `ProductionAgentConfig` extended with `swarm?: SwarmConfig | false`. `AgentEvent` union extended with `SwarmEvent` types for TUI event forwarding.
- **Agent main loop** (`src/agent.ts`) — `run()` now checks for `swarmOrchestrator` before falling through to planning/direct execution. New `runSwarm()` method handles the full swarm lifecycle including event bridge setup and cleanup.
- **Assistant message format** — Messages now include `metadata.thinking` when reasoning content is present. `lastResponse` falls back to thinking content when visible content is empty.
- **Subagent spawn dedup bypass** — Swarm workers (agents named `swarm-*`) skip the duplicate spawn prevention check, since the orchestrator handles retry logic at the task level.
- **Subagent execution policy** — Subagents now get `defaultPolicy: 'allow'` since they're already constrained to their registered tool set and the parent's `'prompt'` policy can't work without `humanInLoop`.
- **Resilient fetch** (`src/providers/resilient-fetch.ts`) — `NetworkConfig` extended with `maxRetriesFor429` (default: 2). Retry loop uses `maxRetries + maxRetriesFor429` for 429 errors with steeper 3^n backoff.
- **Config builder** (`src/defaults.ts`) — `buildConfig()` now includes `swarm` field from user config.
- **Integrations barrel** (`src/integrations/index.ts`) — 47 new exports for the entire swarm module (types, classes, factories, constants).
- **LearningStore** (`src/integrations/learning-store.ts`) — Now creates parent directories with `mkdirSync(recursive: true)` before opening the SQLite database, preventing ENOENT errors when the `.agent/` directory doesn't exist yet.
- **SmartDecomposer** (`src/integrations/smart-decomposer.ts`) — Falls back to heuristic decomposition when LLM returns 0 subtasks instead of propagating an empty result.
- **REPL mode** (`src/modes/repl.ts`) — Accepts and passes through `swarm` config option.
- **TUI mode** (`src/modes/tui.tsx`) — Accepts and passes through `swarm` config option.
- **Dashboard tailwind config** — Extended with swarm-specific color palette entries.
- **Existing swarm-mode.md** — Added link to the new comprehensive guide at the top.

## [0.1.9] - 2026-02-06

### Added
- **Prompt cache markers (P1)** - System prompts are now sent as structured `CacheableContentBlock[]` with `cache_control: { type: 'ephemeral' }` markers, enabling LLM provider-level prompt caching. Static sections (prefix, rules, tools, memory) are marked for caching; dynamic content (session ID, timestamp) is not. Anthropic and OpenRouter adapters pass markers through; OpenAI adapter gracefully flattens to string. Expected 60-70% cache hit rate on multi-turn sessions.
- **Shared file cache (P2)** - New `SharedFileCache` (LRU, TTL-based) shared across parent and child agents via same-process Map reference. Eliminates redundant file reads in multi-agent workflows (previously 3x reads of large files like agent.ts at 212KB). All file paths normalized via `path.resolve()` for consistent keys. Write operations and `undo_file_change` invalidate cache entries. Configurable max size (5MB default) and TTL (5 min default).
- **Budget pooling (P4)** - New `SharedBudgetPool` replaces independent per-subagent budgets. Parent reserves 25% for synthesis work; remaining 75% is shared across children. Pessimistic reservation accounting prevents over-allocation during parallel spawns. `recordUsage()` and `release()` called in `finally` block to track actual consumption and return unused budget. Pool exhaustion grants minimal 5K emergency budget instead of bypassing limits.
- **Subagent compaction (P5)** - Subagents now have auto-compaction enabled with `maxContextTokens: 80000` (compaction triggers at ~64K tokens via 80% threshold). More aggressive settings: fewer preserved messages, no tool result preservation, smaller summaries.
- **Approval batching (P6)** - New `ApprovalScope` system for subagent pre-approval. Read-only tools (`read_file`, `glob`, `grep`, etc.) auto-approved. Write tools (`write_file`, `edit_file`) scoped-approved within `src/`, `tests/`, `tools/` directories. Directory-boundary-aware path matching prevents false positives (e.g., `src/` won't match `src-backup/`). Tool name matching uses exact comparison, not substring.
- **Comprehensive test coverage** - 81 new tests across 5 test files: `budget-pool.test.ts` (23 tests), `file-cache.test.ts` (22 tests), `approval-scope.test.ts` (14 tests), `timeout-precedence.test.ts` (14 tests), `cache-markers.test.ts` (8 tests)

### Fixed
- **Subagent timeout precedence (P3)** - Changed from `configTimeout ?? agentTypeTimeout` (config always wins) to proper 4-level chain: per-type config > agent-type default > global config > hardcoded fallback. Reviewers now correctly get 180s (not global 300s), researchers get 420s. Added per-type config support via `subagent.timeouts` record.
- **Timeout/iteration validation** - Negative, NaN, and Infinity values in timeout/iteration configs are now rejected and fall through to next precedence level instead of causing runtime errors in `createGracefulTimeout()`.
- **Budget pool initialization** - Pool now uses the agent's actual configured budget (custom or default) instead of always using `STANDARD_BUDGET` (200K). Users with 500K budgets no longer get a pool capped at 200K.
- **Cache markers fallback** - When KV-cache context is not configured, `buildCacheableSystemPrompt()` returns empty array (signal to use plain string) instead of an unmarked block that would be sent as structured content without cache benefits.
- **Approval scope matching** - Tool name matching changed from `includes()` to exact `===` comparison, preventing `requireApproval: ['bash']` from blocking `bash_completion`. Path matching now checks directory boundaries, preventing `src/` from matching `src-backup/file.ts`.

### Changed
- **LLM Provider interface** - `chat()` method widened to accept `(Message | MessageWithContent)[]` across both provider interfaces (`src/types.ts` and `src/providers/types.ts`). All 4 provider adapters (Anthropic, OpenRouter, OpenAI, Mock) updated.
- **Subagent budget model** - Subagents no longer get independent 150K budgets (which exposed 250%+ of intended cost). Budget is now drawn from a shared pool bounded by the parent's total budget.
- **Subagent spawn flow** - `spawnAgent()` now allocates from budget pool, passes file cache, sets approval scope, enables compaction, and records actual usage on completion.

## [0.1.8] - 2026-02-06

### Added
- **Command history and debug panel in TUI** - HistoryManager for persistent command history with deduplication and search; DebugPanel for real-time debug logging with color-coded levels and timestamps; ErrorDetailPanel for structured error display; TUI toggles for debug output and command history
- **Agent resilience and timeout handling** - Graceful wrapup during timeouts with structured summaries before cancellation; metrics for success, failure, cancellation, and retries; incomplete action recovery with configurable retry limits; TUI display of subagent metrics and structured reports

### Changed
- **Subagent timeout flow** - ProductionAgent supports graceful wrapup and structured reports on timeout; cancellation and economics integrations updated for new metrics and recovery behavior
- **TUI** - Integrated HistoryManager and DebugPanel; ToolCallItem and app layout updates for new panels and error details

## [0.1.7] - 2026-02-05

### Added
- **Session loading in TUI** - New `/load <session-id>` command to load a session by ID; checks for existing sessions and loads messages from checkpoints or entries; SQLiteStore syncs message counts with checkpoint data; detailed logs during load including session metadata and error handling; thread management supports auto-checkpoints and message sync
- **Tasks Panel** - New TasksPanel in TUI for real-time task display and management; task create/update events; keyboard shortcuts to toggle panel; visual indicators for task status and blocking conditions
- **Task management system** - TaskManager for persistent task tracking and coordination across subagents; task create/update/list with event emissions; ProductionAgent integration; agent-type-specific timeout and iteration limits; Active Agents Panel in TUI for real-time subagent monitoring; TaskManager tests
- **Unified tracing with subagent hierarchy** - `setTraceCollector` on ProductionAgent to share trace collectors with subagents; subagent context tagging in TraceCollector to aggregate events in parent trace file; TUI trace summaries with subagent hierarchies and metrics; tests for unified tracing (subagent view, event tagging, metric aggregation)

### Changed
- **Subagent timeout and cancellation** - External cancellation token in ProductionAgent for subagent timeouts; updated timeout configs for research-style tasks; TUI shows `timing_out` during cancellation; Active Agents Panel includes `timing_out` state; partial subagent results preserved on timeout

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

[Unreleased]: https://github.com/eren23/attocode/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/eren23/attocode/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/eren23/attocode/compare/v0.1.9...v0.2.0
[0.1.9]: https://github.com/eren23/attocode/compare/v0.1.8...v0.1.9
[0.1.8]: https://github.com/eren23/attocode/compare/v0.1.7...v0.1.8
[0.1.7]: https://github.com/eren23/attocode/compare/v0.1.6...v0.1.7
[0.1.6]: https://github.com/eren23/attocode/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/eren23/attocode/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/eren23/attocode/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/eren23/attocode/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/eren23/attocode/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/eren23/attocode/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/eren23/attocode/releases/tag/v0.1.0
