# Search Quality Evaluation Report

_Generated: 2026-03-21 21:39:40_

## Summary

| Repo | Queries | MRR@10 | NDCG@10 | P@10 | R@20 | Time (ms) |
|------|---------|--------|---------|------|------|-----------|
| attocode | 10 | 0.550 | 0.304 | 0.140 | 0.305 | 16107 |
| fastapi | 5 | 0.400 | 0.213 | 0.080 | 0.187 | 15794 |
| gh-cli | 5 | 0.167 | 0.119 | 0.060 | 0.150 | 3706 |
| pandas | 5 | 0.292 | 0.123 | 0.060 | 0.120 | 8188 |
| redis | 5 | 0.247 | 0.214 | 0.140 | 0.310 | 6052 |
| **Overall** | 30 | 0.367 | 0.213 | 0.103 | 0.229 | 49847 |

## attocode

| Query | MRR | NDCG | P@10 | R@20 | Time |
|-------|-----|------|------|------|------|
| token budget management and enforcement | 1.000 | 0.485 | 0.200 | 0.400 | 16060ms |
| message routing and tool dispatch | 0.167 | 0.139 | 0.100 | 0.250 | 6ms |
| swarm task decomposition and scheduling | 1.000 | 0.339 | 0.100 | 0.200 | 8ms |
| agent session persistence and checkpoints | 0.500 | 0.214 | 0.100 | 0.200 | 6ms |
| code intelligence AST parsing and symbol indexing | 0.333 | 0.170 | 0.100 | 0.200 | 5ms |
| safety guardrails and content filtering | 0.000 | 0.000 | 0.000 | 0.000 | 4ms |
| MCP server integration and tool protocol | 0.500 | 0.581 | 0.300 | 0.750 | 6ms |
| execution loop and iteration control | 0.500 | 0.246 | 0.100 | 0.250 | 4ms |
| worker pool and parallel agent spawning | 0.500 | 0.214 | 0.100 | 0.200 | 6ms |
| codebase embedding and semantic search | 1.000 | 0.655 | 0.300 | 0.600 | 3ms |

<details>
<summary>Low-MRR queries (3)</summary>

**Query:** message routing and tool dispatch

Expected:
- `src/attocode/types/messages.py` (found)
- `src/attocode/core/tool_executor.py` (missed)
- `src/attocode/tools/registry.py` (missed)
- `src/attocode/core/response_handler.py` (missed)

Retrieved (top 10):
- 1. `src/attocode/tui/widgets/message_log.py` 
- 2. `src/attocode/integrations/context/ast_server.py` 
- 3. `lessons/22-model-routing/router.ts` 
- 4. `src/attocode/integrations/swarm/worker_pool.py` 
- 5. `src/attocode/code_intel/api/middleware.py` 
- 6. `src/attocode/types/messages.py` **relevant**
- 7. `src/attoswarm/coordinator/task_dispatcher.py` 
- 8. `src/attocode/integrations/utilities/routing.py` 

**Query:** code intelligence AST parsing and symbol indexing

Expected:
- `src/attocode/integrations/context/codebase_ast.py` (found)
- `src/attocode/integrations/context/code_analyzer.py` (missed)
- `src/attocode/integrations/context/ast_chunker.py` (missed)
- `src/attocode/code_intel/indexing/parser.py` (missed)
- `src/attocode/code_intel/storage/symbol_store.py` (missed)

Retrieved (top 10):
- 1. `src/attoswarm/workspace/reconciler.py` 
- 2. `src/attocode/code_intel/service.py` 
- 3. `src/attocode/integrations/context/codebase_ast.py` **relevant**
- 4. `src/attocode/integrations/context/ast_service.py` 
- 5. `src/attocode/code_intel/tools/dead_code_tools.py` 
- 6. `src/attocode/code_intel/api/routes/embeddings.py` 

**Query:** safety guardrails and content filtering

Expected:
- `src/attocode/integrations/safety/policy_engine.py` (missed)
- `src/attocode/integrations/safety/bash_policy.py` (missed)
- `src/attocode/integrations/safety/edit_validator.py` (missed)
- `src/attocode/integrations/security/patterns.py` (missed)

Retrieved (top 10):
- 1. `tests/unit/attoswarm/test_scheduler.py` 
- 2. `src/attocode/agent/agent.py` 
- 3. `src/attoswarm/coordinator/aot_graph.py` 
- 4. `src/attoswarm/workspace/git_safety.py` 
- 5. `src/attocode/code_intel/storage/content_store.py` 
- 6. `src/attocode/code_intel/indexing/parser.py` 
- 7. `lessons/18-react-pattern/observation-formatter.ts` 
- 8. `src/attocode/tricks/recursive_context.py` 
- 9. `legacy/src/providers/adapters/anthropic.ts` 

