# Agent pilot R2: Claude Code with and without code-intel search

**Status: On 29 file-localization tasks, Claude Code (Sonnet 5.5) with
Read, Grep and Glob gave file Acc@5 0.655 to 0.690. The code-intel MCP
server did not change Acc@5 in two studies. It made each run 1.8 to 2.1
times as expensive and 2 to 8 seconds slower. When the agent could choose,
it called the server in 4 of 58 runs. Thus, for this task, the server adds
cost and gives no measured gain.** Our offline search has an Acc@5 hit on 9
of the 29 tasks. The agent with grep has one on about 20 tasks. The agent
also has a hit on every task where our search has an Acc@10 hit. An
enriched study then used 29 tasks where our search finds the files and the
`grep` arm does not. The server again gave no Acc@5 gain (0.793 in both
setups), and each run cost 1.84 times as much.

## What we ran

- **Task.** `PROMPT_V1` of `localize_study.py`. The agent gets the issue
  text and names at most 10 files that a fix must edit, most likely first.
  It cannot edit files or run code.
- **Isolation.** A history-free snapshot of each repository, a fresh copy for
  each trial, read-only tools, no hooks, no memory and no other MCP servers.
  The timeout is 600 s. A wiring check confirmed that the guidance loads,
  the home instructions do not load, the MCP server answers and the agent
  cannot write files.
- **Model.** `claude-sonnet-5-5` in Claude Code 2.1.287, on the subscription.
- **Tasks.** 29 tasks from 27 repositories of the R1 core mix: Loc-Bench 10,
  the graded blind pack 6, PolyBench 6, SWE-bench-Live 5 and LCA 2. They
  cover ten languages. A 30th task had a `.claude` folder in its snapshot,
  so the study excluded it.
- **Setups.**

| Setup | Tools |
|---|---|
| `native` | Read, Grep and Glob |
| `intel` | the same tools, the code-intel MCP server (daily profile) and its guidance |
| `intel_first` | as `intel`, and the prompt tells the agent to call `semantic_search` first |
| `issue_only` | no tools: the control for answers that the model knows already |

- **Studies.** Both studies use the same 29 tasks.

