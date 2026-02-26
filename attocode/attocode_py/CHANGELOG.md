# Changelog

All notable changes to the Attocode Python agent will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.3] - 2026-02-26

### Added

- **Recording integration** — `integrations/recording/` with `RecordingSessionManager` for session capture; `--record` CLI flag and `record` config option; HTML export for visual replay
- **Codebase tools** — `tools/codebase.py` with `get_repo_map`, `get_tree_view`; auto-registered when codebase context is available; preseed repo map injected on first run so the LLM has project structure from turn 1
- **AST services** — `ast_service.py`, `cross_references.py` with `ASTService`, `CrossRefIndex`, `SymbolLocation`, `SymbolRef`; exported from context integration
- **Model cache** — `providers/model_cache.py` with `init_model_cache()` and model context-window lookup; replaces hardcoded 200k default with per-model values
- **attoswarm coordinator** — `coordinator/aot_graph.py`, `event_bus.py`, `orchestrator.py`, `subagent_manager.py`; `workspace/file_ledger.py`, `reconciler.py` for multi-agent file coordination
- **attoswarm TUI** — Swarm dashboard, focus screen, timeline screen; `swarm_bridge.py`; `swarm/` widgets; `swarm.tcss` styles
- **CLI** — `--version` flag; `--record` flag
- **Config** — `record` option for session recording

### Changed

- **Conversation persistence** — Messages persist across TUI runs; subsequent prompts carry over prior conversation; `/clear` resets conversation history in addition to screen
- **Doom loop blocking** — Tool calls identical 5+ times are hard-blocked before execution with `LoopDetector.peek()`; blocked calls return structured error for the LLM
- **Completion analysis** — Removed future-intent and incomplete-action heuristics from `analyze_completion()`
- **Tool events** — `TOOL_START`, `TOOL_COMPLETE`, `TOOL_ERROR` now include `args` and `iteration` metadata
- **Codebase context** — Extended with preseed map, symbol extraction; `get_preseed_map()` for first-turn injection

### Tests

- `test_aot_graph.py`, `test_event_bus.py`, `test_file_ledger.py`, `test_reconciler.py`, `test_stores.py` — attoswarm coordinator and workspace
- `test_ast_service.py` — AST service
- `test_model_cache.py` — model cache pricing and context lookup
- `test_recording/` — recording integration
- Updated `test_codebase_context.py`, `test_completion.py`, `test_anthropic.py`, `test_attoswarm_snapshots.py`

## [0.1.2] - 2026-02-24

### Added

- **`attoswarm` package** — standalone hybrid swarm orchestrator with file-based coordination protocol
  - `coordinator/loop.py` — `HybridCoordinator` main loop with task state machine, dependency DAG, watchdog, budget enforcement
  - `coordinator/scheduler.py` — dependency-aware task assignment matching roles to free agents
  - `coordinator/merge_queue.py` — completion claim tracking with judge/critic quality gates
  - `coordinator/state_writer.py` — atomic state snapshot persistence
  - `coordinator/budget.py` — token + cost tracking with hard-limit enforcement
  - `coordinator/watchdog.py` — heartbeat-based agent health monitoring
  - `adapters/` — subprocess-based agent adapters for Claude, Codex, Aider, and Attocode backends with stdin/stdout line protocol
  - `protocol/` — `TaskSpec`, `RoleSpec`, `SwarmManifest`, `InboxMessage`, `OutboxEvent` models; atomic JSON I/O; file-based locks
  - `workspace/worktree.py` — git worktree isolation per agent with branch lifecycle and graceful fallback when `.git` missing
  - `config/` — YAML config loader with `SwarmYamlConfig` schema (roles, budget, merge, orchestration, watchdog, retries)
  - `cli.py` — Click CLI with `run`, `start`, `tui`, `resume`, `inspect`, `doctor`, `init` commands
  - `tui/` — Textual dashboard for live run monitoring (phase, tasks, agents, events)
  - `replay/` — `attocode_bridge.py` for replaying swarm runs
  - Decomposition modes: `manual`, `fast`, `parallel`, `heuristic`, `llm` (falls back to `parallel`)
  - Heartbeat wrapper script with `[HEARTBEAT]`/`[TASK_DONE]`/`[TASK_FAILED]` protocol markers and debug mode
  - Task state machine: `pending → ready → running → reviewing → done/failed` with transition validation
