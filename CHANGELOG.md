# Changelog

All notable changes to the Attocode Python agent will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Agent module extraction** — `agent.py` split into 5 focused modules: `checkpoint_api.py` (checkpoint/undo), `mcp_connector.py` (MCP server wiring), `run_context_builder.py` (full run-context init), `subagent_api.py` (spawn/delegate), `swarm_runner.py` (swarm entry point)
- **Code-intel tool modules** — 15 MCP tools from monolithic `server.py` organized into `tools/analysis_tools.py`, `navigation_tools.py`, `search_tools.py`, `lsp_tools.py`, `learning_tools.py`
- **Code-intel helpers** (`code_intel/helpers.py`) — 15+ pure functions for complexity scoring, convention detection, tech-stack identification, and framework pattern matching
- **Config validator** (`config_validator.py`) — early fail-fast validation of provider, model, API key format, and working directory before agent init
- **Database migrations** (`persistence/migrations.py`) — schema versioning with `check_and_migrate()`; v1→v2 adds `usage_logs` table
- **Async AST initialization** (`ast_service.py`) — `async_initialize(batch_size=50)` parses files concurrently via `asyncio.to_thread()`
- **Swarm coordinator extraction** — `loop.py` split into `failure_handler.py`, `output_harvester.py`, `review_processor.py`, `task_dispatcher.py`
- **Task retry logic** (`orchestrator.py`) — per-task attempt tracking, per-task timeouts, AST reconciliation wiring
- **AST-aware conflict resolution** (`file_ledger.py`) — 3-way merge with base snapshots; reduces false-positive OCC conflicts when parallel agents edit non-overlapping regions
- **Robust JSON task parser** (`task_parser.py`) — 3-strategy fallback (direct → cleaned → balanced brackets) for LLM task decomposition output
- **Adapter output parsing** — `aider.py`, `claude.py`, `codex.py` adapters now extract tokens/cost from subprocess stdout; all adapters gain static `build_command()` methods
- **Updated model registry** (`models.yaml`) — added Claude Opus 4.6, Sonnet 4.6, o3, o4-mini; fixed Haiku 4.5 date; removed deprecated gpt-4-turbo

### Changed

- **Model registry externalized** — hardcoded `BUILTIN_MODELS` dict in `providers/base.py` replaced with `models.yaml`; loader uses `_load_builtin_models()` from YAML
- **CI pipeline** (`.github/workflows/ci.yml`) — added mypy type checking, pytest coverage reporting, and codecov upload (gated on Python 3.12)
- **CLI entry point** (`cli.py`) — calls `validate_config()` before agent initialization
- **SessionStore** (`store.py`) — runs `check_and_migrate()` on init for forward-compatible schema
- **GLM-5 provider** — fixed `zhipu` → `zai` in model registry to match codebase convention

### Internal

- `agent.py` reduced from ~840L to ~430L (delegates to extracted modules)
- `code_intel/server.py` reduced by ~2,200L (tools + helpers extracted)
- `coordinator/loop.py` reduced from ~1,500L to ~970L (4 modules extracted)
- `attoswarm/cli.py` task parsing extracted to `task_parser.extract_json_array()`
- No public API changes — all extractions are internal reorganization

### Planned

- Execution backend abstraction (`BaseEnvironment` ABC with Local/Docker/SSH/Singularity/Modal backends)
- Fix `attoswarm tui` not picking up new TUI widgets when installed via `uv tool install`
- Enabling code understanding tools of attocode to other AI coders as a skill system

## [0.1.16] - 2026-03-06

### Added

- **Graph visualization commands** — `/graph`, `/deps`, `/impact`, `/hotspots` slash commands for interactive codebase graph exploration
- **Graph screen** (`tui/screens/graph_screen.py`) — dedicated TUI screen for dependency graph, impact analysis, and hotspot heatmap visualization
- **Repo overview widget** (`tui/widgets/repo_overview.py`) — interactive codebase tree with fuzzy search, lazy symbol loading, language bar chart
- **Dependency graph widget** (`tui/widgets/dependency_graph.py`) — tree-based dependency visualization
- **Hotspot heatmap widget** (`tui/widgets/hotspot_heatmap.py`) — visual heatmap of code complexity hotspots
- **Impact graph widget** (`tui/widgets/impact_graph.py`) — blast radius visualization for file changes
- **Fuzzy search in repo overview** — search files and symbols with fuzzy matching, auto-expand on symbol match, single-char guard
- **Constants in symbol search** — `top_level_vars` now indexed in fuzzy search and visible in expanded tree nodes
- **5 new MCP code-intel tools** — `graph_query`, `find_related`, `community_detection` + enhancements to existing tools

