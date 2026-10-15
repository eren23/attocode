# Bounded code intelligence validation

Use local code intelligence for finding implementations, inspecting known symbols,
planning changes, and returning after edits or a restart. These are the supported
development priorities. Hosted compatibility remains covered by the product suite;
legacy agent and swarm features are outside this work. Offline gates verify tool
behavior and resource use. Agent completion benefit still needs separate evidence.

## Run the checks

From the repository root, with the existing development environment:

```sh
.venv/bin/python -m eval.quality quick
.venv/bin/python -m eval.quality local
.venv/bin/python -m eval.quality storage
.venv/bin/python -m eval.quality report .attocode/quality/runs/RUN_ID
.venv/bin/python -m eval.quality gc
```

| Tier | Contents | Runtime limit |
| --- | --- | --- |
| `quick` | Changed-surface lint, search/reference contracts, language fixtures, supervisor/cloud failures, short lifecycle check | 2 minutes |
| `local` | Quick checks, product/navigation/remote contracts, edit and index reuse, 100/1,000/10,000-file gate, 20 lifecycle cycles | 10 minutes |
| `broad` | Local plus 36 pinned source packs / 144 retrieval questions and the unchanged frozen ranking gate | 60 minutes on the remote worker |

For an offline broad run using already available snapshots on the Mac, use
`broad --seconds 600`. Missing snapshots fail without downloading; the remote
worker explicitly enables public source downloads. Repository dependencies and
tests from those downloaded source packs are never executed.

The runner reuses the current virtual environment. It puts disposable source,
indexes, pytest output, and caches below `.attocode/quality/`, with a 5 GiB managed
storage budget, a 4 GiB process-tree RSS budget and a 2 GiB free-space floor.
These are sampled limits: a fast allocation can briefly overshoot before the
supervisor stops the process. Existing environments, shared caches and historical
studies are outside that workspace and are never automatically removed.

One run owns the workspace lock. The supervisor enforces a deadline, caps each
log at 2 MiB while draining excess output, and terminates the process group and
observed descendants. If process inspection is unavailable, it refuses to start
the test. A timeout, missing fixture, changed input, or unverified cleanup is an
incomplete run, never a pass. A completed failing assertion is a failure.

Each report records source/fixture/harness hashes, interpreter, timing, sampled
peak disk/RSS, individual outcomes and cleanup. Scratch directories are removed
in `finally`; reports remain for review. `gc` prints exact expired owned report
paths; add `--apply` to remove them. It keeps active, unknown and foreign data.
An interrupted controller can leave scratch requiring inspection; the budget
then blocks new runs rather than silently expanding storage. Shared uv/model
caches, original traces, scores, source blobs, Docker images and
`.claude/worktrees/stage1` are protected. `storage` distinguishes Docker's sparse
logical disk size from allocated bytes; deleting `Docker.raw` is not a cleanup
operation offered by this runner.

## What the evidence covers

`eval/quality/workflows.yaml` freezes 36 repositories and 144 unscoped queries
with literal source anchors, line numbers and hashes. Each pack attempts definition
lookup, selected source, scoped search, caller syntax, dependencies, impact,
candidate tests and restart. The original six packs have relationship labels;
most new packs have definition/retrieval labels only. Unlabeled relationships are
`limited`, never successful relationship assertions. The queries are development
anchors with non-exhaustive relevant-file labels, not a held-out benchmark.

Run subsets without repeating the entire matrix:

```sh
.venv/bin/python -m eval.quality broad --suite workflows --pack requests --seconds 600
.venv/bin/python -m eval.quality broad --suite workflows --shard 1/3 --seconds 600
.venv/bin/python -m eval.quality broad --suite workflows --resume PATH/workflows.json --seconds 600
.venv/bin/python -m eval.quality report A/workflows.json --merge B/workflows.json --merge C/workflows.json
.venv/bin/python -m eval.quality broad --suite ranking --seconds 600
```

Shards are sorted by pack ID and disjoint. Aggregation requires identical source,
harness, fixture, manifest, dependency, Python/platform, grammar-cache and relevant
setting identities. Resume reuses only completed clean packs with all questions
observed. Failed/incomplete packs run again. Reports from different platforms or
code versions cannot be merged into one apparent matrix. Cloud `run` accepts
`--pack`, `--shard`, `--suite` and `--resume`. The controller checks resume source
hashes before renting; the worker also requires an identical environment before
reusing evidence. Cross-platform resume is rejected, not relabeled compatible.

Each pack has a 180-second evaluation limit inside the unchanged tier deadline.
The first expanded run used 90 seconds; CockroachDB needed 73 seconds just to warm
scoped search, so that limit could cut off later checks. Both interrupted results
and completed observations are retained. One source pack and its copied blobs are
removed before admitting the next. Original cached inputs remain read-only.

