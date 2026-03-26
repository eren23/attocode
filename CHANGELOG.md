# Changelog

All notable changes to the Attocode Python agent will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.8] - 2026-03-26

### Added

#### Research Campaign Worktree Engine
- Isolated research experiments now run in dedicated git worktrees instead of mutating the main repository in place
- Research campaign persistence now stores experiment lineage, related experiment IDs, findings, steering notes, and checkpointed run state in SQLite
- New research strategies and operator flows for `ablate`, `compose`, `reproduce`, `hold`, `resume`, `kill`, and manual promotion
- Real patch-import and compose pre-application support through `WorktreeManager.apply_diff()`

#### Research CLI Surface
- `attoswarm research start` now supports parallel experiment batches, resume, promotion repeats, and worktree-backed execution
- Added `attoswarm research leaderboard`, `feed`, `monitor`, `compare`, `reproduce`, and `import-patch`
- Legacy `attoswarm research "<goal>" -e ...` invocation remains supported as a compatibility alias to `research start`

#### Research Testing & CI
- Hermetic research integration harness using real subprocess CLI execution, real git repos, real worktrees, and fake local workers
- Real CLI coverage for research start, resume, compare, reproduce, import-patch, feed, monitor, and operator controls
- Added focused research unit coverage for accept policies, evaluators, hypothesis generation, worktree management, and orchestrator failure paths
- Dedicated GitHub Actions job for research integration tests, with slow/local scenarios excluded from default CI

### Changed

#### Evaluator & Promotion Semantics
- Command evaluator accepts structured JSON metric output with secondary metrics, constraint checks, artifacts, and seed metadata
- Candidate promotion now supports validation-gated acceptance instead of immediate promotion-only workflows
- Findings generation now distinguishes accepted wins from invalid/error results for better campaign memory

#### Worker Launching
- Research subprocess workers now honor `role.command` overrides consistently, including fallback role selection

### Fixed

#### Patch Import Reliability
- Patch application now strips non-patch preambles and normalizes trailing newlines before `git apply --3way`
- Failed patch imports reset the worktree back to `HEAD` cleanly instead of leaving partial state behind

## [0.2.7] - 2026-03-25

### Added

#### Metal Shading Language Support
- `.metal` file extension mapped to C++ parser across all code-intel layers (`LANG_EXTENSIONS`, `_EXT_TO_LANG`, `LANG_MAP`, `LANGUAGE_CONFIGS`)
- `LANGUAGE_CONFIGS["metal"]` alias for C++ tree-sitter config
- VS Code/Cursor extension (`extensions/vscode-metal/`) with TextMate grammar for Metal-specific syntax highlighting
  - Function qualifiers: `kernel`, `vertex`, `fragment`, `compute`, `mesh`, `object`
  - Address space qualifiers: `device`, `constant`, `threadgroup`, `thread`
  - Vector/matrix/texture types, SIMD group operations, atomic operations
  - Metal attribute syntax: `[[buffer(N)]]`, `[[thread_position_in_grid]]`, etc.
  - Packaged as `.vsix` for easy installation

#### Readiness Report Engine
- 8-phase codebase audit: Baseline, API & Business Logic, Frontend Flows, Data Layer, Test Coverage, Security Surface, Observability, Deployability
- Tracer bullet end-to-end verification tracing entry points through dependency chains
- Weighted scoring with letter grades (A-F) per phase and overall
- MCP tool `readiness_report` via `readiness_tools.py` for agent-accessible audits
- `ReadinessEngine.run()` with configurable phase selection and scope filtering
- `ReadinessEngine.format_report()` for human-readable output
- Implementation: `src/attocode/code_intel/readiness.py` (972 lines)

#### Trigram Index & Fast Search
- Memory-mapped trigram inverted index for fast regex candidate pre-filtering
- Two-file mmap storage: lookup table (binary search) + postings (file-ID lists)
- File-ID mapping persisted in SQLite for cross-session reuse
- `extract_required_trigrams()` regex analysis for optimal candidate filtering
- Integrated into `fast_search` MCP tool and `grep_search` code path
- Skips binary files, dotfiles, `node_modules`, `.venv`, and other non-source directories
- Implementation: `trigram_index.py` (648 lines) + `trigram_regex.py` (160 lines)

#### OpenShell Sandbox Integration
- NVIDIA OpenShell sandbox for policy-governed agent isolation
- `OpenShellSandboxSession` for persistent sessions with exec, credential injection, and network policy hot-reload
- `OpenShellSandbox` with declarative YAML policy enforcement (Landlock LSM, network proxy, seccomp)
- Two-phase spawner: network ON during setup (install deps), restricted during agent work
- Policy cascade: task > worker > swarm config with `network_policies` concatenation
- All subprocess calls use `asyncio.create_subprocess_exec` (no shell injection)
- Implementation: `openshell.py` (542 lines) + `openshell_spawner.py` (315 lines)

### Planned (v0.2.9)
- Embedding-based semantic search (NDCG target: 0.40+)
- Ground truth YAML for 20+ benchmark repos
- Persistent index cache across CodeIntelService instances
- Go-specific search ranking improvements

## [0.2.6] - 2026-03-24

### Added

#### Phase 3 Language Support (11 new languages)
- Added tree-sitter configs for Erlang, Clojure, Perl, Crystal, Dart, OCaml, F#, Julia, Nim, R, and Objective-C
- `tree-sitter-language-pack` fallback when individual grammar packages are not installed (10/11 languages available)
- Clojure macro-call handler (`_process_clojure_call`) for `defn`, `defn-`, `defmacro`, `defmulti`, `defmethod`, `defprotocol`, `defrecord`, `deftype`, `ns`
- R assignment-based function extraction (`_process_r_assignment`) for `f <- function() {}` patterns
- Language aliases: `objective-c` → `objc`, `f#` → `fsharp`
- Import extraction for all 11 new languages in `_extract_import_module`
- Visibility and base class extraction for Dart, Crystal, Objective-C, Nim

#### Architecture Analysis Fallback
- Directory-based module analysis when Louvain community detection returns trivial results (single community or modularity < 0.05)
- `_directory_based_module_analysis()` groups files by top-level directory with symbol counts and hub file detection
- Fallback propagated to `LocalGraphProvider`, `DbGraphProvider`, `graph_viz`, and MCP `community_detection` tool
- 22 repos improved from 2/5 to 4/5 on architecture task