### Changed

- `symbol_count` property now includes `top_level_vars` (consistent with `get_symbols()`)
- License changed from MIT to custom Attocode License (free for personal use and small teams; larger commercial use requires notification)

### Fixed

- Constants searchable but not visible when expanding tree nodes in repo overview
- Tautological auto-expand tests replaced with score-based assertions

### Tests

- 21 fuzzy search tests (`tests/unit/tui/test_fuzzy_search.py`)

## [0.1.15] - 2026-03-06

### Added

- **Vision support**: `vision_analyze` tool for analyzing images via vision-capable LLMs (accepts URLs, file paths, or base64 data)
- **Inline image support in TUI**: drag-drop or paste image paths into the prompt; images are extracted, base64-encoded, and sent as `ImageContentBlock` alongside text
- **Image path extraction** (`tools/image_utils.py`): `extract_image_paths()` handles bare paths, quoted paths, and macOS backslash-escaped drag-drop paths; `load_image_to_source()` with size/path validation
- **OpenRouter provider preferences**: `OpenRouterPreferences` dataclass for controlling upstream provider routing (order, only, ignore, sort, quantizations, max_price)
- **Model capabilities cache**: `is_vision_capable()` and `get_cached_capabilities()` in `model_cache.py`, populated from OpenRouter `/api/v1/models` architecture data
- **ZAI vision-disable safety**: ZAI provider automatically strips image blocks before sending to GLM models (text-only endpoint); agent sets user-facing warning via `pop_image_warning()`
- **Azure vision support**: `_format_message()` properly converts `ImageContentBlock` to Azure's `image_url` content part format
- **OSS demo eval harness** (`eval/oss_demo/`): manifest-driven benchmarking for multi-agent code-intel tasks with YAML config, result validation, and Markdown report generation

### Changed

- **DRY extraction**: Shared `providers/openai_compat.py` module for `format_openai_content()`, `format_openai_messages()`, `describe_request_error()` — deduplicated from OpenRouter and OpenAI providers
- **Vision tool security hardening**: `danger_level` changed from `SAFE` to `MODERATE`; path traversal protection (resolve against working directory); SSRF protection (reject non-HTTPS URLs and private/internal IPs)
- **Vision provider no longer cached permanently** — provider is created per call, avoiding stale state after model or API key changes
- **ZAI `_strip_images` uses deny-list filter** — filters out `ImageContentBlock` instead of allow-listing `TextContentBlock`, so future block types pass through safely
- **ZAI all-image messages get placeholder** — instead of being silently dropped, all-image messages are replaced with a `[image removed]` placeholder to preserve conversation turn structure
- **ZAI image stripping DRY** — extracted `_maybe_strip_images()` helper shared by `chat()` and `chat_stream()`, eliminating duplicated check-and-strip logic
- **TUI vision check removed** — duplicated vision capability check in `app.py` removed; agent is now the single authority for vision checks; TUI surfaces warnings via `pop_image_warning()` after agent completion

### Fixed

- **Image handling in OpenRouter/OpenAI/Anthropic providers**: `_format_content()` now properly converts `ImageContentBlock` to provider-specific dicts; unknown block types fall back to text representation instead of sending raw dataclass instances; Anthropic URL-source images now use correct `{"type": "url", "url": ...}` format
- **OpenRouter preferences crash on unknown config keys**: `OpenRouterPreferences` construction now filters unknown keys from user config instead of raising `TypeError`
- **Vision tool registration silently swallowing exceptions**: Now logs a warning when the vision tool fails to register
- **TUI accessing private provider/config attributes** — removed `_provider` and `_config` access from TUI; uses public `pop_image_warning()` API instead
- **`pop_image_warning()` was dead code** — now wired into TUI's `on_agent_completed` handler
- **Redundant `MessageLog` query** in `on_prompt_input_submitted` — consolidated to single query

### Tests

- 60 vision tests in `test_vision_tool.py`: input detection, URL/path validation, tool spec, tool execution (local file, base64, URL rejection, SSRF), image path extraction (bare, quoted, escaped, multi-image, drag-drop), `load_image_to_source`, `build_initial_messages` with images, ZAI vision-disabled (strip from chat, strip from chat_stream, all-image placeholder, multi-text-block preservation, warning log assertion, agent pop_image_warning lifecycle), Azure format, vision capability cache
- `test_model_cache.py`: ZAI vision model recognition, text-only exclusion, known model coverage
- `test_openai.py`: content formatting for text and image blocks
- `test_openrouter.py`: preferences construction, unknown key filtering, model capabilities caching
- `test_eval_oss_demo.py`: manifest loading, result validation, report generation

