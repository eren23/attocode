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
| `broad` | Local plus six pinned workflow packs and the existing 53-case, 21-repository ranking gate | 60 minutes on the remote worker |

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

`eval/quality/workflows.yaml` pins FastAPI, Express, this repository's TypeScript
frontend, GitHub CLI, ripgrep and Gson. Each pack checks definition discovery,
source selection, scoped search, caller syntax, dependencies, impact, candidate
tests and restart. Ambiguous definitions use file and line selection; references
follow at most ten bounded pages. Impact can be found in the depth layers even
when the flattened list is trimmed. A short known identifier such as `cn` uses
symbol lookup; its search check uses source terms `twMerge clsx`.

Remote source acquisition fetches a shallow filtered commit and inspects only
the downloaded objects, so inspecting omitted large files cannot trigger an
unbounded lazy fetch. Workflow reports record the Git version and a bounded
stderr tail when a source command fails.

These are development evidence anchors, not held-out relevance judgments or
exhaustive call resolution. Caller syntax is not necessarily a linked reference.
Unavailable import/test anchors are explicitly marked limited. Existing negative
evidence tests retain `absence_proven: false` for partial analysis. The parser
fixtures check definitions and missing names in 18 programming languages; they
do not establish precise cross-file references, dependencies or test selection
for every language. Data/config formats need their own behavior checks.

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

## DigitalOcean batches

The optional controller uses DigitalOcean's API and SSH. It selects one
`s-8vcpu-16gb-amd` shared CPU worker in `fra1`, with at least 8 vCPUs and
16 GiB memory, and verifies the
live provider quote before provisioning. The admission budget is $1 per batch
and $10 per UTC month, before tax. A reservation is retained for the whole month;
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
60 minutes. Results exported to the Mac are JSON/logs only, at most 20 MiB total.
Before package installation, a 15-second DNS probe checks the worker's configured
resolver. If it fails, the disposable Ubuntu worker temporarily uses public
resolvers `1.1.1.1` and `8.8.8.8` on `eth0`, logs the intervention, and retries
for at most 15 seconds. Continued failure aborts setup. This changes neither
the account's VPC settings nor the Mac's DNS; healthy worker DNS is preserved.
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
