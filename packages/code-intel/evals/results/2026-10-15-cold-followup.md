# Two-batch cold-index follow-up: release still blocked

Both approved follow-up batches completed. Each passed 35 of 36 pinned source
packs; CockroachDB body-index warmup remained incomplete. The repairs did not
establish an end-to-end improvement. 0.1.6 remains unpublished.

The [normalized record](2026-10-15-cold-followup.json) retains both source/harness/
fixture/pack/archive identities, every pack status, failure diagnostics, resource
measurements, controller phases and verified cleanup. The earlier
[four-batch cycle](2026-10-15-cold-repair-cycle.md) is preserved separately.

| Full batch | Source | Region | Keyword stage | Body unfinished at total warmup | Controller | Compute estimate |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| `3559bf173ff742ab` | `4f33254` | Frankfurt | 55.955 s | 98.125 s | 24.04 min | $0.0668 |
| `36a9a84ae9954f66` | `19beb72` | Amsterdam | 57.280 s | 132.860 s | 23.93 min | $0.0665 |

Frankfurt capacity became unavailable before the second reservation. An explicit
controller change selected the same shared 8-vCPU/16-GiB size in Amsterdam at the
same $0.16667/hour quote. That refused preflight created no worker or reservation.
The two environments are not a controlled latency comparison. Neither full run
passes the unchanged cold gate; the small contention probes do not supersede this.

## Final full-gate evidence

- **532 contracts passed, 22 skipped**, zero errors/failures. Lint, scale and
  lifecycle passed. The failed workflow gate caused ranking to be skipped.
- **35/36 packs passed their defined contracts**, including explicit limitations.
  Completed checks had 125 passed, 120 limited and 37 unsupported outcomes.
  Optional grammars were unavailable in this cloud environment; separate grammar
  CI coverage does not make these unsupported operations successful assertions.
- **140/144 retrieval questions observed**, with 99 labeled hits in the first five
  and 127 in the first 24. Four Cockroach questions are missing. Labels are
  non-exhaustive development targets; missing observations are not zero-hit results.
  No agent-outcome or ranking-improvement claim is supported.
- Cockroach definition/source checks passed in **35.743/42.321 seconds**. Keyword
  warmup took **57.280 seconds**, with 4,980 reused ASTs. Body warmup was incomplete
  at **132.860 seconds total**. The 90-second polling threshold is checked after
  a tool response; it is not hard cancellation. Zero file counts during warmup
  are placeholder diagnostics until the body index is built, not progress evidence.
- Controller **1435.531 seconds**, within its 90-minute budget. Both follow-up
  runs completed clean bootstrap before setup, with one report per worker and no
  observed restart. The historical 100-minute overrun did not recur; these runs
  do not prove universal deadline correctness.
- Peak managed check disk **1,117,188,250 bytes**, sampled process-tree RSS
  **682,283,008 bytes**, below 5 GiB/4 GiB caps. Exported report/log/XML files
  totaled **1,465,131 bytes**. Source corpora and indexes stayed on the worker.
- Both follow-up workers were deleted; all 16 ledger entries have verified
  cleanup. Independent provider API inspection found zero active quality workers.

## Changes retained and their limits

[PR #194](https://github.com/eren23/attocode/pull/194) batches structural SQL writes;
[PR #197](https://github.com/eren23/attocode/pull/197) batches keyword-cache writes
and body deletions. Their [structural](2026-10-15-structural-write-contention.md)
and [lexical](2026-10-15-lexical-sql-contention.md) component probes preserve rows
and demonstrate scheduling-sensitive contention differences. They did not resolve
the full cold-start failure. Exact-row, replacement-order, cancellation, rollback
and retry controls passed; no ranking weights, labels or warmup limits changed.

[PR #196](https://github.com/eren23/attocode/pull/196) streams bounded progress logs
without waiting for a full read buffer and preserves bounded worker exception
messages alongside partial checks. This made the final failure observable during
execution. [PR #195](https://github.com/eren23/attocode/pull/195) recorded the approved
two-batch budget extension; [PR #198](https://github.com/eren23/attocode/pull/198)
records the explicit same-size/rate region change. Every reported non-skipped
exact-head CI check passed before these merges.

## Cost and release decision

The two follow-up rentals total **$0.1333 estimated compute**; all 16 ledger
rentals total **$0.7820 estimated compute**. The $16 monthly reservation cap is an
admission limit, not a charge. The last user-reported dashboard amount was $0.62
before the preceding repair cycle; no fresh invoice was obtained.

Both additional rental slots are exhausted. No extra worker, 0.1.6 tag or
publication is authorized by the failed gate. No model/Claude request, global tool
upgrade, host MCP restart or protected-cache cleanup was performed.

## Next diagnostic, pending a separate execution allowance

The two complete follow-up attempts did not establish an end-to-end improvement.
Component contention probes preserve semantics but do not identify the dominant
cost in CockroachDB. Further performance changes should follow a bounded diagnostic
that separates elapsed time from work performed:

1. Add opt-in aggregate counters for discovery/stat/hash/AST extraction, keyword
   construction/frequency aggregation/cache serialization/SQL, and body
   tokenization/window construction/SQL/commit. Record monotonic wall time and
   current-thread CPU time separately. Keep per-file data bounded (counts and a
   capped slow-file list), record partial progress on cancellation, and test that
   disabled instrumentation preserves behavior and instrumented rows/ranking match.
2. Use the same pinned Cockroach revision and worker size, with fresh disposable
   indexes. Compare the normal concurrent startup path with an isolated lexical
   path after structural hydration; preserve source/fixture identity, full input
   scope, completed-file/byte counts, and CPU/memory/disk bounds. This is a mechanism
   diagnostic, not a release gate or an agent study. Sequential/isolated timing must
   include the work moved before lexical startup when discussing user latency.
3. Choose a repair only when the measurements identify a dominant subphase or
   repeated work. Require exact cache/FTS/ranking parity and rollback/freshness
   controls. Run a bounded Cockroach confirmation before spending on another full
   matrix; a final unchanged all-pack/ranking gate remains required for release.

Current source facts limit interpretation: `candidate_diagnostics` returns zero
file counts until body indexing is built, so these fields are not progress counters.
`_warm_candidate_indexes` separates keyword/importance/body only. The shared
`CodebaseContextManager` expires its discovery cache after 300 seconds; the observed
57-second keyword stage alone does not demonstrate a repeated discovery.

No additional rental, model request or profiling run is authorized or performed by
this plan. The two-batch allowance is exhausted; 0.1.6 stays unpublished.
