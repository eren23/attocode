# Attocode Roadmap

## v0.2.6 -- Language Support, Search Quality & Architecture (Released 2026-03-24)

1. ~~**Language-specific symbol extraction**~~ -- DONE: 11 new tree-sitter configs (Erlang, Clojure, Perl, Crystal, Dart, OCaml, F#, Julia, Nim, R, Objective-C); total 36 languages supported
2. ~~**Architecture analysis fallback**~~ -- DONE: directory-based module detection when dependency graph is sparse; 22 repos improved from 2/5 to 4/5
3. ~~**Search ranking improvements**~~ -- DONE: graduated symbol boosting, multi-term coverage, path relevance, non-code penalty; MRR +23%, NDCG +16%
4. ~~**Lazy embedding initialization**~~ -- DONE: embedding model loads on first `semantic_search()` call, not on construction; bootstrap latency 20s → 0.8s
5. ~~**3-way benchmark expansion**~~ -- DONE: 19 → 49 repos benchmarked across 30+ languages
6. ~~**FK constraint fix**~~ -- DONE: save files before symbols in `ast_service.py`

## v0.2.7 -- Search Quality & Evaluation

1. **Embedding-based semantic search** -- NDCG target: 0.40+ (currently 0.248); hybrid vector + BM25 ranking
2. **Ground truth expansion** -- add YAML files for 15+ more benchmark repos (currently 5)
3. **Go-specific search improvements** -- Go MRR 0.200 lags Python 0.725; index package docs, use module paths
4. **Persistent index across instances** -- cache survives CodeIntelService reconstruction; warm start for all repos
5. **ast-grep integration** -- optional structural pattern searches alongside tree-sitter parsing

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
