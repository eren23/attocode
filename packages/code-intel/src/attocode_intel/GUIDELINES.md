# Code Intelligence MCP Server — Agent Guidelines

> A broad tool suite for deep codebase understanding. This guide helps AI agents use it
> efficiently, minimizing token usage while maximizing insight.
>
> These tools are available via MCP (stdio/SSE) **and** as a REST API over HTTP.
> The HTTP API supports multi-project management, bearer token auth, and interactive
> docs at `/docs`. Start the HTTP server with:
> `attocode code-intel serve --transport http --project /path/to/repo`

---

## Tool Inventory

### Orientation (300–6000 tokens each)

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `project_summary` | High-level overview (identity, stats, entry points, architecture) | First call on unknown codebase |
| `repo_map` | Token-budgeted file tree with symbols | Small/medium codebases (<2000 files) |
| `explore_codebase` | Drill down one directory at a time | Large codebases, targeted exploration |
| `hotspots` | Files ranked by complexity/coupling/risk | Identify risky areas before changes |
| `conventions` | Coding style and patterns detected from code | Before writing new code |
| `bootstrap` | All-in-one orientation (summary + map + conventions + search). Optional `indexing_depth` param: "auto" (default), "eager", "lazy", "minimal" | **Best first call** — replaces 2-4 sequential calls |
| `hydration_status` | Check indexing progress (tier, phase, coverage) | Large repos — decide whether to wait or proceed |

### Symbol Lookup (50–3000 tokens each)

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `search_symbols` | Find function/class definitions by name | Know the name, need the location |
| `symbols` | List all symbols in a single file | Understand a file's API surface |
| `cross_references` | Definition sites + all usage sites for a symbol | Understand how something is used |
| `file_analysis` | Detailed file analysis (chunks, imports, exports) | Need full file understanding |

### Dependencies (100–1500 tokens each)

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `dependencies` | Direct imports and importers for a file | Quick dependency check |
| `dependency_graph` | Multi-hop dependency tree (BFS both directions) | Understand module relationships |
| `graph_query` | BFS traversal with typed edges and direction control | Targeted import/importer walks |
| `find_related` | Find structurally similar files (Jaccard + 2-hop) | Discover related modules |
| `community_detection` | Connected-component clustering of the import graph | Understand module boundaries |
| `impact_analysis` | Transitive blast radius of file changes | **Before modifying files** |
| `relevant_context` | Subgraph capsule — file + neighbors with symbols | Understand a file in context (replaces N+1 calls) |

### LSP (20–1500 tokens each)

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `lsp_definition` | Type-resolved go-to-definition | Jump to where something is defined |
| `lsp_references` | All references with type awareness | Find all usages precisely |
| `lsp_hover` | Type signature + documentation | Check types without reading code |
| `lsp_diagnostics` | Errors and warnings from language server | Verify code correctness |

### Search & Security (300–2000 tokens each)

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `semantic_search` | Natural language code search. Optional `mode`: "auto" (default), "keyword" (fast), "vector" (wait for embeddings) | Find code by description, not name |
| `security_scan` | Secret detection (13 patterns), anti-patterns (21 rules incl. supply-chain obfuscation: invisible Unicode, eval-on-decoded-data, install-hook scrutiny), dependency issues | Security review, supply-chain hardening |

### Rule-Based Analysis (200–5000 tokens each)

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `analyze` | Run rules from language packs against files. Returns rich findings with code context, antipattern explanations, few-shot examples, and fix suggestions. Filter by language, category, severity, or pack. | **Deep analysis** — performance antipatterns, correctness bugs, security issues, style violations |
| `list_rules` | Browse all registered rules by language, category, severity, or pack. Use `verbose=True` for descriptions. | Discover available checks before running analysis |
| `list_packs` | Show installed packs and available example packs | See what's active vs what can be installed |
| `install_pack` | Install an example language pack (go, python, typescript, rust, java) into `.attocode/packs/` | Activate language-specific analysis for your project |
| `register_rule` | Register a custom YAML rule at runtime. For permanent rules, add files to `.attocode/rules/` | Add project-specific or domain-specific checks on the fly |

**Language packs are NOT auto-loaded** — use `install_pack("go")` to activate packs relevant to your project. Once installed, rules are customizable in `.attocode/packs/<name>/rules/*.yaml`. Each finding includes surrounding code context (10 lines), an explanation of why it matters, and fix examples.

