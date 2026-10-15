# Retrieval audit and file-scoped navigation repair

Local follow-up to 0.1.6, based on `d5a596e`. No release, model request, cloud
worker, ranking default change, global tool upgrade or host MCP restart.

The saved full gate contains 144 complete retrieval observations: 99 labeled
hits in the first five, 29 additional hits at ranks 6–24, and 16 targets absent
from the returned page. Every miss is listed in
[the audit](2026-10-15-retrieval-audit.json). Those 16 are **unresolved page
misses**, not proven index or candidate-generation misses. The recorded pool
size is the 24 candidates returned to the service, not all internal candidates.

Native-source review also found a label gap: FastAPI's bearer-token question
returned `fastapi/security/http.py` at rank 5. Its `HTTPBearer.__call__` reads
Authorization, checks the bearer scheme and returns credentials. The frozen
label only named `security/oauth2.py` (rank 21). The source hash and lines
303–316 are recorded separately; historical scores and labels are unchanged.

## Bounded candidate tracing

[Replay evidence](2026-10-15-retrieval-replay.json) covers the same four frozen
questions each for FastAPI and Laravel, using pinned local source and the
lexical search path. No repository code is executed. The two packs ran
sequentially under a 180-second, 512 MiB disk and 1.5 GiB RSS supervisor.
They completed in 13.734 seconds, with 177,803,264 bytes peak managed disk and
146,505,728 bytes sampled RSS. Temporary sources and indexes were removed.

Laravel's dot-notation configuration target is present at body-file rank 26,
then fused-file rank 32 before the 24-result cutoff. A new request for 96
results returns it at rank 37. Deeper retrieval changes candidate generation;
this is not a stable cursor. The FastAPI OAuth2 target remains at rank 21.
Local Laravel transaction rank is 14 versus 13 in the prior Linux run, so
these are diagnostics, not an exact replay of every cloud rank or a before/after
ranking comparison. No reordering rule was selected from these observations.

Six additional [questions](../designs/2026-10-15-fresh-navigation-queries.json)
were frozen from native source before querying. These use already-seen
repositories and non-exhaustive labels; they are fresh questions, not an
independent held-out repository study. Results: **3/6 at five, 5/6 at 24,
6/6 at 96**. The encryption target is in the original keyword candidates
(rank 38), fused at 46, and returned at 34 on the deeper request. The fresh
replay took 12.622 seconds, peaked at 121,876,480 managed disk bytes and
160,088,064 sampled RSS, and cleaned its scratch. Search usefulness remains
an open problem; these results do not show a ranking improvement.

## Concrete repair

`ASTService.get_file_symbols(path)` expanded each qualified name through the
global definitions list without filtering by file. Two files defining the
same function therefore made `symbols_data("one.py")` report both files.
The defect reproduced before edits in Python, Go and TypeScript. Callers that
filtered the result themselves still paid for unrelated definitions.

`CrossRefIndex` now maintains file/name groups referencing the existing
location objects. File lookups and persistence use those groups. Addition,
removal, persisted loading and LSP replacement maintain them under the existing
lock. Within-name order and overloads are retained, and returned lists are
copies. No persistent schema, source exclusion, ranking policy or timeout changed.

[The component probe](2026-10-15-file-symbol-probe.json) compares the exact
baseline lookup with the candidate on 160 and 640 generated files, 32 shared
names per file, four alternating lookup observations per arm. At 640 files:

| Measurement | Baseline | Candidate |
| --- | ---: | ---: |
| Locations returned over all file requests | 13,107,200 | 20,480 |
| Median lookup time | 18.42 ms | 1.08 ms |
| Test-suggestion ranking component | 145.23 ms | 19.01 ms |

After filtering the baseline to the requested file, location evidence hashes
match. Test-suggestion outputs also match exactly. The extra file-group
containers use 2,347,776 bytes for 20,480 definitions (shallow container measure;
location objects are shared). This is a memory-for-lookup tradeoff, not zero-cost
caching. These synthetic component times do not establish Cockroach runtime
headroom; its last measured 177.579/180-second result still stands.

## Validation and reproduction

Final bounded local run `20261015T181735-2c14d451` passed **615 tests, 8 skips**, lint,
scale and lifecycle checks in 38.99 seconds elapsed. Peak managed disk was
128,132,655 bytes and sampled RSS 831,602,688 bytes. Source/fixture hashes were
stable and scratch cleanup verified. [Normalized result](2026-10-15-file-symbol-validation.json).
This final run includes the fresh-query replay option and new test lint targets;
the source and fixtures at that checkpoint matched its hashes. The subsequent
[importance repair](2026-10-15-expansion-importance.md) records validation of the
combined upstream candidate. Whitespace
checks passed. The earlier local run also passed before those harness additions.

New regression controls cover file boundaries, absolute paths, deletion and
rename, restart, overloads, LSP replacement, persisted loading, and lookup/
persistence without scanning the global collision list. Audit controls keep
missing questions, truncated/warming pages and conflicting scores distinct.
The first replay attempt failed before indexing because its instrumented
method could not be assigned to a slotted instance; a subclass corrected the
probe. That failed attempt is retained privately and not counted as a pass.

```sh
.venv/bin/python -m eval.quality.retrieval_audit SAVED_WORKFLOWS_JSON --output audit.json
.venv/bin/python -m eval.quality.file_symbol_probe --baseline d5a596e --output probe.json
.venv/bin/python -m eval.quality local --root /private/tmp/attocode-quality-followup
```

Run `retrieval_replay` through `eval.quality.runner.supervise` with the bounds
above and `environment(root)` to isolate caches and disable models/downloads.
It accepts at most two packs, limits each source pack to 64 MiB, and deletes
one pack before starting the next. Its output retains bounded stage ranks
and file paths, not source archives or indexes.

Next search work should compare query expansion and fusion on frozen candidate
pools with multiple relevant source labels, then use a new untouched query set.
The fresh questions above are now consumed evidence. Larger Cockroach timing
confirmation needs a separately authorized cloud run; no allowance remains.
