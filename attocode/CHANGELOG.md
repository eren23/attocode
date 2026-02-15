# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.4] - 2026-02-15

### Added

#### ESLint 9 and Prettier
- **ESLint 9 and Prettier** — Add eslint.config.js with TypeScript and import-x rules; .prettierrc.json and .prettierignore; lint, lint:fix, format, format:check scripts; CI workflow updates; formatting and lint fixes across src and tests

#### Config Module
- **Config module with schema** — New `attocode/src/config` (index, config-manager, schema, base-types); `loadConfig()` supports hierarchical sources; legacy `config.ts` delegates to it; deprecate `loadUserConfig()` for backward compatibility; wire main.ts and integrations to use `loadConfig` from config/index; tests for config schema and config manager (`tests/config/`)

#### Agent Architecture Refactor
- **Agent state machine** — New `AgentStateMachine` for formalized phase tracking with typed transitions and metrics
- **Base manager pattern** — New `BaseManager` class for consistent lifecycle management across managers
- **Execution loop extraction** — Extracted execution loop, response handling, and tool execution into dedicated modules (`execution-loop.ts`, `response-handler.ts`, `tool-executor.ts`, `subagent-spawner.ts`) for improved organization; tool execution enhanced with batching and policy enforcement
- **Core module exports** — Updated core index with new module structure and exports

#### Swarm Shared State
- **SharedContextState** — Cross-worker failure learning and reference pooling among swarm workers
- **SharedEconomicsState** — Doom loop aggregation and shared insights across workers; methods for recording failures and tool calls
- **ProductionAgent integration** — Updated agent and related modules to utilize shared states for coordination and resource management
- **Tests** — `shared-context-state.test.ts`, `shared-economics-state.test.ts`

#### Tree-sitter AST
- **AST-based symbol and dependency extraction** — Tree-sitter integration for Python and TypeScript; improved codebase context analysis
- **Edit validator** — Post-edit syntax validation using tree-sitter; execution loop runs syntax validation after file edits
- **Swarm worker budget** — Per-worker utilization metrics in swarm worker budget tracking
- **Tests** — `codebase-ast.test.ts`, `edit-validator.test.ts`

#### Agent Execution and Safety
- **Swarm decomposition fallback** — ProductionAgent falls back to direct execution when swarm decomposition fails
- **Strict tool usage** — Defaults enforce strict tool usage rules for file operations
- **Execution policy** — Improved settings for non-interactive modes and subagent risk management
- **Safeguards** — Tool call limits and context overflow prevention in execution loops
- **Tests** — `execution-loop.test.ts`, `tool-executor.test.ts`, `economics-global-doom.test.ts`

#### Task Management and Diagnostics
- **Completion event diagnostics** — ProductionAgent completion event now includes insights on available tasks and pending tasks with owners
- **`countPendingTasksWithOwners()`** — New function for task management accuracy
- **Task ownership normalization** — Only in-progress tasks retain ownership metadata; enhances task dispatchability
- **TUI diagnostics** — Display additional diagnostic info when task completion is blocked; improved user feedback
- **Tests** — Task ownership normalization and scenario validation in `task-manager.test.ts`

#### Other
- **package-lock.json** — Lockfile for consistent installations
- **Lifecycle hooks** — Document payload/event usage and operational notes in API reference
- **Trace dashboard** — Agent topology page, code map, session detail enhancements, swarm dashboard improvements

### Changed

- **Legacy config** — `loadUserConfig()` in config.ts deprecated; use `loadConfig()` from config/index
- **Agent structure** — ~3.4K lines extracted from agent.ts into core modules; cleaner separation of concerns

### Documentation

- **README** — Branch change highlights, resilience tuning
- **TUI/modes guide** — Bounded incomplete-action auto-loop behavior
- **Troubleshooting** — New guide: `open_tasks` stale leases, swarm `dispatchLeaseStaleMs` stale dispatched recovery
- **API/config** — Document `resilience.taskLeaseStaleMs`, swarm `resilience.dispatchLeaseStaleMs`
- **Swarm configuration guide** — Clarify camelCase/snake_case alias support in budget, communication, resilience
- **examples/config/config.json** — Add `taskLeaseStaleMs`

### Fixed