Execution can finish successfully while evidence remains `limited` or
`unsupported`; inspect the outcome counts, not just the command exit code.
A missing optional grammar or an explicitly ignored labeled source is unsupported,
not a positive assertion. A wrong answer for eligible supported source is failed.
Missing packs/questions, changed inputs and unverified cleanup are incomplete.
The pinned Perl pack includes real source under `dist/`, which default discovery
excludes; the original failure is retained. New reports identify this independently
from the ignore policy. A separate regression proves that explicit `!dist/` in
root `.gitignore` admits it and that removing the override removes its symbols.
The frozen source pack itself is not altered to obtain a pass.

Remote source acquisition fetches a shallow filtered commit and inspects only
the downloaded objects, so inspecting omitted large files cannot trigger an
unbounded lazy fetch. Workflow reports record the Git version and a bounded
stderr tail when a source command fails.
Cold search responses explicitly marked `warming` are retried for up to 90
seconds per pack, with warming-response counts and elapsed time recorded.
Ready responses and errors are never retried to obtain a better answer. The eight workflow checks remain distinct from the four unscoped retrieval observations.

These are development evidence anchors, not held-out relevance judgments or
exhaustive call resolution. Caller syntax is not necessarily a linked reference.
Unavailable import/test anchors are explicitly marked limited. Existing negative
evidence tests retain `absence_proven: false` for partial analysis. The parser
fixtures cover 18 core programming languages, six data/config formats and 12
optional languages. Optional checks skip when grammars are absent; the CI-only
acquisition script requests only that explicit set in a disposable cache. Neither
capability discovery nor product navigation downloads missing grammars.

Static module ownership covers JSONC/local extends, declared Go module/package
files, Rust local path dependencies, C/C++ compilation-database include order,
Java/C#/PHP/Kotlin/Scala namespaces, Swift literal target paths, and literal
Ruby/Lua/Bash/Elixir/Zig imports. Explicit aliases and type-qualified calls have
positive and negative controls. Dynamic imports, compiler flags/macros beyond the
bounded recognized cases, arbitrary build scripts and type inference remain
unresolved. An LSP reference stores the selected file/line/qualified symbol identity;
workspace edits invalidate old precise links before they can be reused.

`operations.json` inventories every advertised operation against gateway calls in
passing tests. `response_observed`, `error_only` and `unmapped` are separate; a
successful response is not proof that every semantic branch is correct. All 139
current operations have input-rejection checks. Real stdio and authenticated HTTP,
profiles, multi-workspace isolation, limits and malformed protocol cases are tested
separately. Direct internal calls and subprocess MCP calls are outside this runtime
inventory. `contracts.xml` preserves per-test pass/skip/failure evidence.

The installed TypeScript server has a cold selected-definition/edit/shutdown test.
The opt-in Python/Go/Rust worker matrix allows at most 30 seconds of explicit server
warmup and 15 seconds for an edit; it does not establish cold production latency.
Production precision retains its two-second deadline and reports partial evidence
when unavailable. CI installs pinned test servers in disposable runners, never on
the user's device. Linux/macOS wheel jobs cover Python 3.12 and 3.13 and upgrade a
0.1.5 index/configuration before checking the candidate wheel.

The ranking gate uses its unchanged frozen baseline. A temporary local commit
lets that gate inspect the current working input without committing or publishing
the user's checkout. Its source snapshots are disposable and its engine hash is
reported. Passing it means no threshold regression on those known queries, not
improved intent understanding. No baseline is rewritten by `eval.quality`.

Lifecycle checks alternate watched/unwatched sessions and exercise add, edit,
rename, deletion and restart. They check owned worker shutdown and descriptor
growth after 20 cycles. Warm search must stay below a 2-second p95 and returning
focused lookup below 1 second on the one-file lifecycle workload. The separate
10,000-file import-chain gate bounds hydration to 90 seconds and checks dependency
coverage. These workloads do not establish latency on arbitrary real monorepos,
or prove that every cause of the historical root-suite descriptor failure is fixed.

The local and broad contract suites also include 72 seeded mixed-edit comparisons
against a fresh index and independently enumerated Python definitions. A disabled
repair negative control must fail. A small six-language workspace checks duplicate
symbol selection, exact source ranges, Unicode/spaced paths, ignored generated
files, malformed-source recovery and TypeScript import updates, live and reopened.
File symlinks outside the workspace, broken links and loops are excluded from
discovery and freshness tracking; internal file aliases remain supported, including
retargeting between requests. These checks are not an OS sandbox against concurrent
filesystem changes.

