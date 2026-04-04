# Attocode Roadmap

## v0.2.6 -- Language Support, Search Quality & Architecture (Released 2026-03-24)

1. ~~**Language-specific symbol extraction**~~ -- DONE: 11 new tree-sitter configs (Erlang, Clojure, Perl, Crystal, Dart, OCaml, F#, Julia, Nim, R, Objective-C); total 36 languages supported
2. ~~**Architecture analysis fallback**~~ -- DONE: directory-based module detection when dependency graph is sparse; 22 repos improved from 2/5 to 4/5
3. ~~**Search ranking improvements**~~ -- DONE: graduated symbol boosting, multi-term coverage, path relevance, non-code penalty; MRR +23%, NDCG +16%
4. ~~**Lazy embedding initialization**~~ -- DONE: embedding model loads on first `semantic_search()` call, not on construction; bootstrap latency 20s → 0.8s
5. ~~**3-way benchmark expansion**~~ -- DONE: 19 → 49 repos benchmarked across 30+ languages
6. ~~**FK constraint fix**~~ -- DONE: save files before symbols in `ast_service.py`

## v0.2.7 -- Search Quality, Evaluation & Adaptive Indexing (Released 2026-03-28)

1. ~~**Embedding-based semantic search**~~ -- DONE: hybrid vector + BM25 with RRF; two-stage retrieval
2. ~~**Persistent index across instances**~~ -- DONE: SQLite-backed IndexStore with incremental updates
3. ~~**Progressive hydration**~~ -- DONE: adaptive tier-based indexing (small/medium/large/huge); skeleton init <2s for any repo; background hydration thread; on-demand gap filling
4. ~~**3-way benchmark (20 repos)**~~ -- DONE: grep vs ast-grep vs code-intel across 12 languages; code-intel 4.7/5 quality
5. ~~**New MCP tools**~~ -- DONE: `hydration_status` tool; `indexing_depth` param on bootstrap; `mode` param on semantic_search
6. **Ground truth expansion** -- add YAML files for 15+ more benchmark repos (currently 5)
7. **Go-specific search improvements** -- Go MRR 0.200 lags Python 0.725; index package docs, use module paths
8. **ast-grep integration** -- optional structural pattern searches alongside tree-sitter parsing

## v0.2.15 -- Search Performance & New Search Modes (Released 2026-04-04)

1. ~~**BM25 keyword index disk cache**~~ -- DONE: SQLite cache with incremental mtime-based updates; 8x speedup on cockroach-scale repos (20s → 2.5s warm)
2. ~~**Trigram pre-filtering for BM25**~~ -- DONE: narrows candidate docs before scoring; zero accuracy loss (full corpus IDF preserved)
3. ~~**Numpy-accelerated vector search**~~ -- DONE: BLAS matmul replaces Python loop; 183x speedup at 10K vectors; in-memory cache with version invalidation; pure Python fallback
4. ~~**Frecency-boosted search**~~ -- DONE: SQLite-backed file access scoring with exponential decay; `frecency_search` MCP tool with two-phase file ordering
5. ~~**Fuzzy search (Smith-Waterman)**~~ -- DONE: typo-resistant search via local sequence alignment; `fuzzy_search`, `fuzzy_filename_search`, `fuzzy_score` tools
6. ~~**Cross-mode search suggestions**~~ -- DONE: "did you mean" fallbacks between filename and content search
7. ~~**Query constraints (fff-style)**~~ -- DONE: `git:modified`, `!pattern`, `path/`, `*.ext` filters with git porcelain XY parsing
8. ~~**Query history & combo boosting**~~ -- DONE: SQLite-backed query-to-file tracking; 3+ selections activate combo boost
9. ~~**Code-intel testing infrastructure**~~ -- DONE: fixtures, mocks, helpers; 9 tool test modules
10. ~~**Overall benchmark improvement**~~ -- DONE: 35% faster (4,182ms → 2,731ms avg), quality stable at 4.7/5

## v0.2.x -- Code Intel Infrastructure

1. **Cross-repo search in org** -- aggregate embeddings across repositories, org-scoped vector queries
2. **Better git integration** -- commit graph exploration, blame-weighted hotspots, PR-aware analysis
3. **Cross-service analysis** -- detect API contracts (OpenAPI, gRPC), map service-to-service calls
4. **More tests** -- integration tests for all 40 MCP tools, Playwright E2E, target 60% coverage
5. **Full MCP feature parity** -- ensure all tools work in all modes (local, remote, service)
6. **Better offline mode**:
   - Offline embedding fallback (auto-switch to local model like `all-MiniLM-L6-v2`)
   - Pre-computed analysis bundles (`.attocode-bundle` export for air-gapped use)
   - Offline learning sync (queue locally, sync on reconnect)
   - Git-based offline analysis (blame, history, branches via pygit2 without DB)

## v0.3.0 -- Swarm + Code Intel Integration

1. **Swarm mode update to loops** -- migrate from DAG-based to loop-based execution architecture
2. **Swarm using code intel** -- bootstrap orientation, impact analysis for task scoping, cross-refs for merge conflicts, learning system for per-repo patterns

## v0.4.0 -- Platform

- Hosted cloud service
- GitHub App integration
- VS Code extension
- Webhook-driven CI analysis

## Backlog Ideas

- **Change risk scoring** -- complexity + churn + centrality
- **Architecture drift detection** -- boundary violations
- **Test coverage mapping** -- source ↔ test file cross-reference
- **Code clone detection** -- AST-based near-duplicate identification
- **API contract analysis** -- auto-detect REST endpoints, generate surface map
- **Documentation coverage analysis**
- **Refactoring suggestions** -- god classes, feature envy, long parameter lists