**Custom rules** in `.attocode/rules/*.yaml` or `.attocode/plugins/` are auto-loaded alongside installed packs.

### Memory & Recall (50–500 tokens each)

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `recall` | Retrieve relevant project learnings | At task start or in unfamiliar code |
| `record_learning` | Record patterns/conventions/gotchas | When you discover something important |
| `learning_feedback` | Mark learning as helpful/unhelpful | After using a recalled learning |
| `list_learnings` | Browse all stored learnings | Audit or review project knowledge |

---

## The Cardinal Rule: Progressive Disclosure

**Never load what you don't need.** Start broad, drill down only where relevant.

```
LEVEL 0: Orient     → bootstrap() or project_summary() + repo_map()
LEVEL 1: Locate     → explore_codebase() or search_symbols() or semantic_search()
LEVEL 2: Understand → relevant_context() or symbols() + dependencies()
LEVEL 3: Deep Dive  → lsp_hover(), lsp_references(), impact_analysis()
LEVEL 4: Act        → Make changes, then lsp_diagnostics() + impact_analysis() to verify
```

**Flow:**
1. Already familiar with codebase? Skip to Level 1 or 2.
2. Know which file to target? Go directly to Level 2.
3. Know a symbol name? Use `search_symbols` → Level 2.
4. No idea where to look? `bootstrap(task_hint="your task")` → Level 1.

---

## Codebase Size Strategies

### Small (<100 files) — 2 calls for complete understanding

```
project_summary(max_tokens=2000) + repo_map(max_tokens=3000, include_symbols=True)
```

Or just: `bootstrap(max_tokens=5000)` (1 call)

### Medium (100–2000 files) — 3 orientation + targeted drill-down

```
bootstrap(task_hint="your task", max_tokens=8000)
→ explore_codebase("relevant_dir")
→ relevant_context(["target_file.py"])
```

### Large (2000+ files) — Hierarchical, NO full repo_map

```
bootstrap(task_hint="your task", max_tokens=8000)
→ explore_codebase("src")
→ explore_codebase("src/core")
→ search_symbols("TargetClass") or semantic_search("what you need")
→ relevant_context(["found_file.py"])
```

**Never call `repo_map` on large codebases** — it wastes tokens. Use `explore_codebase` to drill down.

> **Progressive hydration**: For repos with >1K source files, code-intel uses skeleton
> initialization (parses only the top ~300-500 most important files in <2s). Remaining
> files are parsed in the background. Use `hydration_status` to check progress.
> Tools like `symbols()` and `cross_references()` automatically trigger on-demand
> parsing for files not yet in the index — you don't need to wait for full hydration.

---

## Task-Specific Workflows

### Bug Fixing

```
1. search_symbols(bug_related_name)     → Find the function/class
2. lsp_diagnostics(file)                → Check for existing errors
3. cross_references(symbol_name)        → Find all usage sites
4. lsp_hover(file, line)                → Understand types
5. impact_analysis([file])              → Check blast radius before fix
6. Fix the bug
```

### Feature Development

```
1. bootstrap(task_hint="feature desc")  → Orient + find similar code
2. conventions()                        → Learn project style (if not in bootstrap)
3. dependency_graph(similar_file, 2)    → Understand module boundaries
4. symbols(target_file)                 → Understand API surface
5. Implement the feature
```

### Refactoring

```
1. hotspots(10)                         → Find highest-risk files
2. cross_references(symbol)             → Find all usages of what you're changing
3. impact_analysis([files_to_change])   → Full blast radius
4. dependency_graph(file, 2)            → Understand coupling
5. lsp_references(file, line)           → Precise reference locations
6. Refactor
```

### Code Review

```
1. impact_analysis(changed_files)       → Blast radius of changes
2. hotspots(10)                         → Are changes in risky areas?
3. conventions()                        → Do changes follow project style?
4. analyze(files=changed_files)         → Rule-based analysis (perf, correctness, security)
5. lsp_diagnostics(file) × N           → Errors in each changed file (parallel)
6. security_scan(path="changed_dir")    → Secret/supply-chain check
```

### Onboarding / First Contact

