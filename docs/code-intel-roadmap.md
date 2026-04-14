# Code Intelligence Roadmap

> Authoritative roadmap for attocode code-intel. Replaces the old HTTP API roadmap (Phases 2-5).
> Baseline: **v0.2.20** (April 14, 2026).

---

## Current State (v0.2.20)

| Metric | Value |
|--------|-------|
| MCP tools | 123 |
| HTTP API endpoints | 171 |
| Languages | 36+ |
| Rule packs | 5 (Go, Python, TypeScript, Rust, Java) |
| Rules | ~57 (regex Tier 1 only) |
| Rule accuracy | F1=0.87 |
| Security rules | 101+ (OWASP, framework-specific, supply-chain) |
| Dataflow analysis | Intra-procedural (single function) |
| Search modes | 7 (semantic, BM25, trigram, frecency, fuzzy, cross-mode, regex) |
| Tests | 1,055 |
| Benchmark tasks | 120 (MCP bench) + 46 annotated files (rule accuracy) |

### Key subsystems already shipped

- **Rule engine**: Metavariables, boolean combinators, inline test framework, CI runner, SARIF v2.1.0, profiling, community marketplace, Semgrep importer
- **Search**: BGE embeddings, BM25 disk cache (176x warm speedup), frecency with exponential decay, Smith-Waterman fuzzy, query constraints (fff-style filters)
- **Reproducibility**: Retrieval pins, portable snapshots, embedding rotation (6-state machine), named overlays
- **Progressive hydration**: Skeleton-first indexing, 20x faster large repos (cockroach 24.5s -> 1.2s)
- **Security**: Intra-procedural dataflow (sources -> sinks), 30 OWASP rules, 35 framework rules, 7 supply-chain malware patterns
- **HTTP API**: 171 endpoints, orgs/repos model, auth, CORS, snapshots, GC, pins in every search response

---

## Phase 1: Structural Analysis Foundation (v0.2.21)

**Theme:** Move rules from regex to AST-aware. Build function-level call graph. This is the highest-leverage change — `UnifiedRule.structural_pattern` field exists but is inert, `RuleTier.STRUCTURAL` enum is defined, tree-sitter parses 36 languages. All that's missing is the wiring.

### Deliverables

- [ ] **ast-grep structural rule executor**
  - Implement Tier 2 execution in `rules/executor.py` — dispatch to ast-grep when `rule.tier == STRUCTURAL`
  - Accept `structural_pattern` strings in YAML rules (field already exists on `UnifiedRule`)
  - Fallback to regex Tier 1 for languages without ast-grep grammars
  - Key files: `rules/executor.py`, `rules/model.py`, `rules/loader.py`

- [ ] **Function-level call graph**
  - Extend `CrossRefIndex` with `call_edges: dict[str, set[str]]` (qualified_caller -> qualified_callees)
  - Extract call expressions during tree-sitter parsing in `ts_parser.py`
  - Store edges in `IndexStore` alongside symbol defs/refs
  - New MCP tool: `call_graph(symbol, direction, depth)`
  - Validate against PyCG benchmarks (`eval/pycg/` harness exists). Target: P>0.8, R>0.5 on micro-benchmarks
  - Key files: `cross_references.py`, `ts_parser.py`, `ast_service.py`, `index_store.py`

- [ ] **LSP-enriched cross-references**
  - `ingest_lsp_results` callback (wired in `service.py`) does not feed call-graph edges yet
  - Insert LSP definition/references as high-confidence call edges with `source: "lsp"` attribution
  - Call graph gets progressively better when LSP servers are available
  - Key file: `ast_service.py`

- [ ] **5 more language packs + structural rules**
  - C/C++, C#, PHP, Ruby packs with both regex and structural patterns
  - Expand Go and Python packs with structural rules
  - Goal: 10 packs, 100+ rules total
  - Key dir: `rules/packs/examples/`

- [ ] **Benchmark expansion for structural rules**
  - Extend `eval/rule_accuracy/corpus/` with structural rule ground truth
  - Target: F1>=0.87 overall, F1>0.90 for structural-only subset

- [ ] **Rule synthesis from examples**
  - Given pos/neg code samples, generate candidate regex and structural patterns
  - `synthesize_rule(positive_samples, negative_samples, language)` -> `UnifiedRule`
  - Regex synthesis via common substring extraction + generalization (literal -> `\w+` -> `.*`)
  - Structural synthesis via ast-grep pattern templates from AST diff of pos vs neg
  - LLM-assisted mode: feed code samples + CWE description to Claude, get candidate YAML rules
  - Auto-populate metavar constraints from sample variance
  - Key files: new `rules/synthesis.py`, hooks into `model.py`, `metavar.py`

