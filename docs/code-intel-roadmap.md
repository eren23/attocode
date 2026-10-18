# Code Intelligence Roadmap

## Current priorities — 2026-10-17

The standalone package is `attocode-code-intel` **0.1.8**. The root agent was
retired on 2026-10-16 (PR #222) and is preserved at the `agent-archive-2026-10-16`
tag. Read the [workstream](intelligence-workstream.md) for release and experiment
evidence, the [quality guide](intelligence-quality.md) for bounded checks, and the
[generated catalog](intelligence-tools.md) for the current tool surface.
The phase plan below is retained history, not a release schedule or proof that
an unchecked feature shipped when its old target version was reached.

| Priority | Action | Completion evidence / limits |
| --- | --- | --- |
| Released 0.1.7 and 0.1.8 | Change investigation, focused change reports, and the database repairs from #214–#216 | See the [0.1.7](intelligence-0.1.7.md) and [0.1.8](intelligence-0.1.8.md) release notes. Change reports are local full-profile operations; daily and lean defaults are unchanged. |
| Unreleased | Dogfood fixes; one search candidate rejected | [Search batch](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-17-search-batch.md): Python docstrings and parameter types on the tree-sitter path, impact results in depth order, three prose words removed from search terms. Ranking gate MRR@5 0.530→0.555. Fresh validation is unchanged (13 of 27 judged files at five). Docstrings cost two pandas workflow labels at five. The concept-coverage candidate changed all four controls and lost one validation label, so it does not ship. |
| First-page relevance | "tested" intent shows source and test | [One frozen candidate](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-17-test-source-slot.md) on 16 new questions over aspnetcore, luarocks, zls and otp: judged files at five 14→16, no individual loss. "test" and "tests" searches still find 0 of 8 implementation labels at five; the source-slot form lost judged tests on development. Swift `Tests/` and Xcode `*Tests/` folders count as tests since 0.1.10. More test names (`_test.dart`, `_test.exs`, `_tests.erl`, `Test.m`, Perl `.t` and others) count as tests (Unreleased). [Name-paired source](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-18-paired-source.md) for "test" searches gained two aspnetcore files on development but none on 16 new questions over crystal, dart-sdk, postgrest and ring: most tests check code in a file with another name. [One query-word source hit](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-18-query-source.md) after the first five tests gained two implementation files at 24 on 20 new questions, with no loss, but failed the frozen one-run p95 limit; later repeats passed. Next: a latency rule over repeated runs, then new frozen questions. |
| First-page relevance | File-level coverage and "tested" intent rejected | [Two frozen candidates](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-17-file-coverage.md) on 32 new questions over rails, SwiftFormat, spdlog and ggplot2. File-level concept coverage gained four files at five on development but zero net on validation, with losses in three of four sets. "tested" intent found the test file on 5/8 questions but pushed the implementation file out on 3. Next: a test-intent order that keeps the best source file in the first five, on new questions. |
| Next performance work | Find a mechanism that improves cold Cockroach headroom | Last real target: 167.970/180 seconds. Retain byte-equivalent index controls, then seek a bounded end-to-end improvement; the two tokenization prototypes were rejected. Any new cloud run needs a new approved scope. |
| Deeper search pages | Fixed delivery; relevance remains open | [Fresh same-pool comparison](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-16-deep-page-diversity.md): distinct files precede repeated chunks even when the pool cannot fill a unique-file page. One fresh page improves 37→86 distinct files; labeled coverage is unchanged (all labels 5/6 at 24, 6/6 at 96). Both six-question sets are consumed; future relevance changes need new judgments. |
| First-page relevance | Prefix stripping rejected; current behavior retained | [One frozen candidate](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-16-navigation-prefix.md): 11/12 development label misses at five already existed in the pool. Stripping navigation prefixes regressed development and left fresh coverage unchanged at 19/24 labeled pairs. Both gates failed; no product change. |
| Reliability | Continue diagnosing intermittent Rust readiness | Shared document lifecycle is fixed, but the evidence follow-up reproduced Rust failures in initial selected-definition and post-edit reference checks. Root cause remains unproven. Bounded protocol traces now accompany the unchanged real-server gate. |
| Deferred | Structural-rule accuracy corpus | Add positive and negative ground truth for structural rules with a pinned local executor; report per-rule confusion counts. Existing positives alone are not accuracy evidence. |

## Historical Phase 1 snapshot (v0.2.23)

Baseline: v0.2.22 (April 16, 2026); Phase 1: v0.2.23 (May 3, 2026).
The counts and benchmark results below describe that checkpoint. They are not
current tool counts, general speed guarantees or agent-outcome measurements.

| Metric | v0.2.21 baseline | v0.2.23 (Phase 1 shipped) |
|--------|------------------|----------------------------|
| MCP tools | 123 | 127 (+ `call_graph`, `rule_hygiene`, `synthesize_rule`, `evolve_rules`) |
| HTTP API endpoints | 171 | 171 |
| Languages | 36+ | 36+ |
| Rule packs | 5 (Go, Python, TypeScript, Rust, Java) | 10 (+ cpp, csharp, kotlin, php, ruby) |
| Rules | ~57 (regex Tier 1 only) | 91 (Tier 1 + Tier 2 ast-grep) |
| Call graph | none | function-level via `CrossRefIndex.call_edges` + LSP enrichment |
| Rule hygiene | manual | auto-prune dead/noisy + persistent disable |
| Rule synthesis | none | `synthesize_rule` (deterministic LCS-regex + LLM-assisted) |
| Rule evolution | none | `evolve_rules` (GA: mutation/crossover/k=3 tournament) |
| Rule accuracy | F1=0.87 | F1=0.87 (corpus expansion deferred — see Phase 1 carry-forward) |
| Security rules | 101+ (OWASP, framework-specific, supply-chain) | 101+ |
| Dataflow analysis | Intra-procedural (single function) | Intra-procedural (Phase 2 will go inter-procedural) |
| Search modes | 7 (semantic, BM25, trigram, frecency, fuzzy, cross-mode, regex) | 7 |
| Tests | 1,055 | ~1,745 (+ ~117 Phase 1 tests + 6 post-review fixups) |
| Benchmark tasks | 120 (MCP bench) + 46 annotated files (rule accuracy) | + PyCG synthetic micro-bench (P=R=1.0) |

### Subsystems recorded at that checkpoint

- **Rule engine**: Metavariables, boolean combinators, inline test framework, CI runner, SARIF v2.1.0, profiling, community marketplace, Semgrep importer
- **Search**: BGE embeddings, BM25 disk cache (176x warm speedup), frecency with exponential decay, Smith-Waterman fuzzy, query constraints (fff-style filters)
- **Reproducibility**: Retrieval pins, portable snapshots, embedding rotation (6-state machine), named overlays
- **Progressive hydration**: Skeleton-first indexing, 20x faster large repos (cockroach 24.5s -> 1.2s)
- **Security**: Intra-procedural dataflow (sources -> sinks), 30 OWASP rules, 35 framework rules, 7 supply-chain malware patterns
- **HTTP API**: 171 endpoints, orgs/repos model, auth, CORS, snapshots, GC, pins in every search response

---

## Phase 1: Structural Analysis Foundation — ✅ SHIPPED in v0.2.23

**Historical status:** Core implementation shipped on branch `feat/update-85`, with audit follow-ups (R1/R2/R3 + I1–I5 + H1) and coverage gap tests (T1/T2/T3). Structural corpus expansion and AST-diff synthesis remained deferred, as listed below. 10 packs, 91 rules, 4 new MCP tools (`call_graph`, `rule_hygiene`, `synthesize_rule`, `evolve_rules`).

### Deliverables

- [x] **ast-grep structural rule executor** — Tier 2 dispatch in `rules/executor.py` via `sg run --pattern` and `sg scan --inline-rules` when `structural_context`/`structural_selector` set. Multi-metavar (`$$$X`) capture. Per-language regex fallback for languages outside `_AST_GREP_LANGS` and when binary missing.

- [x] **Function-level call graph** — `CrossRefIndex.call_edges` + `callers_of` populated by `add_reference()`. `IndexStore` schema 2 → 3. `call_graph(symbol, direction, depth)` MCP tool + `CodeIntelService.call_graph_data`. PyCG harness rewired; synthetic micro-bench hits P=R=1.0.

- [x] **LSP-enriched cross-references** — `ingest_lsp_results` resolves callee from query position + caller from each result's enclosing function. `merge_lsp_results` upgrades tree-sitter refs to LSP source on collision (only when caller info present, so legacy callbacks don't invert edges).

