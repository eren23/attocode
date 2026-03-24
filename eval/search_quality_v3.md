# Search Quality Evaluation Report

_Generated: 2026-03-24 12:58:09_

## Summary

| Repo | Queries | MRR@10 | NDCG@10 | P@10 | R@20 | Time (ms) |
|------|---------|--------|---------|------|------|-----------|
| attocode | 10 | 0.725 | 0.379 | 0.160 | 0.350 | 18235 |
| fastapi | 5 | 0.529 | 0.260 | 0.100 | 0.227 | 16402 |
| gh-cli | 5 | 0.200 | 0.161 | 0.100 | 0.240 | 2656 |
| pandas | 5 | 0.329 | 0.133 | 0.060 | 0.120 | 8271 |
| redis | 5 | 0.213 | 0.173 | 0.120 | 0.250 | 6589 |
| **Overall** | 30 | 0.453 | 0.248 | 0.117 | 0.256 | 52152 |

## attocode

| Query | MRR | NDCG | P@10 | R@20 | Time |
|-------|-----|------|------|------|------|
| token budget management and enforcement | 1.000 | 0.470 | 0.200 | 0.400 | 18173ms |
| message routing and tool dispatch | 1.000 | 0.390 | 0.100 | 0.250 | 8ms |
| swarm task decomposition and scheduling | 1.000 | 0.460 | 0.200 | 0.400 | 10ms |
| agent session persistence and checkpoints | 0.500 | 0.214 | 0.100 | 0.200 | 8ms |
| code intelligence AST parsing and symbol indexing | 0.250 | 0.146 | 0.100 | 0.200 | 6ms |
| safety guardrails and content filtering | 0.000 | 0.000 | 0.000 | 0.000 | 5ms |
| MCP server integration and tool protocol | 1.000 | 0.788 | 0.300 | 0.750 | 8ms |
| execution loop and iteration control | 0.500 | 0.369 | 0.200 | 0.500 | 4ms |
| worker pool and parallel agent spawning | 1.000 | 0.339 | 0.100 | 0.200 | 8ms |
| codebase embedding and semantic search | 1.000 | 0.616 | 0.300 | 0.600 | 4ms |

<details>
<summary>Low-MRR queries (2)</summary>

**Query:** code intelligence AST parsing and symbol indexing

Expected:
- `src/attocode/integrations/context/codebase_ast.py` (found)
- `src/attocode/integrations/context/code_analyzer.py` (missed)
- `src/attocode/integrations/context/ast_chunker.py` (missed)
- `src/attocode/code_intel/indexing/parser.py` (missed)
- `src/attocode/code_intel/storage/symbol_store.py` (missed)

Retrieved (top 10):
- 1. `src/attocode/code_intel/db/models.py` 
- 2. `src/attocode/code_intel/service.py` 
- 3. `src/attoswarm/workspace/reconciler.py` 
- 4. `src/attocode/integrations/context/codebase_ast.py` **relevant**
- 5. `src/attocode/integrations/context/ast_service.py` 
- 6. `src/attocode/code_intel/tools/dead_code_tools.py` 

**Query:** safety guardrails and content filtering

Expected:
- `src/attocode/integrations/safety/policy_engine.py` (missed)
- `src/attocode/integrations/safety/bash_policy.py` (missed)
- `src/attocode/integrations/safety/edit_validator.py` (missed)
- `src/attocode/integrations/security/patterns.py` (missed)

Retrieved (top 10):
- 1. `src/attoswarm/workspace/git_safety.py` 
- 2. `src/attocode/agent/agent.py` 
- 3. `src/attoswarm/coordinator/aot_graph.py` 
- 4. `tests/unit/integrations/recording/test_recording.py` 
- 5. `src/attocode/tricks/recursive_context.py` 
- 6. `tests/unit/attoswarm/test_scheduler.py` 
- 7. `src/attocode/tricks/kv_cache.py` 
- 8. `src/attocode/code_intel/db/models.py` 
- 9. `src/attocode/types/messages.py` 