- Trivial `let` → `const`; rename unused catch param to `_err`

## [0.2.3] - 2026-02-13

### Added

#### Pre-Dispatch Auto-Split
- **Pre-dispatch auto-split** — Proactively splits high-complexity foundation tasks before dispatch using heuristic pre-filtering + LLM judgment (`shouldAutoSplit`, `judgeSplit` in orchestrator, `autoSplit` config in types)

#### Per-Model Hollow Tracking
- **Per-model hollow tracking** — Separate hollow completion tracking per model (`recordHollow`, `getHollowRate`, `getHollowCount` in `ModelHealthTracker`), hollow-aware worker selection sorting

#### Unified Policy Engine
- **Unified policy engine** (`policy-engine.ts`, 334 lines) — Centralized permission resolution for all tool and bash operations, merges built-in defaults with user/project overrides, supports per-task-type policy profiles

#### Bash Policy Module
- **Bash policy module** (`bash-policy.ts`, 168 lines) — Single source of truth for bash command classification (read-only, write, file mutation patterns), replaces scattered inline regex

#### Per-Task-Type Configuration
- **Per-task-type configuration** — `BUILTIN_TASK_TYPE_CONFIGS` with type-specific timeouts, budgets, tool requirements, and policy profiles for implement/test/refactor/research/review/document tasks

#### Resilience & Recovery
- **Artifact-aware cascade skip** — Tasks with failed dependencies check for on-disk artifacts before skipping; partial results from failed predecessors are reused
- **Artifact inventory** — Post-swarm disk scan (`collectArtifactInventory`) that reports total files, bytes, and per-task file lists in `swarm.complete` event
- **Mid-swarm re-planning** — Stall detection (`swarm.stall` event) with progress ratio monitoring; automatic re-planning (`swarm.replan`) that generates replacement tasks for stuck work
- **All-probe-failure abort** — `swarm.abort` event when all probe models fail, preventing infinite retry loops
- **Wave-level all-failed recovery** — `swarm.wave.allFailed` event and recovery path when every task in a wave fails
- **Circuit breaker for rate limits** — `swarm.circuit.open`/`closed` events with configurable pause duration

#### Decision Traceability
- **Decision traceability** — Full per-attempt event records (`swarm.task.attempt`) with model, duration, tool calls, failure mode; plus `swarm.task.resilience` events for recovery strategies

#### Foundation Task Detection
- **Foundation task detection** — Tasks with 3+ dependents auto-tagged `isFoundation`, receive extra retries (+1) and relaxed quality thresholds (-1)

#### Quality Gate Enhancements
- **Quality gate enhancements** — `recordQualityRejection` on `ModelHealthTracker` undoes premature `recordSuccess`; pre-flight rejection tracking; file artifact passing to quality judge

#### Swarm Events & Observability
- **Swarm phase progress events** — `swarm.phase.progress` for decomposing/planning/scheduling visibility in dashboard
- **Orchestrator LLM call tracking** — `swarm.orchestrator.llm` events for all orchestrator-level LLM calls with token/cost tracking

#### Other Additions
- **Smart decomposer dependency mapping** — Improved smart-decomposer with proper 0-based task ID mapping for dependency references
- **Model selector write capability** — `selectWorkerForCapability` now handles `'write'` capability with fallback to code workers
- **Swarm config YAML loader enhancements** — Extended YAML config support for all new config fields (`autoSplit`, `hollowTermination`, `probeModels`, `artifactAwareSkip`, `permissions`, `policyProfiles`, `taskTypeConfigs`)

### Fixed

- **SwarmFileWatcher replay bug** — When `sinceSeq=0`, watcher incorrectly skipped to end of `events.jsonl` producing empty Event Feed; fixed to replay from offset 0
- **Worker-pool double-selection** — `dispatch()` now accepts optional pre-selected worker to avoid selecting a different worker than intended
- **toolAccessMode default** — Reverted from `'whitelist'` to `'all'` (whitelist broke swarms without explicit `allowedTools`)
- **swarm-event-bridge completion** — `swarm.complete` now correctly updates `lastStatus.phase` to `'completed'` and cancels pending debounced writes
- **Hollow recording specificity** — Changed generic `recordFailure(model, 'error')` to `recordHollow(model)` for hollow completions, preserving failure tracking while adding hollow-specific metrics
- **selectAlternativeModel ghost models** — Returns `undefined` when no configured alternative exists instead of injecting unconfigured fallback workers
- **Subagent cleanup** — Per-agent blackboard cleanup (`releaseAll` + `unsubscribeAgent`) for subagents, full `clear()` for root
- **DynamicBudgetPool parallel spawns** — Temporarily swapped in for parallel spawn operations
- **Quality gate file artifacts** — `evaluateWorkerOutput` accepts optional `fileArtifacts` param for passing actual file contents to judge