- [x] **5 more language packs + structural rules** — cpp, csharp, php, ruby, kotlin added; Tier-1 + Tier-2 patterns. **10 packs, 91 rules** (just under the 100-rule target).

- [ ] **Benchmark expansion for structural rules** — DEFERRED. Current `eval/rule_accuracy/corpus/` not yet expanded with the 30 new structural rules' ground-truth fixtures. Per-pack integration tests assert FIRE-on-positive; H1 audit added a default-threshold no-fire-on-CLI test.

- [x] **Rule synthesis from examples** — `rules/synthesis.py` with deterministic LCS-based regex + LLM-assisted (validation loop). `synthesize_rule` MCP tool. Structural synthesis via AST diff is deferred (regex covers most useful cases).

- [x] **Evolutionary rule optimization framework** — `rules/evolution.py` with mutation (regex widen/narrow + severity/confidence shifts), crossover (50/50 scalar splice), k=3 tournament, 10% elitism, plateau early-stop, JSONL audit log. `evolve_rules` MCP tool.

- [x] **Auto-pruning of dead/noisy rules** — `rules/hygiene.py` + `rule_hygiene()` MCP tool. Dead rules (0 matches across 10+ sessions), noisy rules (FP > 0.5 after 10+ samples), drift reporting. Persistent in `.attocode/rule_feedback.json`; thread-safe; survives registry reloads.