#### 3-Way Benchmark Expansion
- Extended `benchmark_3way.py` from 19 to 49 repos across 30+ languages
- Added repo configs for cockroach, express, prisma, rails, requests, cosmopolitan, ripgrep, starship, spring-boot, spark, vapor, WordPress, protobuf, crystal, dart-sdk, elixir, emqx, fsharp, ggplot2, iTerm2, julia, kemal, metabase, mojo, nickel, Nim, ocaml, otp, perl5, ring
- Added ast-grep patterns for Java; updated `_AST_GREP_UNSUPPORTED` with 12 unsupported languages

#### Churn Analysis & Code Evolution
- `churn_hotspots` and `change_coupling` data methods in `CodeIntelService`
- `TemporalCouplingAnalyzer` integration for file churn scoring
- Churn scores integrated into `_compute_file_metrics` composite metrics

#### OpenCode Backend Integration
- OpenCode spawner and command handling in swarm module
- Adapter registry support for dynamic backend selection
- `HybridCoordinator` OpenCode command management

#### SWE-Atlas QnA Evaluation Framework
- `repo_manager.py` for repository cloning and caching
- `runner.py` for task execution with CodeIntelService + LLM answer generation
- `scorer.py` for rubric-based scoring with LLM judges
- CLI commands for running evaluations and reporting results

### Changed

#### Search Quality Improvements
- Lazy embedding provider initialization — model loads on first `semantic_search()` call, not on construction (bootstrap latency: 20s → 0.8s for non-search tasks)
- Graduated symbol name boosting in BM25: exact match 3.0x, substring 2.0x, tokenized 1.5x (was flat 1.5x)
- Multi-term coverage bonus: 80%+ term coverage gets 1.4x, 50%+ gets 1.15x
- Source directory path boost: files in `src/`, `lib/`, `pkg/`, `core/` get 1.2x
- Non-code file penalty: `.md`, `.txt`, `.yml`, `.json` etc. get 0.3x
- Definition-type boost: class 1.3x, function 1.15x, method 1.1x
- Search quality metrics: MRR@10 0.367→0.453 (+23%), NDCG@10 0.213→0.248 (+16%), Recall@20 0.200→0.256 (+28%)

#### Persistent Index Store
- SQLite-backed `IndexStore` for symbols, references, and dependencies
- Incremental indexing: only re-parses files with changed mtime
- Cross-reference index supports LSP-sourced results

### Fixed
- Foreign key constraint failure in `ast_service.py` — files must be saved before symbols/refs (reordered `save_files_batch` before `persist_file`)
- Multi-strategy symbol search with scoring in `ASTService`
- Version bump: `__init__.py` synced to 0.2.6

### Metrics (49-repo benchmark)
- **Code-intel avg quality**: 4.2/5 → 4.4/5
- **Failure rate**: 19% → ~12% (below 5/5)
- **Bootstrap latency** (non-search): 20s → 0.8s (warm cache)
- **MRR@10**: 0.367 → 0.453
- **Languages supported**: 25 → 36 (tree-sitter configs)

## [0.2.5] - 2026-03-22

### Added

#### Fresh Context Protocol (F1)
- Dumb zone detection at 40-60% context fill with quality degradation warnings
- `handle_fresh_context_refresh()` in execution loop — spawns fresh context with structured handoff
- Thread fork preservation of old conversation before refresh
- `CONTEXT_FRESH_REFRESH` event type for observability

#### Dynamic Tool Creation (F2)
- `DynamicToolRegistry` for runtime tool definition with sandboxed execution
- JSON Schema parameter validation and blocked builtin protection
- Persistence to `.attocode/tools/` with auto-load on session start
- `/define-tool` command for listing and creating dynamic tools

#### MCP Server Scaffolding (F3)
- `MCPScaffolder` generates Python MCP servers from specifications
- Template-based code generation using FastMCP pattern
- Persistence to `.attocode/mcp-servers/` with spec.json for reload
- `/scaffold-mcp` command for creating local MCP servers

#### Autonomous Pipeline (F4)
- `AutonomousPipeline` with 5 phases: Research → Plan → Implement → Verify → Commit
- Phase-level result tracking with duration and artifact collection
- Fresh context per phase option for peak quality
- Enhanced `/auto` command integration

#### Graph-Ranked Repo Map (F6)
- PageRank algorithm on import/dependency graphs
- Task-relevance scoring combined with connectivity importance
- Token-budgeted output with configurable limits (default 1024 tokens)
- File categorization (core, util, test, api, config)

#### Architect/Editor Model Split (F7)
- `DualModelWorkflow` separating reasoning (architect) from editing (editor)
- Architect prompt generation for analysis-only passes
- Editor prompt generation with file contents injection
- Response parsing with confidence extraction and change detection
- Config fields: `architect_model`, `editor_model` in AttoConfig

#### Boomerang Orchestrator Mode (F8)
- `Orchestrator` decomposes complex tasks into mode-specific subtasks
- Dependency-aware scheduling with `get_ready_subtasks()`
- Context summaries passed between subtasks to prevent explosion
- Synthesis prompt generation for final result aggregation
- `/orchestrate` command

#### File-Driven Project State (F9)
- `ProjectStateManager` persists state in `.attocode/project/` directory
- `STATE.md` for cross-session decisions (append-only with timestamps)
- `PLAN.md` for current task plan (overwrite semantics)
- `CONVENTIONS.md` for code conventions
- Auto-loaded on session start, injected into system prompt
- `/project-state` command for viewing and adding entries

#### Parallel Background Agents (F10)
- `ParallelAgentManager` with pipe-separated task parsing
- Git worktree isolation per agent (configurable max agents)
- Merge conflict detection for overlapping file modifications
- Status tracking and result aggregation
- `/parallel` command

#### Watch Mode (F11)
- `FileWatcher` scans for `# AI:`, `// AI:`, `/* AI: */` trigger comments
- Directory tree scanning with configurable extensions and ignore patterns
- Trigger removal after processing
- File modification detection via mtime polling
- `/watch` command for scanning triggers

