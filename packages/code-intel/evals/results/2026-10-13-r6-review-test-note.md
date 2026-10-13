# Study R6: a test suggestion that states its limits

**Status: no evidence that the server helps a review. The predefined
“no harm” rule is met, narrowly.** On 29 new tasks, with 3 trials per
setup, test Recall@5 was 0.722 for `intel_first` and 0.716 for `native`
(Δ +0.007, 95% bootstrap range −0.046 to +0.052). Help requires Δ ≥ 0.05
and a range above 0. No harm requires the lower end to be above −0.05.
The lower end clears that margin by about 0.004; this is not evidence
that every change review is unharmed.

In [R4 Stage 1](2026-10-12-r4-stage1-review-agents.md), agents often
named only the tests from `suggest_tests` and stopped searching. R6
checks a small response change: the tool states its strongest evidence
and says that its candidate list is incomplete. It changes no ranking
or candidates.

## Design and product change

The design was written on 2026-10-12 before the task pick, product
change or runs. It is `studies/r6-design.md` in the external evals store,
with SHA-256 `f04156b3b26244e6d31687ef1e2f58fffa23693e84d815a3ee7197749089a8b6`.
Its amendment, made before the product change was merged, adds the
`indirect` label for priority 3.

`suggest_tests` adds:

- `evidence`: the strongest evidence in the list, `direct` (priority 1),
  `imports` (2), `indirect` (3), `names` (4), or `none`.
- `note`: fixed text explaining that the candidates come only from file
  names and imports, the list is incomplete, and nearby tests may also
  check the change.

The main study keeps the R4 Stage 1 client, model, prompt and tools:
Claude Code 2.1.287, `claude-sonnet-5-5`, `REVIEW_PROMPT_V2`, and
read-only Bash alongside Read, Grep and Glob. `native` has those tools;
`intel_first` also has the server's daily tool list, and its prompt
requires `git diff --name-only` followed by one `suggest_tests` call.
The agent then chooses its tools. It names at most 10 existing test
paths and does not run tests or edit files.

Tasks are the first 30 eligible R5 tasks in SHA-256(id) order that no
earlier agent study used. Each comes from a different repository, and
none comes from an R4 Stage 1 repository. The pick rejects base trees
with agent guidance, as in R4 Stage 1. Preparation excluded
`IBM/sarama-3258` because its patch does not apply. The 29 remaining
tasks give 174 eligible runs of the original 180 scheduled.

The primary metric is the mean paired difference in test Recall@5,
using each task's mean over its 3 trials. The 95% range bootstraps tasks
(also repositories). A failed run scores 0. A rerun is allowed only for
an infrastructure failure. The readings are help, no harm, or otherwise
no evidence of help with harm not excluded, as defined above.

## Pilot

The pilot used the 9 known R4 tasks with discordant setup scores,
`intel_first` only, with 2 trials each. A run is “anchored” when every
answer path in its first 5 appears in the `suggest_tests` output.
The continuation rule was at most 6 anchored runs out of 18.

The pilot had 5/18 anchored runs and no failures, so it passed. Its
Recall@5 was 0.630. These were known development tasks; the main study
gives the result on new tasks.

## Main result

Study `6cd6c1c624a9` (`studies/r6-main`), frozen on 2026-10-12 and run
on 2026-10-13. All 174 eligible trials completed successfully, with
87 per setup and 3 per task. There were no scored retries or interrupted
trials.

| Measure | `intel_first` | `native` |
|---|---:|---:|
| Test Recall@5 | 0.722 | 0.716 |
| Hit@5 | 0.828 | 0.805 |
| Tasks where the setup is higher | 3 | 1 |
| Median client-reported cost (USD) | 0.0276 | 0.0261 |
| Median timed seconds | 10.3 | 8.2 |
| Median turns | 5 | 5 |
| Grep + Glob calls per run | 0.56 | 1.05 |
| Mean answer length | 5.97 | 5.66 |
| Failures | 0 | 0 |

- Δ Recall@5 = +0.007, with a 95% range of −0.046 to +0.052.
- 25 of 29 tasks had the same mean score in both setups.
- The mean client-reported cost ratio was 1.00. These are CLI cost
  estimates; the runs used the subscription, with paid usage disabled.