**Dependencies:** None (foundational).

**Carry-forward to Phase 2 / Phase 3**:
- Structural-rule corpus expansion (the deferred benchmark item).
- AST-diff-based structural synthesis (richer than regex synthesis).
- DB-side `SymbolReference.caller_qualified_name` uses migration 019. The local maintenance follow-up now covers parser output → persisted SQL rows → HTTP, and propagates the field through local HTTP too. This is not a new migration or full indexing-pipeline test.

---

## Phase 2: Inter-Procedural Dataflow (proposal; original target v0.2.24)

**Theme:** Follow taint across function boundaries. The current `security/dataflow.py` explicitly documents its limitation: "Intra-procedural only." This phase removes it using the Phase 1 call graph.

### Deliverables

- [ ] **Cross-function taint propagation**
  - When a tainted variable is passed as an argument, propagate taint to the callee's parameter
  - When a function returns a tainted-derived value, mark the return as tainted at the call site
  - Configurable call-depth limit (default 3) to prevent analysis explosion
  - Key file: `security/dataflow.py` (currently 530L, expect ~800-1000L after)

- [ ] **Sanitizer-aware taint tracking**
  - `TaintSanitizerDef` (and related) models exist in `rules/model.py`; a dedicated pack YAML loader was removed pending this phase — reintroduce loading or embed definitions as needed
  - Wire sanitizers into dataflow: taint killed when value passes through sanitizer function
  - Language packs have sanitizer YAML stubs (Go has `taint/sanitizers.yaml`)
  - Key files: `dataflow.py`, `rules/model.py`, pack `taint/` YAML under each language pack

- [ ] **Type-hint-aware analysis (Python/TypeScript)**
  - Extract type annotations via tree-sitter; use LSP hover when available
  - Reduce FPs: an `int` parameter is not a SQL injection vector
  - Key files: `ts_parser.py`, `dataflow.py`

- [ ] **`deep_scan` composite tool**
  - Chains rule analysis + dataflow + dead code in one call, unified report
  - Modeled after existing `review_change` composite pattern in `composite_tools.py`

- [ ] **`compare` and `migration_plan` tools**
  - `compare(base_ref, head_ref)`: diff-based analysis with rule/dataflow findings on delta
  - `migration_plan(old_api, new_api)`: cross-references + call graph -> migration checklist
  - Carried forward from old roadmap Phase 5, now feasible with call graph

- [ ] **Continuous rule evolution loop**
  - Background process: run evolutionary optimization on rules with low confidence or high FP rate
  - Trigger conditions: rule gets 3+ FP in a week, or new corpus files added
  - Evolved variants compete against parent on the full corpus; winner replaces parent only if strictly better
  - Audit trail: `.attocode/evolution_log.jsonl` with generation history, fitness progression, mutations applied
  - New MCP tool: `evolve_rules(target_rules=[], generations=20, corpus_path=None)`