## [0.1.14] - 2026-03-05

### Added

- **Release guard workflow checks** in GitHub Actions:
  - Tag `vX.Y.Z` must match `project.version` in `pyproject.toml`
  - Tag `vX.Y.Z` must match `attocode.__version__`
  - Release aborts if `attocode==X.Y.Z` is already published on PyPI
- **New slash command reliability coverage** (`tests/unit/test_commands_reliability.py`) to validate routed commands pre/post run, command palette routing, and mode/thread persistence.
- **Tool-call diagnostics and resilience events**:
  - Suspicious streamed pseudo-tool markup detection (`tool.markup.suspicious`)
  - Streamed-vs-executed command mismatch detection (`tool.call.mismatch`)
  - Loop-guard activation events (`tool.loop_guard.activated`)

### Changed

- Bumped package version from `0.1.13` to `0.1.14`
- Slash commands now bootstrap a lightweight command context before first prompt, so command features are available earlier.
- Added `/tasks` and `/debug` command handlers and aligned help/palette key hints with current TUI bindings (`Ctrl+T`, `Ctrl+I`).
- Subagent spawning now uses `SubagentSpawner` budget/time controls and returns structured error details.
- Approval "always allow" behavior now uses scoped argument patterns instead of broad command-name grants.
- TUI now surfaces warning-status events for tool-markup drift and loop-guard activation.

### Fixed

- `Plan mode` and `file tracking` unavailable messages no longer suggest unsupported `/config set ...` toggles.
- Policy evaluation now applies bash risk classification for explicit deny on blocked commands.
- Session permission replay no longer restores legacy wildcard bash grants.
- Repeated failing `spawn_agent` calls now switch to local fallback mode instead of repeatedly retrying broken subagent flows.

### Tests

- Added targeted coverage for policy pattern grants, bash block rules, approval bridge scoped grants, markup diagnostics, loop-guard blocking, and subagent fallback behavior.

## [0.1.13] - 2026-03-05

### Added

- **Swarm dashboard control bar** with Pause/Resume and Cancel actions (`SwarmControlBar`)
- **Task-level swarm controls** in Tasks tab: skip pending/ready task (`s`) and retry failed task (`r`)
- **Swarm orchestrator runtime controls**: `pause()`, `resume()`, `skip_task()`, and `retry_task()`
- **Live swarm event callback bridge** for immediate TUI refresh and timeline/event-log updates
- **Extended swarm panel telemetry**: quality counters and budget burn-rate ETA
- **Semantic embedding provider selection** via `ATTOCODE_EMBEDDING_MODEL` and explicit model routing
- **Nomic local embedding provider** (`nomic-ai/nomic-embed-text-v1.5`) and `semantic-nomic` optional dependency extra
- **Incremental semantic indexing APIs**: `reindex_file()` and `reindex_stale_files()` with stale/deleted file handling
- **Vector-store file metadata tracking** for indexed mtime/chunk freshness
- **Queue-based semantic reindex tests** (`test_semantic_search.py`) covering dedup and re-queue behavior

### Changed

- `/spawn` now supports optional model override: `/spawn [--model <model>] <task>`
- `/spawn` now executes delegated work asynchronously via `await _spawn_command(...)`
- `SemanticSearchManager` now uses richer chunks (including method-level chunks) and incremental metadata updates
- `VectorStore` now uses SQLite with `check_same_thread=False` plus lock-guarded DB operations
- Swarm dashboard pane updates are now event-driven for faster visible feedback during task lifecycle transitions

### Fixed

- `/spawn` failure reporting now surfaces actual `error` details when present instead of returning blank/partial failures
- Semantic reindex dispatch on file changes no longer creates one thread per change; now uses bounded queued reindexing
- Help/docs drift for `/spawn` syntax corrected to include `--model`
- Duplicate quality rejection counting in swarm event bridge corrected
- Embedding dimension mismatch now auto-invalidates stale vector index content

### Documentation

- Updated slash-command docs for `/spawn [--model <model>] <task>`
- Updated optional dependency docs with `semantic` and `semantic-nomic` extras
- Updated swarm dashboard docs with runtime controls (pause/resume/cancel + task skip/retry)

### Tests