```
1. bootstrap(max_tokens=8000)           → Complete orientation (1 call)
   OR
   project_summary() ∥ repo_map()       → Orientation (2 parallel calls)
2. hotspots() ∥ conventions()           → Risk areas + style (2 parallel calls)
3. explore_codebase("src")              → Drill into source
```

Total: ~6 calls, ~12-15K tokens for complete codebase understanding.

---

## Parallel Call Groupings

These tools are safe to call simultaneously:

```
# Orientation (no dependencies between them)
project_summary() ∥ repo_map()

# File understanding (different data sources)
symbols(file) ∥ dependencies(file) ∥ lsp_diagnostics(file)

# Cross-cutting analysis (independent queries)
impact_analysis([files]) ∥ cross_references(name) ∥ hotspots()

# Multi-file diagnostics (no shared state)
lsp_diagnostics(file_a) ∥ lsp_diagnostics(file_b) ∥ lsp_diagnostics(file_c)

# Orientation + task search
project_summary() ∥ semantic_search(task_description)
```

**Do NOT parallelize:** `bootstrap()` with `project_summary()` or `repo_map()` — bootstrap already includes them.

---

## LSP Fallback Table

When the language server is unavailable or returns "LSP not available":

| LSP Tool | Fallback |
|----------|----------|
| `lsp_definition` | `search_symbols(name)` — finds definitions by name matching |
| `lsp_references` | `cross_references(symbol_name)` — regex-based reference finding |
| `lsp_hover` | `file_analysis(path)` — shows full file structure with types |
| `lsp_diagnostics` | Run linter via bash (e.g., `ruff check file.py`, `eslint file.ts`) |

---

## Token Budget Rules

| Tool | Optimal Budget | Notes |
|------|---------------|-------|
| `repo_map` | 6000 tokens | Above 10000 wastes context with low-value files |
| `explore_codebase` | ~600-900 tokens | `max_items=30` is the sweet spot |
| `file_analysis` | ~1500 tokens (500-line file) | Most expensive per-file tool — use `symbols` if you only need API surface |
| `dependency_graph` | depth=2 | depth=3 explodes on hub files (exponential growth) |
| `bootstrap` | 8000 tokens | Includes summary + map + conventions + search |
| `project_summary` | 4000 tokens | Trim to 2000 for small codebases |
| `hotspots` | Stable | Call at most once per session |
| `conventions` | Stable | Call at most once per session (use `path` param for directory-specific) |

---

## Anti-Patterns

1. **Reading 10+ files when 2 tool calls suffice.** `dependency_graph + symbols` gives the same structural info as reading all those files.

2. **Skipping orientation.** Always call `bootstrap()` or `project_summary()` first on unknown codebases. Context saves more tokens than it costs.

3. **Oversized repo maps.** `repo_map(max_tokens=20000)` wastes context. Stay at 6000 for medium, skip entirely for large codebases.

4. **Using regex `cross_references` when LSP is available.** `lsp_references` is more precise. Only use `cross_references` as a fallback.

5. **Repeated `hotspots`/`conventions` calls.** These are stable within a session — results won't change. Call each at most once.

6. **Deep dependency graphs on hub files.** `dependency_graph("types.py", depth=3)` will return hundreds of files. Use depth=2 max, or depth=1 for hub files.

7. **`file_analysis` when you only need `symbols`.** `file_analysis` returns full chunks with code; `symbols` returns just the API surface at 1/3 the tokens.

8. **`semantic_search` for known exact names.** Use `search_symbols("MyClass")` — it's faster and more precise. Save `semantic_search` for "find code that handles authentication"-style queries.

9. **Ignoring importance scores in `explore_codebase` output.** High-importance files (>0.7) are entry points and hubs. Start there.

---

## Graph Query Tools (New)

### `graph_query` — Directed BFS with edge types

Walk imports or importers from a file with depth control.

```json
{"file": "src/core/loop.py", "edge_type": "IMPORTS", "direction": "outbound", "depth": 2}
```

Returns files grouped by hop distance:
```
Hop 1:
  > src/core/tool_executor.py
  > src/core/response_handler.py
Hop 2:
  >> src/providers/base.py
  >> src/tools/registry.py
```

Use `direction: "inbound"` or `edge_type: "IMPORTED_BY"` to reverse:
```json
{"file": "src/types/events.py", "direction": "inbound", "depth": 1}
```