</details>

## fastapi

| Query | MRR | NDCG | P@10 | R@20 | Time |
|-------|-----|------|------|------|------|
| request validation and dependency injection | 0.143 | 0.113 | 0.100 | 0.200 | 16388ms |
| OpenAPI schema generation | 1.000 | 0.339 | 0.100 | 0.200 | 4ms |
| WebSocket handling and connection management | 0.500 | 0.296 | 0.100 | 0.333 | 1ms |
| middleware stack and request lifecycle | 1.000 | 0.553 | 0.200 | 0.400 | 2ms |
| response model serialization and encoding | 0.000 | 0.000 | 0.000 | 0.000 | 7ms |

<details>
<summary>Low-MRR queries (2)</summary>

**Query:** request validation and dependency injection

Expected:
- `fastapi/dependencies/utils.py` (found)
- `fastapi/dependencies/models.py` (missed)
- `fastapi/routing.py` (missed)
- `fastapi/params.py` (missed)
- `fastapi/param_functions.py` (missed)

Retrieved (top 10):
- 1. `fastapi/exceptions.py` 
- 2. `fastapi/exception_handlers.py` 
- 3. `docs_src/handling_errors/tutorial006_py310.py` 
- 4. `docs_src/handling_errors/tutorial005_py310.py` 
- 5. `docs_src/handling_errors/tutorial004_py310.py` 
- 6. `tests/test_dependency_contextvars.py` 
- 7. `fastapi/dependencies/utils.py` **relevant**
- 8. `tests/test_validation_error_context.py` 

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
- 3. `scripts/contributors.py` 
- 4. `scripts/notify_translations.py` 
- 5. `scripts/sponsors.py` 
- 6. `scripts/people.py` 
- 7. `docs_src/generate_clients/tutorial001_py310.py` 
- 8. `docs_src/generate_clients/tutorial002_py310.py` 

</details>

## gh-cli

| Query | MRR | NDCG | P@10 | R@20 | Time |
|-------|-----|------|------|------|------|
| CLI command factory and command execution | 0.333 | 0.318 | 0.200 | 0.500 | 2649ms |
| GitHub API client and authentication | 0.333 | 0.170 | 0.100 | 0.200 | 3ms |
| pull request creation and review workflow | 0.000 | 0.000 | 0.000 | 0.000 | 2ms |
| issue listing and filtering | 0.333 | 0.318 | 0.200 | 0.500 | 1ms |
| repository cloning and forking | 0.000 | 0.000 | 0.000 | 0.000 | 1ms |

<details>
<summary>Low-MRR queries (5)</summary>

**Query:** CLI command factory and command execution

Expected:
- `internal/ghcmd/cmd.go` (found)
- `pkg/cmd/root/root.go` (missed)
- `pkg/cmd/factory/default.go` (missed)
- `pkg/cmdutil/factory.go` (found)

Retrieved (top 10):
- 1. `pkg/cmd/issue/lock/lock.go` 
- 2. `git/command.go` 
- 3. `pkg/cmdutil/factory.go` **relevant**
- 4. `git/client.go` 
- 5. `internal/run/stub.go` 
- 6. `pkg/cmd/root/help.go` 
- 7. `pkg/cmd/extension/mocks.go` 
- 8. `internal/ghcmd/cmd.go` **relevant**
- 9. `pkg/cmd/extension/git.go` 

**Query:** GitHub API client and authentication

Expected:
- `api/client.go` (missed)
- `api/http_client.go` (missed)
- `internal/authflow/flow.go` (missed)
- `pkg/cmd/auth/shared/login_flow.go` (missed)
- `internal/config/config.go` (found)

Retrieved (top 10):
- 1. `pkg/cmd/attestation/verify/options.go` 
- 2. `internal/gh/mock/config.go` 
- 3. `internal/config/config.go` **relevant**
- 4. `internal/run/stub.go` 
- 5. `api/queries_repo.go` 
- 6. `pkg/cmd/attestation/verify/policy.go` 
- 7. `pkg/cmd/attestation/verification/sigstore.go` 
- 8. `pkg/cmd/attestation/verification/tuf.go` 
- 9. `pkg/cmd/codespace/mock_api.go` 