### Improved

- **Agent.ts** — +582 lines of improvements including enhanced subagent lifecycle, better cancellation handling, improved spawn orchestration
- **Swarm orchestrator** — +1,984 lines with comprehensive resilience, traceability, and recovery improvements
- **Task queue** — +293 lines with `partialDependencyThreshold` support, improved wave scheduling
- **Worker pool** — +282 lines with better dispatch logic, worker selection improvements
- **Quality gate** — +356 lines with enhanced evaluation, pre-flight checks, artifact awareness
- **Economics** — +181 lines with improved budget tracking and doom loop detection
- **Safety module** — Enhanced safety checks and policy integration
- **CLI** — Updated CLI with new command support and configuration options

### Tests

#### New Test Files (~6,391 lines)
- `tests/swarm/auto-split.test.ts` — Pre-dispatch auto-split heuristics, LLM judge parsing, config defaults (11 tests)
- `tests/swarm/anti-death.test.ts` — Death spiral prevention, hollow termination, probe model fallback
- `tests/swarm/artifact-inventory.test.ts` — Post-swarm artifact collection and reporting
- `tests/swarm/cascade-timing.test.ts` — Cascade skip timing, artifact-aware skip, partial dependency threshold
- `tests/swarm/decision-traceability.test.ts` — Per-attempt records, resilience events, decision logging
- `tests/swarm/resilience-all-paths.test.ts` — All resilience recovery paths (micro-decompose, degraded acceptance, auto-split)
- `tests/swarm/resume-recovery.test.ts` — Session resume, checkpoint restore, wave recovery
- `tests/swarm/swarm-orchestrator-resilience.test.ts` — Orchestrator-level resilience integration tests
- `tests/integrations/bash-policy.test.ts` — Bash command classification, read-only detection, mutation patterns
- `tests/integrations/policy-engine.test.ts` — Policy resolution, profile merging, override precedence

#### Modified Test Files
- `tests/swarm/model-selector.test.ts` — Added 7 new tests for hollow tracking, quality rejection, write capability
- `tests/swarm/swarm-quality-gate.test.ts` — Enhanced quality gate test coverage
- `tests/swarm/swarm-quality-death-spiral.test.ts` — Death spiral detection improvements
- `tests/swarm/swarm-hollow-completion.test.ts` — Hollow completion handling updates
- `tests/swarm/foundation-and-gaps.test.ts` — Foundation task detection tests
- `tests/swarm/config-loader.test.ts` — Extended config loading tests
- `tests/swarm/types.test.ts` — New type validation tests
- `tests/swarm/worker-prompts.test.ts` — Worker prompt generation tests
- `tests/economics.test.ts` — Economics system test updates
- `tests/smart-decomposer-deps.test.ts` — Decomposer dependency mapping tests
- `tests/tool-recommendation.test.ts` — Tool recommendation test updates

### Documentation

- `docs/swarm-mode.md` — Updated swarm mode documentation
- `docs/swarm/configuration-guide.md` — Extended configuration guide with new options
- `docs/swarm/examples/quality-focused.yaml` — Quality-focused swarm configuration example

## [0.2.2] - 2026-02-10

### Added

#### Swarm Hollow Completion Fix & Dashboard Improvements

