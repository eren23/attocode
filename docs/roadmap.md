# Attocode Roadmap

## v0.2.6 -- Symbol Extraction & Search Quality

1. **Fuzzy symbol search** -- `find_symbol()` currently does exact match on qualified names; add substring, prefix, and fuzzy matching so `search_symbols("IO")` finds `cats.effect.IO` and `search_symbols("Router")` finds `Phoenix.Router`
2. **Language-specific symbol extraction queries** -- validate and fix tree-sitter query patterns for all 25 languages; current gaps: Scala `object`/`trait` methods, Elixir `defp` private functions, Lua table-based OOP, Zig `pub const` declarations, HCL `resource`/`data` block names, Haskell type class instances
3. **Symbol search index** -- build a name→locations inverted index during `initialize()` for O(1) lookup instead of scanning all definitions
4. **Search quality ground truth expansion** -- add ground truth YAML files for all 19 benchmark repos (currently only 5 have them: attocode, fastapi, gh-cli, pandas, redis)
5. **ast-grep integration** -- optionally use ast-grep for structural pattern searches alongside tree-sitter parsing

## v0.2.x -- Code Intel Infrastructure

1. **Cross-repo search in org** -- aggregate embeddings across repositories, org-scoped vector queries
2. **Better git integration** -- commit graph exploration, blame-weighted hotspots, PR-aware analysis
3. **Cross-service analysis** -- detect API contracts (OpenAPI, gRPC), map service-to-service calls
4. **More tests** -- integration tests for all 40 MCP tools, Playwright E2E, target 60% coverage
5. **Full MCP feature parity** -- ensure all tools work in all modes (local, remote, service)
6. **Better offline mode**:
   - Persistent incremental indexing (cache in `.attocode/cache/`, reparse only changed files via git diff)
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