#### Bug Finder (F12)
- Pattern-based static analysis for common bug patterns
- Detects: bare excepts, eval/exec, shell injection, swallowed exceptions, TODOs
- Unified diff parsing for branch comparison
- Confidence-rated findings with severity levels (critical/high/medium/low)
- `/bugfind [branch]` command with structured report output

#### Progressive Disclosure Skills (F13)
- 3-tier loading: L1 (name+desc, ~100 tokens), L2 (instructions, <5K), L3 (resources)
- Trigger-based skill matching with confidence scoring
- Zero-token overhead for unused skills
- Context token estimation and skill unloading

#### Trajectory Analysis (F14)
- `TrajectoryTracker` records (reasoning, tool_call, result) triples
- Pattern detection: repetitive loops, spinning, regression, productive exploration
- `detect_spinning()` complements existing loop detector
- Summary generation for `/trace` command integration
- Exported from `integrations/quality/__init__.py`

#### Code Intelligence Improvements
- Added `repo_map_ranked` MCP tool — PageRank-based file ranking with task-relevance weighting
- Added `bug_scan` MCP tool — diff scanning for bug patterns with confidence rating
- MCP server now exposes **40 tools** (up from 38)
- Fixed language support for **7 languages**: Scala, Elixir, Zig, Haskell, HCL, Bash, Lua
- Added `.scala`, `.ex/.exs`, `.zig`, `.hs`, `.tf/.tfvars`, `.hcl` to file discovery
- Fixed `shell` → `bash` language normalization in AST service
- Raised file indexing cap: 2,000 → 5,000 (configurable via `ATTOCODE_FILE_CAP`)
- Raised dynamic cap tiers: 5K/10K → 10K/20K for large repos
- Increased symbol slicing limits across repo map, search index, and context selection
- Extended tree depth from 4 → 6, reference display from 50 → 100, entry points from 10 → 20
- Extended file watcher to cover all 25+ supported languages

#### 3-Way Benchmark Framework
- New `scripts/benchmark_3way.py` — compares grep vs ast-grep vs code-intel across 19 repos
- New `scripts/.internal/gen_3way_chart.py` — generates 4-panel comparison PNG chart
- Quality-based scoring (rewards signal density over output volume)
- Results: code-intel 4.4/5, grep 3.8/5, ast-grep 2.4/5 across 19 repos and 15+ languages

### Fixed
- TUI snapshot tests regenerated after widget/theme changes
- `cleanup_worktrees()` now skips non-git directories (prevents spurious warnings)
- Code-intel symbol extraction for Scala, Elixir, Zig, Bash, Lua, HCL repos (was returning empty)
- `EXTENSION_LANGUAGES` missing 5 file extensions causing 0 symbols indexed for those languages
- Benchmark scoring bias rewarding output volume over structured quality

### Changed
- `__init__.py` barrel exports updated across 6 packages (core, tools, code_intel, persistence, skills, mcp)
- Feature initializer extended with project_state, dynamic_tools, and trajectory features
- Command palette updated with 7 new commands
- Version bumped to 0.2.5

## [0.2.4] - 2026-03-22

### Added

#### Swarm Test Task Quality Enforcement

- **Test-specific quality gate** — test tasks require score 4/5 (vs 3/5 for others), configurable via `test_quality_threshold`
- **V11 pre-flight check** — test tasks auto-rejected (score 1) if output contains no test execution evidence; controlled by `test_require_execution_evidence`
- **Test-specific judge rubric** — LLM judge uses stricter 1-5 scale for test tasks; no test output = score 1-2 regardless of narrative
- **Verification-before-judge reorder** — for test tasks, verification gate runs before the judge so it sees actual test pass/fail data
- **Fail-safe score=2 for test tasks** — on LLM judge error, test tasks default to reject instead of pass
- **ToolAction transparency** — each subagent tool call captured (tool name, arguments, output, exit code, test flag); surfaced in judge prompt, events, and state.json
- **Worker package installation** — test task prompts explicitly allow `pip install`, `npm install`, `go mod tidy`, `cargo build`
- **Go and Cargo test runner support** — verification gate detects `go.mod`/`Cargo.toml` and runs `go test ./...` / `cargo test`
- **Test task timeout increase** — 360s (was 240s)
- **Test evidence in checkpoint restoration** — `test_output` and `tool_actions_summary` persisted across resume

#### Swarm Event Bridge & TUI Transparency

- **10 new event handlers** — circuit breaker open/closed, pause/resume, wave start/complete, verification failures, file conflicts now tracked in state.json instead of silently dropped
- **Circuit breaker visibility** — rate limit backoff state (open/closed, pause_until, rate_limit_count) exposed in state.json
- **Pause/resume tracking** — swarm pause state and reason visible to TUI
- **Wave lifecycle tracking** — per-wave start/complete times, task counts, pass/fail stats
- **Verification results tracking** — per-task verification pass/fail with check details
- **File conflict tracking** — worker file collision details surfaced
- **Expanded timeline fields** — 11 new data fields extracted from events (pause_ms, checks, assessment, strategy, etc.)

#### Swarm Event Bridge Performance

- **Batched event file flushes** — `.flush()` every 20 events or 0.5s instead of every event
- **Batched task detail writes** — dirty-set debouncing (0.3s) instead of immediate per-event file writes
- **Compact task detail JSON** — `indent=None` instead of `indent=2`
- **Quality results eviction** — capped at 100 entries with oldest-first eviction

#### Bug Fixes

- **Go import parser** — fixed tree-sitter node traversal for `import_declaration` → `import_spec` → `path` field
- **YAML parser** — recursive traversal for `document → block_node → block_mapping → block_mapping_pair`
- **Semantic search config penalty** — strengthened from 0.3 to 0.15 to properly deprioritize config files
- **CLI remote tests** — added httpx.get mock to prevent real HTTP calls
- **Economics unlimited budget test** — fixed assertion for clamped max_tokens
- **Archive test** — assertion accepts clean-slate info event after archive
- **Hollow termination default** — test aligned with code default (`True`)
- **Stale dispatch recovery** — test handles `list[tuple]` return type correctly
- **Artifact-aware skip** — test avoids single-dep rescue heuristic
- **Verification gate** — test updated for new `is_test_task` parameter

#### New Tests