- Added unit tests for semantic reindex queue behavior (`tests/unit/integrations/context/test_semantic_search.py`)
- Verified context integration suite with new tests included

## [0.1.12] - 2026-03-04

### Added

- **2 new MCP code-intel tools** (20 total): `bootstrap` (all-in-one codebase orientation — summary + repo map + conventions + search in one call) and `relevant_context` (subgraph capsule — BFS from center file(s) with neighbor symbols)
- **`notify_file_changed` MCP tool** — agents can explicitly notify the server about file changes, updating AST index and invalidating stale embeddings immediately
- **`attocode://guidelines` MCP resource** — serves `GUIDELINES.md` (tool inventory, progressive disclosure strategy, task workflows, anti-patterns) to any MCP client
- **File watcher + notification queue** — background `watchfiles` watcher auto-updates AST index; fallback queue file (`.attocode/cache/file_changes`) for CLI-based notifications
- **`notify` CLI subcommand** — `attocode-code-intel notify --stdin` reads JSON from PostToolUse hooks or raw file paths; `--file <path>` for explicit notifications; uses `fcntl` file locking
- **PostToolUse hook management** — `install_hooks()` / `uninstall_hooks()` for Claude Code; `--hooks` flag on `attocode code-intel install claude`; tag-based idempotent dedup; matcher format: plain string (`"Edit|Write|NotebookEdit"`)
- **Agent guidelines** (`GUIDELINES.md`) — shipped inside package: tool inventory with token costs, progressive disclosure levels, codebase-size strategies, task-specific workflows, parallel call groupings, LSP fallback table, 10 anti-patterns
- **Tree-sitter parser** (`ts_parser.py`) — unified parser for 9 languages (Python, JS, TS, Go, Rust, Java, Ruby, C, C++) with graceful degradation when `tree-sitter` not installed
- **AST chunker** (`ast_chunker.py`) — structural code chunking at function/method/class boundaries with source extraction; reciprocal rank fusion (RRF) for merging ranked results
- **Graph store** (`graph_store.py`) — SQLite-backed persistent cache for dependency graph, file metadata, and symbol index; content hashing via xxhash; reduces cold start from 5-15s to 0.5-2s
- **Two-stage semantic search** — wide recall (vector top-50 + keyword top-50) merged with RRF; outperforms single-stage on code retrieval benchmarks
- **Incomplete action retry** — execution loop detects narrative-only responses (no tool calls despite claiming work remains) and auto-retries up to 2 times with a system nudge
- **Configurable compaction thresholds** — `compaction_warning_threshold` and `compaction_threshold` in config, `AgentBuilder.with_compaction()` kwargs, wired through CLI
- **Dual-trigger compaction** — monitors both context window usage and economics budget usage; either hitting threshold triggers compaction
- **Force compaction** — `handle_auto_compaction(force=True)` uses `emergency_compact()` for budget recovery; accurate `tokens_saved` computation
- **`apply_budget_extension()`** — atomic budget extension that correctly syncs soft-limit ratio across `_ctx.budget` and `_ctx.economics.budget`; emits `BUDGET_EXTENSION_REQUESTED/GRANTED/DENIED` trace events
- **Budget extension wired in TUI** — `set_extension_handler()` connected to `BudgetExtensionDialog` in `_run_tui()`
- **Lazy session store** — `ensure_session_store()` allows `/sessions`, `/load`, `/resume` to work before the first prompt
- **`/resume` auto-latest** — calling `/resume` with no argument resumes the most recent session
- **`trace-*` session ID guard** — `/load` and `/resume` return clear errors for dashboard trace session IDs (not resumable)
- **TUI status bar dual metrics** — shows `ctx X%` (context window) and `bud X%` (economics budget) separately, each color-coded by threshold; token section shows both `ctx N/M` and `bud N/M`
- **`_sync_status_metrics()`** — single consolidated method replacing 5 duplicated inline status sync blocks in TUI app
- **`tree-sitter` optional extra** — `pip install attocode[tree-sitter]` for 9 language grammars
- **`watch` optional extra** — `pip install attocode[watch]` for `watchfiles` background watcher
- **PageRank importance scoring** — `DependencyGraph.pagerank()` using power iteration (damping=0.85, 20 iterations)

### Changed

