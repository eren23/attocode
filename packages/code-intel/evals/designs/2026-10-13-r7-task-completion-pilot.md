# R7 protocol: optional code intel on completed bug fixes

Designed and implemented locally on 2026-10-13 after R6. The authorized
scope is build and offline preparation only. No R7 model request has been
made; the two excluded model wiring checks and 32 scored runs remain pending.

## Question and scope

When an agent can edit code and run tests, does optional access to the
[proposed seven-tool profile](../../../../docs/intelligence-daily-profile-proposal.md)
improve completed fixes enough to justify a larger evaluation?

R2 and R3 measured file localization; R4 Stage 1 and R6 measured naming
tests. They found no demonstrated agent benefit. R7 measures a complete
fix, with independent test grading. It does not reopen those localization
or review claims. The proposed profile and its conditional instructions
are one treatment package; this two-arm pilot cannot identify the effect
of profile width alone.

## Tasks and pick rule

Use the existing local SWE-bench Lite development pool: 274 issue tasks
from 12 repositories at dataset revision
`97f9af8814fe7eb15dcd9b2abaa9010e1eadda63`. Choose 8 tasks from 8 different
repositories. These public development tasks may be known to the model
and overlap prior localization work; the pilot gives no held-out claim.

Read the raw cached dataset, not the normalized navigation matrix. The
matrix's `instances.jsonl` retains paths and queries, but drops
`FAIL_TO_PASS`, `PASS_TO_PASS`, and the test patch. The raw input is:

```
~/Documents/AI/attocode-evals/matrix/datasets/
  lite@97f9af8814fe7eb15dcd9b2abaa9010e1eadda63/data/test-00000-of-00001.parquet
```

Before agent runs:

1. Freeze the raw input hash. Order repositories by SHA-256 of the
   repository name and issues within each repository by SHA-256 of the
   instance ID. Take the first eligible issue from each of the first
   8 eligible repositories. Do not screen by model outcomes, tool ranks,
   gold-file retrieval, patch size or apparent difficulty.
2. Eligibility requires a reproducible isolated runtime, a base commit,
   nonempty failing-test and regression-test sets, and a separately
   applicable gold code patch and official test patch. Exclude guidance
   conflicts using the existing study convention. Log every exclusion
   before trials; proceed in hash order. If fewer than 8 repositories
   qualify, stop and amend the design before any agent run.
3. Run independent grader controls: base code with the official test
   patch must reproduce the failing tests and preserve regression tests;
   gold code plus the official test patch must pass both sets. A scoring
   control with a regression failure must be classified unresolved.
4. Freeze all 8 IDs, source/image digests, setup commands, full test lists,
   test-patch hashes, controls and exclusion reasons. Use the identical
   eligible set for both arms. No replacements after outcomes exist.

The pinned raw Parquet SHA-256 is
`008ac523001de665d3f1e4f4179587dcd68dd7b2f2d5bd878a5385e3e938b59d`.
An isolated evaluator environment contains PyArrow and SWE-bench v4.1.0
at commit `726c5461e2ef52d83cf1ea2107870a8bb3328d57`; current upstream main
expects a different dataset format. Record installed dependency versions
and reject drift. Keep raw gold/test data and preparation exclusions private.
The final pack preserves generated build artifacts without upstream Git
history; both image-only and mounted-source base/gold controls must pass.

## Arms, model and prompt

| Arm | Agent tools |
|---|---|
| `native` | Read, Grep, Glob, Edit, Write and task-runtime Bash |
| `lean_optional` | Exactly the same native tools, plus the seven advertised code-intel tools |

Use Claude Code with `claude-sonnet-5-5`, the same version in both arms,
subscription authentication only, no API fallback or fallback model.
The latest study used Claude Code 2.1.287; record the actual version at
freeze and reject later version drift. Pin and hash the engine, harness,
dependencies, container images and client settings.

Both arms receive the same task prompt:

