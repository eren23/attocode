# TypeScript to Python Porting Report

> Feature gap analysis between the TypeScript (legacy) and Python (active) implementations of Attocode.
> Generated March 2026.

## Summary

The Python version (`src/attocode/`) is the active implementation with ~351 source files and ~91k LOC. It has surpassed the TypeScript version in most areas and introduced several Python-only features. The TypeScript version is preserved in `legacy/` for reference.

---

## Fully Ported (no action needed)

These features exist in both implementations with equivalent or superior functionality in Python:

- **Core agent loop** --- execution engine, state machine (8 lifecycle states), completion analysis
- **All 13 tools** --- read_file, write_file, edit_file, list_files, glob, grep, bash, codebase_overview, ast_query, spawn_agent, task_*, permission, vision
- **7 LLM providers** --- Anthropic, OpenRouter, OpenAI, Azure, ZAI, Mock + resilient provider with fallback chain
- **14 integration domains** --- budget, context, safety, persistence, agents, tasks, skills, mcp, quality, recording, streaming, swarm, lsp, utilities
- **TUI** --- Textual replaces Ink; 56+ files across 7 subdirectories with swarm dashboard, session browser, approval dialogs
- **Context engineering tricks** --- reversible compaction, KV-cache, failure evidence, recitation, recursive context, serialization diversity
- **Session persistence** --- SQLite store with 12 tables, checkpoints, goals, audit logs
- **Sandboxing** --- Seatbelt (macOS), Landlock (Linux), Docker, Basic fallback
- **Tracing** --- 42 event kinds, JSONL collector, analysis pipeline
- **Swarm orchestration** --- 20 modules (~10,343L), roles, critic, quality gates, failure classifier
- **Standalone attoswarm** --- separate package with CLI, both in-process and hybrid modes
- **57 slash commands** (vs ~40 in TS)
- **Skills & agents system** --- loader, executor, dependency graph, state persistence
- **MCP support** --- client, client_manager, config, tool_search, tool_validator, custom_tools, meta_tools
- **Budget economics** --- doom-loop detection, phase tracking, budget pools, dynamic budget, cancellation

---

## TS-Only Features (not ported)

Features that exist in the TypeScript codebase but not in Python. Assessment of whether they're worth porting.

| Feature | TS Location | Status | Worth Porting? | Notes |
|---------|-------------|--------|----------------|-------|
| **Trace Dashboard (web UI)** | `tools/trace-dashboard/` | Not ported | **YES** | Hono + React + Recharts dashboard for trace visualization. Valuable for trace analysis. Could be rebuilt as Python + FastAPI app or kept as a standalone web tool. |
| **Docusaurus docs site** | `docs-site/` | Superseded | NO | MkDocs Material replaces this entirely. |
| **`core/protocol/`** (bridge, types) | `src/core/protocol/` | Not ported | MAYBE | Protocol abstraction layer for client-server communication. Python uses direct function calls. |
| **`core/queues/`** (atomic counter, event/submission queues) | `src/core/queues/` | Not ported | LOW | Python's `asyncio.Queue` and standard concurrency primitives suffice. |
| **`analysis/`** (feedback loop, prompt templates) | `src/analysis/` | Not ported | MAYBE | Feedback loop analysis could be useful for eval pipelines. `prompt-templates.ts` and `trace-summary.ts` may have value for structured analysis. |
| **`costs/`** (model pricing registry) | `src/costs/` | Not ported | **YES** | Model pricing registry for cost tracking and budget display. Currently Python tracks tokens but not dollar costs per model. |
| **`safety/type-checker.ts`** | `integrations/safety/` | Not ported | LOW | TypeScript-specific type checking integration. Python has mypy/ruff which work differently. |
| **`safety/edit-validator.ts`** (syntax check) | `integrations/safety/` | Not ported | MAYBE | Validates edited files still parse correctly after edits. Could prevent broken code commits. |
| **`utilities/sourcegraph.ts`** | `integrations/utilities/` | Not ported | LOW | Niche Sourcegraph code search integration. |
| **`utilities/graph-visualization.ts`** | `integrations/utilities/` | Partially ported | NO | Python has `/graph`, `/deps`, `/impact`, `/hotspots` commands which cover this. |
| **`utilities/openrouter-pricing.ts`** | `integrations/utilities/` | Not ported | **YES** | OpenRouter pricing data for cost tracking. Useful for budget display in multi-provider setups. |
| **`utilities/image-renderer.ts`** | `integrations/utilities/` | Different approach | NO | Python uses Textual's image support instead. |
| **`persistence/codebase-repository.ts`** | `integrations/persistence/` | Not ported | MAYBE | Codebase snapshot storage for comparing state over time. |
| **`templates/`** (AGENT.template, SKILL.template) | `src/templates/` | Not ported | **YES** | Scaffolding templates for `/agents new` and `/skills new` commands. Python versions create minimal stubs; TS templates are more complete. |
| **`session-picker.ts`** | `src/` | Not ported | LOW | Python TUI has an integrated session browser widget that replaces this. |
| **`first-run.ts`** | `src/` | Not ported | **YES** | Guided onboarding flow for new users (API key setup, provider selection, first prompt). Python has `/setup` command but lacks automatic first-run detection. |
| **`packages/attoswarm/`** (standalone TS lib) | `packages/attoswarm/` | Different | NO | Python has its own `attoswarm` package at `src/attoswarm/`. |
| **`packages/attoswarm-dashboard/`** (React TUI) | `packages/attoswarm-dashboard/` | Different | NO | Python TUI has integrated swarm dashboard screens. |
| **`packages/attoswarm-adapter-claude-code/`** | `packages/` | Not ported | MAYBE | Adapter for using Claude Code as a swarm worker. Could be useful if Claude Code is available on the system. |
| **`packages/attoswarm-adapter-codex/`** | `packages/` | Not ported | LOW | Adapter for OpenAI Codex as a swarm worker. Codex availability is limited. |