</details>

## fastapi

| Query | MRR | NDCG | P@10 | R@20 | Time |
|-------|-----|------|------|------|------|
| request validation and dependency injection | 0.000 | 0.000 | 0.000 | 0.000 | 15784ms |
| OpenAPI schema generation | 0.500 | 0.214 | 0.100 | 0.200 | 3ms |
| WebSocket handling and connection management | 0.500 | 0.296 | 0.100 | 0.333 | 1ms |
| middleware stack and request lifecycle | 1.000 | 0.553 | 0.200 | 0.400 | 2ms |
| response model serialization and encoding | 0.000 | 0.000 | 0.000 | 0.000 | 5ms |

<details>
<summary>Low-MRR queries (2)</summary>

**Query:** request validation and dependency injection

Expected:
- `fastapi/dependencies/utils.py` (missed)
- `fastapi/dependencies/models.py` (missed)
- `fastapi/routing.py` (missed)
- `fastapi/params.py` (missed)
- `fastapi/param_functions.py` (missed)

Retrieved (top 10):
- 1. `fastapi/exception_handlers.py` 
- 2. `fastapi/exceptions.py` 
- 3. `docs_src/handling_errors/tutorial006_py310.py` 
- 4. `docs_src/handling_errors/tutorial005_py310.py` 
- 5. `docs_src/handling_errors/tutorial004_py310.py` 
- 6. `tests/test_dependency_contextvars.py` 
- 7. `docs_src/dependencies/tutorial008_an_py310.py` 
- 8. `docs_src/dependencies/tutorial008_py310.py` 

**Query:** response model serialization and encoding

Expected:
- `fastapi/encoders.py` (missed)
- `fastapi/responses.py` (missed)
- `fastapi/routing.py` (missed)
- `fastapi/_compat/shared.py` (missed)
- `fastapi/utils.py` (missed)

Retrieved (top 10):
- 1. `fastapi/openapi/models.py` 
- 2. `fastapi/_compat/v2.py` 
- 3. `tests/test_sse.py` 
- 4. `scripts/contributors.py` 
- 5. `scripts/notify_translations.py` 
- 6. `scripts/sponsors.py` 
- 7. `scripts/people.py` 
- 8. `docs_src/generate_clients/tutorial001_py310.py` 

</details>

## gh-cli

| Query | MRR | NDCG | P@10 | R@20 | Time |
|-------|-----|------|------|------|------|
| CLI command factory and command execution | 0.500 | 0.246 | 0.100 | 0.250 | 3701ms |
| GitHub API client and authentication | 0.000 | 0.000 | 0.000 | 0.000 | 2ms |
| pull request creation and review workflow | 0.000 | 0.000 | 0.000 | 0.000 | 1ms |
| issue listing and filtering | 0.333 | 0.346 | 0.200 | 0.500 | 1ms |
| repository cloning and forking | 0.000 | 0.000 | 0.000 | 0.000 | 1ms |

<details>
<summary>Low-MRR queries (4)</summary>

**Query:** GitHub API client and authentication

Expected:
- `api/client.go` (missed)
- `api/http_client.go` (missed)
- `internal/authflow/flow.go` (missed)
- `pkg/cmd/auth/shared/login_flow.go` (missed)
- `internal/config/config.go` (missed)

Retrieved (top 10):
- 1. `pkg/cmd/attestation/verify/options.go` 
- 2. `internal/run/stub.go` 
- 3. `api/queries_repo.go` 
- 4. `api/queries_pr_review.go` 
- 5. `pkg/cmd/attestation/verify/policy.go` 
- 6. `pkg/cmd/attestation/verification/sigstore.go` 
- 7. `pkg/cmd/attestation/verification/tuf.go` 
- 8. `pkg/cmd/factory/default.go` 

**Query:** pull request creation and review workflow

Expected:
- `pkg/cmd/pr/create/create.go` (missed)
- `pkg/cmd/pr/review/review.go` (missed)
- `pkg/cmd/pr/shared/finder.go` (missed)
- `api/queries_pr.go` (missed)
- `pkg/cmd/pr/shared/survey.go` (missed)