> Fix the issue below in this repository. You may inspect and edit code
> and run tests using the provided task environment. Choose tools when
> they help. Leave your completed changes in the workspace and report
> the tests you ran and any remaining issue.
>
> {problem_statement}

Only the treatment has MCP descriptions and conditional server routing
instructions. There is no forced first call, task-specific tool hint,
chain-of-thought requirement or claim that the server is beneficial.
Do not supply gold paths, the gold patch, grading test lists, official
test patches or hints containing reference solutions to the agent.

Run 2 independent trials per task and arm: **32 scored runs**, 16 per arm.
Shuffle task/repetition blocks with seed 7332, and randomize arm order
inside each block. Use fresh workspaces, sessions and task runtimes.
Personal instructions, memory, hooks, unrelated MCP servers and other
agent sessions are excluded. Provider and OS cache state remain
uncontrolled and must be disclosed.

## Runtime and index contract

Use the existing host Claude client for native reads and edits. Execute
repository programs through the provided Docker helper, with the same
mounted workspace, Linux amd64 platform, 2 CPUs, 4 GiB memory and no
network in both arms. Native host reads are bounded by instructions and
trace audit, not an OS sandbox: this is the user-selected runtime boundary.
Keep unrelated tools, settings, memory and MCP servers out of the client.
Finish dependency installation and cache required build wheels before
the agent timer. Online preparation is separate from offline execution. The server must inspect the exact
working tree the agent edits; verify an edit is reflected in a later
inspection. Keep hidden grader inputs outside both the workspace and
the server's indexed roots. Freeze the transport and runtime adapter.

Prepare the treatment index before the timed agent attempt, as in R6.
Record warm-up time and failure separately. Also report end-to-end time
including index preparation; do not infer an installation or cold-start
speedup from the warm-index comparison. A pretrial preparation failure
excludes a task for both arms, before any scored trial starts.

At most 2 excluded wiring runs, one per arm, must show edits, test
execution and output capture working in the intended runtime. The
treatment check additionally verifies the exact seven advertised tools,
an answered MCP call, working-tree freshness and absence of the reference
solution. These calls may be forced only in excluded wiring checks.

## Independent grading

At the time limit or normal completion, preserve the submitted patch,
trace and runtime logs. Grade in a separate fresh base checkout with
the submitted patch and the immutable official test patch. Agent test
reports and agent-modified tests do not determine the verdict. A
submission conflicting with the official test patch fails the attempt;
do not repair its patch manually.

An attempt is resolved only when **all recorded FAIL_TO_PASS and
PASS_TO_PASS tests pass**, with no missing or skipped required tests,
using the pinned task runtime. Require actual completed test execution;
test collection errors and empty runs cannot pass. Agent changes to
grader controls or attempts to weaken test execution cannot pass.
Keep the test output, parsed results and applied patch hashes.

The existing local `eval/swebench/grader.py:grade_local` cannot serve
unchanged: it checks at most 20 regression tests, does not require
regression success in its final verdict, and uses the host Python for
pytest. The `grade_official` adapter is also not evidence that an
installed official harness API or its runtime is verified. Implement
and validate a strict adapter against the pinned evaluator before
freezing R7; do not change old study graders or results.

Each model attempt has a 600-second wall-time limit. A model timeout,
exhausted model budget, invalid submission or protocol violation scores
unresolved; preserve it. A runtime/infrastructure failure may be rerun
only after an arm-blind documented diagnosis, with the original retained.
Apply the same rule to both arms. Report all attempts and reruns. Never
rerun because an answer or patch is poor.

## Metrics and pilot continuation gate

Primary: resolved fraction per task, averaged over its two trials, then
the mean paired difference (`lean_optional` minus `native`) over 8 tasks.
Report all 16 trial pairs and 8 task differences. Do not select the better
trial or substitute pass@2 for the primary metric. Include treatment
attempts with no MCP calls; do not condition quality comparisons on
adoption.

Secondary:

- Naturally chosen successful MCP use: any MCP call is adoption; an
  answered, non-error code-analysis call other than `capabilities` is
  substantive adoption. Count both, by run, task and tool. Neither
  proves that the call helped. Failed calls and coverage limits remain
  visible in the trace.