- MCP code-intel server expanded from 18 to 20 tools
- `STANDARD_BUDGET.max_tokens`: 1M → 100M tokens (cost `budget_max_cost=10.0` is now the primary constraint)
- `conventions` tool now supports optional directory scoping
- `semantic_search.index()` expands language coverage when tree-sitter grammars are installed
- `ast_service.initialize()` picks up tree-sitter supported languages dynamically
- `/extend` command now calls `agent.apply_budget_extension()` preserving soft-limit ratio
- `tomli_w>=1.0` moved to required dependencies (Codex TOML installer)
- `mcp` moved from `code-intel` extra to required dependencies

### Fixed

- **Hook matcher format** — `_build_hook_config()` produces `"matcher": "Edit|Write|NotebookEdit"` (string), not `{"tool_name": ...}` (dict) which Claude Code rejected with "matcher: Expected string, but received object"
- **Hook dedup on reinstall** — tag-based detection (`_HOOK_TAG` in command) replaces old `entry.get("matcher") == _HOOK_MATCHER` which couldn't match across format changes, causing duplicates
- **Compaction `tokens_saved` always 0** — now accurately computed as `tokens_before - tokens_after`
- **Budget extension discarding soft limit** — previous inline `ExecutionBudget(...)` construction lost the soft-limit ratio; `apply_budget_extension()` preserves it
- **Status bar showing stale/partial metrics** — consolidated `_sync_status_metrics()` ensures all fields update atomically

### Documentation

- README: editable tool install section (`uv tool install --force --editable ...`)
- `docs/getting-started.md`: same editable install section
- `docs/sessions-guide.md`: lazy init note, trace-vs-resumable session clarification
- `docs/troubleshooting.md`: "Edited code but TUI still shows old behavior" section

### Tests

- `test_code_intel.py`: 1,309 new lines — bootstrap, relevant_context, notify, hooks, guidelines resource, file watcher, notification queue
- `test_agent.py`: `apply_budget_extension()`, `ensure_session_store()`, budget extension events
- `test_completion.py`: `_has_incomplete_action`, `_has_future_intent`, new `analyze_completion` checks
- `test_loop.py`: incomplete action retry logic, force compaction, dual-trigger compaction
- `test_cli.py`: compaction threshold wiring
- `test_commands_sessions.py`: lazy store init, `/load trace-*` error, `/resume` auto-latest
- `test_app.py`: `_sync_status_metrics()` consolidation
- `test_widgets.py`: status bar dual-metric display

## [0.1.11] - 2026-03-03

### Added

- **6 new IDE integration targets for code-intel MCP server** — `attocode code-intel install`
  now supports 10 targets (up from 4):
  - **VS Code / GitHub Copilot** (`vscode`) — writes `.vscode/mcp.json`
  - **Claude Desktop** (`claude-desktop`) — writes `claude_desktop_config.json` at
    platform-specific path (macOS, Linux, Windows)
  - **Cline** (`cline`) — writes `cline_mcp_settings.json` in VS Code globalStorage
  - **Zed** (`zed`) — writes `.zed/settings.json` with Zed's `context_servers` format;
    supports `--global` for user-level install
  - **IntelliJ IDEA** (`intellij`) — prints step-by-step manual setup instructions
  - **OpenCode** (`opencode`) — prints step-by-step manual setup instructions
- **Platform-aware config resolver** — `_get_user_config_dir()` resolves correct config
  paths for Claude Desktop and Cline across macOS, Linux, and Windows
- **Target constants** — `AUTO_INSTALL_TARGETS`, `MANUAL_TARGETS`, `ALL_TARGETS` exported
  from installer module for programmatic use
- **Expanded `code-intel status`** — now checks all 8 auto-install targets (was 4)

## [0.1.10] - 2026-03-03

### Fixed

- **PyPI token leak via sdist over-inclusion** — `snapshot_report.html` (pytest-textual-snapshot
  HTML report) captured environment variables including a PyPI API token. Hatchling's sdist builder
  couldn't resolve `.gitignore` for the nested project layout, so it included everything. Added
  explicit `[tool.hatch.build.targets.sdist]` exclude rules for snapshot reports, session DBs,
  trace files, recordings, and other non-source artifacts.

### Security

- Deleted `snapshot_report.html` containing leaked (auto-revoked) PyPI token
- Added sdist exclusions: `*.db`, `*.jsonl`, `.attocode/traces/`, `.attocode/sessions/`,
  `.attocode/recordings/`, `.claude/`, `.agent/`, `.traces/`, `site/`, `dist/`, `.venv/`

## [0.1.9] - 2026-03-03

### Added

- **7 new MCP code-intel tools** (18 total): `lsp_definition`, `lsp_references`, `lsp_hover`,
  `lsp_diagnostics`, `explore_codebase`, `security_scan`, `semantic_search`