**Query:** pull request creation and review workflow

Expected:
- `pkg/cmd/pr/create/create.go` (missed)
- `pkg/cmd/pr/review/review.go` (missed)
- `pkg/cmd/pr/shared/finder.go` (missed)
- `api/queries_pr.go` (missed)
- `pkg/cmd/pr/shared/survey.go` (missed)

Retrieved (top 10):
- 1. `api/queries_pr_review.go` 
- 2. `pkg/search/result.go` 
- 3. `pkg/cmd/project/shared/queries/queries.go` 
- 4. `pkg/cmd/workflow/shared/shared.go` 
- 5. `pkg/cmd/attestation/inspect/bundle.go` 
- 6. `internal/featuredetection/feature_detection.go` 
- 7. `pkg/cmd/agent-task/capi/sessions.go` 
- 8. `pkg/cmd/agent-task/capi/job.go` 
- 9. `pkg/cmd/pr/shared/templates.go` 

**Query:** issue listing and filtering

Expected:
- `pkg/cmd/issue/list/list.go` (missed)
- `pkg/cmd/issue/list/http.go` (missed)
- `api/queries_issue.go` (found)
- `pkg/cmd/issue/shared/lookup.go` (found)

Retrieved (top 10):
- 1. `pkg/search/result.go` 
- 2. `pkg/cmd/project/shared/queries/queries.go` 
- 3. `api/queries_issue.go` **relevant**
- 4. `pkg/cmd/pr/list/list_test.go` 
- 5. `pkg/cmd/repo/list/list_test.go` 
- 6. `internal/featuredetection/feature_detection.go` 
- 7. `pkg/cmd/pr/shared/templates.go` 
- 8. `pkg/cmd/issue/shared/lookup.go` **relevant**
- 9. `pkg/cmd/status/status.go` 

**Query:** repository cloning and forking

Expected:
- `pkg/cmd/repo/clone/clone.go` (missed)
- `pkg/cmd/repo/fork/fork.go` (missed)
- `pkg/cmd/repo/create/create.go` (missed)
- `git/client.go` (missed)

Retrieved (top 10):
- 1. `internal/codespaces/api/api.go` 
- 2. `pkg/search/result.go` 
- 3. `api/queries_repo.go` 
- 4. `pkg/cmd/repo/list/http.go` 
- 5. `internal/featuredetection/feature_detection.go` 
- 6. `pkg/cmd/repo/create/http.go` 
- 7. `pkg/cmd/repo/edit/edit.go` 
- 8. `internal/featuredetection/detector_mock.go` 

</details>

## pandas

| Query | MRR | NDCG | P@10 | R@20 | Time |
|-------|-----|------|------|------|------|
| missing data handling and NaN propagation | 0.000 | 0.000 | 0.000 | 0.000 | 8192ms |
| DataFrame indexing and label-based access | 0.500 | 0.214 | 0.100 | 0.200 | 41ms |
| CSV parsing and file I/O | 1.000 | 0.339 | 0.100 | 0.200 | 9ms |
| groupby aggregation and split-apply-combine | 0.143 | 0.113 | 0.100 | 0.200 | 11ms |
| datetime and timedelta operations | 0.000 | 0.000 | 0.000 | 0.000 | 18ms |

<details>
<summary>Low-MRR queries (3)</summary>

**Query:** missing data handling and NaN propagation

Expected:
- `pandas/core/missing.py` (missed)
- `pandas/core/dtypes/missing.py` (missed)
- `pandas/core/ops/missing.py` (missed)
- `pandas/core/array_algos/masked_reductions.py` (missed)
- `pandas/core/nanops.py` (missed)