- **66 cc_spawner tests** — 24 new tests for `_extract_tool_actions()`, `_is_test_command()`, `_extract_test_output()`, `_parse_cc_output()` with tool actions
- **80 verification gate tests** — 4 new tests for `is_test_task`, Go runner, Cargo runner
- **19 quality gate tests** — new `test_quality_gate.py` covering V11 pre-flight, test rubric, threshold=4, fail-safe=2, verification evidence

#### Evaluation Framework

- **12-repo benchmark suite** — expanded from 3 to 12 repos across 10 languages (Python, Go, C, C++, Kotlin, Swift, Elixir, Ruby, Zig, PHP) with 10 tasks per repo (6 original + dead_code, distill, graph_dsl, code_evolution)
- **Ground-truth search quality evaluation** (`eval/search_quality.py`) — 30 queries across 5 repos with verified relevant file lists; computes MRR@10, NDCG@10, Precision@10, Recall@20
- **Needle-in-the-haystack tasks** (`eval/needle_tasks/`) — 15 deep code understanding tasks across 5 types: call chain tracing, dead code detection, impact assessment, architecture quiz, cross-file symbol resolution
- **Competitive comparison** (`eval/competitive/`) — latency and quality benchmarking against published baselines from Sourcegraph, GitHub Code Search, CodeSearchNet, Greptile
- **Code-intel vs grep ablation** — `--mode both` flag on benchmark_ci.py, search_quality, and needle_tasks to run side-by-side comparison; grep baseline uses ripgrep for equivalent tasks
- **LLM-as-judge scorer** (`eval/llm_judge.py`) — async Claude-powered evaluation on 5 rubric dimensions (completeness, accuracy, depth, actionability, signal-to-noise) with pairwise comparison support
- **SWE-Atlas QnA adapter** (`eval/sweatlas/`) — loader for Scale Labs' 124-task deep codebase understanding benchmark
- **PyCG call graph adapter** (`eval/pycg/`) — precision/recall evaluation against verified Python call graph ground truth
- **OSS demo automated runner** — `cmd_run` in eval/oss_demo for executing evaluation tasks via CodeIntelService directly
- **4 new quality scorers** — `score_dead_code`, `score_distill`, `score_graph_dsl`, `score_code_evolution` in eval/quality_scorers.py

#### Configuration

- **Configurable file indexing cap** — `ATTOCODE_FILE_CAP` environment variable (default 2000) replaces hardcoded limit in service.py and navigation_tools.py; higher values improve coverage on large repos at the cost of bootstrap time

#### Documentation

- **Evaluation & Benchmarks guide** (`docs/guides/evaluation-and-benchmarks.md`) — covers benchmark suite, search quality metrics, needle tasks, competitive comparison, online benchmarks, and ground-truth format
- **Updated MCP tool count** — corrected 36 → 38 tools in docs/code-intel-http-api.md

### Fixed

- **dead_code MCP tool startup crash** — `explore_codebase` was referenced from `_analysis_tools` but is defined in `_navigation_tools`; fixed module reference in server.py
- **dead_code circular import** — `dead_code_tools.py` top-level import of `server.py` caused circular import when `CodeIntelService.dead_code_data()` was called directly; added try/except guard with stub MCP for deferred loading

## [0.2.3] - 2026-03-21

### Added

#### Phase 1 — CLI & Maintenance Commands

- **8 new CLI commands** — `query`, `symbols`, `impact`, `hotspots`, `deps`, `gc`, `verify`, `reindex` under `attocode code-intel`, providing direct terminal access to code intelligence without needing a running server
- **`gc` garbage collection** — clears orphaned embeddings and unreferenced content in local, remote, and service modes; clears AST cache in pure local mode
- **`verify` integrity checks** — validates branch files, embeddings, parent branch refs, and symbols against the database; in local mode checks for cache and index file presence
- **`reindex` full rebuild** — clears cache and stale index, re-runs embedding indexing from scratch; triggers `index_repository` job in remote mode

#### Phase 2 — Advanced Analysis Tools

- **`dead_code` MCP tool** — detects unreferenced symbols, files, and modules at three analysis levels using the cross-reference index; entry-point heuristics auto-exclude tests, CLI mains, and framework routes; confidence scoring ranks results by removal safety
- **`distill` MCP tool** — compresses codebase information at three fidelity levels: `full` (repo map), `signatures` (~70% compression, public API surface with type hints and first-line docstrings), `structure` (~90%+ compression, file tree + import adjacency list); supports dependency-graph expansion from seed files
- **`graph_dsl` MCP tool** — Cypher-inspired query language for dependency graph traversal with depth ranges, WHERE filters (language, line_count, importance, fan_in, fan_out, is_test, is_config), LIKE operator, multi-hop chains, COUNT aggregation, and glob patterns; backed by `GraphQueryParser` + `GraphQueryExecutor`

#### Phase 3 — History & ADR Tools

- **`code_evolution` MCP tool** — traces commit history for a file or symbol with line-level change stats, author tracking, date filtering, and rename-following via `git log --follow --numstat`
- **`recent_changes` MCP tool** — aggregates recent git activity, ranks files by commit frequency and churn, shows contributor breakdown; useful for identifying active development areas and merge conflict hotspots
- **`record_adr` MCP tool** — records architecture decision records with context, decision, consequences, related files, and tags; persisted in `.attocode/adrs.db` (SQLite, WAL mode)
- **`list_adrs` MCP tool** — lists ADRs with filtering by status, tag, or free-text search
- **`get_adr` MCP tool** — retrieves full ADR details in Markdown format
- **`update_adr_status` MCP tool** — updates ADR status with lifecycle transition validation (proposed -> accepted -> deprecated -> superseded); enforces `superseded_by` requirement

#### Phase 4 — HTTP API & Observability

- **`POST /api/v2/orgs/{org_id}/search`** — cross-repository semantic search across all repos in an org; single pgvector query with per-repo manifest scoping; supports `repo_ids` filter and `file_filter` glob
- **`GET /api/v2/projects/{id}/evolution`** — structured JSON endpoint for code evolution (commit history with per-file stats)
- **`GET /api/v2/projects/{id}/recent-changes`** — structured JSON endpoint for recent file changes with aggregation
- **`GET /api/v2/projects/{id}/graph-viz`** — D3 force-directed compatible graph data with nodes, links, and community detection; supports BFS from root file or top-N by importance
- **`GET /api/v1/metrics`** — aggregated query metrics in JSON and Prometheus text exposition format; tracks request latency by category (p50/p95/p99), search cache hit rates, and per-tool call success/failure; in-memory ring buffer with 10K cap; unauthenticated for monitoring infrastructure
- **`MetricsCollector`** — thread-safe module-level singleton with ring-buffered recording of request, search, and tool call metrics; Prometheus formatter with HELP/TYPE annotations