- **Import resolution fix for `src/` layout** — `_detect_source_prefixes()` +
  `_build_file_index()` in `codebase_context.py` fixes dependency graph for projects using
  `src/` package layout (orphan rate: ~100% → 8%, edges: 0 → 1,062)
- **Hierarchical codebase explorer** — `hierarchical_explorer.py` with single-level drill-down,
  importance scores, and symbol annotations
- **Security scanner** — `integrations/security/` with pattern-based secret detection,
  anti-pattern scanning, dependency audit
- **Semantic search** — `integrations/context/semantic_search.py` with keyword-based fallback
  (embedding support optional)
- **Vector store + embeddings** — `vector_store.py` and `embeddings.py` for optional
  embedding-powered search
- **LSP tools** — `tools/lsp.py` registers go-to-definition, references, hover, diagnostics
  as agent tools
- **Explore tool** — `tools/explore.py` for hierarchical codebase navigation
- **Security tool** — `tools/security.py` for codebase security scanning
- **Semantic search tool** — `tools/semantic_search.py` for natural language code search
- **File change notifications** — `_notify_file_changed()` in tool executor notifies codebase
  context, hierarchical explorer, and AST service on file writes/edits
- **LSP enabled by default** — lazy initialization means no cost until first LSP tool call
- **Swarm TUI differential updates** — `AgentsDataTable` and `TasksDataTable` preserve cursor
  position across refreshes
- **AoT graph enhancements** — partial-dependency execution support, timeout overrides per task,
  agent assignment annotations in `DependencyTree`
- **attoswarm decomposer** — new `coordinator/decompose.py` module
- **Project metadata** — authors, keywords, classifiers, and project URLs added to `pyproject.toml`

### Changed

- MCP code-intel server expanded from 11 to 18 tools
- `FeatureConfig.enable_lsp` default changed from `False` to `True`
- `PolicyEngine` — new safe tool rules for explore, security, and LSP tools
- Barrel exports updated in `integrations/__init__.py` and `integrations/context/__init__.py`

### Fixed

- **Dependency graph completely broken for `src/` layout projects** — imports like
  `from attocode.core.loop import ...` were unresolvable because the file index only contained
  `src/attocode/core/loop.py` keys; the resolver looked up `attocode/core/loop.py` which didn't
  match. Now `_build_file_index()` adds prefix-stripped alternate keys. This fixes
  `dependency_graph`, `dependencies`, `impact_analysis`, `hotspots`, and `project_summary`
  MCP tools.

### Tests

- `test_decompose.py` — new decomposer tests
- Updated `test_aot_graph.py`, `test_scheduler.py`

## [0.1.8] - 2026-03-02

### Added

- **Hotspots: percentile-based scoring** — composite scores now use project-relative
  percentile ranks (0.0-1.0) instead of raw values, adapting to any project size
- **Hotspots: adaptive category thresholds** — god-file, hub, coupling-magnet, and
  new wide-api categories use P90 of project distribution with minimum floors
- **Hotspots: function-level hotspots** — "Longest functions" section shows top 10
  functions by composite complexity (length + params + missing return type)
- **Hotspots: public API surface** — `pub=N` metric per file, `wide-api` category
  for files with many public symbols
- **Conventions: per-directory divergence** — detects when directories (e.g. tests/)
  diverge > 20pp from project-wide type hint or docstring rates
- **Conventions: error hierarchy detection** — scans for Exception subclasses,
  reports root exceptions and subtypes
- **Conventions: `__all__` detection** — counts files defining `__all__` exports
- **Conventions: `slots=True` / `frozen=True`** — enhanced dataclass decorator parsing
- **Conventions: visibility distribution** — reports public/private function percentages
- **Conventions: method types** — reports @staticmethod, @classmethod, @property counts
- **Code-intel MCP server** — `attocode-code-intel` standalone MCP server exposing 11
  code intelligence tools (repo_map, symbols, search_symbols, dependencies,
  impact_analysis, cross_references, file_analysis, dependency_graph,
  project_summary, hotspots, conventions) for use by any MCP-compatible AI assistant
- **Code-intel installer** — `attocode code-intel install <target>` installs the MCP
  server into Claude Code, Cursor, Windsurf, or Codex; `uninstall` and `status` commands
- **Codex installer support** — `attocode code-intel install codex` writes
  `.codex/config.toml` (TOML-based config) with `--global` for user-level install
- **`tomli_w` dependency** — added for TOML writing support (Codex config)

