# Unprofiled startup stages — 2026-10-24

**Next target: persisted cross-reference restoration and conservative repair.**
In this single unchanged-engine diagnostic, restart initialization takes 14.268s:
index loading takes 3.750s, followed by 6.480s of repair. Summary encoding takes 1.074s
inside repair. These clocks identify a better next investigation target than the
previous profile's encoding call counts; they do not establish an optimization gain.

Source inspection shows potentially redundant construction: SQLite rows
become `StoredSymbol`/`StoredReference`, then navigation objects; repair subsequently
creates another index and rebuilds its definitions. Reducing this redundant work is
an inference to test next, not a demonstrated per-conversion cost or speed benefit.
Keep all existing parsing, source/parser/schema/navigation checks and repair rules.
The rejected fingerprint and bounded-JSON candidates remain rejected.

## One unchanged-engine diagnostic

[Actions 40100357564](https://github.com/eren23/attocode/actions/runs/40100357564)
executes frozen diagnostic source `9c5b5c4511f3c7c4d5621026c7bb92b6fbaad460`.
All 349 engine files equal baseline `8cb0ce316c510a85ba27f2a30697e692437c6f7e`
and the published 0.1.17 implementation. One pinned Cockroach workspace has 9,758 source
entries / 133,715,342 logical bytes, from commit 53aadff3cedde4d810c72b69ddd96e6a735d93e7.
It runs clocked cold→plain restart reference→clocked restart, each in a fresh process.
All three reach exact 4,980 parse/reference readiness and return identical data for all
ten navigation operations, with validated physical workspace routes, source, origins
and native identities. Four existing retrieval queries are consumed operational
anchors; this is no fresh relevance or agent/model study. Canonical comparison
excludes only diagnostic `semantic_search.data.ranking.index` and normalizes the
validated follow-up workspace field. Result order, counts and other fields remain.

| Process | Lifetime s | Navigation and close s | Readiness s |
| --- | ---: | ---: | ---: |
| Clocked cold | 64.187 | 59.804 | 44.247 |
| Plain restart reference | 25.064 | 19.751 | 14.490 |
| Clocked restart | 23.766 | 19.883 | 14.488 |

These are one pass on one runner with warm OS caches. The process difference between
reference and clocked restart is not a speedup: the engine is unchanged, ordering and
unobserved work vary, and a single reference cannot prove zero observer overhead.
Readiness, process lifetime and parent admission are separate clocks. Raw admission
adds 0.657–0.670s per phase outside process lifetime, within the aggregate budget.

## Restart attribution

The initial workspace executor task takes 14.268s wall / 13.481s thread CPU. Stage clocks
below belong to that task's ancestry, excluding selected lexical background calls.

| Stage | Calls | Inclusive wall s | Thread CPU s | Relationship |
| --- | ---: | ---: | ---: | --- |
| Skeleton initialization | 1 | 13.938 | 13.152 | Contains discovery, summary restore and snapshot restore |
| Summary restore | 1 | 1.306 | 1.306 | Before structural restore |
| Discovery | 1 | 0.731 | 0.731 | Before structural restore |
| Structural restore | 1 | 11.681 | 10.895 | Contains missing-file parsing, index load and repair |
| Missing-file parsing | 779 | 1.343 | 1.342 | Inside structural restore |
| Persisted index load | 1 | 3.750 | 3.750 | Before repair |
| Repair | 1 | 6.480 | 5.695 | Includes graph construction, persistence and snapshot save |
| Snapshot save | 1 | 1.640 | 1.393 | Inside repair; includes encoding and identity checks |
| Summary encoding | 1 | 1.074 | 1.074 | Inside snapshot save |
| Index persistence | 1 | 1.003 | 0.662 | Inside repair |

**Nested times are not additive.** Load and repair are disjoint sibling scopes;
encoding is already inside repair. Repair's exclusive remainder is 3.603s wall/
3.406s CPU, covering unwrapped work and observer bookkeeping rather than one
identified function. A narrower candidate still needs correctness controls and a
separate frozen unprofiled comparison before adoption.

The source-bound read-only cache observer records 110,974 symbols and 417,568 references.
The bounded summary contains 4,201 of 4,980 files; 779 are absent, and initialization records
779 parse calls. Its 33,554,424 bytes sit 8 bytes below the 32 MiB cap. All four before/after
restart observations have identical snapshot/summary hashes. The raw cache database
is not retained; this does not prove why each individual summary was omitted.

## Cold start and observer limits

The hydration root takes 42.295s wall/33.695s CPU. Its 4,480 remaining parse calls take
11.944s wall/11.278s CPU; 50 index-persistence calls take 13.819s wall/7.608s CPU;
snapshot save takes 1.998s including 1.117s encoding. These are nested under hydration.
The hydration remainder is 14.349s wall / 13.224s CPU and remains a broad unwrapped scope.
The initial task's 10.724s wall/2.325s CPU also leaves a large non-attributed/waiting
remainder beyond its 1.227s skeleton initialization; no specific cause is assigned.

The recorder uses monotonic wall and per-thread CPU clocks, not cProfile or a profile
callback. It retains 11,861 cold spans / 139 actual executor tasks and 856 restart spans /
25 tasks. Per-thread parents and timestamps distinguish main work, workspace
initialization, later executor work, AST hydration and other selected background
calls. Cold startup also records 6,500 module-parse calls outside workspace and
hydration ancestry. Their enclosing background work is not captured; the lexical
candidate worker itself is unwrapped and its full CPU remains unmeasured. Wall
intervals can overlap across threads.
Hook modules are preloaded and charged to the separate import clock.

Completed-row publication accounts for 0.246s cold CPU/0.723s summed wall and 0.017s
restart CPU/wall. These counters cover serialization, locking and flush only, not
all wrapper setup, clock reads, imports or shutdown. Exclusive stage scopes include
unobserved work and observer costs; this is not whole-process CPU accounting.

## Controls, bounds and retained evidence

The initial absence control records one expected assertion inside a successful
workflow. Preliminary controls pass 295 cases; the first complete set passes 297.
Independent review then finds an executor metadata path that can lose an already
scheduled future. Its focused online regression records the exact expected assertion;
the fix guards metadata before submission and preserves the future. Final controls
pass 298 unskipped cases: 277 maintained plus 21 observer/process controls. Original failed
assertions, their source and subsequent positive runs remain in the archive.

The single payload completes in 136.290s under 600s / 2 GiB RSS / 2 GiB disk / 64 MiB evidence.
Clocked cold is capped 180s, each restart 120s, inside the aggregate; observer records
are capped 20,000 / 8 MiB per clocked process. All resource, source and owned-cleanup gates
pass. There is no rerun, resume, retuning, replacement or performance/relevance verdict.
Independent replay binds all original ZIP bytes, all 349 engine files, pinned source,
93 raw responses, three PIDs, exact routes, stage source locations, thread nesting,
executor inventory, clock arithmetic and cross-phase chronology.

The [machine report](2026-10-24-unprofiled-stages.json) and
[archive](2026-10-24-unprofiled-stages.tar.gz) retain all six original Actions archives,
executed designs/operators/tests, the unchanged engine, raw spans and admissions.
Archive SHA-256 `2461e36c91a916d034445d58b355798c41ecf012a38823124bce3b18403f98a1`;
3,281,123 bytes / 410 members. Every member and executed source is checked against its
manifest and pinned Git bytes.

All temporary instrumentation, controls, designs and dispatch choices are retired.
Product, tests, maintained harness, dependencies and version match baseline. No new
release or product optimization ships. All product execution stays online; local
Docker, global tools and MCP are untouched.
