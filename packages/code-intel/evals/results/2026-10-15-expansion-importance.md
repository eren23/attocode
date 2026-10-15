# Expansion comparison and importance publication

Work on top of `d5a596e`, including the preceding file-symbol repair, prepared
for upstream integration after local validation. The retrieval
experiment did not meet its improvement rule, so no ranking policy was enabled.
Neither repair is part of published 0.1.6.

The [machine-readable record](2026-10-15-expansion-importance.json) retains
candidate lists, labels, hashes, paired outcomes, timing counters and validation.
The [protocol](../designs/2026-10-15-expansion-ablation.md) and both question
manifests were frozen before execution. No model or cloud worker was used.

## Expansion and fusion

Development reused 14 FastAPI/Laravel questions. The source-verified HTTPBearer
alternative supplements the old FastAPI label; earlier published scores remain
unchanged. All expansion arms used the same warmed indexes. File RRF used only
the retained candidate lists from its associated expansion arm, with fixed
weights and the existing test-intent policy.

| Input | Fusion | Labeled hit@5 | Labeled hit@24 |
| --- | --- | ---: | ---: |
| Current expansion | Existing | 9/14 | 12/14 |
| Current expansion | File RRF | 7/14 | 11/14 |
| Whole-token expansion | Existing | 10/14 | 13/14 |
| Whole-token expansion | File RRF | 8/14 | 12/14 |
| Original query | Existing | 11/14 | 13/14 |
| Original query | File RRF | 11/14 | 12/14 |

Original query with existing fusion was selected before validation, recorded
in [the selection snapshot](2026-10-15-expansion-choice.json). Its
`validation_not_run` field describes that historical selection moment.

On 12 new source-anchored Requests/GitHub CLI questions, both current expansion
and original query achieved **12/12 at five and 24**, with identical first-target
ranks. Retrieval p95 was 21.34 ms versus 23.42 ms. The selected arm had no lost
hits but also no additional hit, failing the predeclared improvement requirement.
File RRF, which was not selected, reached 11/12 at five in both arms.

No new opt-in or default policy was added. The validation ceiling limits what
can be inferred; it is not evidence that expansion can never hurt. Questions
were not replaced or tuned after seeing the outcome. These repositories have
prior evaluation exposure, labels are non-exhaustive, and this measures source
retrieval rather than agent outcomes. These questions are now consumed evidence.

## Importance publication repair

Foreground profiling exposed a window where `_kw_index_built` was true while
cache persistence was still running, before warmup had loaded importance scores.
A concurrent query then created another context to obtain those scores,
rediscovering and reparsing the workspace on the request thread.

The keyword builder now publishes importance from its existing context before
marking the keyword index ready. It replaces the complete score map atomically,
removing deleted paths and preserving the previous complete map if inventory
iteration fails. Keyword/importance phase timings remain exclusive. This does
not change scoring weights, expansion, timeout limits or persistent schemas.

Four regression tests failed on the old implementation and pass after the fix:
query during cache save, delete/rename refresh, interrupted inventory publication
and direct builder readiness. Existing cold-index and discovery checks pass too.

A forced cache-save overlap on 128 generated Go files used two alternating
observations per arm, loading the old methods from a hash-verified source copy.

| Measurement | Before | After |
| --- | ---: | ---: |
| Extra foreground discoveries | 1 | 0 |
| Extra foreground parse calls | 128 | 0 |
| Foreground query time | 49.39–55.08 ms | 7.17–7.27 ms |
| Total controlled workload time | 254.39–258.08 ms | 205.35–212.19 ms |

Foreground results including scores, ready results and importance maps have
identical hashes across all four observations. Both parser/discovery entry
points were instrumented. This proves removal of duplicate work in the forced
window; it does not establish general throughput or Cockroach timing headroom.

A separate 256-file Go navigation profile also no longer shows foreground
importance discovery. Absolute pre/post profile durations are not a controlled
speed comparison: initial tokenizer setup and profiler overhead differ. The
last cloud Cockroach observation remains 177.579 seconds against 180 seconds.

## Validation and resource bounds

- Local run `20261015T183830-4bf2ab4f`: **622 passed, eight skipped**, plus lint,
  100/1,000/10,000-file scale checks and lifecycle checks; 38.53 seconds,
  122.3 MiB peak managed disk and 575.4 MiB sampled process-tree RSS.
- Frozen ranking run `20261015T183920-eb47e343`: **passed**, 68 query variants
  across five methods; 39.56 seconds, 338.1 MiB peak managed disk. No Acc@5 or
  R@5 losses against its historical baseline. Product MRR@5 stayed 0.537;
  keyword MRR@5 changed from 0.495 to 0.487 within the existing gate tolerance.
  Fifteen query/method top-five lists changed. This is not exact output parity,
  and the historical comparison does not isolate the contribution of either
  local repair. The controlled overlap comparison above does isolate its fix.
- Development and validation ran for 15.87 and 3.75 supervised seconds, with
  peak managed disk 116.2 and 62.6 MiB. The final overlap probe took 1.26 seconds.
  Source packs, generated workspaces, indexes and task-owned tokenizer cache
  were removed; only small reports remain. Shared studies and caches were kept.
- Final source and fixture hashes match both final validation reports. An
  initial probe attempt failed due to an empty `patch.multiple` call; its log
  is retained as failed evidence. An incorrect fusion-test ordering expectation
  was corrected to reflect the predeclared body weight; the policy was unchanged.

Private raw evidence is in `.attocode/quality/runs/20261015-expansion-profile`.
The recorded local experiments preceded upstream publication. No release,
global tool upgrade or host MCP restart was performed. No additional cloud
spending occurred. Further timing claims require testing
the eventual published candidate on the large repository within a new cloud
allowance; the previously approved slots remain exhausted.