- **Phase progress events** — Swarm orchestrator now emits `swarm.phase.progress` events during decomposition, scheduling, and planning phases, making the 4-5 minute pre-execution delay visible in the dashboard instead of a silent wait.
- **`write` worker capability** — New capability type for synthesis/merge tasks. Merge subtasks now map to `write` instead of `code`, enabling dedicated synthesizer workers. Falls back to `code` workers when no `write`-capable worker exists.
- **Capability normalization** — YAML configs now accept aliases: `refactor`→`code`, `writing`/`synthesis`/`merge`→`write`, `docs`→`document`, etc. Unknown capabilities are silently dropped with fallback to `['code']`.
- **Task-type system prompts** — Workers receive role-appropriate instructions: research tasks get "RESEARCH TASK RULES" (no coding, use web_search), merge tasks get "SYNTHESIS TASK RULES" (no re-research, work with given material), document tasks get "DOCUMENTATION TASK RULES". Code/test/refactor tasks preserve the original ANTI-LOOP RULES unchanged.
- **Flat-DAG detection** — Orchestrator logs a warning when decomposition produces zero dependency edges across 3+ tasks, helping diagnose ordering issues.
- **Model failover write fallback** — `selectAlternativeModel()` now falls back to code workers for `write` capability, matching the happy-path fallback in `selectWorkerForCapability()`.
- **Tool call count in task events** — `swarm.task.completed` events now include `toolCalls` count, persisted in per-task detail files for dashboard drill-down.

### Fixed

- **Hollow completion check no longer kills research tasks** — `isHollowCompletion()` is now task-type-aware: research, analysis, and design tasks with 0 tool calls but substantial text output (200+ chars) are treated as valid completions instead of being rejected and retried with contradictory "You MUST use tools" feedback.
- **Dependency resolution** — `convertLLMResult()` now resolves multiple LLM reference patterns (integer indices, `task-N`, `subtask-N`, `st-N`, descriptions). Invalid/unresolvable references are filtered instead of kept as dangling strings. Self-dependencies are removed.
- **Decomposition prompt** — Rewritten to mandate integer indices for dependencies, includes 2 concrete examples (parallel research + merge, sequential chain), and explicitly instructs LLMs to create merge tasks for independent subtasks.

### Improved

- **Dashboard event feed auto-scroll** — Auto-scroll now detects when user has scrolled up and pauses, resuming when scrolled back to bottom. Stable event keys prevent DOM thrashing.
- **Dashboard worker timeline** — Now shows dispatched (in-progress) tasks with estimated elapsed time, not just completed tasks.
- **Dashboard task inspector** — Shows tool call count from worker output. Auto-loads detail for failed tasks so users can immediately see what went wrong. Load button available for both completed and failed tasks.

### Tests

- 3 new/modified test files with 16+ new tests:
  - `tests/smart-decomposer-deps.test.ts` (7 tests) — dependency resolution patterns
  - `tests/swarm/worker-prompts.test.ts` (6 tests) — task-type prompt branching
  - `tests/swarm/model-failover.test.ts` (3 tests) — write capability failover
  - `tests/swarm/swarm-hollow-completion.test.ts` — 5 new tests for research/analysis/design task exemption
  - Updated: `types.test.ts`, `model-selector.test.ts`, `config-loader.test.ts`

#### Phase 1: Bug Fixes & Hardening

- **Enhanced tool batching algorithm** (`src/agent.ts`) — Replaced consecutive-grouping with accumulate-and-flush pattern. Parallelizable tools now accumulate until a non-parallelizable tool flushes them as a batch. Example: `[read1, read2, write, read3, grep]` produces 3 batches instead of 4, reducing sequential overhead.
- **Conditional parallel writes** (`src/agent.ts`) — `write_file` and `edit_file` on different files can now execute in parallel. File-path conflict detection prevents concurrent writes to the same file. Safe MCP tools (`dangerLevel: 'safe'`) are auto-added to the parallel set.
- **Fuzzy doom loop detection** (`src/integrations/economics.ts`) — New `computeToolFingerprint()` extracts primary arguments (path, command, pattern) for fingerprint-based similarity detection. Catches near-identical tool calls (e.g., same file with minor arg variations) at threshold+1 (4 instead of 3) to avoid false positives.
- **Plan mode bash allowlist** (`src/modes.ts`) — Replaced blocklist approach with a strict allowlist for bash commands in plan mode. Defines `SAFE_BASH_PATTERNS` (ls, cat, grep, git status, etc.) and `DANGEROUS_SUFFIXES` (pipes to rm, redirects, -exec). Only commands matching safe patterns AND not matching dangerous suffixes pass through.
- **Duration budget network fix** (`src/agent.ts`) — LLM API call time no longer counts against the agent's duration budget. `economics.pauseDuration()` before provider calls and `resumeDuration()` after, so only agent "thinking time" is measured.