## [0.1.7] - 2026-03-01

### Added

- **Swarm TUI overhaul** — TabbedContent layout with 5 tabs (Overview, Tasks, Agents, Events, Messages)
- `TasksDataTable`, `AgentsDataTable` — DataTable widgets with row selection and status icons
- `EventsLog` — RichLog with delta-append, auto-scroll, color-coded events
- `DependencyTree` — Tree widget with collapsible task dependency hierarchy
- `MessagesLog` — orchestrator-worker inbox/outbox message viewer
- `SwarmSummaryBar` — always-visible phase/counts/cost/elapsed summary
- `dag_summary` and `elapsed_s` fields in SwarmState
- Enriched DAG nodes with description, task_kind, role_hint, assigned_agent, target_files, result_summary, attempts
- `read_all_messages()` in StateStore for unified inbox/outbox timeline
- Richer task transition events with `assigned_agent`; `model` field in `_active_agents()`

### Fixed

- Tasks stuck in PENDING column — status_map missing `running`, `reviewing`, `blocked`, `done` statuses
- Agent status override (was always "running"/"idle", now uses actual status from state)
- Footer showing 0/0 (dag_summary and elapsed_s not written to state)
- Event timeline flicker (switched from Static full-rerender to RichLog delta-append)
- Double-click requirement for task/agent selection (switched to DataTable cursor_type="row")

### Known Bugs

- `attoswarm tui` shows old layout when installed via `uv tool install .` — tool snapshot doesn't pick up working-tree widget changes from `attocode` package. Workaround: use `uv run attoswarm tui` from project dir, or commit and reinstall.

## [0.1.6] - 2026-03-01

### Added

- **Tool argument normalization** — `_normalize_tool_arguments()` with alias mapping, fuzzy matching, and type coercion for non-Anthropic LLMs (GLM-5 etc.)
- **Improved tool descriptions** — explicit parameter names in write_file, edit_file, read_file, list_files, glob_files, bash
- **New provider tests** — Azure, OpenAI, OpenRouter, fallback chain, resilient provider
- **New integration tests** — MCP split, quality, tasks, verification gate, interactive planning
- **New tricks tests** — failure evidence, KV cache, recitation, reversible compaction

### Changed

- Tool executor wires `coerce_tool_arguments()` into execution pipeline (was built but never called)
- Various provider, integration, and safety module improvements

### Fixed

- Mermaid diagrams not rendering on GitHub Pages documentation (added mermaid.js CDN + init script)
- Recording gallery HTML not rendering exploration graph mermaid diagrams (switched to `<div class="mermaid">` + mermaid.js)

## [0.1.5] - 2026-02-28

### Added

