# Agent study R4, Stage 1: agents name the tests for a change

**Status: no evidence that the server helps a review. On 29 tasks, with 3
trials each, `intel_first` had a test Recall@5 of 0.602 and `native` had
0.700 (Δ -0.097, range -0.220 to +0.002). The rule needs Δ ≥ 0.05 and a
range above 0.** The difference points against the server, and the range
almost excludes 0. The agents with the server explored less and often
named only the tests that `suggest_tests` gave.

Stage 1 follows the R4 design (`studies/r4-design.md` in the evals
store). Stage 0 measured `suggest_tests` alone. R5 then met the rule on
383 new tasks (Δ +0.1003, see the [R5 results](2026-10-12-r5-test-suggestions.md)).
Stage 1 asks if an agent reviews a change better with the server.

The first complete study (180 runs) is not valid, because of a harness
bug. This document gives the result of the rerun. The section
[Studies that do not count](#studies-that-do-not-count) gives the
reasons.

## Rules

From the R4 design, written before Stage 0:

- **Setups.** `native`: Read, Grep, Glob and Bash. `intel_first`: the
  same tools and the code intel server (daily list). The prompt of
  `intel_first` asks for `git diff --name-only` and then one
  `suggest_tests` call with those files. After that, the agent chooses
  its tools.
- **Model and client.** Claude Code 2.1.287 with `claude-sonnet-5-5`.
- **Trials.** 3 for each task and setup.
- **Prompt.** `REVIEW_PROMPT_V2`: "Review the uncommitted change in this
  repository. Name the existing test files that a reviewer must run to
  check this change, best first, at most 10. Do not run tests and do not
  edit files. Bash runs only read-only commands, such as `git diff`.
  Return JSON with a `tests` list of repository-relative paths."
- **Metric.** Test Recall@5 of each task, as the mean of its 3 trials.
  The result is the mean paired difference (`intel_first` minus
  `native`), with a 95% range from a repository bootstrap. Each task
  comes from its own repository, so the bootstrap samples tasks.
- **Reading.** A range above 0 and a mean difference of 0.05 or more
  show that the server helps a review. A range that includes 0, or a
  mean difference below 0.05, shows no evidence of help.

Changes to the design, all before any run of the study that counts:

- **Task pick.** The design asks for 30 R5 tasks in hash order. The study
  harness refuses a repository with its own agent guidance (a `.claude`
  folder, `AGENTS*.md`, `CLAUDE*.md`, `.mcp.json` or
  `.codex/config.toml`). 10 of the first 30 tasks have such a file. The
  pick (`studies/r4_stage1_pick.py`) thus takes the first 30 tasks in
  hash order whose base tree has none of these files. It reads each tree
  from the GitHub API. It uses no result of any study.
- **Bash.** The design gives Bash "for `git diff` only". Claude Code runs
  read-only commands, such as `ls` and `git diff`, without a permission
  rule, also in `dontAsk` mode. It denies other commands, for example a
  test run or a file write. The wiring check found this (#169). Read-only
  Bash gives no new access: Read, Grep and Glob already read every file.
- **Rerun.** The first complete study was not valid (see below). We
  decided before the rerun that the rerun gives the result.

## Result

Study `r4-stage1d`: engine and harness from `main` at `569aede`
(attocode-code-intel 0.1.4). The harness excluded 1 task: the index of
`wasm-bindgen-5051` was not ready in 30 minutes. Thus 29 tasks and 174
runs. No run failed.

| | `intel_first` | `native` |
|---|---:|---:|
| Recall@5 | 0.602 | 0.700 |
| Hit@5 | 0.690 | 0.782 |
| Tasks where the setup is higher | 3 | 6 |
| Median cost for each run (USD) | 0.0230 | 0.0214 |
| Median seconds | 10.1 | 8.1 |
| Median turns | 5 | 5 |

- Δ Recall@5 = -0.097. The 95% range is -0.220 to +0.002.
- The mean cost of `intel_first` was 0.92 times the mean cost of
  `native`.
- 20 of 29 tasks had the same score in both setups.
- No `suggest_tests` result showed a gold test that the agent then did
  not name.

## Why the server setup scored lower (exploratory)

The design sets no rule for this section.

- **The agents took the list of the tool.** In 56 of 87 `intel_first`
  runs, all answer paths in the first 5 came from the `suggest_tests`
  output.
- **The agents searched less.** In 87 runs, `intel_first` agents called
  Grep 20 times and Glob 7 times. `native` agents called Grep 40 times and
  Glob 30 times.
- **The losses came where the tool had no answer.** `native` was higher
  on 6 tasks. On 4 of them (`libavif`, `BootstrapBlazor`, `helidon`,
  `kueue`), `suggest_tests` in R5 had no gold test in its first 5. On
  these 4 tasks, `native` had Recall@5 1.00 and `intel_first` had 0.00
  to 0.67.
- **The agents were better than the tool alone.** On the same 29 tasks,
  `suggest_tests` alone (R5) had Recall@5 0.463, and the file-name grep
  had 0.311. `native` agents had 0.700.

The forced first call thus did not add a missing test. It gave the agent
a list that the agent did not check further.

## Tool use

The `intel_first` agents called no server tool other than the required
`suggest_tests`. This is also true for the invalid study. The design makes
this tool use the evidence for the cut of the daily list. The user
decides the cut.

## Studies that do not count

A frozen study keeps its task list and its harness. Each change thus
needed a new frozen study.

| Study | What happened |
|---|---|
| `r4-stage1` | The first pick by hash order. 10 of its 30 tasks have agent guidance files, and the harness excluded all 10. No runs. |
| `r4-stage1b` | The new pick. The wiring check failed: Claude Code ran `ls` without a rule (#169). No scored runs. |
| `r4-stage1c` | 180 runs. Not valid, because of the bug below. |
| `r4-stage1d` | The result above. |

**The bug in `r4-stage1c`.** The harness applied each change with
`git apply --intent-to-add`. With Git 2.50.1 on macOS, this command
writes an index that holds only the changed files. In each trial:

- `git diff` showed each changed file as a new file with all of its lines,
  not the edit. `git diff --name-only` still gave the correct names.
- `git status` showed every other file as deleted and untracked.
- `git ls-files` listed only the changed files. The `suggest_tests` name
  finder reads `git ls-files`. Its output in the trials contained 50 of
  the 75 paths that it gave first in R5.

Both setups had the same broken repository, but the bug harmed the tool
more than the agent. `r4-stage1c` gave Recall@5 0.615 in both setups
(Δ 0.000, range -0.124 to +0.123). We do not use this number. The R4
Stage 0 and R5 runner uses plain `git apply`, so those results are not
affected. #170 fixes the harness and adds a test that fails with the old
command.

`r4-stage1c` also stopped one session early. A diff in the `gleam` task
quotes "rate limit exceeded", and the quota check also read tool results.
#170 fixes this too.

## What this does not show

- One model, one client version, one prompt and one task type.
- `intel_first` forces one call. The study has no setup where the agent
  alone decides to call the server. In R2 and R3, agents seldom called it
  on their own.
- The gold set holds the tests that the developers changed. Other tests
  can also check a change. Recall is thus a lower bound.
- 29 tasks give a wide range (about ±0.11). The study can miss a small
  gain or a small loss.
- The pick excludes repositories with agent guidance files, about a third
  of the R5 tasks in hash order.
- The preparation of the last task ran during the first session, on the
  same Mac. This can change the seconds, not the answers.

## Next

- By the design, the server gives no measured help to an agent that
  names the tests for a change. With R3 (localization), this is the
  second agent task without a gain.
- The losses suggest a product lead: when `suggest_tests` has no strong
  evidence, it can say so, so that the agent keeps searching. A change
  needs new tasks to check it, because the R5 tasks are now known.
- The cut of the daily list is the user's decision. No agent in R4
  called a server tool that the prompt did not require.

## Files

In the evals store (`matrix/studies/`):

- `r4-design.md`: the design.
- `r4_stage1_pick.py`, `r4-stage1_pick.log`, `r4-stage1_ids.txt`: the
  pick (`r4-stage1_ids.first.txt`: the first pick).
- `r4_stage1.py`: the paired score (`--check` runs its self-test).
- `r4-stage1-start.sh`: the start script (wiring check, then trials).
- `r4-stage1d/`: the study, with `runs.jsonl`, `summary.md` and
  `review.md`.
- `r4-stage1c/`: the invalid study, kept for the record.
