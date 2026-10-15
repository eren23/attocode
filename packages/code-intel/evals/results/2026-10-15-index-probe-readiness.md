# Cold-index stage diagnostic readiness

The [two full follow-up failures](2026-10-15-cold-followup.md) remain the release
outcome. This change prepares a mechanism diagnostic; it does not fix the cold
start or establish a performance improvement. No new cloud/model request occurred.

## Instrumentation

`ATTOCODE_INTEL_INDEX_PROBE=1` enables one fresh, bounded profile per lexical
warmup attempt. Ordinary clients allocate no profile and retain their existing
response format. A fixed phase/counter vocabulary covers discovery/stat, keyword
reads/hash lookup/parse/span reuse/document construction/frequency aggregation,
cache serialization/SQL/commit, and body discovery/read/spans/tokenization/SQL/
commit. At most eight slow-file entries retain relative names capped at 160
characters; no source text is retained. Counts describe attempted work, not
committed rows. Successful commits are counted separately.

Completed scopes record monotonic wall time and current-thread CPU time.
Timings are **inclusive**: parents include children, so summing all phases double
counts work. Active scopes expose elapsed wall time only; another thread cannot
read the indexing thread's CPU clock. Wall minus thread CPU includes scheduling,
I/O and waiting, and is not proof of GIL contention. Instrumentation adds overhead,
especially to tokenization/SQL calls, and cannot replace an uninstrumented gate.

Snapshots use a short collector lock and do no source I/O. The diagnostic runner
writes the latest snapshot every half-second, overwriting one bounded JSON file.
Partial progress survives warmup errors or supervisor termination. The last saved
normal-exit snapshot is taken before closing services, so shutdown is excluded
from its elapsed startup measurement and included in the parent's supervised time.

## Two diagnostic modes

`python -m eval.quality.index_probe` defaults to 24 tiny Python files. Each mode
runs in a fresh process and fresh source/index directory. `concurrent` uses the
ordinary MCP gateway's warmup scheduling. `prehydrated` waits for the structural
hydration thread to complete before the gateway schedules lexical warmup; it
refuses failed/incomplete hydration. This is an experimental diagnostic mode,
not a new product default. Total elapsed startup includes the structural wait;
its time is also recorded separately.

The same pinned `--pack cockroach` selection is available only with explicit
Linux-worker downloads. Both modes retain source inventories (file/byte counts
and content digest), effective worker settings, code/harness/fixture/pack hashes,
index status, structural state and partial failure diagnostics. The parent checks
source equality and worker identities. Source acquisition and both modes share
one 600-second wall/monotonic budget and the existing 5-GiB disk/4-GiB RSS limits.
All materialized sources, acquired blobs and indexes live under the owned work
folder and are removed; only bounded JSON/logs remain. No repository builds,
model selection or model downloads occur.

```sh
# Local synthetic wiring only; no corpus download or paid resource.
.venv/bin/python -m eval.quality.index_probe --seconds 90

# Future authorized diagnostic worker, one pinned pack; currently budget-blocked.
.venv/bin/python -m eval.quality cloud probe --pack cockroach
```

The cloud route uses the normal controller, ledger, published-source admission,
fresh independent cleanup heartbeat, one-worker rule, and deletion verification.
Its worker test service has an independent 660-second TERM/KILL boundary around
the 600-second supervised probe. Selection is recorded as `suite: index-probe`,
never a full gate. Shards, resume and suite overrides are refused. The monthly
reservation cap remains $16 and all 16 slots are used; this preparation does not
authorize another rental.

## Validation and limits

Controls compare profiling on/off with identical keyword docs, every SQLite/FTS
row including row IDs, and ranked keyword search results. Cancellation retains
partial counters while the body transaction rolls back. Deterministic clock tests
check inclusive CPU/wall accounting and incomplete snapshots; retention tests
check fixed labels and bounded slow-file output. Diagnostic mode tests enforce
structural completion ordering and reject corpus acquisition before creating a
local work folder. Cloud controls verify ordinary budget/deletion behavior,
selection rejection, the actual worker command, independent deadline and export.

The synthetic runs validate wiring and cleanup. Their small workload does not
establish meaningful contention, representative Cockroach cost or a mode speedup.
A real pinned diagnostic is still pending. Use its measured dominant subphase to
choose a repair, require exact semantic/rollback/freshness controls, confirm on
Cockroach, and then rerun the unchanged full matrix before publishing 0.1.6.

Final bounded local run `20261015T134645-74c362f7` passed **562 tests, 8 skips**,
lint, scale and lifecycle in 38.904 seconds. Source/fixture hashes stayed stable;
cleanup was verified. Peak managed disk was 186,607,123 bytes and sampled RSS
763,035,648 bytes. The final synthetic run `index-probe-769c73c91130` completed
both modes on identical 24-file input, with matching worker source identities,
24 completed body files each, and verified cleanup. Its [raw phase observations](2026-10-15-index-probe-readiness.json)
are wiring evidence only. The final cloud-controller focused suite passed 45 tests
with 4 Linux-only skips; the indexing/diagnostic focused suite passed 60 tests.