- **Session resume & persisted permission grants** — `/resume` works in-session; grants loaded from DB on startup
- **Skill system overhaul** — long-running lifecycle (init/execute/cleanup), `SkillStateStore` for persistent state, `SkillDependencyGraph` with topological sort and version compatibility
- **Unified session graph recording** — `SessionGraph` DAG covering all event types (LLM, tools, subagents, budget, compaction); `PlaybackEngine` for frame-by-frame replay with filtering; Mermaid diagram export
- **Landlock sandbox enforcement** — actual Linux ctypes syscall wrappers (`PR_SET_NO_NEW_PRIVS`, `ruleset_create`/`add_rule`/`restrict_self`) replacing shell fallback
- **Swarm TUI data enrichment** — per-task JSON persistence, DAG+event fallback reconstruction, agent cards show task titles and model info, `TaskDetailScreen` modal, `agent_id` in all swarm events
- **Thread manager serialization** — `snapshot_all()`, `restore_snapshots()`, `to_dict()`/`from_dict()` for DB persistence
- **Policy engine grant loading** — `load_grants()` bulk import, `approved_commands` property
- **TUI theme management** — `set_theme()` with dark/light/auto, `active_theme_name` property
- **Documentation** — Architecture, Providers, Sandbox, Budget, MCP, Testing guides; Contributing guide; LICENSE file
- **CI/CD pipeline** — `.github/workflows/` with GitHub Actions
- **Package typing markers** — `py.typed` for `attocode_core` and `attoswarm`
- **Example swarm project** — [attocodepy_swarmtester_3](https://github.com/eren23/attocodepy_swarmtester_3) demonstrates hybrid swarm orchestration

### Changed

- Swarm orchestrator writes enriched `active_agents` (model, task_title) and per-task JSON files
- `SubagentManager._emit_status()` propagates model through all lifecycle phases
- `StateStore.build_task_detail()` falls back to DAG+event reconstruction when task files missing
- `StateStore.build_agent_detail()` enriched with task_title, duration from events, result message
- Agent grid shows task title (30 chars) instead of raw task_id
- Task board column headers include "click to inspect" hint
- Detail inspector shows task_title/duration/result for agents, agent/model/duration for tasks

### Tests

- New test modules for: agent state machine, subagent spawner, blackboard, delegation, budget pool, dynamic budget, graph types, playback, docker/landlock/seatbelt sandboxes, skill dependency graph, skill state, skill executor, thread manager

## [0.1.4] - 2026-02-27

### Added

- **MCP integration overhaul**
  - `MCPClient.connect()` now expands `${VAR}` env references via `_expand_env()` and inherits parent `os.environ` (previously child process lost PATH)
  - Agent uses `MCPClientManager` for MCP lifecycle (eager + lazy loading)
  - `/mcp list` shows real connection state (connected/failed/pending) instead of always "configured"; failed servers show error message
  - `/mcp tools`, `/mcp search`, `/mcp stats` fallback to `_registry` when ctx is not yet available
  - `ToolRegistry.set_tool_resolver()` for lazy MCP tool discovery

- **Swarm system enhancements**
  - New modules: `cc_spawner.py` (Claude Code subprocess spawner), `critic.py` (wave review + fixup tasks), `roles.py` (role config with scout/critic/judge)
  - Wave review: critic role can assess completed waves and generate fixup tasks
  - Scout pre-execution: read-only agent gathers codebase context before implementation tasks
  - Quality gate wired to execution with LLM judge scoring, threshold relaxation for foundation tasks, retry with feedback
  - Model failover on consecutive timeouts/rate-limits
  - Hollow detection emits `swarm.hollow_detected` events
  - Task completion events now include output, files_modified, tool_calls, session_id, num_turns, stderr

- **`/swarm` command group** — 7 subcommands: `init`, `start`, `status`, `stop`, `dashboard`, `config`, `help`
  - `/swarm init` auto-generates `.attocode/swarm.yaml` from current model
  - `/swarm start <task>` launches swarm execution inline
  - `/swarm status` shows live task/worker/phase state

- **TUI improvements**
  - Swarm dashboard: 8 new dedicated panes (overview, tasks, workers, quality, files, decisions, model health, AST blackboard)
  - `swarm_dashboard.tcss` stylesheet
  - Focus screen refactored with improved layout
  - Swarm monitor: enhanced rendering and state display
  - Status bar: new swarm-aware metrics
  - Tool calls widget: expanded display
  - Event system: new event types and hooks for swarm integration
  - `AgentInternalsPanel` widget

- **Timeline screen** — `TimelineScreen` accepts `state_fn` callback for live polling with 0.5s timer and proper `on_unmount` cleanup

- **`AgentConfig`** gains `provider` and `api_key` fields
- **`PolicyEngine`** — new safe rules for `codebase_overview`, `get_repo_map`, `get_tree_view`
- **`TraceCollector._increment_counters()`** internal API + `TraceWriter` wired to it

### Changed

- **Timeout defaults** increased from 120s → 600s across all providers (Anthropic, OpenAI, OpenRouter, Azure, ZAI, resilient provider)
- **Subagent timeouts** tripled (e.g. default 5min → 15min, researcher 7min → 20min)
- **Subagent max iterations** doubled (e.g. default 15 → 30, researcher 25 → 50)
- **Timeout extension on progress** 60s → 120s; budget max duration 3600s → 7200s
- **`AgentBuilder.with_provider()`** now forwards `timeout` kwarg
- **Streaming failure fallback** — execution loop now falls back to non-streaming before erroring
- **`httpx.StreamError`** now caught in OpenAI/OpenRouter `chat_stream()`
- **`_describe_request_error()`** helper for OpenAI/OpenRouter — better error messages for httpx timeouts
- **`InefficiencyDetector._detect_empty_responses()`** skips events lacking token data (fewer false positives)
- **Agent's `_run_with_swarm()`** rewritten: uses `cc_spawner`, `SwarmEventBridge`, AST server sharing, proper result mapping
- **`SwarmConfig`** gains new fields; barrel re-exports for cc_spawner, roles, critic
- **attoswarm CLI** — major refactor with proper backend command building (`_build_backend_cmd`), environment variable stripping for nested agent sessions (`_STRIP_ENV_VARS`), `RoleConfig` support in schema

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