Retrieved (top 10):
- 1. `api/queries_issue.go` 
- 2. `pkg/search/result.go` 
- 3. `internal/featuredetection/detector_mock.go` 
- 4. `internal/featuredetection/feature_detection.go` 
- 5. `pkg/cmd/pr/merge/http.go` 
- 6. `pkg/cmd/pr/shared/editable_http.go` 
- 7. `pkg/cmd/pr/shared/templates.go` 
- 8. `pkg/cmd/pr/status/http.go` 

**Query:** issue listing and filtering

Expected:
- `pkg/cmd/issue/list/list.go` (found)
- `pkg/cmd/issue/list/http.go` (missed)
- `api/queries_issue.go` (found)
- `pkg/cmd/issue/shared/lookup.go` (missed)

Retrieved (top 10):
- 1. `pkg/cmd/pr/list/list_test.go` 
- 2. `pkg/cmd/repo/list/list_test.go` 
- 3. `pkg/cmd/issue/list/list.go` **relevant**
- 4. `pkg/cmd/workflow/shared/shared_test.go` 
- 5. `api/queries_issue.go` **relevant**
- 6. `internal/featuredetection/detector_mock.go` 
- 7. `internal/featuredetection/feature_detection.go` 

**Query:** repository cloning and forking

Expected:
- `pkg/cmd/repo/clone/clone.go` (missed)
- `pkg/cmd/repo/fork/fork.go` (missed)
- `pkg/cmd/repo/create/create.go` (missed)
- `git/client.go` (missed)

Retrieved (top 10):
- 1. `internal/featuredetection/detector_mock.go` 
- 2. `internal/featuredetection/feature_detection.go` 
- 3. `api/queries_repo.go` 
- 4. `pkg/cmd/repo/view/http.go` 
- 5. `internal/codespaces/api/api.go` 
- 6. `pkg/cmd/codespace/mock_api.go` 
- 7. `api/query_builder.go` 
- 8. `pkg/cmd/project/shared/queries/queries.go` 

</details>

## pandas

| Query | MRR | NDCG | P@10 | R@20 | Time |
|-------|-----|------|------|------|------|
| missing data handling and NaN propagation | 0.000 | 0.000 | 0.000 | 0.000 | 8122ms |
| DataFrame indexing and label-based access | 0.333 | 0.170 | 0.100 | 0.200 | 33ms |
| CSV parsing and file I/O | 1.000 | 0.339 | 0.100 | 0.200 | 8ms |
| groupby aggregation and split-apply-combine | 0.000 | 0.000 | 0.000 | 0.000 | 10ms |
| datetime and timedelta operations | 0.125 | 0.107 | 0.100 | 0.200 | 15ms |

<details>
<summary>Low-MRR queries (4)</summary>

**Query:** missing data handling and NaN propagation

Expected:
- `pandas/core/missing.py` (missed)
- `pandas/core/dtypes/missing.py` (missed)
- `pandas/core/ops/missing.py` (missed)
- `pandas/core/array_algos/masked_reductions.py` (missed)
- `pandas/core/nanops.py` (missed)

Retrieved (top 10):
- 1. `pandas/tests/series/test_missing.py` 
- 2. `pandas/tests/arithmetic/test_object.py` 
- 3. `pandas/tests/reshape/test_cut.py` 
- 4. `pandas/tests/series/test_arithmetic.py` 
- 5. `pandas/tests/arrays/categorical/test_missing.py` 
- 6. `pandas/tests/generic/test_frame.py` 
- 7. `pandas/io/stata.py` 
- 8. `pandas/tests/frame/test_subclass.py` 
- 9. `pandas/tests/generic/test_generic.py` 

**Query:** DataFrame indexing and label-based access

Expected:
- `pandas/core/indexing.py` (found)
- `pandas/core/frame.py` (missed)
- `pandas/core/indexes/base.py` (missed)
- `pandas/core/indexes/multi.py` (missed)
- `pandas/core/series.py` (missed)

Retrieved (top 10):
- 1. `pandas/tests/series/test_logical_ops.py` 
- 2. `pandas/io/stata.py` 
- 3. `pandas/core/indexing.py` **relevant**
- 4. `pandas/core/indexes/period.py` 
- 5. `asv_bench/benchmarks/indexing.py` 
- 6. `pandas/tests/frame/indexing/test_indexing.py` 
- 7. `pandas/core/generic.py` 

**Query:** groupby aggregation and split-apply-combine

Expected:
- `pandas/core/groupby/groupby.py` (missed)
- `pandas/core/groupby/generic.py` (missed)
- `pandas/core/groupby/ops.py` (missed)
- `pandas/core/groupby/grouper.py` (missed)
- `pandas/core/apply.py` (missed)