- The timed seconds exclude setup and index warm-up. They do not show
  an end-to-end speed gain.
- The server showed 6 gold paths that the final answers did not name:
  `tests/auxil/utils.py` on AirbrakesV2 and
  `tests/got/test_reply_headers.js` on nock, each in all 3 trials.
- Read-only Bash enforcement denied 1 call in `intel_first` and 10 in
  `native`. By the frozen review rules, a denied call does not fail a run.

The task differences are exploratory; the design sets no rule for them:

| Task | `intel_first` Recall@5 | `native` Recall@5 |
|---|---:|---:|
| capstone-2743 | 0.333 | 0.000 |
| nock-2880 | 0.500 | 0.333 |
| AirbrakesV2-151 | 0.750 | 0.500 |
| hal-cgp-180 | 0.444 | 1.000 |

## Anchoring and tool use

52/87 `intel_first` runs were anchored (59.8%). They made 38 Grep and
11 Glob calls, against 55 and 36 for `native`. Thus agents with the
server still searched less through these tools. Bash can also inspect
files, so Grep and Glob counts do not measure all exploration.

All 87 `suggest_tests` responses contained both `evidence` and `note`.
The strongest evidence was `direct` in 51, `imports` in 12, `indirect`
in 6, `names` in 9, and `none` in 9. Each server-assisted run made exactly
the one required server call. No agent chose an additional server tool.

R4 Stage 1 had 56/87 anchored runs (64.4%); the R6 pilot had 5/18
(27.8%). These are different task sets. R6 has no main-study setup with
the old response, so neither the anchoring difference nor the improved
paired score relative to R4 identifies an effect of the note. The pilot's
low anchoring rate did not carry over to the new tasks.

The `pilot_rule_met: false` field in the main anchoring artifact is not
a main-study failure: that helper reports true only for an 18-run pilot
with at most 6 anchored runs. The main study has its own primary rules.

## Reproducibility and limits

The frozen engine SHA-256 is `509fd11110a1…`; the harness is
`97bcf290ffd4…`. Every frozen engine Python file matches the checkout at
`73826f0`. Before launching and again before scoring, the frozen
manifest, engine, harness, Claude client and runtime/dependency checks
passed. The existing Cargo 1.94.1 under `~/.cargo/bin` was selected to
match the recorded environment. All seven excluded wiring checks
passed. A detached launch ended before recording any trials; the actual
study ran in one persistent command session with two workers and a
50-minute limit.

The scorer uses the preserved
`.claude/worktrees/stage1/eval/metrics.py`, SHA-256 `a40c34c0dec8…`.
The analysis verified complete three-trial pairs before reporting.

This is one model, client and prompt, with a forced first server call.
It measures naming developer-changed test files, which are not an
exhaustive set of relevant tests; it does not measure executing tests,
finding bugs or completing a review. The task pick excludes repositories
with guidance. A 29-task sample and a no-harm margin cleared by only
0.004 warrant a narrow reading.

The study does not meet the rule for a claim that the server improves
agent reviews. It leaves the daily tool-list decision with the user;
no tool-list or ranking default changed.

## Artifacts

In `/Users/eren/Documents/AI/attocode-evals/matrix/studies/`:

- `r6-design.md`, `r6-design.sha256`: the design and its checksum.
- `r6-main_ids.txt`, `r6-main_pick.log`, `r6_pick.py`: the task pick.
- `r6-pilot/`: the pilot, traces and scored outputs.
- `r6-main/manifest.json`, `preparation.json`, `wiring/result.json`,
  `run.log`, `runs/`: frozen inputs, preparation, checks and raw trials.
- `r6-main/runs.jsonl`, `summary.md`, `review.md`: frozen-harness scores.
- `r6-main/paired-score.json`, `anchoring.json`, `r6-analysis.json`:
  the paired result, anchoring result and secondary counts.
- `r4_stage1.py`, `r6_anchor.py`: the predeclared analysis scripts.

The analysis command for this session is
`/private/tmp/r6-finalize-20261013.py`. It refuses an incomplete schedule
and invokes the frozen summary and both predeclared scripts.
