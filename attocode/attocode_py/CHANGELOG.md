# Changelog

All notable changes to the Attocode Python agent will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