#### Swarm Quality Improvements

- **Mandatory compilation checks** — per-language syntax/compilation checks (Python `compile()`, `tsc --noEmit`, `node --check`, `json.loads`) run on modified files before the LLM quality gate, catching broken code early and saving quality gate costs; structured `file:line` errors are attached to `RetryContext` for precise worker feedback
- **Task enrichment pipeline** — post-decomposition enrichment adds acceptance criteria, code context snippets, technical constraints, and modification instructions to thin subtask descriptions; rule-based criteria generated per task type (implement, test, refactor, document, deploy); LLM enrichment for tasks still below `enrichment_min_description_chars` threshold; requests re-decomposition if >50% of tasks remain thin
- **Verification gate decoupling** — `enable_verification` now operates independently of the `quality_gates` flag; runs pytest, mypy/tsc, and ruff/eslint on worker outputs with structured test failure and fix suggestion feedback in retry context
- **User intervention hook** — opt-in feature (`enable_user_intervention: false` by default) that pauses tasks for human review after N failed attempts (`user_intervention_threshold: 3`); emits `swarm.task.intervention_needed` event with error details; defers cascade-skip to allow user action
- **Structured retry context** — `RetryContext` now carries `compilation_errors`, `test_failures`, and `verification_suggestions` fields so retried workers see exact error locations and actionable fix suggestions instead of raw error text

### Documentation

- **`docs/guides/cli-commands.md`** — comprehensive reference for all 8 new CLI commands with flags, usage examples, and sample output
- **`docs/guides/advanced-analysis.md`** — guide covering dead code detection (3 levels, entry-point heuristics, confidence scoring), code distillation (3 levels with compression examples), and graph DSL (full syntax reference with 10 example queries)
- **`docs/guides/code-history.md`** — guide for `code_evolution` and `recent_changes` tools with use cases and HTTP API examples
- **`docs/guides/observability.md`** — metrics endpoint documentation with JSON/Prometheus format examples, category reference, and Prometheus/Grafana setup instructions
- **`docs/guides/architecture-decisions.md`** — ADR workflow guide with lifecycle diagram, transition rules, and end-to-end workflow example
- **`docs/code-intel-http-api.md`** — updated with all new endpoints and expanded MCP tools list (27 -> 36 tools)
- **`docs/guides/swarm-quality.md`** — guide covering mandatory compilation checks, task enrichment pipeline, verification gate, user intervention hook, structured retry context, and full SwarmConfig quality fields reference

## [0.2.2] - 2026-03-19

### Added

- **Swarm run summaries** — `run_summary.py` now derives modified-file counts from change manifests, task metadata, or git worktree state while filtering out runtime bookkeeping
- **Attoswarm release-state coverage** — new tests for exact child lineage anchoring, safe finalization, planning-failure handling, and current snapshot fixtures/baselines
- **Child swarm lineage** — `continue` now persists explicit lineage metadata including parent run, base ref, base commit, and result commit for follow-up swarms
- **Codex MCP adapter path** — `codex-mcp` backend support, stream parsing, and adapter tests were added for multi-turn Codex worker flows
- **Swarm-side test verification** — `test_verifier.py` adds explicit verification plumbing for post-task validation in hybrid swarm runs
- **TUI stop confirmation** — explicit stop confirmation screen separates dashboard detach from coordinator shutdown

### Changed

- **Hybrid swarm lifecycle** — `continue` now anchors child runs to the exact saved parent commit, `resume` restores persisted shared-workspace manifests without replaying stale control messages, and the dashboard's normal quit path detaches instead of stopping the coordinator
- **Swarm terminal states** — shared planning failures now stop explicitly as `planning_failed` instead of degrading into a fake single repo-wide task, and CLI/TUI summaries distinguish stopped, planning-failed, and completed runs
- **Git finalization** — TUI and CLI finalization both route through the git safety net and exclude `.agent` runtime artifacts from branch finalization and changed-file summaries
- **Attocode TUI responsiveness** — high-frequency stream/tool updates are coalesced, repeated successful tool starts are removed from the main log, and concurrent same-name tool calls keep separate rows
- **Approval and swarm bridges** — TUI event handling was simplified around the approval bridge and swarm bridge so dashboard state updates are less fragmented
- **Model registry and Codex defaults** — built-in model metadata, OpenAI capability flags, Codex backend integration, and benchmark baselines were updated together for the new swarm backend surface
- **Swarm docs** — start vs continue vs resume, detach/reattach behavior, troubleshooting guidance, and the default hybrid example config have been aligned with the current CLI behavior

### Fixed

- **`continue --monitor` run identity** — the monitor now follows the same child `run_dir` as the coordinator instead of opening an empty sibling run
- **Swarm stop semantics** — leaving the dashboard no longer shuts the run down unless the explicit stop flow is used
- **Attoswarm snapshot suite drift** — snapshot fixtures and stable-app layout were refreshed to match the current dashboard structure and state schema
- **Default hybrid example preflight** — `.attocode/swarm.hybrid.yaml.example` now passes `attoswarm doctor` on a default install without requiring `aider`
- **Shared-workspace resume control replay** — stale control messages no longer immediately re-trigger old shutdown behavior on resume
- **Swarm merge safety** — branch finalization and changed-file summaries no longer treat `.agent` runtime files as product changes

### Tests

- **Hybrid swarm coverage expanded** — added or extended tests for child swarms, worktree anchoring, Codex parsing, Codex MCP integration, control-message resume behavior, run summaries, and attoswarm TUI snapshots
- **TUI regression coverage expanded** — added coverage for buffered tool/stream rendering, distinct concurrent tool rows, attoswarm fixture contracts, and current dashboard snapshots

## [0.2.1] - 2026-03-17

### Added

