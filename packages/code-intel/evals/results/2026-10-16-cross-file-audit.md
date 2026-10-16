# Cross-file search: one hit is not a complete route through the code

Six new questions all returned at least one labeled file in the first five,
but only one returned every labeled file there. Increasing depth helped coverage,
but one known file still disappeared between the retained pool and delivery.
No retrieval weight, ranking default, model or release changed.

This diagnostic follows merged [PR #216](https://github.com/eren23/attocode/pull/216),
which repairs incremental reference and current-branch impact workflows. Search
measurements ran on `7974210f085d5a832a053d82c91e116f0e815318` after that merge.
The [machine-readable record](2026-10-16-cross-file-audit.json) retains all ordered
file results, stage ranks, source identity, resource observations and cleanup.

## Frozen questions and limits

The [six-question manifest](../designs/2026-10-16-cross-file-questions.json) was
source-reviewed and frozen before retrieval, SHA-256
`8d75705738819f73c530f4410a92f4183bf5366a9355ebe32108df386e7bce34`.
There are two questions each for pinned ripgrep, OkHttp and Cats Effect snapshots.
Each question labels two or three distinct files, with source hashes, line anchors
and a reason each file contributes. They cover configuration-to-execution,
queuing-to-cleanup, upgrade-to-frame handling, context switching and resource release.

These are new questions on previously exposed repositories/files, labeled by the
implementing agent. Labels are non-exhaustive and not independent human judgments.
Six long, cross-file questions do not estimate general search quality or agent
completion. All six are consumed development evidence after this run. There was
no candidate selection, weight tuning, replacement question or repeated scoring.

The existing `eval.quality.retrieval_replay` ran the default provider-free search
with expansion enabled at requested depths 24 and 96. It records distinct returned
files in their first-occurrence order. A request counts hits/chunks, not necessarily
distinct files: depth 96 is a new query with wider pools, not a stable cursor.
These are lexical file-retrieval observations, not an MCP output-budget test.

For historical context, **15/24** was the preceding held-out baseline. The later
[body-file trial](2026-10-15-protocol-body-followup.md) baseline was **18/24**;
its candidate reached 20/24 but failed the full gate. Neither number is directly
comparable to these six questions.

## Results

| Request / measurement | Any label found | All labels found | Retrieved label pairs | Mean per-question labeled recall |
| --- | ---: | ---: | ---: | ---: |
| Depth 24, first five distinct files | 6/6 | 1/6 | 7/13 | 55.6% |
| Depth 24, all delivered distinct files | 6/6 | 5/6 | 11/13 | 88.9% |
| Depth 96, all delivered distinct files | 6/6 | 5/6 | 12/13 | 94.4% |

Relevant-file ranks at depth 24:

| Question | Labeled files and delivered ranks |
| --- | --- |
| ripgrep multiline stream | searcher/mod.rs 5; flags/hiargs.rs absent; searcher/glue.rs absent |
| ripgrep match limit and trailing context | searcher/core.rs 3; flags/hiargs.rs 7 |
| OkHttp queued work and executor rejection | Dispatcher.kt 1; RealCall.kt 8 |
| OkHttp upgrade and incoming frames | WebSocketReader.kt 1; RealWebSocket.kt 2 |
| Cats Effect context switching | IO.scala 4; IOFiber.scala 13 |
| Cats Effect outcome-aware resource release | Resource.scala 3; MonadCancel.scala 12 |

Finding an entry point is different from surfacing the labeled execution path.
Four questions had their second labeled implementation at ranks 7–13, so Hit@5
alone would hide the missing context.

## Reproduced delivery limitation

For the multiline-stream question, depth 24 retained `hiargs.rs` at fused file
rank 30, outside delivery. `glue.rs` was absent from that request's retained
stages. At depth 96, both files appeared: `hiargs.rs` at fused rank 30 and
`glue.rs` at fused rank 58 (body rank 63). Yet delivery contained only 30 distinct
files and omitted `glue.rs`.

The relevant default path is `_default_file_diversity` in `query_ranking.py`.
It selects distinct files only when it can fill the entire requested count.
Otherwise it returns the first requested chunks. This query's retained pool
contained 88 distinct files, fewer than the requested 96, so repeated chunks
crowded out a known relevant candidate. This is not evidence of missing indexing.

A model-free control on the unchanged function reproduces the mechanism:
120 chunks from one file followed by 87 other files yield 24 distinct files for
a request of 24, but only one distinct file for a request of 96. The control and
actual observations are both retained in the JSON; the synthetic control is not
counted as a retrieval-quality result.

The next candidate to evaluate is preserving the available first-occurrence file
order when a pool cannot fill a requested page, with an explicit choice about
whether to return fewer hits or append remaining chunks. That needs contract tests
for scoped/test-intent queries, stable counts and ordering, followed by fresh
multi-relevant validation before changing defaults. No such candidate was run here.

## Resources and reproduction

Three sequential supervised invocations took **6.759 seconds** total. Peak managed
storage was **38.2 MiB** and sampled process-tree RSS **107.4 MiB**. Each invocation
had a 180-second deadline, 512 MiB disk ceiling and 1.5 GiB RSS ceiling; source
materialization was capped at 64 MiB. Each pack's temporary source/index/cache was
removed, with reports retained. Existing shared sources and study caches were
read-only. No download, cloud worker, model request or upstream repository test ran.

Single warmed query observations ranged from 15.78–34.23 ms at depth 24 and
20.21–51.60 ms at depth 96; these are not repeated latency estimates.

The underlying command, repeated once per pack under `eval.quality.runner.supervise`, was:

```sh
.venv/bin/python -m eval.quality.retrieval_replay \
  --pack ripgrep \
  --questions packages/code-intel/evals/designs/2026-10-16-cross-file-questions.json \
  --output /private/tmp/ripgrep-cross-file-audit.json
```

Use the existing cached pinned sources, provider-free quality environment and
stated resource bounds when reproducing. Reruns are development checks, not
fresh validation. No product implementation changed in this evidence follow-up.