- [ ] **Evolutionary rule optimization framework**
  - Population-based optimization of rule patterns using genetic programming
  - **Mutation operators**: regex widening/narrowing, metavar constraint relaxation/tightening, severity adjustment, composite pattern node insertion/removal, scope boundary changes
  - **Crossover**: splice composite pattern subtrees between high-performing rules, combine metavar constraints from two parents
  - **Fitness function**: weighted combination of precision, recall, CASTLE score, and execution speed (from `RuleProfiler`). Configurable weights via `.attocode/evolution.yaml`
  - **Selection**: tournament selection (k=3) with elitism (top 10% survive unchanged)
  - Evaluate candidates against `eval/rule_accuracy/corpus/` + `RuleTestRunner` inline fixtures
  - Generations capped (default 50), early stopping when F1 plateaus for 5 generations
  - Key files: new `rules/evolution.py`, uses `profiling.py` (fitness), `testing.py` (validation), `registry.py` (storage)

- [ ] **Auto-pruning of dead/noisy rules**
  - Already identified 82 dead rules in benchmarks — wire this into a continuous check
  - Rules with 0 matches across 10+ scanned repos: mark `enabled=False` with `disabled_reason="dead"`
  - Rules with FP rate > 0.5 after 10+ feedback samples: auto-disable with notification
  - `rule_hygiene()` MCP tool: report dead rules, noisy rules, confidence drift
  - Persistent state in `.attocode/rule_feedback.json` (already exists)

**Dependencies:** None (foundational).

---

## Phase 2: Inter-Procedural Dataflow (v0.2.22)

**Theme:** Follow taint across function boundaries. The current `security/dataflow.py` explicitly documents its limitation: "Intra-procedural only." This phase removes it using the Phase 1 call graph.

### Deliverables

- [ ] **Cross-function taint propagation**
  - When a tainted variable is passed as an argument, propagate taint to the callee's parameter
  - When a function returns a tainted-derived value, mark the return as tainted at the call site
  - Configurable call-depth limit (default 3) to prevent analysis explosion
  - Key file: `security/dataflow.py` (currently 530L, expect ~800-1000L after)

- [ ] **Sanitizer-aware taint tracking**
  - `TaintSanitizerDef` model exists in `rules/model.py`, `taint_loader.py` loads from YAML
  - Wire sanitizers into dataflow: taint killed when value passes through sanitizer function
  - Language packs have sanitizer YAML stubs (Go has `taint/sanitizers.yaml`)
  - Key files: `dataflow.py`, `rules/packs/taint_loader.py`

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

## Phase 3: Search Quality & Developer Experience (v0.2.23)

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

## Phase 4: Integration & CI/CD (v0.2.24)

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

## Phase 5: Scale & Production (v0.2.25)

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

## Phase 6: Intelligence Platform (v0.2.26)

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

| Phase | Version | Theme | Key Unlock | Deps |
|-------|---------|-------|------------|------|
| 1 | v0.2.21 | Structural Foundation | ast-grep rules, call graph, rule synthesis & evolution | None |
| 2 | v0.2.22 | Inter-Procedural Dataflow | Cross-function taint, Bayesian confidence, LLM rule gen | P1 |
| 3 | v0.2.23 | Search & DX | Graph-boosted ranking, autofix, clones | P2 |
| 4 | v0.2.24 | Integration & CI/CD | GitHub App, VS Code, pre-commit | P1-3 |
| 5 | v0.2.25 | Scale & Production | Monorepo sharding, remote repos, OTel | P4 |
| 6 | v0.2.26 | Intelligence Platform | Cross-service, federated rule evolution, risk scoring | P5 |

### Architectural principles

1. **Call graph in `CrossRefIndex`, not a separate store.** One persistence path through `IndexStore`.
2. **Inter-procedural dataflow extends, not replaces.** Layer on top of the clean 530-line intra-procedural engine.
3. **ast-grep as subprocess, not embedded.** Avoids Python/Rust FFI. Latency acceptable on pre-filtered file sets.
4. **Rules stay data-driven (YAML).** No Python per rule. Keeps community marketplace viable.
5. **LSP is progressive enhancement, not requirement.** Everything works without LSP. Results get better when LSP is available.
