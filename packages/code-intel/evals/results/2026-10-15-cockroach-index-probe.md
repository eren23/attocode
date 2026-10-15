# CockroachDB cold-index mechanism diagnostic

Both instrumented modes ended with body indexing incomplete. Waiting for structural
hydration reduced keyword work's elapsed time, but added an earlier wait and did
not produce a ready search index. Do not enable that scheduling change as a fix.
The [last full release gate](2026-10-15-cold-followup.md) still fails; standalone
0.1.6 remains unpublished.

## Input and execution

One approved worker ran source `fa4f69def7a55a14e38e4c17c966ef2c4eb23a00`
(PR #200 instrumentation plus PR #201 admission extension), batch
`4169fd3304ce43ef`, report `index-probe-6558a497f249`. The worker was the same
8-vCPU/16-GiB shared AMD size in Amsterdam, quoted at $0.16667/hour.
`cloud probe --pack cockroach` used two fresh processes and fresh source/index
directories, concurrent first and prehydrated second, within one 600-second budget.
The pinned corpus inventories matched: 9,758 files, 134,387,784 bytes, SHA-256
`ea14ffbe7909899749be3b3d413453ee117f8552e409aa5267e5474b80b6654c`.
Both workers' source/harness/fixture/pack hashes matched the saved launch identity.
No model ran; ranking, precision and NL embedding providers were disabled.

The [normalized raw record](2026-10-15-cockroach-index-probe.json) preserves both
final profiles, partial counts, source revisions, effective worker environment,
resource samples and verification outcomes. Controller SSH commands and local
paths are omitted. The private archive's digest is retained for integrity.

## Observed outcomes

| Measurement | Concurrent | Prehydrated |
| --- | ---: | ---: |
| Search outcome | Incomplete | Incomplete |
| Observation elapsed before close | 161.532 s | 182.592 s |
| Explicit prehydration wait | 0 s | 56.273 s |
| Lexical warmup elapsed at final snapshot | 125.306 s | 92.663 s |
| Keyword phase | 51.028 s | 14.206 s |
| Keyword discovery wall / thread CPU | 36.794 / 3.288 s | 3.526 / 2.269 s |
| Keyword files completed / documents | 9,736 / 81,734 | 9,736 / 81,734 |
| Existing structural ASTs reused | 4,980 | 4,980 |
| Body files completed / started | 5,699 / 5,700 | 6,366 / 6,367 |
| Body windows attempted | 127,931 | 142,653 |
| Body document construction wall / thread CPU | 49.918 / 41.588 s | 54.585 / 46.546 s |
| Body SQL wall / thread CPU | 21.117 / 12.339 s | 21.997 / 13.336 s |
| Body tokenizer calls | 2,273,516 | 2,568,084 |
| Body tokenizer wall / thread CPU | 21.910 / 20.926 s | 24.623 / 23.549 s |
| Keyword commits / body commits observed | 1 / 0 | 1 / 0 |

Observation elapsed starts before the first MCP operation and ends at the last
pre-close checkpoint; it includes prehydration, but excludes source acquisition
and shutdown. Supervised arm times, including those costs, were 186.857 and
206.274 seconds. Neither elapsed value is time to successful search.
The existing readiness helper checks its 90-second polling threshold after an
operation returns. Its elapsed time, the background index clock and total startup
are different clocks; the 90-second message is not an exact per-operation cap.

## Interpretation and limits

- Structural scheduling affects keyword discovery in this pair. The concurrent
  checkpoint showed hydration still active during discovery, whereas the second
  arm waited for it. The wall/thread-CPU gap is not a direct GIL measurement; I/O,
  scheduling and other waits can contribute. One fixed-order pair on a shared
  worker cannot isolate CPU contention from filesystem cache and order effects.
- Body construction and SQL remain substantial after structural hydration is
  complete. The active body-file loop had run 71.870 and 77.505 seconds at the
  final snapshots, respectively. Counts differ, so these are partial workloads,
  not equal-work speed comparisons. No body commit had completed. The ordinary
  `body_indexed_files: 0` summary was a readiness placeholder, not zero progress.
- Keyword discovery was measured once in each arm; body discovery was effectively
  zero. This does not support repeated discovery between keyword and body stages.
  Source inspection does show the lexical warmup creates its own context manager
  and inventory, separate from structural discovery. Sharing a valid snapshot is
  a candidate repair, not a measured result of this diagnostic.
- Timings are inclusive. Body document construction includes tokenization, reads,
  span lookup and probe overhead; adding the nested phases double-counts time.
  Completed scopes have thread CPU; active scopes have wall time only. Structural
  snapshot `elapsed_ms` is age at snapshot, not a recorded hydration completion
  duration.
- Millions of instrumented tokenizer calls can perturb the workload. Their clock,
  lock and bookkeeping overhead is included in enclosing phases and was not
  separately calibrated here. Do not transfer these body timings to ordinary
  uninstrumented operation or claim a stable speedup from this pair.

## Concrete next work

1. Calibrate profiling overhead on a bounded generated body workload and reduce
   hot-loop timing frequency if material. Preserve partial progress and validate
   exact token streams, FTS rows, row order and ranked results with profiling on/off.
2. Test reuse of an immutable, compatible structural discovery snapshot for lexical
   startup, with fresh discovery as fallback. Cover edits, symlink boundaries,
   ignore rules, discovery caps, cancellation and stale snapshots; do not skip
   freshness work merely to lower timing.
3. Use the corrected measurements to target body document construction and FTS
   writes. Preserve overlapping/truncated window terms, whole-file terms, duplicate
   symbols and atomic rollback. Require an uninstrumented Cockroach confirmation
   before spending on another unchanged full matrix, and require the full gate
   before releasing 0.1.6.

These are follow-up actions, not completed fixes. This single-worker allowance is
exhausted; further cloud validation requires a separate extension. No additional
worker or full-matrix retry was started.

## Bounds, cleanup and cost

The probe service ran 400.119 seconds within its 600-second diagnostic budget and
660-second outer service limit. The full controller took 524.089 seconds
(8.73 minutes), including bootstrap, setup and collection, within 90 minutes.
Both arms exited nonzero for incomplete readiness, with no supervisor resource
violation or truncated log. Source identities stayed unchanged. Peak managed
worker storage was 1,376,796,980 bytes and sampled process-tree RSS 612,032,512
bytes, below 5 GiB and 4 GiB. Owned source/index work was removed.

Report collection and download passed. Only 24,761 uncompressed report/log bytes
were exported; source corpora and indexes were not downloaded to the Mac.
Provider GET returned 404 for the worker, the project worker list was empty, and
all 17 ledger entries have verified cleanup. The prior 16 ledger rows were
unchanged. This diagnostic used $0.0243 estimated compute; all 17 rentals total
$0.8063 estimated compute before tax, not an invoice. The $17 monthly reservation
cap is admission accounting, not actual spending.

Budget extension validation passed 45 local cloud tests with 4 Linux-only skips,
Ruff and whitespace checks. All 18 reported exact-head CI checks for PR #201
passed or were deliberately skipped, including both Python root/product suites,
ranking, wheels, real servers and image checks. This does not convert the
incomplete diagnostic into a product or release-gate pass.
