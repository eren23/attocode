# Document lifecycle repair and body-file retrieval follow-up

On top of merged `25d08c4`, the LSP client now owns document-open state and
versions across warmup, precision and edit callers. The retrieval candidate
improved development and some held-out metrics, but failed its full gate and
was not enabled. Two indexing prototypes were measured and left out.

The [machine-readable evidence](2026-10-15-protocol-body-followup.json) retains
source identities, frozen choice, ordered candidates, raw protocol event
observations, component measurements and resource supervision. No new cloud
worker, model request, global installation, host MCP restart or release occurred.

## Rust investigation and protocol fix

PRs #210 and #212 each initially failed the warmed Rust selected-definition
check with `not_resolved`; an unchanged job retry passed. The failure logs do
not establish the cause. Six alternating local baseline/control pairs all
passed, so the intermittent CI failure was not reproduced locally.

Those traces did reveal duplicate document opens after warmup and duplicate
version numbers when two callers sent the same edit. The LSP specification
requires balanced [open/close notifications](https://raw.githubusercontent.com/microsoft/language-server-protocol/gh-pages/_specifications/lsp/3.17/textDocument/didOpen.md).
The client previously had no shared document state, even though warmup and
precision sent notifications through the same server process.

The client now retains only a content digest and sent version per open URI.
An identical open/edit is a no-op; changed content for an open URI becomes a
change with a strictly increasing version. A change for an unopened document
first opens it. Close is balanced, and shutdown/restart clears process-specific
state. No timeout, inspection assertion or language-server readiness rule was
weakened. No source-text copy is retained in this new map.

A strict subprocess regression failed before the repair with duplicate opens
and non-increasing versions. It now covers shared callers, stale caller-local
versions, changed content delivered through open, repeated close, reopen and
server restart. The protocol/streaming suite passed **192 tests**. Six fresh
real-Rust checks passed with three wire opens and one change per fixture,
without duplicate notifications. This proves the lifecycle correction, not
that every cause of the earlier CI failure is eliminated.

## Retrieval: development gain did not pass the complete held-out gate

The [predeclared protocol](../designs/2026-10-15-body-file-trial.md) reused all
48 preceding questions as consumed development evidence. Exactly one candidate
was fixed before scoring: unique-file RRF over retained keyword/body lists,
weights 1:2, k=60, existing test-intent demotion, deterministic path ties.

| Split / arm | Labeled Hit@5 | Labeled Hit@24 | Mean labeled Recall@5 | MRR@24 |
| --- | ---: | ---: | ---: | ---: |
| Consumed development baseline | 33/48 | 44/48 | 0.615 | 0.499 |
| Consumed development candidate | 40/48 | 46/48 | 0.760 | 0.659 |
| Fresh validation baseline | 18/24 | 22/24 | 0.667 | 0.508 |
| Fresh validation candidate | 20/24 | 23/24 | 0.792 | 0.708 |

Development had seven new top-five hits, no top-five losses and no individual
top-24 losses, passing its screen. The [24 new questions](../designs/2026-10-15-body-file-validation.json)
were then source-reviewed and frozen before any retrieval. Each of six pinned
cached repositories contributed four questions. Source files and repositories
are not disjoint from development; labels remain non-exhaustive. Express's
mounted-child question crosses component boundaries but labels only its
in-repository application glue.

Validation gained two top-five hits (Express destination headers and OkHttp
read-timeout override), below the required three. It also lost the existing
top-24 hit for Phoenix code reloading, despite a net top-24 gain. **Both fail
conditions matter; aggregate improvement does not override individual loss.**
The candidate therefore stays evaluation-only. No weight sweep, post-validation
candidate tuning, opt-in flag or ranking-default change followed.

Warmed p95 was 29.56 ms baseline and 29.72 ms candidate. Candidate timing
includes baseline retrieval plus fusion over its retained pools. Three bounded
validation invocations took 15.678 seconds total, peaking at 102.7 MiB managed
disk and 126.3 MiB process-tree RSS. All 24 questions are now consumed evidence.
A later harness-only refactor adds explicit choice-guard tests; it does not
change candidate scoring or rerun the held-out questions. The frozen report
hashes preserve the actual evaluated implementation.

## Cockroach component investigation

A cached pinned slice of 32 alphabetically selected non-test Go files, each
4–128 KiB, totaled 652,101 bytes. No full local checkout or index was created.
A profile identified tokenization as a substantial component. Prehydrated ASTs
were then used for four alternating observations per arm; all source-window
and whole-file-term output hashes matched within each comparison.

| Prototype | Baseline median | Prototype median | Decision |
| --- | ---: | ---: | --- |
| Bounded cross-file token cache | 51.93 ms | 55.96 ms | Reject: slower |
| Filter short tokens before lowercase, remove generator | 48.39 ms | 46.90 ms | Do not adopt: small component gain |

The cache reduced tokenizer calls from 13,311 to 11,424 but added enough lookup
and bookkeeping overhead to lose time. The allocation prototype's roughly 3%
component difference does not establish useful end-to-end headroom. Neither
changed product indexing. Measurements include output serialization, omit SQL
persistence, and are not a full-cloud comparison. The last actual Cockroach
workflow remains **167.970/180 seconds**, with a narrow margin.

All task-owned source/fixture/index/cache data is cleaned after verification;
only reports and small operator scripts remain. Protected studies and shared
caches are preserved. Further cloud work needs a new allowance: the preceding
conditional retry ended when its target passed.


## Final local verification

The [final verification record](2026-10-15-protocol-body-validation.json) binds
the final source and fixture hashes to a passing local suite: **648 passed,
eight skipped**, lint, scale and lifecycle. The unchanged frozen ranking gate
also passed all 68 query variants across five methods. Local and ranking runs
completed in about 41 and 42 seconds. Their source hashes stayed unchanged
through execution. The ranking candidate function is AST-identical to its
frozen development implementation; only its validation admission guard was
refactored afterwards. Product indexing/ranking code is unchanged by this PR.