- **Research framework** (`src/attoswarm/research/`) — hypothesis-driven experiment orchestrator with evaluator, accept policy, experiment DB, scoreboard, and config; 8 new modules
- **EvalHarness + SwarmTraceBridge** — `eval/research_adapter.py` for benchmark integration; `src/attocode/integrations/swarm/trace_bridge.py` for swarm-to-tracing bridge
- **TUI task management screens** — `AddTaskScreen`, `EditTaskScreen`, `CompletionScreen` for inline task CRUD and swarm completion review
- **TUI widgets** — `AgentTraceStream` (live agent trace), `BudgetProjectionWidget` (budget forecast), `ConflictPanel` (file conflict display), `FailureChainWidget` (failure chain viz)
- **Orchestrator enhancements** — approval workflow, learning bridge, failure analyzer, subagent manager, archive module; ~843 lines of new orchestrator logic
- **Workspace safety** — `git_safety.py` (branch protection, dirty-state checks), `change_manifest.py` (change tracking), `conflict_advisor.py` (conflict resolution hints)
- **CLI expansion** — 557+ lines of new CLI commands in `attoswarm/cli.py`
- **Swarm config schema** — new fields in `config/schema.py` and `config/loader.py`

### Improved

- **TUI performance** — `build_task_list()` O(N×M) `is_foundation` edge scan replaced with O(1) forward-map lookup (`stores.py`)
- **Graph screen** — `action_show_graph()` now passes `working_dir` from state/cwd so hotspots, deps, and impact data load correctly (`app.py`)
- **TUI widgets** — enhanced `AgentGrid`, `DAGView`, `DecisionsPane`, `DetailInspector`, `EventTimeline`, `MessagesLog`, `OverviewPane`, `TaskBoard` with richer data display
- **Tracing** — inefficiency detector expanded; collector and types extended for swarm trace events

### Tests

- **New test files** — `test_cli.py`, `test_control_messages.py` (697 lines), `test_git_safety.py` (236 lines)

## [0.2.0] - 2026-03-15

### Added

- **Service-mode backend** — Multi-user FastAPI application with JWT, OAuth (GitHub, Google), API keys, and password auth; PostgreSQL + pgvector for embeddings; Redis for pub/sub and cache; dual-mode architecture (local SQLite vs remote HTTP)
- **24 API route modules** — Auth, orgs, projects, repos, branches, files, files_v2, git_v2, search, graph, embeddings, learning, activity, webhooks, websocket, notify, jobs, preferences, presence, api_keys, health, lsp
- **Provider abstraction** — `DbProvider` (Postgres-backed), `LocalProvider` (SQLite + filesystem), `RemoteProvider` (HTTP bridge to service mode)
- **Background workers** — ARQ worker with indexing pipeline, debouncer for git events, incremental AST + embedding indexer
- **Git integration** — Git manager, credentials handling, storage layer; branch overlay, diff engine, blame hunks
- **Frontend SPA** — React 19 + TypeScript + Vite dashboard with Shadcn UI; login, register, OAuth callback
- **Frontend pages** — Dashboard, Activity, Analysis (conventions, hotspots, symbols), Embeddings, File Browser, Graph (dependency visualization), Learnings, Search, Security, Settings, Branch Compare, Commit History/Detail, Repo Detail
- **Frontend components** — Activity feed, analysis panels, auth guards, file tree/viewer, embedding search/status, git commit list/diff viewer, dependency graph with controls
- **Webhook secret encryption** — `crypto.py` for encrypted webhook secrets at rest; migration 009
- **Database migrations** — 010 (commits table), 011 (commit changed files), 012 (branch merged_at), 013 (revoked tokens), 014 (blame hunks)
- **Security scanner DB** — `security_scanner_db.py` for storing scan results
- **Documentation** — `docs/architecture-v2.md`, `docs/roadmap.md`, guides for local development, repos-and-branches, semantic-search
- **Docker** — `docker-compose.dev.yml`, `docker-compose.service.yml` for local and service-mode deployment
- **CLI remote mode** — `--remote` / `ATTocode_REMOTE_URL` for connecting to service-mode backend

### Changed

- **`pyproject.toml`** — version bump to 0.2.0; dependency updates
- **Code-intel API** — refactored for provider abstraction; routes use `DbProvider` in service mode
- **Frontend API client** — generated schema, React Query hooks for all endpoints

### Tests

- **New unit tests** — `test_advisory_lock`, `test_branch_versioning`, `test_cli_remote`, `test_config_remote`, `test_db_security_scan`, `test_diff_engine`, `test_notify_enhanced`, `test_org_isolation`, `test_pubsub_streams`, `test_remote_provider`, `test_webhook_encryption`; expanded `test_service_mode`, `test_api`

### Fixed

- **Security scan "Branch 'main' not found"** — removed hardcoded `branch or "main"` fallback in `db_provider.py` (5 call sites) and `notify.py` (1 call site); `get_branch_context()` now properly looks up the repository's default branch from the DB when branch is empty
- **Force graph glitching on community toggle** — `communityColorMap` was called inline in `GraphPage.tsx` creating a new object every render, triggering full SVG teardown; now memoized with `useMemo`
- **Graph node animation stall** — fade-in animation used `r=0` with uncapped stagger delay (346 nodes × 15ms = 5s); replaced with opacity fade, delay capped to 800ms total
- **Graph 0 edges** — `Dependency` table empty when indexer dependency pass hasn't run; added `_compute_import_edges()` fallback in `DbGraphProvider` that extracts import edges on-the-fly from stored `FileContent`
- **Search page blank on error** — added `isError` state rendering with message and link to Embeddings page for indexing; added "Semantic search powered by embeddings" hint to `SearchBar`

### Improved