- **`attocode_core` package** — shared utilities extracted for cross-package use
  - `ast_index/indexer.py` — `CodeIndex.build()` scans Python/TS/JS files for symbols (functions, classes, imports)
  - `dependency_graph/graph.py` — `DependencyGraph.from_index()` with `impacted_files()` transitive closure
- **TUI swarm monitor** (`src/attocode/tui/screens/swarm_monitor.py`) — fleet-level Textual screen
  - Auto-discovers runs via `**/swarm.state.json` glob
  - Fleet view with phase, task counts, agent counts, error counts
  - Per-run detail: tasks table (state, kind, role, attempts, title, error), events table (heartbeat/stderr filtered), agents table (CWD, restarts)
  - Budget display in title bar (tokens + USD)
  - File change events shown inline in events table
  - `Ctrl+M` binding and `/swarm-monitor` command
- **CLI hybrid swarm integration**
  - `--hybrid` flag routes to `attoswarm` coordinator
  - `attocode swarm <subcommand>` passthrough (start, run, doctor, init, tui, inspect, resume)
  - `attocode swarm monitor` aliased to `attoswarm tui`
- **`TraceVerifier`** (`tests/helpers/trace_verifier.py`) — post-run integrity checker
  - 7 checks: poisoned prompts, task transition FSM, terminal events, stuck agents, budget limits, exit code propagation, coding task output evidence
  - `run_all()` + `summary()` for CI/manual use
- **`SyntheticRunSpec`** test fixtures (`tests/helpers/fixtures.py`) — builds complete fake run directories for deterministic TUI/integration testing
- **Example config** (`.attocode/swarm.hybrid.yaml.example`) — ready-to-copy hybrid swarm config
- **Operations guide** (`docs/hybrid-swarm-operations.md`) — runbook covering prerequisites, commands, observability, configs, test matrix, TUI ops, failure modes
- **`swarm-verify` skill** (`.attocode/skills/swarm-verify/`) — skill for verifying swarm run integrity
- **File change detection on task completion** — `_detect_file_changes()` runs `git diff --name-only HEAD` + `git ls-files --others` in agent worktree, emits `task.files_changed` event
- **Workspace mode in spawn events** — `agent.spawned` events include `cwd`, `workspace_mode`, `workspace_effective`

### Changed

- `_run_single_turn()` now exits with code 1 when `result.success` is False
- Version test no longer asserts specific version number

### Tests

- **`tests/unit/attoswarm/`** (9 files, ~60 tests) — scheduler dependency resolution, worktree creation/fallback/cleanup, heartbeat wrapper generation, merge queue roundtrip, budget overflow, CLI commands, adapter parsing, resume, spawn logging
- **`tests/unit/attocode_core/`** (1 file) — `CodeIndex.build()` Python symbol extraction
- **`tests/unit/tui/test_attoswarm_snapshots.py`** (5 snapshot tests) — empty init, executing, completed, failed with errors, many agents
- **`tests/unit/test_trace_verifier.py`** (22 tests) — all 7 verifier checks with pass/fail cases
- **`tests/integration/test_attoswarm_smoke.py`** — deterministic smoke tests using fake worker scripts
- **`tests/integration/test_attoswarm_live_smoke.py`** — opt-in live backend tests (`ATTO_LIVE_SWARM=1`)
- **`tests/unit/test_cli.py`** — swarm passthrough dispatch, exit code propagation (success + failure)

## [0.1.1] - 2026-02-22

### Fixed

