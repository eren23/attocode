# Cold-index discovery reuse, body memoization and probe calibration

The [pinned diagnostic](2026-10-15-cockroach-index-probe.md) found costly keyword
discovery and substantial body construction after structural hydration finished.
This follow-up removes duplicate work and lowers diagnostic overhead locally.
It has **not** been confirmed on CockroachDB, and the last full release gate still
fails. No cloud worker, model request, timeout increase or release was added.

## Changes and boundaries

Structural discovery publishes an immutable inventory only after an untruncated
scan below the existing safety ceiling. Before reuse, lexical warmup validates
root, ignore policy, age, relevant directory/file metadata and symlink target
identities. Ctime/inode are included, so restoring a file's old mtime and size does
not make its changed source eligible for reuse. Directory metadata is captured
before enumeration; additions, removals and edits during discovery invalidate the
handoff. Missing `.gitignore` is tracked too. No source content is read during
validation. A permission error, stale/incompatible snapshot or unavailable donor
falls back to normal discovery; cancellation propagates.

The recipient receives independent FileInfo objects and applies its own file cap.
The original freshness timestamp is retained. Truncated donors cannot silently
impose their cap on another consumer. Snapshot capture retains at most 100,000
metadata guards; hitting that bound disables sharing, not normal discovery.
Incremental dirty-file notification invalidates the published snapshot. The service
callback never initializes structural indexing or waits for hydration.

Body construction now memoizes exact displayed line text within one file. This
helps generated source with repeated lines while preserving truncated identifiers,
Unicode tokenization, overlapping windows and whole-file term order. Retention is
bounded by 1,024 entries and 32,768 text/term characters plus container overhead.
Long/unique lines retain the original tokenization path; the cache is discarded
between files. SQL transactions, row order and ranking weights are unchanged.

Probe schema **2** times every 64th body/keyword tokenizer and keyword-serializer
call, starting with the first. It records the exact observed call count separately.
The durations are the sampled calls only, **not extrapolated totals**; sampled
phase `calls` counts completed timed scopes. Sampling continues across files and
resets with the warmup attempt. Other phase timings, partial-work counters,
exception behavior and commit accounting remain. Ordinary profiling-off calls
still return the original function and read no profiler clocks.

## Bounded component observations

Both checked-in probes use generated temporary files, no downloads, and compare
against methods from local baseline `3d7c41c`. The [raw record](2026-10-15-discovery-body-repair.json)
contains code/probe hashes, all observations, output hashes, platform and cleanup.
No timing threshold is used as a correctness gate.

| Generated workload | Baseline median | Candidate median |
| --- | ---: | ---: |
| Body construction, repeated text, profiling off | 0.102063 s | 0.019055 s |
| Body construction, mostly unique text, profiling off | 0.111139 s | 0.112251 s |
| Two consumers discovering 640 files | 0.179183 s | 0.115283 s |

Body timings are four rotated-order observations per mode on eight generated
files per workload, each workload below 2 MiB. Empty known spans deliberately
exclude AST parsing; no SQL or full gateway work is measured. Every body/window
and whole-file term stream has the same digest across baseline, candidate and
profiling modes. Repeated text benefits; unique text shows no meaningful gain.

On the candidate's unique-text workload, profiling every call had median
0.186908 s versus 0.143900 s with sampling and 0.112251 s with profiling off.
Sampling reduces measured overhead here but does not remove it. Short repeated-
text timings are close and noisy. These observations do not establish a universal
overhead ratio or make the earlier instrumented cloud measurements uninstrumented.

Discovery timings are three alternating-order observations per mode. The baseline
runs the original discovery twice; the candidate includes snapshot capture in the
first discovery and validation/copying for the second consumer. Inventories,
importance scores and order have identical digests. The fixture is small and
uncontended; it does not predict the cloud's scheduling, disk or startup latency.

## Correctness and verification

- Discovery controls cover immutable objects, identical ordering/importance,
  new/deleted/edited files (including restored mtime/size), ignore changes, new
  directories, oversize files becoming eligible, internal/external symlink changes,
  stale/wrong-root/wrong-policy snapshots, consumer caps, donor truncation,
  cancellation, permission failures, guard bounds and edits during enumeration.
- Service wiring avoids structural initialization when no donor exists and avoids
  rediscovery when a valid donor exists. A fresh reference index matches keyword
  documents, complete SQLite/FTS rows including row IDs, and ranked search results.
- Body checks compare each emitted window and whole-file term stream with direct
  tokenization, including long truncated lines and Unicode separators. Memoization
  is bounded and per file. Existing SQL/BM25, second-batch rollback and retry tests
  continue to pass.
- Sampling tests check exact clock-read counts, exact observed call counts across
  wrappers, exception propagation, bounded vocabulary and explicit sample labels.
  Profiling on/off retains exact cache/FTS rows and rankings. Partial cancellation
  still exposes attempted work without claiming a committed body transaction.
- Negative controls fail as intended when discovery reuse is disabled and when the
  old body method is restored. The implementation was not changed by those controls.

The focused package/root semantic suite passed **84 tests**. Final bounded local
run `20261015T150441-19249d91` passed **583 tests, 8 skips**, lint, scale and
lifecycle in **47.807 seconds**, with stable source/fixture hashes and verified
cleanup. Peak managed storage was 106,604,024 bytes and sampled process-tree RSS
801,849,344 bytes. An earlier run was correctly marked incomplete because source
changed during it; that run is not a pass.

Fresh synthetic run `index-probe-110451210e57` completed both modes on identical
24-file source, with one discovery reuse and one body commit per mode, schema-2
profiles, matching worker identities and verified cleanup. It validates wiring,
not CockroachDB performance. The client host's existing MCP process was not
restarted and its installed global tool was not upgraded.

## Remaining release work

Require uninstrumented pinned CockroachDB confirmation of this candidate before
another full 36-pack gate. If the target still fails, use the sampled diagnostics
to choose the next repair; do not enable a full-hydration wait or inflate the
readiness limit merely to turn the check green. Publish 0.1.6 only after the full
gate passes. All 17 previous cloud reservations remain used and their workers
are deleted; additional cloud validation requires a new allowance.