### `find_related` — Structural similarity

Find files related by import patterns (not just direct imports).

```json
{"file": "src/agent/agent.py", "top_k": 5}
```

Returns ranked list with relationship type:
```
Files related to src/agent/agent.py:
  [  9] src/agent/builder.py  (direct)
  [  6] src/core/loop.py  (direct)
  [  3] src/agent/context.py  (direct)
  [  2] src/providers/base.py  (transitive)
```

### `community_detection` — Module clustering

Find natural groupings in the codebase.

```json
{"min_community_size": 5, "max_communities": 10}
```

Returns communities with hub files:
```
Community 1 (45 files):
  Hub: src/types/events.py (degree 32)
  - src/agent/agent.py (degree 15)
  - src/core/loop.py (degree 12)
  ...

Community 2 (18 files):
  Hub: src/tui/app.py (degree 14)
  ...
```

### Resources

Two MCP resources for direct content access:

- `attocode://project/{path}` — File content with line numbers (path-traversal protected)
- `attocode://symbols/{name}` — Symbol definitions with source snippets

10. **Modifying files without `impact_analysis` first.** Always check the blast radius before making changes to shared/hub files.

11. **Skipping `recall()` at task start.** Recalled learnings prevent repeated mistakes and surface project conventions you'd otherwise miss.

---

## Keeping the Index Fresh

The code-intel server maintains an AST index and semantic search embeddings. These update automatically via a file watcher, but you can also trigger updates explicitly:

### `notify_file_changed` Tool

Call this after batch file edits to immediately refresh the index:

```
notify_file_changed(files=["src/foo.py", "src/bar.py"])
```

This updates the AST index **and** invalidates stale semantic search embeddings for those files. Recommended after:
- Editing multiple files in a batch
- Creating or deleting files
- Operations where the ~200ms watcher debounce matters

### Automatic Updates

The file watcher handles most cases automatically. It:
- Monitors code files (`.py`, `.js`, `.ts`, `.go`, `.rs`, etc.)
- Updates AST index + invalidates embeddings on change
- Has ~200ms debounce (handled by watchfiles)

If `watchfiles` is not installed, use the `notify_file_changed` tool as the primary update mechanism.

---

## Quick Reference Card

```
TASK                          PRIMARY TOOL              FOLLOW-UP
─────────────────────────────────────────────────────────────────
First time in codebase        bootstrap(task_hint)      explore_codebase(dir)
Find a function/class         search_symbols(name)      symbols, file_analysis
Navigate directories          explore_codebase(path)    explore_codebase(deeper)
Find similar code             semantic_search(query)    dependency_graph
Understand a file             symbols + dependencies    file_analysis if needed
Understand a file in context  relevant_context([file])  (includes neighbors)
Check types                   lsp_hover                 lsp_definition
Find all usages               lsp_references            cross_references (fallback)
Before modifying              impact_analysis([files])  dependency_graph
Identify risky code           hotspots                  conventions
Review changes                impact_analysis           lsp_diagnostics, security_scan
Learn project style           conventions(path=dir)     conventions() for global
Recall project learnings      recall(query, scope)      learning_feedback(id)
Record a discovery            record_learning(...)      (persists across sessions)
```

---

## Memory & Recall

The server maintains a project-local learning database (`.attocode/cache/memory.db`).
Use these tools to build institutional knowledge that persists across sessions.

**Recommended workflow:**
1. At task start: `recall(query="what I'm about to do", scope="relevant/dir/")`
2. During work: When you discover gotchas or patterns, `record_learning(...)`
3. After using recalled info: `learning_feedback(id, helpful=true/false)`

**Learning types:**

| Type | When to use |
|------|-------------|
| `pattern` | Recurring code pattern that works well |
| `convention` | Project naming/style/architecture convention |
| `gotcha` | Non-obvious behavior or common mistake |
| `workaround` | Known issue with a known workaround |
| `antipattern` | Pattern that looks right but causes problems |

**Scope matching:** Learnings are scoped to directories. `recall(scope="src/core/")`
returns learnings for `src/core/`, then `src/`, then global — most specific first.

**Confidence:** Learnings start at 0.7 confidence. Helpful feedback boosts (+0.05),
unhelpful reduces (-0.1). Learnings with < 0.15 confidence are auto-archived.