Retrieved (top 10):
- 1. `pandas/tests/series/test_missing.py` 
- 2. `pandas/tests/reshape/test_cut.py` 
- 3. `pandas/tests/arithmetic/test_object.py` 
- 4. `pandas/tests/series/test_arithmetic.py` 
- 5. `pandas/tests/arrays/categorical/test_missing.py` 
- 6. `pandas/tests/generic/test_frame.py` 
- 7. `pandas/io/stata.py` 

**Query:** groupby aggregation and split-apply-combine

Expected:
- `pandas/core/groupby/groupby.py` (missed)
- `pandas/core/groupby/generic.py` (missed)
- `pandas/core/groupby/ops.py` (missed)
- `pandas/core/groupby/grouper.py` (missed)
- `pandas/core/apply.py` (found)

Retrieved (top 10):
- 1. `asv_bench/benchmarks/strings.py` 
- 2. `asv_bench/benchmarks/groupby.py` 
- 3. `pandas/tests/resample/test_resample_api.py` 
- 4. `asv_bench/benchmarks/frame_methods.py` 
- 5. `pandas/core/window/rolling.py` 
- 6. `asv_bench/benchmarks/rolling.py` 
- 7. `pandas/core/apply.py` **relevant**
- 8. `pandas/tests/groupby/aggregate/test_aggregate.py` 

**Query:** datetime and timedelta operations

Expected:
- `pandas/core/arrays/datetimes.py` (missed)
- `pandas/core/arrays/timedeltas.py` (missed)
- `pandas/core/arrays/datetimelike.py` (missed)
- `pandas/core/tools/datetimes.py` (missed)
- `pandas/core/indexes/datetimes.py` (missed)

Retrieved (top 10):
- 1. `asv_bench/benchmarks/index_object.py` 
- 2. `asv_bench/benchmarks/multiindex_object.py` 
- 3. `pandas/_libs/index.pyi` 
- 4. `asv_bench/benchmarks/timedelta.py` 
- 5. `asv_bench/benchmarks/tslibs/timedelta.py` 
- 6. `asv_bench/benchmarks/arithmetic.py` 
- 7. `pandas/tests/scalar/timestamp/test_timezones.py` 
- 8. `pandas/core/indexes/timedeltas.py` 
- 9. `pandas/core/resample.py` 

</details>

## redis

| Query | MRR | NDCG | P@10 | R@20 | Time |
|-------|-----|------|------|------|------|
| event-driven server architecture and command handling | 0.200 | 0.131 | 0.100 | 0.200 | 6578ms |
| data structure implementation for sorted sets | 0.000 | 0.000 | 0.000 | 0.000 | 3ms |
| persistence and RDB snapshot mechanism | 0.200 | 0.131 | 0.100 | 0.200 | 2ms |
| cluster communication and node discovery | 0.167 | 0.139 | 0.100 | 0.250 | 4ms |
| memory management and eviction policies | 0.500 | 0.466 | 0.300 | 0.600 | 2ms |

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
- 1. `src/module.c` 
- 2. `deps/hiredis/test.c` 
- 3. `deps/hiredis/adapters/libevent.h` 
- 4. `src/server.h` 
- 5. `src/server.c` **relevant**
- 6. `src/ae_epoll.c` 
- 7. `src/eventnotifier.h` 

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
- 8. `src/config.c` 

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
- 3. `src/server.h` 
- 4. `src/redis-cli.c` 
- 5. `src/rdb.c` **relevant**
- 6. `src/redis-check-aof.c` 

**Query:** cluster communication and node discovery

Expected:
- `src/cluster.c` (missed)
- `src/cluster_legacy.c` (found)
- `src/cluster_slot_stats.c` (missed)
- `src/cluster_asm.c` (missed)

Retrieved (top 10):
- 1. `src/cluster.h` 
- 2. `src/cluster_legacy.h` 
- 3. `src/redis-benchmark.c` 
- 4. `src/redis-cli.c` 
- 5. `src/module.c` 
- 6. `src/cluster_legacy.c` **relevant**

</details>