- **Impact analysis UX** — added explanatory text ("Direct = files that import changed files"), mini flow diagram (`Changed → Direct → 2nd Order`), taller stacked bar (`h-8`) with inline file-count labels, clearer layer names ("Directly imports changed files" instead of "Direct (depth 1)")
- **Embeddings search results** — merged `EmbeddingSearchPreview` and "Find Similar" button list into unified display; `SimilarFilesPanel` now appears above results; `onFindSimilar` prop added to `EmbeddingSearchPreview`
- **Sidebar navigation** — split flat repo nav into "Code" (Files, Commits, Search) and "Insights" (Analysis, Graph, Security, Embeddings, Knowledge Base, Compare) sub-groups with `SectionDivider` labels
- **Graph aesthetics** — curved bezier edges (quadratic `<path>` replacing `<line>`), softer glow filter (`opacity 0.2`, `stdDeviation 4`), brighter label text (`#e4e4e7`, `11px`), refined community color palette for dark backgrounds
- **Graph controls** — "Select File or Directory" button (was plain "Browse"), wider dropdown (`w-96`) with search filter input, auto-triggers graph generation on file selection
- **Graph-to-files** — new "View Side-by-Side" panel (`GraphFilePanel`, 450px) alongside graph; "Open in Files" renamed to "Open in Full Page"; `NodeInfoCard` updated with `Columns2` icon
- **Graph simulation stability** — position cache across re-renders (`positionCacheRef`), tuned `velocityDecay(0.4)`, `alphaDecay(0.028)`, `alphaMin(0.001)`, warm restart with `alpha(0.3)` when restoring cached positions, stale cache cleanup
- **CSS refinements** — deeper card hover shadows, primary glow ring, `focus-visible` outline glow, 150ms transitions on interactive elements

## [0.1.19] - 2026-03-09

### Added

