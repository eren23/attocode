# Intelligence breadth and depth workstream

Accepted scope: 36 language/format adapters, 36 pinned source packs, 144 unscoped
retrieval questions, six workflow families, and deeper cross-file navigation in
three successive groups. This is offline product evidence, not an agent study.

**Current release:** `attocode-code-intel` 0.1.8 (2026-10-17). See the
[0.1.8 release notes](intelligence-0.1.8.md).

**Latest search batch, 2026-10-17:** [test intent for "tested" questions](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-17-test-source-slot.md).
Short "tested" and "testing" searches keep the source order and show the best test hit second. On 16 new frozen
questions, judged files at five went from 14 to 16 with no loss. "test" and "tests" searches still miss every
implementation label at five.

**Previous search batch, 2026-10-17:** [file-level coverage and "tested" test intent](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-17-file-coverage.md).
Both candidates failed their predeclared rules on 32 new questions, so the search code does not change.
File-level concept coverage had no net first-five gain on validation. "tested" intent found more test files but pushed out implementation files.

**Previous search batch, 2026-10-17:** [dogfood fixes and one search candidate](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-17-search-batch.md).
Three defects found by using Attocode on this repository are fixed. On 12 fresh validation questions, the fixes keep
every file and quote judgment unchanged. The one retrieval candidate failed two predeclared rules and does not ship.

**Previous search batch, 2026-10-16:** [explicit test search and transient precision recovery](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-16-search-recovery-batch.md).
One frozen test-intent partition improved labeled hits at five from 3/8 to 6/8,
with four unchanged production controls. Transient precision replies retry within
the existing deadline, and partial caches expire. Six fresh real Rust fixtures
passed after an actual intermittent null-response failure was captured. The
bounded gate passed 829 tests (nine skips), 120 repeated navigation checkpoints,
seven source packs and frozen ranking in 171.081 seconds; scratch cleanup passed.
PostgreSQL and full upstream CI gate merge. No new cloud rental or release.

**Previous follow-up, 2026-10-15:** [document lifecycle and body-file trial](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-15-protocol-body-followup.md).
Shared LSP document state prevents duplicate opens and edit versions across
callers; strict protocol and six fresh Rust fixtures pass. The intermittent CI
failure's cause is not proven. Body-file fusion improved consumed development
33→40/48 at five, then fresh validation 18→20/24, but lost one existing top-24
hit and failed the full gate. Ranking remains unchanged. Two local Cockroach
component prototypes were not adopted; no new cloud rental or release occurred.

**Previous follow-up, 2026-10-15:** [Cockroach and fresh retrieval cycle](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-15-headroom-retrieval.md).
The merged fixes passed Cockroach at 167.970/180 seconds, still a narrow margin.
All 48 new source-backed retrieval questions are complete: baseline 33/48 at
five and 44/48 at 24. Neither fixed candidate improved development Hit@5;
no ranking policy was added. All 22 workers are deleted, cumulative estimated
compute is $0.9264 before tax. The unused conditional retry is not launchable
after the passing target. No additional release or model study was performed.

**Release status, 2026-10-15:** [0.1.6 is released and verified](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-15-release-016.md).
The full gate passed all 36 pinned packs, 144 retrieval observations, ranking,
591 contract tests (22 skips), lint, scale and lifecycle. The controller finished
in 21.368 minutes under its unchanged 90-minute limit. All 11 release jobs and
11 actual-PyPI clean-install/upgrade checks passed; the wheel's 268 Python files
match the validated source commit `c3624b2`.

Cockroach keyword/body indexing took 28.037/68.810 seconds, with a ready index
and 19.691-second restart. Measured checks and queries totaled 177.579 seconds;
the margin under the unchanged 180-second pack deadline is narrow. Discovery
now receives validated cached ASTs before building imports. The earlier full-path
no-reparse claim was corrected because its counter omitted discovery parsing.

The full gate distinguishes 127 passed assertions, 124 label limitations and
37 unsupported checks. Retrieval yielded 99/144 labeled hits at five, 128/144
at 24; labels are non-exhaustive development targets, not agent-benefit evidence.
No ranking or model default changed.

At the release checkpoint, all 21 workers were deleted; baseline ledger rows
and reservations are retained.
The three-worker cycle added $0.0898 estimated compute, cumulative $0.9119 before
tax (not an invoice). All three approved reservations are used under the $21 cap;
the separately approved follow-up is reported above. Only 1,601,899 report/log bytes returned to the
Mac. Protected studies/caches, global tools and the running host MCP are unchanged.

**Local follow-up:** [retrieval audit and file-scoped navigation repair](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-15-retrieval-file-symbol.md).
All 144 saved pages are classified; bounded FastAPI/Laravel tracing shows a
candidate present below the page cutoff and a relevant file omitted by the
original labels. Six fresh questions yielded 3/6 at five, 5/6 at 24 and 6/6 at 96.
File symbol lookups now exclude same-named definitions in other files and avoid
scanning their global name lists. This repair merged in PR #210 and is not part of published
0.1.6. Search ranking and the narrow Cockroach timing margin remain open.

**Second local follow-up:** [expansion comparison and importance publication](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-15-expansion-importance.md).
Disabling expansion improved development hits at five from 9/14 to 11/14, but
both arms reached 12/12 on fresh validation. The predeclared improvement rule
failed, so no ranking policy changed. Profiling exposed a separate publication
race: queries could rediscover and reparse the workspace while keyword cache
persistence was still running. Publishing importance first removes that extra
work; a controlled 128-file overlap retained identical scores and order while
reducing query time from 49–55 ms to about 7 ms. This is component evidence,
not a new Cockroach timing result. These follow-up repairs merged in PR #210 and do not change the published
0.1.6 artifact.