### Recommended Porting Priority

1. **`first-run.ts`** --- Auto-detect first run, guide through API key + provider + first prompt
2. **`costs/model-registry.ts`** + **`openrouter-pricing.ts`** --- Dollar cost tracking per model
3. **Trace Dashboard** --- Web UI for trace analysis (could be a separate `attocode-dashboard` package)
4. **`templates/`** --- Richer scaffolding for skills and agents
5. **`analysis/feedback-loop.ts`** --- Post-session analysis for eval

---

## Python-Only Features (ahead of TS)

Features that exist only in the Python implementation:

| Feature | Location | Notes |
|---------|----------|-------|
| **Vision/image tool** | `tools/vision.py` | Image analysis via multimodal models (v0.1.15+) |
| **Explore tool** | `tools/explore.py` | Codebase exploration with heuristic file selection |
| **Security scanning** | `integrations/security/` | Dependency audit and vulnerability scanning |
| **Recording/replay** | `integrations/recording/` | Full session graph with 11 NodeKinds, 6 EdgeKinds, frame-by-frame replay |
| **Code intelligence MCP server** | `code_intel/` | Standalone MCP server exposing AST analysis, cross-references, repo maps |
| **AST client/server/service** | `integrations/context/` | More sophisticated AST pipeline with client-server architecture |
| **Cross-references** | `integrations/context/cross_references.py` | Symbol cross-reference analysis across files |
| **Swarm roles & critic** | `integrations/swarm/roles.py`, `critic.py` | Role-based workers (architect, implementer, reviewer) + critic agent |
| **Message bus** | `integrations/swarm/` | Inter-agent messaging system |
| **Worktree manager** | `integrations/swarm/` | Git worktree isolation for parallel workers |
| **ZAI provider** | `providers/zai.py` | GLM-5 model support |
| **Azure provider** | `providers/azure.py` | Azure OpenAI endpoints |
| **Graph commands** | `commands.py` | `/graph`, `/deps`, `/impact`, `/hotspots` commands |
| **57 slash commands** | `commands.py` | vs ~40 in TypeScript |
| **Textual TUI snapshots** | `tests/unit/tui/` | Snapshot testing for TUI components |
| **Swarm budget** | `integrations/swarm/swarm_budget.py` | Dedicated budget management for swarm orchestration |
| **Swarm state store** | `integrations/swarm/swarm_state_store.py` | Persistent swarm state |
| **Failure classifier** | `integrations/swarm/failure_classifier.py` | Automated classification of task failures |
| **Request throttle** | `integrations/swarm/request_throttle.py` | Rate limiting for provider API calls |
| **CC spawner** | `integrations/swarm/cc_spawner.py` | Claude Code subprocess spawner for hybrid mode |

---

## Architecture Comparison

| Aspect | TypeScript | Python |
|--------|-----------|--------|
| **Entry point** | `src/main.ts` (CLI + TUI combined) | `src/attocode/cli.py` (Click CLI) |
| **TUI framework** | Ink (React-based) | Textual (Python-native) |
| **Agent core** | `agent.ts` (~3,100L) | `agent/agent.py` + 6 files (~2,400L) |
| **Execution loop** | `core/execution-loop.ts` (~1,866L) | `core/loop.py` |
| **State machine** | Embedded in agent | `core/agent_state_machine.py` (8 states) |
| **Type system** | `types.ts` (~1,500L) | `types/` directory with multiple modules |
| **Build system** | TypeScript + esbuild | Hatch + uv |
| **Package manager** | npm | uv (with pip fallback) |
| **Testing** | Vitest | pytest + pytest-asyncio |
| **Linting** | ESLint + Prettier | Ruff |
| **Source LOC** | ~45,000 | ~91,000 |
| **Source files** | ~180 | ~351 |

---

## File Mapping (Key Modules)

| TypeScript | Python Equivalent |
|-----------|-------------------|
| `src/agent.ts` | `src/attocode/agent/agent.py` |
| `src/core/execution-loop.ts` | `src/attocode/core/loop.py` |
| `src/providers/adapters/anthropic.ts` | `src/attocode/providers/anthropic.py` |
| `src/tools/` | `src/attocode/tools/` |
| `src/integrations/budget/economics.ts` | `src/attocode/integrations/budget/economics.py` |
| `src/integrations/swarm/swarm-orchestrator.ts` | `src/attocode/integrations/swarm/orchestrator.py` |
| `src/integrations/context/codebase-context.ts` | `src/attocode/integrations/context/codebase_context.py` |
| `src/integrations/safety/sandbox/` | `src/attocode/integrations/safety/sandbox/` |
| `src/integrations/persistence/sqlite-store.ts` | `src/attocode/integrations/persistence/store.py` |
| `src/tui/` (Ink) | `src/attocode/tui/` (Textual) |
| `src/tracing/` | `src/attocode/tracing/` |
| `src/tricks/` | `src/attocode/tricks/` |
