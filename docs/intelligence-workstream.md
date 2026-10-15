# Intelligence breadth and depth workstream

Accepted scope: 36 language/format adapters, 36 pinned source packs, 144 unscoped
retrieval questions, six workflow families, and deeper cross-file navigation in
three successive groups. This is offline product evidence, not an agent study.

**Current status, 2026-10-15:** implementation and cold-index follow-ups are merged
through PR #186 (`deaa836`). Required implementation CI passed. The final full cloud
gate failed: 35/36 packs completed, CockroachDB search warmup incomplete, ranking
not run. 0.1.6 remains unpublished. All six permitted workstream batches are used,
all workers deleted, total estimated compute $0.4487. The final controller also
recorded a wall duration exceeding its configured bound; cause is unestablished.
See the [final six-run evidence](../packages/code-intel/evals/results/2026-10-15-breadth-cloud.md).
The progress entries below are historical observations, not a passing release gate.

## Milestones

| Milestone | Status | Required evidence |
| --- | --- | --- |
| Coverage foundation | Validated locally and in CI | Frozen source-backed manifest; honest outcomes; bounded selection, shards and resume; complete baseline |
| Python, JS/TS, Go, Rust | Implemented; final gates pending | Module/alias/re-export and negative controls; real language-server checks |
| C/C++, Java, C# | Implemented; final gates pending | Include/package/namespace resolution, ambiguity and selected-definition identity |
| Ruby, PHP, Kotlin, Swift, Scala, Elixir, Lua, Bash, Zig | Implemented; final gates pending | Explicit module bindings, qualified references and dynamic-case limitations |
| Protocol and operation coverage | Implemented; final gates pending | Catalog-to-test inventory, real MCP/HTTP, profiles, isolation and failure cases |
| Release and final matrix | Implemented; final gates pending | Coherent candidate hashes, required CI, clean install/upgrade, verified cleanup |

The existing six source packs and frozen ranking baseline remain evidence inputs.
New labels must be frozen before evaluating product changes. Missing labels,
unsupported capabilities and incomplete execution are not successful assertions.
All mutations of source packs happen in disposable copies, never cached inputs.

## Execution bounds

Quick/local remain capped at 120/600 seconds. Managed disk is capped at 5 GiB,
process-tree RSS at 4 GiB, with a 2 GiB free-space floor. Broad worker tests have
60 minutes and the controller has 90 minutes. One worker at a time; $1 reservation
per batch, $10 per UTC month, at most six additional batches for this workstream.
Read the live ledger before admission. No budget increase or automatic paid runs.
Temporary tools and optional grammars belong on disposable workers or CI.

Preserve shared caches, evaluation artifacts and frozen studies. No model calls,
model downloads or Claude usage-page checks; R7's STOP remains in force.

## Progress evidence

Implementation starts from main `ecc2c3e19d37ed6e802e39eece30fdd5692faaa6`.
The existing symlink fix is merged but not in released 0.1.5. The first bounded local milestone passed; broader evidence remains explicitly partial. Record each completed milestone's report location, candidate
hash, corrected examples, limitations, runtime/storage and cleanup here.

### Implemented foundation and language work

- Frozen manifest SHA-256:
  `e254cb987f782483d241d93b929d24d2582d74c51627a223638a489d4ff4bc9a`.
  36 pinned repositories, 144 unscoped questions, 141 target files. Labels were
  frozen from native source before running the expanded candidate.
- Pack/shard selection, coherent resume/aggregation, five evidence outcomes,
  per-pack subprocess deadlines/checkpoints/cleanup, JUnit and runtime operation
  inventories are implemented. Cloud selection and bounded resume-report upload are supported; resume checks
  source hashes before rental and full environment identity on the worker.
- Module ownership, static aliases and selected references are implemented across
  all three language groups with negative controls. These remain partial static
  capabilities. See the quality guide for unsupported dynamic/build cases.
- Parser work covers 36 languages/formats, no implicit grammar acquisition,
  bounded slow grammars, C++/Objective-C headers and F# recursive type declarations.
  Bulk persistence avoids scanning all references once per file.
- Real TypeScript cold and installed Rust warmed identity/edit/shutdown checks
  passed. Python/Go worker checks, explicit acquisition of 11 available optional grammars,
  and Linux/macOS 3.12/3.13 upgrade checks have passed CI. Crystal is unavailable
  in the pinned grammar release and remains explicit unsupported evidence.
- Full standalone diagnostic: 525 passed, four skipped, 52.8 seconds, 746.6 MiB
  sampled RSS, 95.5 MiB managed disk, cleanup verified. Seven earlier test-location
  failures remain recorded; study fixtures require external scratch paths.
- Immutable stage A: all 36 attempted, 32 completed without failed assertions,
  two failed and two timed out. 136 retrieval observations: 95 labeled hits at 5,
  124 at 24. Limited/unsupported checks are not positive assertions. The ranking
  gate passed; raw reports remain under `.attocode/quality/runs/`.