## Completed: intelligence-only repository (PR #222)

**Status:** Implemented on 2026-10-16 in PR #222. The agent is preserved at the
`agent-archive-2026-10-16` tag. The text below is the original proposal, kept as history.

The requested next direction is to retire the agent after this validation batch.
This is a transition proposal, not authorization to delete code or publish a new
package. The standalone `attocode-code-intel` distribution already owns the engine;
the root `attocode` distribution depends on it. Its clean-wheel check rejects
imports of the agent, swarm, TUI and model-client packages. That gives the
transition a practical starting point, but does not prove every repository tool
is independent. In particular, quality/ranking tooling still uses root workspace
configuration and preserved historical harness inputs.

1. **Preserve and inventory.** Create a final documented agent tag/archive before
   removal. Map imports, entrypoints, tests, CI, Docker, documentation and release
   automation. Preserve frozen studies and their grading worktree. Existing
   intelligence experiments do not establish that the agent itself is worthless.
2. **Make intelligence the primary product.** Keep the engine, MCP, CLI, API,
   storage, useful dashboard/deployment surfaces, source adapters and quality
   harness. Move root documentation, development commands and CI around those
   supported scenarios. Keep the existing package/import/CLI identity initially
   to avoid bundling a rename with the migration.
3. **Remove agent maintenance deliberately.** Archive agent/swarm orchestration,
   TUI and agent-only examples, model-provider integrations and jobs after their
   useful intelligence tests have moved. Document migration for existing agent
   users; do not silently repurpose the `attocode` package.
4. **Verify the smaller repository.** Require clean standalone installation,
   MCP/CLI/API workflows, PostgreSQL, platform/language-server CI, incremental
   recovery and bounded pinned-corpus checks. Record dependency, checkout,
   install-size and CI-time deltas before making size/speed claims. Keep unrelated
   shared caches and historical evaluations untouched.

The intended result is one clearly supported code-intelligence product, with
measurable retrieval and navigation quality and a smaller maintenance surface.
There is no deletion, rebrand or agent retirement in the current batch.

The entries below are historical evidence.

## Milestones

| Milestone | Status | Required evidence |
| --- | --- | --- |
| Coverage foundation | Validated locally and in CI | Frozen source-backed manifest; honest outcomes; bounded selection, shards and resume; complete baseline |
| Python, JS/TS, Go, Rust | Implemented; bounded gate passed | Module/alias/re-export and negative controls; real language-server checks |
| C/C++, Java, C# | Implemented; bounded gate passed | Include/package/namespace resolution, ambiguity and selected-definition identity |
| Ruby, PHP, Kotlin, Swift, Scala, Elixir, Lua, Bash, Zig | Implemented; bounded gate passed | Explicit module bindings, qualified references and dynamic-case limitations |
| Protocol and operation coverage | Implemented; bounded gate passed | Catalog-to-test inventory, real MCP/HTTP, profiles, isolation and failure cases |
| Release and final matrix | 0.1.6 released and verified | Coherent full 36-pack gate, required release CI, actual PyPI clean install/upgrade, verified cleanup |

The existing six source packs and frozen ranking baseline remain evidence inputs.
New labels must be frozen before evaluating product changes. Missing labels,
unsupported capabilities and incomplete execution are not successful assertions.
All mutations of source packs happen in disposable copies, never cached inputs.

## Historical execution bounds

These allowance changes record earlier stages, not current launch authority.
All 22 workers were deleted at the latest checkpoint; the last passing target
closed its conditional retry. No new rental is authorized by these old caps.

Quick/local remain capped at 120/600 seconds. Managed disk is capped at 5 GiB,
process-tree RSS at 4 GiB, with a 2 GiB free-space floor. Broad worker tests have
60 minutes and the controller has 90 minutes. One worker at a time; $1 reservation
per batch. The separately approved repair cycle raised the monthly reservation
cap from $10 to $14 and allowed four additional batches; all four are now used.
The approved structural-write follow-up allows at most two additional batches,
raising the monthly reservation cap to $16, with one worker at a time and early
stop on success. Reservations are admission limits, not actual charges. Preserve
the existing 14 ledger rows; no further increase is authorized by this follow-up.
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

### Historical remaining delivery gates (subsequently completed)

At this checkpoint, implementation was merged and remote results/cleanup were
recorded, but the full cold matrix still failed on CockroachDB indexing. The
six-batch allowance was exhausted. A separately approved later cycle passed the
full gate and published 0.1.6, as recorded at the top of this page. Keep failures, unsupported
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
completeness. See the [remote record](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-14-breadth-cloud-first.json).

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


### 2026-10-16: fresh timing check and intelligence-first transition

The fresh CockroachDB cloud run on `9518a3d` passed its unchanged 180-second
pack check in 159.621 seconds. The independently verified worker was deleted;
all 23 reserved batches have verified cleanup, with no active quality workers.
Estimated cumulative compute is $0.9405, not an invoice. The $23 reservation cap
is fully used; another rental would need new authorization.

The repository transition is implemented: the complete agent is preserved at
`agent-archive-2026-10-16`, useful tests now import the standalone engine, and the
root workspace, CI and documentation target intelligence. See the
[archive and migration guide](legacy-agent.md). Historical experiment artifacts,
private client settings and shared caches remain separate from this migration.
Final validation and merge evidence are recorded in the transition results.