- **Dashboard CSS ID mismatch** — Tab bar (`#dashboard-tab-bar`) and footer bar (`#dashboard-footer-bar`) were unstyled because CSS selectors targeted non-existent `#dashboard-header` and `#dashboard-footer` IDs. Selectors now match the actual widget IDs rendered in `DashboardScreen.compose()`.
- **Deleted files silently failing in incremental AST updates** — `CodebaseContextManager.update_dirty_files()` would throw on `Path.read_text()` for deleted files and silently `continue`, leaving the file permanently in `_dirty_files`. Now checks `Path.exists()` first; if deleted, removes the file from `_ast_cache`, `_file_mtimes`, and all forward/reverse dependency graph edges, and emits `SymbolChange(kind="removed")` for each symbol so downstream consumers are notified.
- **Memory leak from empty sets in reverse dependency graph** — After `rev.discard(rel_path)`, empty sets remained as keys in `_dep_graph.reverse`. Now cleaned up with `del self._dep_graph.reverse[target]` when the set becomes empty.
- **Dead code in `loop.py`** — Removed unreachable `_codebase_ast` and `_code_analyzer` invalidation branches in `_handle_file_edit()`. These attributes are never initialized on the agent context; only the `codebase_context.mark_file_dirty()` + `update_dirty_files()` path is live.

### Added

- **LLM streaming events wired to live dashboard** — `LLMStreamEnd` events (the majority of LLM calls) now feed `LiveTraceAccumulator.record_llm()`. Previously only non-streaming `LLMCompleted` events were tracked, making the live dashboard blind to most LLM activity.
- **Budget warning tracking in live dashboard** — `LiveTraceAccumulator` now has `budget_warnings` and `last_budget_pct` fields. `on_budget_warning()` feeds these, and the Session Stats box in the live dashboard displays budget warning count and last reported percentage.
- **JS/TS class method extraction** — `parse_javascript()` now tracks `current_class` with brace depth and extracts methods into `ClassDef.methods`, matching the Python parser's behavior. Previously JS class methods were invisible to `diff_file_ast()` and the repo map.
- **JS/TS function return type capture** — `parse_javascript()` now captures return type annotations (e.g., `: Promise<void>`) for both top-level functions and class methods via an extended regex pattern.
- **Session sorting in browser** — Session browser pane supports `s` key to cycle through sort modes: newest first (default), cost descending, efficiency descending, iterations descending. Sort is applied after text filtering.
- **Per-iteration cost column in token flow view** — Token flow table in session detail now shows an "Iter Cost" column (`cumulative_cost - prev_cost`) alongside the existing cumulative cost, making it easy to identify expensive iterations.
- **Empty/loading states for dashboard panes** — Session detail shows "Select a session from the Sessions tab to view details." when no session is loaded. Compare pane shows updated guidance. Session browser shows descriptive message when no trace directory or files exist.

### Tests

- **`test_live_dashboard.py`** (14 tests) — `LiveTraceAccumulator`: LLM recording, rolling windows, tool counting, error tracking, cache rate calculation, top tools sorting, empty defaults, iteration recording, budget warning fields.
- **`test_viz_widgets.py`** (27 tests) — `SparkLine`: empty/single/uniform/normal data, max width. `BarChart`: empty/single/aligned items, zero values. `PercentBar`: 0%/50%/100%/clamped values, threshold colors (green/yellow/red), labels. `ASCIITable`: empty/single row, alignment, separator, missing cells, content height. `SeverityBadge`: all severity levels, unknown fallback, case insensitivity, bracket formatting.
- **`test_analysis.py`** (22 tests) — `SessionAnalyzer`: summary metrics, efficiency score range, zero-iteration safety, timeline ordering/structure, token flow cumulative cost/sorting, tree grouping by iteration. `InefficiencyDetector`: excessive iterations (spinning detection, no false positives with tools), repeated tool calls (doom loop, threshold), token spikes (detection, uniform data). `TokenAnalyzer`: cache efficiency, token breakdown, total cost, cost by iteration, token flow points.
- **`test_dashboard_panes.py`** (21 tests) — `SessionInfo` dataclass creation and slots. `DashboardScreen`: tab definitions, keys, labels, pane IDs, default/custom init, tab cycling math, detail flag. `SessionDetailPane`: sub-tab keys and labels. `ComparePane`: initial state.

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