- **Tree-sitter multi-language parsing** — `LANGUAGE_CONFIGS` for 25 languages (Python, JS/TS, Go, Rust, Java, Ruby, C, C++, C#, PHP, Swift, Kotlin, Scala, Lua, Elixir, Haskell, Bash, HCL, Zig, YAML, TOML, JSON, HTML, CSS) with per-language node-type queries for functions, classes, imports, and methods
- **`GenericTreeSitterExtractor`** — heuristic-based parser covering 50+ additional languages via installed tree-sitter grammars; uses common node-type patterns (function_definition, class_declaration, import_statement) without per-language config
- **`EXTRA_GRAMMAR_MODULES`** — 20+ additional grammar mappings (Dart, R, Julia, OCaml, Perl, Clojure, Erlang, etc.) for generic extractor fallback
- **Elixir custom extractor** — handles `defmodule` (with dotted names), `def`/`defp` functions with correct `parent_class`, and `use`/`import`/`alias`/`require` imports
- **Tree-sitter grammar dependencies** — 25 `tree-sitter-*` packages added to `[project.optional-dependencies]`

### Fixed

- **PHP tree-sitter grammar loading** — `grammar_module` corrected to `tree_sitter_php.php` (nested module path); PHP parsing now works end-to-end
- **C/C++ function name extraction** — was returning return types (e.g. `void`, `int`) instead of actual function names; now correctly extracts the `declarator` identifier
- **Kotlin import extraction** — added `import_list` to `import_types`; imports are now detected
- **Elixir parsing** — previously returned empty results; new custom extractor handles `defmodule`/`def`/`defp`/`use`/`import` correctly

### Tests

- **5 new test methods** — C function name regression test, C++ function name regression test, PHP class+imports test, Kotlin imports test, Elixir module/functions/imports test
- **TestCTreeSitter, TestCppTreeSitter, TestElixirTreeSitter** — 3 new test classes added

## [0.1.18] - 2026-03-08

### Added

- **Multi-language AST parsers** — regex-based parsers for Rust (structs, enums, traits, impl blocks, `use`/`mod`), Go (`func`, `type`, `import`), Java (classes, interfaces, `import`), Ruby (`class`, `module`, `def`, `require`), and C/C++ (`#include`, functions, structs, enums)
- **Multi-language dependency graph resolvers** — `_resolve_rust_import()` (handles `crate::`, `self::`, `super::`, `mod` declarations), `_resolve_go_import()`, `_resolve_java_import()` (package→path conversion), `_resolve_ruby_import()`, `_resolve_c_import()` (`#include` header resolution)
- **Dynamic file cap** (`_compute_dynamic_cap()`) — replaces fixed 2,000-file cap with repo-aware scaling: <1K source files → no cap, 1K–5K → cap at source count, 5K–20K → cap at 5,000, 20K+ → cap at 10,000
- **Importance-scored file selection** — files scored by type (source > config > docs > tests) and proximity to project root before truncation, replacing naive filesystem-order cutoff
- **Embedding index HTTP API** — `POST /index` and `GET /index/status` endpoints with `IndexStatusResponse` Pydantic model (9 fields: provider, available, status, total/indexed/failed files, coverage, elapsed, vector_search_active)
- **`semantic_search_status` MCP tool** — reports provider, coverage, indexing status, and vector search readiness
- **Community detection shared module** (`code_intel/community.py`) — `louvain_communities()` and `bfs_connected_components()` extracted from duplicate implementations
- **`ASTService.get_symbol_names()`** — public API for symbol name lookup (replaces direct `_ast_cache` access)
- **`networkx` optional dependency** — `graph` extra and included in `code-intel` extra
- **CLI `--timeout` flag** for `code-intel index --background` (default 30 min, prevents indefinite hang)

### Changed

- **`LANG_EXTENSIONS`** — added `.c`, `.h`, `.cpp`, `.hpp`, `.cc`, `.cxx` mappings
- **`_collect_files()`** — now applies importance scoring and dynamic cap instead of hard 2,000-file limit
- **Two-stage search RRF fusion** — keyword results now use composite IDs (`func:path:name`) matching vector key space; fixes silent dropping of keyword-only results during merge
- **`start_indexing()` API response** — returns all 9 `IndexStatusResponse` fields (was only 4)
- **`get_index_progress()`** — caches `total_files` to avoid expensive `CodebaseContextManager` re-creation on every polling call; returns thread-safe snapshot copies

### Fixed

- **FastAPI `class FastAPI` not found** — `fastapi/` directory was excluded by old fixed cap that favored `docs_src/` and `tests/` by filesystem order; dynamic cap + importance scoring now keeps source files
- **FastAPI dependency graph empty** — `applications.py` and `routing.py` had no dependency edges because only Python imports were resolved within the capped file set
- **FastAPI `routing.py` symbols empty** — file was excluded by old cap; now included via importance scoring
- **Deno `worker.rs` symbols empty** — no Rust parser existed; new `parse_rust()` extracts structs, enums, traits, impl blocks, functions
- **Deno Rust files not dependency-graphed** — `_resolve_rust_import()` now resolves `use`/`mod` statements to file paths
- **RRF key space mismatch** — vector results keyed by `func:path:name`, keyword results keyed by `file_path` — keyword-only hits were silently dropped from merged output
- **Multi-line def paren counting** — `_join_multiline_defs()` now strips comments and preserves string literals before counting parentheses; prevents incorrect join on `def foo(x):  # has ( in comment`
- **Nested parens in function signatures** — `parse_python()` replaced `[^)]*` regex with balanced-paren-aware `_match_function_def()` helper; correctly parses `def foo(x: int = max(0, 1))`
- **`_parse_python_params` string handling** — parameter splitter now skips string literals, preventing `)` inside default values (e.g. `"bad ) default"`) from breaking param extraction
- **Background indexer race condition** — `start_background_indexing()` now holds `_reindex_lock` during check-and-set of `_bg_indexer`; prevents duplicate indexer threads
- **`close()` thread safety** — joins background indexer thread (5s timeout) before closing vector store; prevents data corruption from mid-write store closure
- **`_index_progress` thread safety** — all progress field mutations in background thread protected by `_reindex_lock`; `get_index_progress()` returns snapshot copies
- **Inflated coverage metric** — `indexed_files` only incremented when embedding entries are non-empty (was counting files even when `embed()` returned empty vectors)
- **Empty graph `NetworkXError`** — `louvain_communities()` returns singleton communities with modularity 0.0 when graph has no edges
- **Dead `seen` set** — removed redundant deduplication in `_build_keyword_index()` DF calculation (iterating `dict.keys()` is already unique)
- **`_select_by_relevance` encapsulation** — replaced direct `svc._ast_cache` access with public `ASTService.get_symbol_names()` method

### Tests

- **7 new test functions** — RRF merge path integration tests (2), paren-in-comment/string/nested-default edge cases (3), empty-graph community detection (1), `_bg_thread` field coverage (1)
- **5,208 total tests pass**, 0 regressions

## [0.1.17] - 2026-03-08

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
- **Task file parser** (`task_file_parser.py`) — loads `tasks.yaml`/`tasks.yml`/`tasks.md` with format auto-detection (YAML structured definitions + Markdown heading extraction); integrated into `orchestrator._decompose_goal()` as highest-priority source
- **Swarm TUI dashboard overhaul** — `OverviewPane` composite widget replacing raw DataTable tab; `AgentCard`/`TaskCard` card-based display components; `SwarmSummaryBar` with live agent activity snapshot and pending-task hint; richer `DetailInspector` and `EventTimeline` rendering; +45 lines of swarm-specific TCSS
- **StateStore performance** (`stores.py`) — incremental JSONL reading via `seek()`; state cache with mtime + state_seq change detection; `has_new_events()` stat-only polling (no file I/O); `_synthesize_messages_from_events()` fallback for shared-workspace mode; `_MAX_CACHED_EVENTS = 2000` cap; `build_per_task_costs()`, `build_agent_detail()`, `build_task_detail()` with DAG fallback reconstruction
- **Orchestrator resume & control** (`orchestrator.py`) — `_restore_state()` for resume from persisted state; `_check_control_messages()` for skip/retry/edit_task via `control.jsonl`; `_check_stale_agents()` watchdog-based silence timeout; `_persist_prompt()`, `_persist_task()`, `_persist_manifest()` for TUI inspection and resume
- **Protocol additions** (`models.py`, `io.py`) — `timeout_seconds` field on `TaskSpec` (per-task timeout, 0 = default); `write_json_fast()` atomic write without fsync for TUI-consumed state
- **Coverage threshold** — `[tool.coverage.report]` with `fail_under = 40` added to `pyproject.toml`

### Changed

- **Model registry externalized** — hardcoded `BUILTIN_MODELS` dict in `providers/base.py` replaced with `models.yaml`; loader uses `_load_builtin_models()` from YAML
- **CI pipeline** (`.github/workflows/ci.yml`) — added mypy type checking, pytest coverage reporting, and codecov upload (gated on Python 3.12)
- **CLI entry point** (`cli.py`) — calls `validate_config()` before agent initialization
- **SessionStore** (`store.py`) — runs `check_and_migrate()` on init for forward-compatible schema
- **GLM-5 provider** — fixed `zhipu` → `zai` in model registry to match codebase convention
- **Orchestrator execution loop** — progress-based while loop replaces level-bounded for loop (fixes retry starvation when tasks fail at deep dependency levels)
- **SwarmSummaryBar** — live agent activity labels, pending-task hints, `g`/`t` keybindings for Graph/Timeline navigation

### Fixed

- **`orchestrator.get_state()`** — referenced wrong `BudgetCounter` attribute names (`self._budget.tokens_used` → `used_tokens`, `cost_used` → `used_cost_usd`); was dead-code since TUI reads from persisted state file

### Tests

- **117 new test functions** across 8 files: `test_protocol_io.py` (28 — atomic writes, corrupt JSON recovery, concurrent access), `test_protocol_locks.py` (4 — flock serialization, exception safety), `test_output_harvester.py` (22 — harvest loop, budget accumulation, completion/failure dispatch), `test_orchestrator.py` (28 — `_handle_result`, `_split_by_conflicts`, `_restore_state`, persistence), `test_control_messages.py` (skip/retry/edit_task, cursor tracking, stale agents), `test_task_file_parser.py` (YAML/Markdown parsing, edge cases), `test_ux_features.py` (activity labels, budget keys, agent colors), `test_stores.py` expanded (+35 — read_state caching, incremental JSONL, event synthesis)
- **Coverage threshold** (`fail_under = 40`) enforced in `pyproject.toml`

### Internal

- `agent.py` reduced from ~840L to ~430L (delegates to extracted modules)
- `code_intel/server.py` reduced by ~2,200L (tools + helpers extracted)
- `coordinator/loop.py` reduced from ~1,500L to ~970L (4 modules extracted)
- `attoswarm/cli.py` task parsing extracted to `task_parser.extract_json_array()`
- `stores.py` grew ~230 lines (incremental JSONL, caching, detail builders)
- `orchestrator.py` grew ~250 lines (resume, control messages, persistence, stale-agent watchdog)
- `task_file_parser.py` — 232 LOC new module
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