- Client-reported cost estimate, tokens and turns; pairwise mean cost
  ratio. Include failures. A missing failed-run cost uses the larger
  observed cost in either arm, with that imputation disclosed.
- Failure-penalized time: normal elapsed time for resolved attempts and
  600 seconds for unresolved attempts. Report the arm mean ratio, raw
  durations and end-to-end setup/index time separately.
- Regression failures, invalid submissions, tool errors, warming
  responses and whether the agent tested its patch. Localization and
  test-path recall are diagnostics, not substitutes for resolution.

Advance to planning a fresh held-out study only if **all** hold:

1. Primary paired resolution difference at least +0.125, equivalent to
   at least two extra resolved attempts among 16 per arm.
2. Mean client-reported cost ratio at most 1.25 and failure-penalized
   time ratio at most 1.25. If costs cannot be recorded comparably,
   the gate is inconclusive and does not authorize a larger run.
3. The frozen-input, isolation, grading and completeness checks pass.

Adoption is descriptive only, with no minimum threshold. The user selected
this outcome-first gate before model runs.

These are development screening thresholds chosen now, not statistical
proof or estimates of effect size. Eight repositories cannot establish
a modest gain or noninferiority. Report uncertainty descriptively and
label any interval exploratory. If a gate fails, stop expansion and
write the result; no wording retry, task substitution, forced-call arm
or extra trials in this pilot. A new proposal would need a new rationale.

A positive pilot permits designing and sizing a new study on untouched
tasks, with repository-aware inference and a task-source audit. It
does not justify changing defaults, claiming a speedup or publishing a
benchmark ranking. A full-versus-seven profile comparison would need
its own design if that becomes the question.

## Subscription and session bounds

No R7 model runs have started. The planned launch is after
the quota reset and after the implementation/readiness gates are met,
using a fresh observation of subscription availability and disabled
paid usage. Keep the existing one-hour observation limit, at most two
workers, and sessions that stop starting attempts after 50 minutes.
Persist in-flight attempts and results; do not use a launcher that
terminates active trials at the session boundary.

The run limit is 32 scored attempts and at most 2 excluded wiring runs.
Stop scheduling new attempts on quota exhaustion or when recorded
client-reported estimates reach $20; up to two in-flight attempts can
finish beyond that estimate. This is a soft scheduling limit, not a
spending guarantee or a conversion of subscription allowance to dollars.
The local CLI describes `--max-budget-usd` as an API-spend limit; do not
assume it enforces a subscription budget. Resume pending trials only
after a fresh quota check, without changing their frozen identities.
Quota pauses can resume the same schedule. Reaching the $20 soft limit
ends this pilot's scheduling: if it is incomplete, retain pending rows,
report an inconclusive continuation gate, and do not raise the cap after
seeing outcomes. Unstarted rows are not model failures.

## Readiness and execution

- Implement the opt-in profile, accurate capabilities/follow-ups and
  conditional routing; verify tools/list and freshness in both watch modes.
- Build the isolated writable task-runtime adapter and strict independent
  grader, with base/gold/regression controls.
- Deterministically pick and prepare 8 tasks; freeze every source and
  evaluator input, prompt, setting and schedule outside the repository.
- Validate artifact preservation, quota stop, timeouts and restart behavior
  offline. Freeze a new identity after any change. The two excluded model
  wiring checks are a later gate before any scored request.

The R6 review/localization harness cannot run this protocol unchanged:
it uses read-only tools and scores named paths. Do not relabel its
`--mode review` output as completed-fix evidence.

Implementation: `repair_grading.py` supplies strict verdicts and the outcome
gate; `repair_worker.py` owns isolated preparation/grading; `repair_study.py`
owns freezing, offline wiring and future bounded execution. See the
[eval commands](../README.md#repair-completion-pilot) for operator steps.
Neither `prepare` nor `wiring --offline` makes a model request.