- [ ] **Bayesian confidence updating**
  - Replace current 5-sample threshold with continuous Beta distribution update
  - Prior: `Beta(alpha=rule.confidence * 10, beta=(1-rule.confidence) * 10)` from YAML-declared confidence
  - Each TP/FP feedback updates the posterior: `alpha += is_tp`, `beta += (1 - is_tp)`
  - Posterior mean = `alpha / (alpha + beta)` replaces `calibrated_confidence`
  - Uncertainty quantification: rules with wide posteriors flagged for more testing
  - Key files: `profiling.py` (extend `FeedbackStore`), `model.py` (add `alpha`/`beta` fields)

- [ ] **LLM-assisted rule generation from CVEs**
  - Feed CVE/CWE descriptions + affected code patterns to Claude
  - Generate candidate YAML rules with metavars, examples, and inline test cases
  - Auto-validate against corpus before registration
  - New MCP tool: `generate_rules_from_cve(cve_id, language)`
  - Key files: new `rules/llm_generator.py`

**Dependencies:** Phase 1 (call graph, synthesis framework, evolution framework).

---

## Phase 3: Search Quality & Developer Experience (proposal; original target v0.2.25)

**Theme:** Make analysis results actionable. Better ranking, polished autofix, new detection capabilities.

### Deliverables

- [ ] **Call-graph-boosted search ranking**
  - Boost results that are call-graph neighbors of the query context
  - Extend existing frecency/combo boosting system
  - Key files: `search_tools.py`, `frecency.py`, `semantic_search.py`

- [ ] **Autofix quality improvement**
  - Multi-line autofix support (current: single search/replace + metavar templates)
  - Preview mode: `apply_fix(finding_id, dry_run=True)` returns unified diff without applying
  - Autofix confidence scoring: structural fixes > regex fixes
  - Key files: `rules/model.py` (AutoFix), `rules/metavar.py`, `rules/enricher.py`

- [ ] **Code clone detection**
  - AST-based near-duplicate identification via tree-sitter node hashing
  - Report clusters with similarity score
  - New tool: `clone_detection(path, min_similarity=0.8, min_lines=10)`

- [ ] **API contract detection**
  - Auto-detect REST endpoints from framework patterns (Flask, Express, FastAPI, Gin, etc.)
  - Build service-to-endpoint map: files -> routes -> HTTP methods -> parameters
  - New tool: `api_surface(path)`

- [ ] **Refactoring smell rules**
  - God classes, feature envy, long parameter lists — implemented as YAML rules, not new code paths
  - 10-15 new rules across existing packs

**Dependencies:** Phase 2 (inter-procedural analysis improves smell and clone accuracy).

---

## Phase 4: Integration & CI/CD (proposal; original target v0.2.26)

**Theme:** Take attocode from local analysis tool to CI pipeline participant. Analysis engine must be mature (Phases 1-3) before external exposure.

### Deliverables

- [ ] **GitHub App for PR analysis**
  - Webhook handler: `pull_request.opened/synchronize` -> `ci_scan` on diff
  - Post findings as PR review comments with inline annotations
  - SARIF upload for GitHub Code Scanning (leverages existing `rules/sarif.py`)
  - Key: new `integrations/github/` package

- [ ] **Webhook-driven CI pipeline**
  - `POST /api/v1/webhooks/push` triggers reindex + scan
  - Support GitHub, GitLab, Bitbucket webhook payloads
  - Carried forward from old roadmap Phase 3

- [ ] **VS Code extension**
  - Connect to HTTP API or MCP server
  - Inline diagnostics from `analyze` and `dataflow_scan`
  - Code actions for autofix suggestions
  - Key: new `extensions/vscode-attocode/`

- [ ] **`attocode scan` CLI + pre-commit hook**
  - Run rules on staged files, exit non-zero on findings
  - `.pre-commit-hooks.yaml` for pre-commit framework
  - Leverages existing `CIRunner` from `rules/ci.py`

- [ ] **Analysis profiles**
  - `.attocode/profiles/{strict,standard,lenient}.yaml`
  - Different rule sets, severity thresholds, confidence cutoffs
  - `ci_scan(profile="strict")` selects a profile

**Dependencies:** Phases 1-3 (mature analysis engine).