Retrieved (top 10):
- 1. `asv_bench/benchmarks/groupby.py` 
- 2. `pandas/tests/resample/test_resample_api.py` 
- 3. `pandas/tests/groupby/aggregate/test_aggregate.py` 
- 4. `pandas/tests/groupby/test_categorical.py` 
- 5. `pandas/tests/groupby/test_groupby.py` 
- 6. `asv_bench/benchmarks/strings.py` 
- 7. `pandas/core/computation/parsing.py` 
- 8. `pandas/core/internals/blocks.py` 

**Query:** datetime and timedelta operations

Expected:
- `pandas/core/arrays/datetimes.py` (missed)
- `pandas/core/arrays/timedeltas.py` (missed)
- `pandas/core/arrays/datetimelike.py` (found)
- `pandas/core/tools/datetimes.py` (missed)
- `pandas/core/indexes/datetimes.py` (missed)

Retrieved (top 10):
- 1. `asv_bench/benchmarks/tslibs/timedelta.py` 
- 2. `asv_bench/benchmarks/index_object.py` 
- 3. `asv_bench/benchmarks/multiindex_object.py` 
- 4. `asv_bench/benchmarks/arithmetic.py` 
- 5. `asv_bench/benchmarks/timedelta.py` 
- 6. `asv_bench/benchmarks/timeseries.py` 
- 7. `pandas/_libs/index.pyi` 
- 8. `pandas/core/arrays/datetimelike.py` **relevant**

</details>

## redis

| Query | MRR | NDCG | P@10 | R@20 | Time |
|-------|-----|------|------|------|------|
| event-driven server architecture and command handling | 0.200 | 0.131 | 0.100 | 0.200 | 6042ms |
| data structure implementation for sorted sets | 0.000 | 0.000 | 0.000 | 0.000 | 3ms |
| persistence and RDB snapshot mechanism | 0.200 | 0.131 | 0.100 | 0.200 | 2ms |
| cluster communication and node discovery | 0.333 | 0.464 | 0.300 | 0.750 | 3ms |
| memory management and eviction policies | 0.500 | 0.345 | 0.200 | 0.400 | 2ms |

<details>
<summary>Low-MRR queries (4)</summary>

**Query:** event-driven server architecture and command handling

Expected:
- `src/server.c` (found)
- `src/networking.c` (missed)
- `src/ae.c` (missed)
- `src/commands.c` (missed)
- `src/connection.c` (missed)

Retrieved (top 10):
- 1. `deps/hiredis/test.c` 
- 2. `src/module.c` 
- 3. `tests/modules/postnotifications.c` 
- 4. `src/redisassert.c` 
- 5. `src/server.c` **relevant**

**Query:** data structure implementation for sorted sets

Expected:
- `src/t_zset.c` (missed)
- `src/ziplist.c` (missed)
- `src/listpack.c` (missed)
- `src/intset.c` (missed)
- `src/dict.c` (missed)

Retrieved (top 10):
- 1. `src/chk.c` 
- 2. `src/t_stream.c` 
- 3. `src/aof.c` 
- 4. `src/server.c` 
- 5. `src/db.c` 
- 6. `src/module.c` 
- 7. `src/cluster_slot_stats.c` 
- 8. `modules/vector-sets/vset.c` 
- 9. `src/t_set.c` 

**Query:** persistence and RDB snapshot mechanism

Expected:
- `src/rdb.c` (found)
- `src/aof.c` (missed)
- `src/rio.c` (missed)
- `src/bio.c` (missed)
- `src/childinfo.c` (missed)

Retrieved (top 10):
- 1. `src/server.c` 
- 2. `src/cluster_asm.c` 
- 3. `tests/modules/hooks.c` 
- 4. `src/redis-cli.c` 
- 5. `src/rdb.c` **relevant**
- 6. `src/redis-check-aof.c` 
- 7. `src/redis-check-rdb.c` 

**Query:** cluster communication and node discovery

Expected:
- `src/cluster.c` (found)
- `src/cluster_legacy.c` (found)
- `src/cluster_slot_stats.c` (missed)
- `src/cluster_asm.c` (found)

Retrieved (top 10):
- 1. `src/redis-benchmark.c` 
- 2. `src/redis-cli.c` 
- 3. `src/cluster_legacy.c` **relevant**
- 4. `src/cluster.h` 
- 5. `src/cluster_legacy.h` 
- 6. `src/cluster_asm.c` **relevant**
- 7. `src/cluster.c` **relevant**

</details>
