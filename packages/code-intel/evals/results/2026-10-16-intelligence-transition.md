# Intelligence-first repository transition

The active repository now develops the standalone intelligence product. The complete
pre-transition agent, swarm, TypeScript implementation, lessons and their tests are
preserved at the published `agent-archive-2026-10-16` tag, commit
`9518a3d7724e2d9fe3f169a0d4a9b2d9ee492500`.

## Preservation and scope

Before removing old paths, the migrated tests and existing product suite passed in
a clean environment with no installed `attocode` distribution and a pytest import
guard rejecting `attocode`, `attoswarm` and `attocode_core`. The same suites passed
after removal. An exact manifest verified all 2,290 retired tracked files against
the archive, including byte-identical copies of retained fixtures.

The [test migration manifest](2026-10-16-intelligence-test-migration.json) maps 163
Python files to their new package locations, with old/new hashes and 2,745 retained
test-function definitions. Parameterization makes executed case counts different.
Mixed test files retain engine assertions while agent-only classes stay in the
archive. One new test explicitly verifies the matrix's unchanged 25 GiB low-disk
refusal; tiny synthetic matrix fixtures use simulated capacity under the outer
storage limit. No historical relevance labels or ranking baselines were rewritten.

The root is a virtual uv workspace. Its lockfile drops from 197 to 177 packages,
removing the agent, Textual and agent provider SDKs among others. Optional embedding
packages remain resolvable but are not installed by the development commands.
`EvalResult` is now a small independent evaluation record. The development setup
uses the standalone migrations and no longer installs semantic-model extras.

Agent release/benchmark jobs are retired. Engine tests, HTTP/MCP integration,
PostgreSQL product checks, ranking, real language servers, optional grammars,
macOS wheels, Docker, dashboard and rule-pack licenses remain checked. Strict docs
builds now run on documentation PRs. Intelligence release builds require engine CI.

## Local verification

[Machine-readable results](2026-10-16-intelligence-transition.json) preserve resource
measurements and every skipped/expected-failure case.

| Check after archive removal | Result |
|---|---|
| Migrated engine and integration tests | 2,794 passed, 5 skipped, 1 expected failure |
| Existing standalone product tests | 1,013 passed, 22 skipped |
| Follow-up after evaluation source-path cleanup | 213 passed |
| Synthetic 100/1,000/10,000-file scale and lifecycle | Passed |
| Frozen 68-query, five-method ranking gate | Passed; baseline unchanged |
| Clean runtime-only wheel, daily/lean MCP and navigation | Passed |
| Scoped Ruff, license checks, lock consistency, strict docs | Passed |

The supervised final stages took 181.6 seconds combined, peaking at 1.47 GiB managed
storage (including the clean environment and its cache) and 775.3 MiB sampled
process-tree RSS. Each stage had a 2 GiB storage/RSS bound and at most ten minutes.
This excludes initial environment preparation, diagnostic runs, the 213-test
follow-up and upstream CI. The full PostgreSQL and real-server checks are verified
in upstream CI; local skips are not counted as passes. This is not a new agent
outcome or search-quality study.

## Fresh CockroachDB timing

Before the migration, the approved fresh cloud check tested the archive commit.
[Its record](2026-10-16-cockroach-fresh-timing.json) reports 159.621 seconds against
the unchanged 180-second pack limit. The controller took 304.245 seconds; the
workflow phase including materialization took 180.441 seconds. Four assertions
passed, four were limited, and none failed or remained incomplete.

The four legacy retrieval anchors yielded 0/4 known-target hits at five and 1/4
at 24. These non-exhaustive labels do not establish useful search quality, and this
targeted check is not a full release gate. Estimated compute was $0.0141 for this
worker and $0.9405 cumulative, not an invoice. Independent API verification found
zero active quality workers and verified cleanup for all 23 reserved batches.
The $23 reservation cap is fully used. Only 48,418 bytes of evidence were exported;
no corpus or index was downloaded.

## Compatibility and limits

The standalone package stays at 0.1.6; no release, model run, model download or
ranking-default change was made. Old agent import aliases are available only in
the archive. Global installed tools, the host's existing MCP process, shared caches,
private study artifacts and the protected frozen worktree were not upgraded or
removed. The host MCP must be restarted before claiming that its long-running
process has loaded the checkout's latest source.