#### Phase 2: Orchestration Enhancements

- **Structured delegation protocol** (`src/integrations/delegation-protocol.ts`) — New `DelegationSpec` interface with `objective`, `context`, `outputFormat`, `toolGuidance`, `boundaries`, `successCriteria`, and `siblingContext` fields. `buildDelegationPrompt()` converts specs into structured subagent prompts. `createMinimalDelegationSpec()` for quick delegation. `DELEGATION_INSTRUCTIONS` constant for orchestrator system prompts. `getDefaultToolsForAgent()` maps agent types to recommended tool sets.
- **Complexity classifier** (`src/integrations/complexity-classifier.ts`) — Heuristic task complexity assessment using 6 weighted signals: task length (0.15), complex keywords (0.25), simple keywords (0.2), dependency patterns (0.2), question vs action (0.1), scope indicators (0.1). Classifies into `simple`, `medium`, `complex`, or `deep_research` tiers. `getScalingGuidance()` returns execution recommendations (agent count, tool budget, swarm eligibility).
- **Tool recommendation engine** (`src/integrations/tool-recommendation.ts`) — `ToolRecommendationEngine` class with task-type to tool-category mapping via `TASK_TYPE_TOOL_MAP`. Supports MCP keyword matching (`MCP_KEYWORD_PATTERNS`) for playwright, sqlite, context7, serper, and github tools. Static `inferTaskType()` maps agent names to task types. `getToolFilterForAgent()` provides filtered tool sets per agent.
- **Injection budget manager** (`src/integrations/injection-budget.ts`) — Priority-based budget allocation for context injections. Default 1500-token budget with 8 priority levels: `budget_warning`(0), `timeout_wrapup`(0), `doom_loop`(1), `failure_context`(2), `learning_context`(2), `recitation`(3), `exploration_nudge`(4), `phase_guidance`(4). Partial truncation for partially-fitting proposals (>100 tokens remaining). Stats tracking with `getLastStats()`.

#### Phase 3: Advanced Capabilities

- **Thinking/reflection strategy** (`src/integrations/thinking-strategy.ts`) — Prompt engineering directives for strategic thinking. `generateThinkingDirectives()` produces pre-action, post-tool, and quality-check prompts based on complexity tier. `getThinkingSystemPrompt()` for parent agents, `getSubagentQualityPrompt()` for child agents. Configurable `minComplexityTier` (default: `medium`).
- **Subagent output store** (`src/integrations/subagent-output-store.ts`) — Filesystem + memory store for subagent outputs, bypassing the coordinator "telephone problem." Full outputs saved to `.agent/subagent-outputs/{id}.json` + `.md`. Parent receives lightweight summaries + references instead of full output. Auto-cleanup when store exceeds `maxOutputs` (default 100). `getSummary()` includes structured report data (findings, actions, failures).
- **Self-improvement protocol** (`src/integrations/self-improvement.ts`) — Error pattern matching with 7 categories: `file_not_found`, `permission`, `timeout`, `syntax_error`, `missing_args`, `wrong_args`, `state_error`. `diagnoseToolFailure()` returns structured diagnosis with suggested fixes. `enhanceErrorMessage()` adds contextual diagnosis and repeated-failure warnings. Persists to LearningStore after 3+ failures of same tool.
- **MCP tool validator** (`src/integrations/mcp-tool-validator.ts`) — Quality scoring (0-100) for MCP tool descriptions with 6 checks: description exists, is informative (not restated name), has property descriptions, specifies required params, includes examples, follows naming conventions. `validateAllTools()` sorts by score. `formatValidationSummary()` for human-readable reports. Default pass threshold: 40.
- **MCP custom tools** (`src/integrations/mcp-custom-tools.ts`) — Factory for standalone API wrapper tools. `createSerperSearchTool()` for web search via SerperAPI (env: `SERPER_API_KEY`) with abort controller timeout. Generic `createCustomTool()` factory for any HTTP API with retry support. `createCustomTools()` for batch creation. `customToolToRegistryFormat()` for tool registry integration.