| Study | Date | Product source | Setups | Trials | Runs |
|---|---|---|---|---:|---:|
| Batch 1 (`r2-pilot`) | 2026-10-09 | `1386961`, before #133 | all four | 2, and 1 for `issue_only` | 203 |
| R2b (`r2b`) | 2026-10-10 | `72872ed` (#133) | `native`, `intel_first` | 1 | 58 |

With #133, the first search waits up to 15 s for the index. R2b used it to
remove the main fault of batch 1 (see "Index build"). Neither study has #135,
the smaller tool list. R2b froze 2 trials and ran the first one only.

## Results

| Study | Setup | Acc@5 | Runs with MCP calls | First search had no index | Median s | Median cost (USD) | Median cache-read tokens |
|---|---|---:|---:|---:|---:|---:|---:|
| Batch 1 | `native` | 0.690 | 0 / 58 | | 6.3 | 0.0165 | 14,094 |
| Batch 1 | `intel` | 0.672 | 4 / 58 | | 8.3 | 0.0298 | 49,438 |
| Batch 1 | `intel_first` | 0.672 | 58 / 58 | 55 / 58 | 9.6 | 0.0358 | 67,259 |
| Batch 1 | `issue_only` | 0.586 | | | 3.0 | 0.0079 | 1,610 |
| R2b | `native` | 0.655 | 0 / 29 | | 5.5 | 0.0185 | 13,823 |
| R2b | `intel_first` | 0.724 | 29 / 29 | 9 / 29 | 14.2 | 0.0375 | 51,422 |

Paired with `native` on the same tasks. The task is the unit. The cost is a
geometric mean ratio. p is a sign-flip p-value over repositories, with the
Holm correction in each study. MDE is the smallest ΔAcc@5 that the test
finds with 80% power.

| Study | Setup | ΔAcc@5 | Higher / lower | p (Holm) | MDE | Cost | Δ seconds |
|---|---|---:|---:|---:|---:|---:|---:|
| Batch 1 | `intel` | -0.017 | 0 / 1 | 1.00 | 0.048 | ×1.77 | +1.7 |
| Batch 1 | `intel_first` | -0.017 | 1 / 2 | 1.00 | 0.084 | ×2.08 | +3.7 |
| R2b | `intel_first` | +0.069 | 2 / 0 | 0.51 | 0.137 | ×2.07 | +8.3 |

All cost ratios and time differences have p 0.0002 or lower.

- **Index build.** In batch 1, the first search of `intel_first` found no
  index in 55 of 58 runs. Thus batch 1 did not measure search results. In
  R2b, this occurred in 9 of 29 runs, for example on matplotlib, meson,
  sqlite, gwt and prettier.
- **Cause of the missing index.** The cause was the harness, not only the
  size of the repository. Its warm-up waited for the symbol index and saved
  no keyword or body index of search. Thus the first search of each run
  built these indexes, and in 9 runs the build took more than the 15 s
  wait. On the crystal snapshot (2,558 files), the fixed warm-up takes 45 s.
  A later harness fix saves these indexes (follow-up 3).
- **The two R2b gains are not clear search gains.** On gocd (LCA), the
  search had no index, and it gave no results. On rocketmq (PolyBench), the
  search had results. But `native` found the files of each task in 1 of
  its 2 batch 1 trials, and `issue_only` found the rocketmq files with no
  tools.
- **Warm search.** In the 20 R2b runs where the search had an index,
  `intel_first` gave Acc@5 0.70 against 0.65 for `native` on the same tasks.
  The median time was 10.6 s against 5.5 s, and the median cost ratio was
  ×1.81.
- **Adoption.** When the agent could choose (`intel`), it called the server
  in 4 of 58 runs.
- **Cost.** The median `intel` run read about 35,000 more tokens from the
  prompt cache than the median `native` run, but `intel` seldom called the
  server. Thus the tool
  list and the guidance cause most of the cost, not the tool results. Every
  model call reads them again, and a localization run has 4 or 5 turns.
- **Known answers.** With no tools, `issue_only` gave Acc@5 0.586. The model
  knows many of these repositories, and the issue text often names the files.

## Offline search against the agents

The table counts the 29 tasks. The rows use the R1 `product` list on the
full issue. A `native` hit is a mean Acc@5 of 0.5 or more over the batch 1
trials.

| R1 `product` | `native` hit | `native` miss |
|---|---:|---:|
| Acc@10 hit | 10 | 0 |
| Acc@10 miss | 11 | 8 |

- `native` has a hit on every task where our search has an Acc@10 hit.
- Of the 8 tasks that `native` misses, 4 have one or more gold files in the
  first 10 of our search. Thus a forced first search can change the result of a few
  tasks at most.
- The offline reciprocal rank and the agent Acc@5 correlate weakly:
  Spearman 0.24 to 0.34 for the tool setups.

## Size of the tool list

The first model call of a run shows the size of the prompt. In both
studies, the median first call had 16,958 to 16,976 tokens with the server
and 4,881 to 4,883 tokens without it. Thus the server added about 12,100
tokens to each call. The table counts the characters of what the server
sends: its tool definitions, its instructions, and the project guidance
that its installer writes.

| Product source | Tools | Descriptions | Input schemas | Instructions | Guidance | Tokens |
|---|---:|---:|---:|---:|---:|---:|
| `1386961` and `72872ed` (both studies) | 24 | 11,361 | 16,006 | 1,051 | 1,122 | 12,100, measured |
| `92b9d87` (main, after #135) | 19 | 9,462 | 10,185 | 1,051 | 1,122 | about 8,900 |

- The estimate for main uses the characters per token of the measured row
  (2.44). A run with the main engine gives the exact value.
- On main, the input schemas are 52% of the characters of the tool list.
  The five largest tools are `inspect_symbol`, `fast_search`, `bootstrap`,
  `semantic_search` and `cross_references`: 41% of the tool list.

## Enriched study

In the pilot, offline `product` had an Acc@5 hit on 9 of the 29 tasks, so
our search had few chances to help. The enriched study (`r2-enriched`,
2026-10-10) used tasks where our search should help.

- **Tasks.** The R1 core mix has 42 issues where `product` has an Acc@10
  hit and the `grep` arm does not. The study took at most one issue from
  each repository: all 13 issues that are not in Python, and 17 Python
  issues in hash order. The harness excluded the fluent-bit snapshot,
  because it holds client guidance files. 29 tasks in six languages
  remain: Loc-Bench 12, SWE-bench-Live 5, LCA 4, SWE-bench Lite 4 and
  PolyBench 4. Two of them are also pilot tasks.
- **Setups.** `native` and `intel_first`, one trial each. The product
  source is main `d126521`, with #135, #141 and #143. The harness has the
  warm-up fix of follow-up 3.

| Setup | Acc@1 | Acc@5 | R@10 | Runs with MCP calls | First search had no index | Median s | Median cost (USD) |
|---|---:|---:|---:|---:|---:|---:|---:|
| `native` | 0.897 | 0.793 | 0.885 | 0 / 29 | | 5.3 | 0.0156 |
| `intel_first` | 0.897 | 0.793 | 0.879 | 28 / 29 | 0 / 28 | 6.5 | 0.0285 |

Paired with `native`, `intel_first` gave ΔAcc@5 +0.000: 1 task higher and
1 lower, range -0.103 to +0.103, MDE 0.137. The cost ratio was ×1.84
(×1.57 to ×2.14, p 0.0001). The time difference was +1.2 s (p 0.11), and
the agent used 0.6 fewer turns (p 0.13).

- **The warm-up fix works.** No search reply reported a warming index,
  against 9 of 29 runs in R2b.
- **The search found the files, but the agent found them without it.** The
  first search had all gold files in its first five results on 18 of 29
  tasks, and one or more gold files on 26. Both setups had an Acc@5 hit on
  23 tasks. The `grep` arm runs one search for each term of the issue. The
  agent reads the issue and searches again after each result. Thus a miss
  of the arm does not show a miss of the agent.
- **Offline scores do not predict the agents.** The Spearman correlation of
  the offline reciprocal rank (R1 rows) and agent Acc@5 was -0.03 for
  `native` and -0.20 for `intel_first`.
- One `intel_first` run (pydantic) did not call the server.

## What this does not show

- With 29 tasks, the MDE of ΔAcc@5 is 0.05 to 0.14. A smaller effect can
  exist.
- One model, one client version and one task: name the files to edit. A
  longer task, such as a fix or a review, can use the server differently.
  In a longer task, the fixed cost of the tool list is a smaller part of
  the total.
- Batch 1 and R2b do not have #135 (the smaller tool list), #141 (plural
  words) or #143 (test files last). The enriched study has all three.
- R2b and the enriched study ran one trial for each task and setup. The
  enriched study has no `issue_only` control.

## Follow-ups

1. Product: make the first search ready sooner on medium repositories.
   While the index builds, tell the agent to use grep.
2. Product: the daily profile on main still adds about 8,900 tokens to
   each call. Make the input schemas and the largest descriptions shorter,
   or remove tools that the agents do not use.
3. Harness: save the search indexes in the warm-up. Done after this note:
   the warm-up now waits until a search reports ready indexes. On the
   crystal snapshot, the first search of a new server then answered in
   0.8 s with results, against 15 s with no results in R2b.
4. A study of tasks where search should help. In 76 tasks of the R1 core
   mix, `product` has an Acc@10 hit and the `grep` arm does not. 42 of
   these tasks are issues from 37 repositories. Done: see "Enriched
   study". The server gave no Acc@5 gain on these tasks either.
5. Choose tasks from agent misses, not from misses of the `grep` arm. For
   example, use the tasks that `native` missed in these studies, or issues
   without code identifiers. Search can add accuracy only where the agent
   with grep fails.

## Reproduce

The study folders are under `~/Documents/AI/attocode-evals/matrix/studies/`.
Each folder keeps the frozen engine, the harness, the transcripts,
`runs.jsonl`, `summary.md`, `review.md` and `agents-report.md`. The task ids
are in `studies/pilot_ids.txt`. Each trial needs a quota file that is at
most one hour old. The user writes it.

```bash
M=~/Documents/AI/attocode-evals/matrix
ST=$M/studies/r2b
python packages/code-intel/evals/study.py freeze --mode localize --project CHECKOUT_OF_72872ED \
  --instances $M/runs/r1/instances.jsonl --ids $M/studies/pilot_ids.txt --model claude-sonnet-5-5 \
  --trials 2 --setups native intel_first --study $ST
python packages/code-intel/evals/study.py prepare --study $ST
python packages/code-intel/evals/study.py wiring --study $ST --quota $M/studies/r2-quota.json
(cd $ST && PYTHONPATH=$ST/engine python $ST/harness/study.py run --study $ST \
  --quota $M/studies/r2-quota.json --jobs 2 --deadline-minutes 50)
python $ST/harness/study.py summary --study $ST
python -m eval.matrix.agents $ST --instances $M/runs/r1/instances.jsonl --matrix $M/runs/r1-core \
  --output $ST/agents-report.md
```

The plain `run` command runs both frozen trials. For the first trial only,
R2b used a wrapper. The wrapper replaced the schedule with its rows of
repeat 0, after `load()` checked the hashes of the manifest and the harness.
Batch 1 used the default setups (all four) and the product source of
`1386961`.

For the enriched study:

```bash
ST=$M/studies/r2-enriched
PYTHONPATH=. python $M/studies/pick_enriched.py  # writes studies/enriched_ids.txt
python packages/code-intel/evals/study.py freeze --mode localize --project CHECKOUT_WITH_THE_WARM_UP_FIX \
  --instances $M/runs/r1/instances.jsonl --ids $M/studies/enriched_ids.txt --model claude-sonnet-5-5 \
  --trials 1 --setups native intel_first --study $ST
python packages/code-intel/evals/study.py prepare --study $ST
bash $ST/start.sh  # the wiring check, then all runs in the background with nohup
```

Then write `summary` and `agents-report.md` as for R2b.