- Immutable stage B local: `20261014T203352-572ed8e3`, 469 passed/four skipped,
  scale and lifecycle passed in about 40 seconds. Broader stage B results are
  being collected. Later fixes require a fresh final candidate.
- The first isolated 0.1.5-to-0.1.6 wheel upgrade check passed all seven phases;
  all three project-local client configurations and persisted index/edit freshness
  were verified. Its temporary environment/cache were removed. The final source wheel also
  passed all seven phases in `release-0.1.6-final`; this is not publication.

### Remaining delivery gates

Implementation is merged, required CI passed and remote results/cleanup are recorded.
The remaining gate is a passing full cold matrix after resolving the CockroachDB
indexing delay. The six-batch allowance is exhausted; no further rental or release
will start automatically. Keep failures, unsupported
cases, missing relationship labels and untested advanced operations visible. No
model benefit, ranking improvement or universal reference resolution is claimed.

### CI corrections and final verification

- Real Python, TypeScript, Go and Rust servers passed selected-definition, duplicate
  identity, edit and shutdown checks. Pyright exposed missing `workspaceFolders`
  during initialization; the client and protocol regression now provide/check it.
- Root tests exposed a relative Go import compatibility regression, now fixed with
  unique-target handling; registered Bash/optional-Crystal expectations were updated.
- Full standalone run `20261014-full-final`: 684 passed/four skipped, 62.7 seconds,
  730.6 MiB sampled RSS, 98.5 MiB managed disk, scratch cleanup verified. Additional
  CI correction/export regressions were checked separately.
- Stage C observed all 144 questions (99 known-target hits at 5, 126 at 24). Two
  qualified-name harness failures are retained. Stage D corrects exact-name matching
  without accepting fuzzy symbols; its full matrix and unchanged ranking gate follow.
- Runtime inventory: 30 operations with successful response observations, 109 with
  rejection-only evidence, zero unmapped. This does not establish semantic coverage
  of all 139 operations; subprocess MCP calls are outside this inventory.
- Cloud reports compact JSON losslessly before the unchanged 2 MiB/file, 20 MiB total
  export limits. No corpora or indexes are downloaded. PR `no-model-review` prevents
  automatic model review for this explicitly model-free workstream.

Final stage D source matrix: all 36 packs and 144 questions completed across three
coherent shards. Outcomes: 157 passed assertions, 124 limited, seven unsupported,
zero failed/incomplete. Known-target hits: 99/144 at five, 126/144 at 24; these are
non-exhaustive development labels. Local contracts: 493 passed/four skipped.
Final ranking and cloud/release evidence are tracked separately. Stage D predates
the report-export-only harness correction; product source is unchanged by it.

Prior-push CI root suite on Python 3.12: 8,477 passed, five skipped, one expected
failure; Python 3.13 also passed. Final commit gates must still run before merge.

The local checks plus source matrix took 504.3 supervised seconds, peaking at
1,249.2 MiB managed storage and 830.4 MiB sampled process-tree RSS. Cleanup was
verified. The unchanged ranking gate is an additional separately recorded check.

Stage D ranking run `20261014T210555-39a71a6c` passed in 55.5 seconds: the
frozen 68-query/five-method gate remains unchanged. Total supervised final local
checks, source matrix and ranking time: 559.8 seconds; all cleanup verified.

### Clean Linux cold-start failures and follow-up

PR #181 merged as `fbd5211f7f8b9c47d7bc37fc18471792a8e6fe41` after its
required checks passed on the final head. The first clean cloud batch,
`293a9ef68f1547fd`, tested that published source. Lint, 480 contracts (18 explicit
skips), scale and lifecycle passed. Of 36 source packs, 34 completed; CockroachDB
exceeded the 180-second pack limit and Pandas exceeded the 90-second cold search
warmup wait. Eight questions are missing, not failed retrieval observations.
The runner correctly stopped before ranking, so this is not a passing broad run.

Retained check outcomes: 123 passed, 116 limited, 37 unsupported; no failed
assertions were observed before the two pack interruptions. Optional grammars
were absent on this clean worker. The report's check-level incomplete count does
not count interrupted packs; their explicit statuses and missing questions govern
completeness. See the [remote record](../packages/code-intel/evals/results/2026-10-14-breadth-cloud-first.json).

The cloud worker and its scratch were deleted and an independent API query found
zero active quality workers. Estimated compute cost: $0.0733; one of this
workstream's six allowed batches used, $4 cumulative monthly reservations.
Reports exported 1.30 MiB, with no corpora or indexes downloaded.

The follow-up batches symbol/reference persistence in atomic groups of at most
100 files and reuses a bounded set of content-hash-checked symbol spans between
keyword and body indexing. It retains no ASTs or source text. Regression controls
check rollback, selected-definition keys, identical source chunks, bounded-cache
fallback and same-size/same-mtime edits. No ranking weights, labels or timeout
limits changed. Final performance and remote revalidation remain required.
