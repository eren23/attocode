# R7 preparation: ready for later model wiring

2026-10-13. Build and offline preparation are complete. **No R7 model
request was made.** Two excluded model wiring attempts and all 32 scored
attempts remain pending. No completion benefit has been measured.

The opt-in local `lean` profile advertises seven tools with watching,
or eight with manual freshness notification. Daily/full defaults,
ranking and remote surfaces remain unchanged. See the
[profile contract](../../../../docs/intelligence-daily-profile-proposal.md)
and the [outcome-first protocol](../designs/2026-10-13-r7-task-completion-pilot.md).
Adoption is descriptive, with no minimum threshold.

## Frozen inputs

- Study: `~/Documents/AI/attocode-evals/matrix/studies/r7-pilot-v2`.
- Identity: `bbdc42518d1b103bf77be381726cc1ebb417c1c2a888579c5f5ba11acec5d163`.
- Canonical pack: `~/Documents/AI/attocode-evals/matrix/repair-pack-r7-ready`.
- Evaluator: isolated `repair-tooling/.venv`, SWE-bench v4.1.0 commit
  `726c5461e2ef52d83cf1ea2107870a8bb3328d57`, recorded dependency versions.
- Raw Lite input: 274 rows, 12 repositories, dataset revision
  `97f9af8814fe7eb15dcd9b2abaa9010e1eadda63`, SHA-256
  `008ac523001de665d3f1e4f4179587dcd68dd7b2f2d5bd878a5385e3e938b59d`.
- Selection: SHA-256 repository order, then SHA-256 instance order;
  8 preparation exclusions recorded before any agent outcome.
- Schedule: 8 repositories × 2 trials × 2 arms, seed 7332, Sonnet 5.5.

| Task | F2P IDs | P2P IDs | Four preparation controls |
|---|---:|---:|---|
| `astropy__astropy-6938` | 2 | 11 | Passed |
| `mwaskom__seaborn-3010` | 1 | 2 | Passed |
| `pydata__xarray-4248` | 1 | 18 | Passed |
| `sympy__sympy-21627` | 1 | 26 | Passed |
| `matplotlib__matplotlib-25433` | 1 | 55 | Passed |
| `django__django-14787` | 1 | 20 | Passed |
| `pallets__flask-5063` | 2 | 54 | Passed |
| `scikit-learn__scikit-learn-13779` | 2 | 18 | Passed |

Each task reproduced every F2P failure while preserving every P2P test
on base code, and resolved every required test with the gold patch.
Both image-only and mounted-source execution passed these controls
(32 container test executions). Eight synthetic regression verdict
controls were rejected. The grader has no P2P cap and rejects missing,
skipped, timed-out or unexecuted required tests. Official test paths are
restored before applying the immutable official test patch.

Snapshots preserve compiled build artifacts needed under a bind mount,
without upstream Git history. Task execution uses pinned Linux amd64
images, 2 CPUs, 4 GiB and no network. Image and build-wheel acquisition
happened during separate online preparation. Docker images are retained.
The host client uses instructions and trace audit, not an OS sandbox.
Hidden gold/test inputs remain outside the public workspace and MCP root.

## Validation

- 143 focused tests passed across profile, diagnostics, compact inspection,
  daily workflows, product/remote behavior and the new repair harness.
  Ruff and `git diff --check` passed. No broad root-suite pass is claimed.
- A clean standalone wheel passed daily and lean stdio startup, navigation
  and bundled-asset checks without the agent distribution. Its four
  modified profile modules match the frozen engine byte for byte.
  This is an unpublished development wheel using version 0.1.4.
- Frozen `prepare` passed all eight tasks, validating exact task, image,
  patch, source, evaluator and worker/grader identities before reusing
  successful prepared controls. No cached inputs were relabeled.
- Frozen `wiring --offline` passed actual Docker execution, the exact seven
  MCP tools and visibility of a container edit through `inspect_symbol`.
- Regression checks cover failures beyond the twentieth P2P ID, test exit
  status preservation, stale caches, virtualenv interpreter paths, quota
  and cost scheduling stops, interrupted artifacts and timed-out attempts.

The first freeze, `studies/r7-pilot`, is preserved with
`preparation-failure.json`. Its manifest resolved the evaluator executable
symlink into system Python. The corrected freeze keeps the virtualenv
path and has a new identity. Earlier diagnostic packs are also retained;
use `repair-pack-r7-ready` and `r7-pilot-v2` for further work.

## Pending work

After a fresh subscription-only quota observation and disabled paid usage,
the next execution stage is two excluded model wiring checks, followed
by the frozen scored schedule if wiring passes. This stage was not part
of build/preparation authorization. `run` refuses to call a model while
wiring is pending. Preserve the 2-worker, 50-minute session and $20
cumulative client-estimate soft scheduling limits. Use the frozen harness
and engine; change either only by freezing a new study identity.

The continuation gate is currently inconclusive because no scored runs
exist. There is no ranking/default change, release, commit or PR. R6
artifacts and the stage1 worktree remain separate and untouched.
