# Cockroach startup/readiness cost attribution — 2026-10-24

Snapshot repair and bounded AST summary encoding dominate this restart's
initialization profile. This diagnostic selects the next investigation target;
it changes no product behavior and establishes no speed improvement.

The [single online attempt](https://github.com/eren23/attocode/actions/runs/40076699285)
uses the unchanged 0.1.17 engine (`3cdaa03`), one cold process to prime the cache,
then one fresh process with profiling. All ten canonical navigation operations
agree across both processes, with full 4,980-file parse/reference readiness.
The 108 raw responses include readiness polls and warming responses; the four
retrieval questions are existing consumed operational anchors.

## Where initialization spends time

The initial executor task takes **44.042 seconds wall / 42.564 seconds thread
CPU** under cProfile, with 109,807,412 recorded calls. The following are
**inclusive, nested function times**; their sum is not a total.

| Function | Calls | Inclusive seconds |
| --- | ---: | ---: |
| `initialize_skeleton` | 1 | 43.036 |
| `_restore_snapshot` | 1 | 38.194 |
| `repair_index` | 1 | 28.090 |
| `_save_snapshot` within repair | 1 | 16.737 |
| `encode_summaries` within save | 1 | 16.086 |
| `_bounded_json` within encoding | 4,979 | 16.009 |
| `load_from_store` | 1 | 7.457 |
| Missing-summary `parse_file` | 770 | 2.455 |
| `restore_summaries` | 1 | 2.112 |
| `discover_files` | 1 | 2.160 |

The source-bound cache observation reports a 33,554,416-byte summary, only
16 bytes below the unchanged 32 MiB bound. It contains 4,210 of the 4,980 parsed
files; 770 summaries are absent. All 770 files are reparsed, and conservative
repair then rebuilds definitions, repairs references, and saves the snapshot.
The observer records identical before/after snapshot and summary SHA-256 values,
counts, and compact metadata. Raw SQLite/cache bytes are not retained, and the
individual reasons for each excluded summary are not measured.

The repair source path still saves a whole bounded summary after a small repair.
That additional work helps frame the earlier
[rejected fingerprint comparison](2026-10-23-restart-routed.md); this diagnostic
does not profile that candidate or attribute its exact runtime. The rejection,
repair counts and measured timings remain unchanged.

## Separate clocks and observer work

| Restart boundary | Seconds | Scope |
| --- | ---: | --- |
| Child process lifetime, including parent cleanup check | 65.853 | Parent launch to completed wait/cleanup |
| Navigation through gateway close | 55.514 | Original inner phase clock |
| Full navigation readiness | 44.480 | Initialization plus readiness response |
| Product/operator import profile | 1.313 | Main thread, before executor work |
| Before/after fixture identity profiles combined | 5.760 | Harness source hashing |
| Parent raw admission | 0.989 | After child exit |
| All parent admission/postvalidation | 2.350 | Includes the preceding admission row |

The old comparison's parent phase clock included admission and postvalidation;
its parent-minus-inner difference cannot all be called application startup.
The new timeline separates process lifetime and parent validation explicitly.
Unprofiled main-thread async/catalog work, raw profile hashing/JSON writing,
profile-manifest audit, and the 2.901-second finish-to-parent-exit interval remain
residuals. The dump-and-summary timer excludes later hashing and JSON writing.

All 25 actual workspace executor tasks are inventoried: dispatch, warmup, and
close. The first warm task takes 0.034 seconds wall; close takes 0.003 seconds.
Four main-thread profiles cover imports, source-before, native identity, and
source-after. Their cProfile intervals never overlap executor profiles.
The lexical candidate indexer starts after the initialization task and can
overlap later work; those later cumulative profiles are not isolated thread CPU.
Direct thread CPU counters are retained separately. Native parser interiors
remain opaque, and profiling substantially changes call-heavy timings.

## Next candidate and validation boundary

Target repeated **bounded AST JSON encoding during snapshot save/repair** first.
A new prototype should reduce that work while preserving exact source, parser,
schema and navigation checks, parse-failure diagnostics, and the existing
32 MiB total / 1 MiB per-file bounds. Correctness and overflow cases come first;
any performance decision then needs a separately frozen, unprofiled cold/restart
comparison. This profile does not predict how many unprofiled seconds it saves.
Persisted cross-reference loading/rebuild is a second measured cost.

## Admission and retained evidence

The payload completes in 182.571 seconds within its fixed 600-second aggregate
window. Peak process-tree RSS is 1,000,198,144 bytes, managed disk 1,318,658,202
bytes, and evidence 7,581,696 bytes; the limits are 2 GiB RSS/disk and 64 MiB
evidence. Cold/restart worker ceilings are 300/240 seconds within the same
aggregate window. Owned descendants and scratch are removed. Controller resource
monitoring records 43.575 CPU seconds across the whole payload; it is separate
from product thread CPU and is not assigned to one initialization function.

The old foreground-only observer fails two explicit coverage assertions as
expected control data. Review exposed lost warm-profile I/O and failed-process
metadata paths; three additional real fault controls reproduce those defects
before the fixes. The final paired run passes all 277 maintained controls and
ten new positive controls, while retaining the two expected old-observer
failures inside a successful Actions job.

Independent host replay checks original ZIP/extracted bytes, all 349 engine
files against Git, the 9,758-entry pinned source inventory, raw responses and
selected-source coordinates, physical workspace routes, source/grammar/origin identities,
all raw pstats/JSON pairs, complete task inventory, disjoint profile intervals,
timelines, limits and cleanup. Compact cache metadata remains a source-bound
online observation. No tested product/operator code executes on the operator Mac.

The [machine-readable report](2026-10-24-startup-cost.json) binds the
[archive of original artifacts and executed sources](2026-10-24-startup-cost.tar.gz).
Temporary dispatch choices, operators, designs and their ten controls are
retired after capture. All 349 product files, dependencies and version remain
exactly 0.1.17; published releases and prior incomplete/rejected evidence remain
unchanged. Local Docker, global tools and MCP processes are untouched.