---

## Phase 5: Scale & Production (proposal; original target v0.2.27)

**Theme:** Large monorepos, remote analysis, observability.

### Deliverables

- [ ] **Monorepo sharding**
  - Shard call graph and cross-ref index by module/package for >50K file repos
  - Lazy cross-module edge resolution
  - Incremental call graph updates (file change -> recompute affected edges only)
  - Key files: `cross_references.py`, `ast_service.py`, `index_store.py`

- [ ] **Remote project analysis**
  - `POST /api/v1/repos/clone` accepts git URL, clones, indexes
  - Shallow clone by default, full clone opt-in
  - Background job system for clone + index
  - Carried forward from old roadmap Phase 2, re-scoped

- [ ] **OpenTelemetry instrumentation**
  - Spans on: rule execution, dataflow analysis, search queries, LSP calls
  - Export via OTLP to any collector

- [ ] **Cross-repo org search**
  - Aggregate embeddings across repositories
  - `semantic_search(query, scope="org")` searches all indexed repos
  - Requires remote project support

- [ ] **Rate limiting & production auth**
  - Per-org rate limits (env var exists, make it tiered)
  - API key rotation, JWT refresh
  - Carried forward from old roadmap Phase 4, scoped down

**Dependencies:** Phase 4 (CI/CD, webhook infra).

---

## Phase 6: Intelligence Platform (proposal; original target v0.2.28)

**Theme:** Long-term vision. Cross-service understanding, adaptive learning, coverage analysis.

### Deliverables

- [ ] **Cross-service analysis**
  - Detect API contracts (OpenAPI, gRPC proto, GraphQL schemas) across repos
  - Map service-to-service calls, detect breaking API changes across boundaries
  - Builds on Phase 5 cross-repo search + Phase 3 API contract detection

- [ ] **Federated rule evolution**
  - Aggregate TP/FP feedback across orgs (opt-in) to train rules on broader corpus
  - Per-project rule overrides that learn from local feedback while inheriting global priors
  - Cross-pollination: high-performing evolved rules from one project proposed to marketplace
  - Builds on Phase 1 evolution framework + Phase 2 Bayesian confidence + Phase 5 cross-repo

- [ ] **Documentation coverage**
  - Cross-reference exported symbols against docstrings/JSDoc/GoDoc
  - New tool: `doc_coverage(path)` with coverage percentage

- [ ] **Test coverage mapping**
  - Cross-reference source files against test files (extends existing `suggest_tests`)
  - Parse test frameworks to identify which functions are exercised
  - New tool: `test_coverage_map(file)`

- [ ] **Change risk scoring**
  - Composite score: complexity + churn + call-graph centrality + recent-bug history
  - New tool: `risk_score(files)`
  - Trivial once call graph and temporal coupling are in place

**Dependencies:** Phase 5 (cross-repo, scale).

---

## Summary

| Phase | Historical target | Theme | Key Unlock | Deps |
|-------|---------|-------|------------|------|
| 1 | v0.2.23 ✅ | Structural Foundation | ast-grep rules, call graph, rule synthesis & evolution | None |
| 2 | v0.2.24 | Inter-Procedural Dataflow | Cross-function taint, Bayesian confidence, LLM rule gen | P1 |
| 3 | v0.2.25 | Search & DX | Graph-boosted ranking, autofix, clones | P2 |
| 4 | v0.2.26 | Integration & CI/CD | GitHub App, VS Code, pre-commit | P1-3 |
| 5 | v0.2.27 | Scale & Production | Monorepo sharding, remote repos, OTel | P4 |
| 6 | v0.2.28 | Intelligence Platform | Cross-service, federated rule evolution, risk scoring | P5 |

### Architectural principles

1. **Call graph in `CrossRefIndex`, not a separate store.** One persistence path through `IndexStore`.
2. **Inter-procedural dataflow extends, not replaces.** Layer on top of the clean 530-line intra-procedural engine.
3. **ast-grep as subprocess, not embedded.** Avoids Python/Rust FFI. Latency acceptable on pre-filtered file sets.
4. **Rules stay data-driven (YAML).** No Python per rule. Keeps community marketplace viable.
5. **LSP is optional enhancement.** Static navigation remains available without it; cursor precision, diagnostics and other server-dependent operations must report their limits explicitly.
