# Competitive Code Search Comparison Report

**Date**: 2026-03-21 21:41
**Repos evaluated**: 5
**Total queries**: 24

---

## Attocode Search Performance

| Repo | Queries | Avg Latency (ms) | P50 (ms) | P95 (ms) | Avg Results | Total Time (ms) |
|------|---------|-------------------|----------|----------|-------------|-----------------|
| attocode | 8 | 2106 | 5 | 16821 | 7.4 | 16851 |
| gh-cli | 4 | 887 | 2 | 3545 | 7.8 | 3549 |
| redis | 4 | 1515 | 3 | 6053 | 7.2 | 6060 |
| fastapi | 4 | 3819 | 3 | 15272 | 7.5 | 15278 |
| pandas | 4 | 1941 | 30 | 7716 | 7.5 | 7765 |
| **Total** | **24** | **2063** | **4** | **15272** | — | **49503** |

## Published Baselines (for context)

| Tool | NDCG | MRR | P50 Latency | Notes |
|------|------|-----|-------------|-------|
| codesearchnet | 0.4 | 0.35 | N/A | Function-level retrieval; not directly comparable to file-le |
| sourcegraph | N/A | N/A | 200ms | Regex-first search; semantic search experimental. Cross-repo |
| github_code_search | N/A | N/A | 150ms | Regex + symbol search. No semantic/embedding search. No impa |
| greptile | N/A | N/A | N/A | AI-powered Q&A over codebases. No published quality metrics. |

## Per-Query Detail

### attocode

| Query | Latency (ms) | Results | Difficulty | Top Result |
|-------|-------------|---------|------------|------------|
| token budget management and enforcement | 16821 | 8 | medium | src/attocode/types/budget.py |
| message routing and tool dispatch | 6 | 8 | medium | src/attocode/tui/widgets/message_log.py |
| swarm task decomposition | 7 | 7 | hard | src/attocode/integrations/swarm/task_queue.py |
| agent session checkpoints | 5 | 7 | medium | src/attocode/commands.py |
| AST parsing and symbol indexing | 3 | 6 | hard | src/attoswarm/workspace/reconciler.py |
| execution loop iteration control | 4 | 8 | easy | src/attoswarm/coordinator/orchestrator.py |
| worker pool parallel spawning | 3 | 8 | hard | src/attocode/integrations/swarm/worker_pool.py |
| semantic search embeddings | 3 | 7 | easy | src/attocode/code_intel/tools/search_tools.py |

### gh-cli

| Query | Latency (ms) | Results | Difficulty | Top Result |
|-------|-------------|---------|------------|------------|
| command factory and execution | 3545 | 8 | medium | git/client.go |
| GitHub API authentication | 2 | 8 | easy | pkg/cmd/attestation/verify/options.go |
| pull request review workflow | 1 | 8 | medium | api/queries_issue.go |
| repository fork handling | 1 | 7 | medium | api/queries_repo.go |

### redis

| Query | Latency (ms) | Results | Difficulty | Top Result |
|-------|-------------|---------|------------|------------|
| event-driven command handling | 6053 | 7 | medium | deps/hiredis/test.c |
| sorted set data structure | 2 | 8 | easy | src/chk.c |
| RDB persistence snapshot | 2 | 7 | medium | src/server.c |
| cluster node discovery | 3 | 7 | hard | src/redis-benchmark.c |

### fastapi

| Query | Latency (ms) | Results | Difficulty | Top Result |
|-------|-------------|---------|------------|------------|
| request validation dependency injection | 15272 | 8 | medium | fastapi/exception_handlers.py |
| OpenAPI schema generation | 3 | 7 | easy | docs_src/generate_clients/tutorial004.js |
| WebSocket connection management | 1 | 6 | medium | fastapi/exceptions.py |
| middleware request lifecycle | 2 | 9 | medium | fastapi/applications.py |

### pandas

| Query | Latency (ms) | Results | Difficulty | Top Result |
|-------|-------------|---------|------------|------------|
| missing data NaN propagation | 7716 | 8 | medium | pandas/tests/generic/test_frame.py |
| DataFrame indexing label access | 30 | 6 | easy | pandas/io/stata.py |
| CSV parsing file IO | 9 | 8 | easy | asv_bench/benchmarks/io/csv.py |
| groupby aggregation split apply combine | 10 | 8 | medium | asv_bench/benchmarks/groupby.py |

## Competitive Positioning

### Where Attocode Leads
- **Impact analysis**: No competitor offers single-call transitive blast radius
- **Dependency graph + DSL**: BFS traversal with Cypher-like query language
- **Dead code detection**: 3-level analysis with confidence scoring
- **Community detection**: Louvain algorithm with modularity scores
- **Hotspot scoring**: Composite risk ranking with god-file/hub labels

### Where Competitors Lead
- **Regex search**: Sourcegraph + GitHub have regex as primary (we have semantic only)
- **Cross-repo navigation**: Sourcegraph SCIP enables compiler-accurate cross-repo refs
- **Scale**: Sourcegraph handles millions of files (we cap at 2,000)
- **AI Q&A**: Greptile/Cody have conversational codebase Q&A

### Parity Areas
- **Semantic search**: Competitive with BM25+TF-IDF (needs embedding upgrade for parity)
- **Symbol search**: Good coverage across 15+ languages via tree-sitter
- **Multi-tenant**: Full org/repo model with pgvector cross-repo search