Two gateway processes share a disposable index in the process tests. An explicit
barrier holds the first writer after snapshot invalidation and partial persistence,
with a real SQLite write transaction open. The second process must demonstrate lock
contention. Both orderly completion and killing the first writer must leave a
complete recoverable index, rolled-back uncommitted writes and SQLite integrity.
Each barrier/wait has a deadline and child processes are reaped in `finally`.
These small fixtures add no downloads or model calls and stay within the existing
local tier's time/storage limits; they are not a long-running contention benchmark.

## DigitalOcean batches

The controller checks both wall and monotonic deadlines, including after a host
suspension. Phase reports expose `wall_seconds` separately from `seconds`.
Remote setup, tests and export run in transient systemd services with a runtime
deadline and `KillMode=control-group`, covering children that start new sessions.
TERM is followed by KILL after ten seconds. Expired controllers refuse new work and
attempt deletion. A suspended/offline controller cannot itself delete a worker:
the independent TTL reaper remains the billing cleanup backstop. These limits
are not a guarantee that provider deletion finishes at exactly 90 minutes.
The service properties follow the upstream [systemd execution](https://github.com/systemd/systemd/blob/main/man/systemd-run.xml)
and [control-group cleanup](https://github.com/systemd/systemd/blob/main/man/systemd.kill.xml)
contracts; Linux CI checks a TERM-resistant detached child with the actual service manager.
Each transient service also creates a unique activation marker under `/run`.
An explicit maintenance restart fails before running its payload again, preserving
the original execution bound. Linux CI checks this with a real service restart.

Search warmup reports `warmup_reused_asts` for content-hash-verified structural
AST reuse; it adds no second AST cache and does not initialize structural indexing
just to attempt reuse. Stage durations describe observed work, not an ETA.
Body indexing shares line tokens between overlapping windows and whole-file
search, preserving separately tokenized truncated lines. It retains this data
for one bounded file only, reuses matching published ASTs if the span cache misses,
and inserts at most 64 windows per SQL statement in the existing atomic refresh.
Equivalence checks cover window/file terms, row order, BM25 and failed-refresh rollback.

The optional controller uses DigitalOcean's API and SSH. It selects one
`s-8vcpu-16gb-amd` shared CPU worker in `ams3`, with at least 8 vCPUs and
16 GiB memory, and verifies the
live provider quote before provisioning. The admission budget is $1 per batch
and $19 per UTC month, before tax. A reservation is retained for the whole month;
runtime estimates are not refunds or invoices. Keep one controller and preserve
its ledger at `.attocode/quality/cloud/ledger.json`.

Before a live batch, publish the reviewed code and configure:

- Controller: `DIGITALOCEAN_ACCESS_TOKEN`, `QUALITY_SSH_KEY` (private key path),
  and `QUALITY_SSH_KEY_ID` (its registered DigitalOcean ID).
- GitHub: repository secret `QUALITY_DIGITALOCEAN_TOKEN` and variable
  `QUALITY_CLOUD_ENABLED=true`; enable and verify `Quality worker cleanup`.

The DigitalOcean MCP OAuth connection is separate from these unattended API
credentials. A successful MCP connection does not configure the controller or
GitHub cleanup job. On 2026-10-14 the connected account returned no droplets,
and its size listing did not include the originally planned dedicated `c-8`.
The user approved the available shared CPU size instead, quoted at $0.16667/hour
before tax. Shared CPU contention can affect timing, so reports from this worker
are not dedicated-CPU latency measurements. The live quote must still pass;
no worker size or region is automatically substituted.

On 2026-10-15 Frankfurt (`fra1`) became unavailable before the final follow-up
batch was reserved. The controller explicitly moved to Amsterdam (`ams3`) for
the same size and quoted rate within the existing batch allowance. Earlier
Frankfurt timings and later Amsterdam timings are separate environments, not a
controlled latency comparison. Admission still refuses if this configured
region is unavailable; it does not choose another region automatically.

```sh
.venv/bin/python -m eval.quality cloud quote
.venv/bin/python -m eval.quality cloud run
.venv/bin/python -m eval.quality cloud reap       # preview expired tagged workers
.venv/bin/python -m eval.quality cloud reap-apply
.venv/bin/python -m eval.quality cloud reconcile
```

`run` creates a billed resource. Admission requires a successful, non-skipped
independent cleanup heartbeat in the last two hours, no existing project worker,
no unresolved cleanup, sufficient monthly reservation, and a clean source commit
already on `origin/main`. Credentials stay on the controller. Only committed
public source reaches the worker; no private working edits, historical studies,
model weights or user home directories are uploaded.

Setup, execution and collection fit a 90-minute controller deadline; tests have
60 minutes. Results exported to the Mac are JSON, logs and JUnit XML, at most 20 MiB total
and 2 MiB per exported file. JSON whitespace is removed without dropping evidence;
JSON inputs above 8 MiB are refused before parsing. Source corpora and indexes
are not downloaded to the Mac.
Before package installation, a 15-second DNS probe checks the worker's configured
resolver. If it fails, the disposable Ubuntu worker temporarily uses public
resolvers `1.1.1.1` and `8.8.8.8` on `eth0`, logs the intervention, and retries
for at most 15 seconds. Continued failure aborts setup. This changes neither
the account's VPC settings nor the Mac's DNS; healthy worker DNS is preserved.
SSH readiness alone does not admit setup: the controller polls
[`cloud-init status --format=json`](https://docs.cloud-init.io/en/latest/reference/cli.html#status)
until first-boot initialization finishes cleanly, within the original eight-minute
readiness budget and controller deadline. Failed, degraded, disabled, malformed or
unfinished initialization prevents setup. This avoids competing with initial
package updates and their service restarts. The final status is retained in
`bootstrap.json` on the controller.
Package installation waits up to 120 seconds for an existing dpkg lock, within
the unchanged 600-second setup limit. It never removes lock files or terminates
another package-manager process. Linux CI exercises lock release and expiry
against an isolated package database using the actual apt executable.
The controller always attempts deletion and verifies provider absence, including
lost create responses and collection failures. Unknown provisioning/deletion
state blocks another launch. `reconcile` verifies external cleanup without
creating a worker or refunding the reservation.

The independent GitHub job checks every 15 minutes for project-tagged workers
older than two hours. GitHub scheduling and provider outages can delay deletion;
this is budget admission and cleanup automation, not a provider-enforced spending
cap. Powered-off droplets remain billable until deleted. See
[DigitalOcean billing](https://docs.digitalocean.com/products/droplets/details/pricing/).
No live provisioning is part of the offline validation.

## CI and the next agent experiment

Standard GitHub runners remain in use. Superseded intelligence/ranking runs are
cancelled, jobs have timeouts, and uploaded results expire after seven days.
Hosted PostgreSQL, wheel, dashboard and image checks remain in CI. Local passes
do not stand in for those unexecuted hosted checks.

Do not automatically start another agent/model study. R7's reviewed STOP remains
in force. The [small follow-up design](../packages/code-intel/evals/designs/2026-10-14-workflow-pilot.md)
requires separate authorization, frozen inputs and passing offline gates first.

### Opt-in cold-index diagnostic

The bounded [stage probe](../packages/code-intel/evals/results/2026-10-15-index-probe-readiness.md)
records inclusive wall/thread-CPU timings and partial work counters without
changing search ranking or the release gate. Run `python -m eval.quality.index_probe`
for tiny local wiring. `python -m eval.quality cloud probe --pack cockroach` selects
one pinned corpus on an authorized worker, with fresh source/index directories
for normal concurrent and prehydrated startup. Its result is diagnostic evidence;
it cannot pass the full quality gate. The approved extension permits one diagnostic worker after the 16 existing
reservations, with a $17 monthly reservation cap. It does not authorize another
full-matrix retry. All admission/deletion guards still apply.

The [first pinned diagnostic](../packages/code-intel/evals/results/2026-10-15-cockroach-index-probe.md)
used that one additional reservation. Both body indexes remained incomplete;
prehydration shortened keyword work but increased total observation elapsed.
All 17 workers are deleted and the allowance is exhausted. The raw profiles guide
follow-up work; they do not authorize another rental or clear the release gate.

The [local discovery/body follow-up](../packages/code-intel/evals/results/2026-10-15-discovery-body-repair.md)
adds probe schema 2: tokenizer/serializer timings sample every 64th call while
`sampling.observed_calls` retains the exact attempted call count. Sampled durations
must not be summed as full-phase cost or extrapolated. Outer phases still include
probe overhead. Fresh discovery snapshots require metadata/policy validation before
reuse; invalid snapshots fall back to discovery. Local checks do not replace the
pending uninstrumented target and full release gates.

The next approved validation extension permits at most two additional workers,
retaining all 17 previous reservations under a $19 monthly cap. Run uninstrumented
`cloud run --pack cockroach --suite workflows` first; run the unchanged full
`cloud run --suite all` only if that target passes on coherent inputs. Collect
results and verify deletion after each. No blind retry or third rental is included;
0.1.6 publication still requires a complete passing full gate.

The [uninstrumented target result](../packages/code-intel/evals/results/2026-10-15-discovery-validation.md)
reached ready body search but exceeded the unchanged 180-second pack deadline
before the final restart check completed. The target failed; the conditional full
run was not launched. All 18 workers are deleted, with $0.8221 cumulative estimated
compute (not an invoice). One reservation remains unused, but the failed target
blocks using it for the full gate. Next work is local restart/freshness analysis;
no release or further rental follows from this incomplete result.