#### Phase 4: Future Architecture (Standalone Modules)

- **Async subagent execution** (`src/integrations/async-subagent.ts`) — `createSubagentHandle()` wraps spawn promises with `isRunning()`, `requestWrapup()`, `cancel()`, `getProgress()`, and `onProgress()`. `SubagentSupervisor` class manages multiple concurrent handles: `add()`, `remove()`, `getActive()`, `getCompleted()`, `waitAll()`, `waitAny()`, `cancelAll()`, `stop()`. Periodic `checkAgents()` enforces `maxDurationMs` and token budget wrapup thresholds.
- **Auto-checkpoint resumption** (`src/integrations/auto-checkpoint.ts`) — `AutoCheckpointManager` with filesystem persistence to `.agent/checkpoints/{sessionId}/`. `save()` respects `minInterval` (30s default), strips messages to keep checkpoints small. `findResumeCandidates(maxAgeMs)` detects recent sessions (default 5min). `cleanupAll()` respects `maxAge` (1hr default) and `maxPerSession` limits.
- **Dynamic budget rebalancing** (`src/integrations/dynamic-budget.ts`) — `DynamicBudgetPool` extends `SharedBudgetPool` with starvation prevention. Priority multipliers: `low`(0.5x), `normal`(1.0x), `high`(1.5x), `critical`(2.0x). `reserveDynamic()` caps at 60% of remaining budget and reserves for expected children. `setExpectedChildren()` enables fair allocation. `releaseDynamic()` returns unused budget. `createDynamicBudgetPool()` factory with configurable parent reserve ratio (default 25%).

#### Tests

- **13 new/modified test files** with 240 tests covering all Phase 2-4 modules:
  - `tests/delegation-protocol.test.ts` (29 tests) — prompt building, minimal specs, delegation instructions, integration
  - `tests/complexity-classifier.test.ts` (37 tests) — classification, signals, recommendations, scaling guidance, edge cases
  - `tests/thinking-strategy.test.ts` (27 tests) — directives, system prompts, quality prompts, tier ordering
  - `tests/tool-recommendation.test.ts` (16 tests) — task-type recommendations, MCP matching, sorting, inferTaskType
  - `tests/injection-budget.test.ts` (13 tests) — allocation, priority sorting, truncation, stats, budget updates
  - `tests/self-improvement.test.ts` (18 tests) — all 7 failure categories, tracking, caching, enhancement
  - `tests/mcp-tool-validator.test.ts` (12 tests) — quality checks, scoring, validation summary
  - `tests/mcp-custom-tools.test.ts` (11 tests) — serper tool, custom tools, registry conversion
  - `tests/subagent-output-store.test.ts` (12 tests) — save/load, filtering, summaries, auto-cleanup
  - `tests/async-subagent.test.ts` (16 tests) — handles, supervisor, waitAll/waitAny, cancellation
  - `tests/auto-checkpoint.test.ts` (13 tests) — save/load, interval throttling, resume candidates, cleanup
  - `tests/dynamic-budget.test.ts` (14 tests) — allocation, caps, priority, release, stats, factory

### Changed
- **Integrations barrel** (`src/integrations/index.ts`) — New exports for all Phase 2-4 modules: delegation protocol, complexity classifier, tool recommendation, injection budget, thinking strategy, subagent output store, self-improvement, MCP tool validator, MCP custom tools, async subagent, auto-checkpoint, dynamic budget.
- **Tool batching** (`src/agent.ts`) — `groupToolCallsIntoBatches()` rewritten with accumulate-and-flush algorithm and file-path conflict detection for conditional parallelism.
- **Doom loop detection** (`src/integrations/economics.ts`) — `updateDoomLoopState()` now uses fingerprint-based fuzzy matching in addition to exact-match detection.
- **Plan mode security** (`src/modes.ts`) — `shouldInterceptTool()` switched from blocklist to allowlist for bash commands.


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

[Unreleased]: https://github.com/eren23/attocode/compare/v0.2.4...HEAD
[0.2.4]: https://github.com/eren23/attocode/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/eren23/attocode/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/eren23/attocode/compare/v0.2.1...v0.2.2
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
