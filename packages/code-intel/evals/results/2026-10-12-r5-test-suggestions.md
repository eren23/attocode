# Study R5: test suggestions on new repositories

**Status: the rule is met, by a small margin. On 383 tasks from 383 new
repositories, `suggest_tests` of attocode-code-intel 0.1.3 had a test
Recall@5 of 0.511. A file-name grep had 0.410 (Δ +0.1003, range +0.063 to
+0.137). The rule needs Δ ≥ 0.10 and a range above 0.** By the design, R4
Stage 1 (the agent review study) can now start. The run also found a crash
at shutdown on 5 large repositories. #166 fixes it.

R5 follows R4. The [R4 results](2026-10-11-agent-r4-stage0.md) give the
background. In R4, we changed the test ranking (#164) with the dev tasks,
and the 56 holdout tasks did not meet the rule (Δ +0.054). After that, all
179 R4 tasks were known. R5 checks the released ranking on tasks that no
earlier study used.

## Rules

We wrote the design before we built the task list and before any run. The
design file is `studies/r5-design.md` in the evals store (sha256
`8edb9704…`). We did not change it after results existed.

- **Tasks.** R1 tasks from SWE-bench Lite, SWE-bench-Live, Loc-Bench and
  PolyBench whose `test_patch` changes 1 to 5 test files that exist at the
  base commit. These files are the gold set. No R4 task, and no
  repository that has an R4 task. From each repository, the task with the
  lowest SHA-256 of its id. This gives 383 tasks from 383 repositories.
- **Arms.** The R4 arms, unchanged.
  - `product`: the first 10 paths of `suggest_tests(files=changed)`,
    attocode-code-intel 0.1.3 from PyPI.
  - `name`: the test files whose file name contains the stem of a changed
    file, in path order.
- **Metric and rule.** The R4 metric (test Recall@5) and the R4 rule:
  `product` 0.10 or more above `name`, with a 95% repository-bootstrap
  range above 0. With one task for each repository, the bootstrap samples
  tasks.
- **Runner and scorer.** `studies/r4_stage0.py` and `studies/r4_score.py`,
  unchanged.
- **Failures.** A task where the product fails keeps an empty `product`
  list. A rerun is allowed only for an infrastructure failure.

The design says that most repositories are Python. That is not correct.
By the main language of the changed files, the 383 tasks are Go 71,
Python 65, Java 43, TypeScript 42, Rust 41, C# 28, JavaScript 28, C++ 12,
C 12, and other 41.

## Result

| | `product` | `name` |
|---|---:|---:|
| Recall@5 | 0.511 | 0.410 |
| Hit@5 | 0.567 | 0.470 |
| Tasks where the arm is higher | 65 | 16 |

- Δ Recall@5 = 192/1915 = +0.1003. The 95% range is +0.063 to +0.137.
- Both arms found no gold file in the first 5 for 151 tasks.
- In the first 5 `product` paths, 170 gold hits had priority 1 (direct
  evidence), 50 priority 2, 18 priority 3 and 18 priority 4 (name only).
- `suggest_tests` gave an empty list for 51 tasks that ran without an
  error.

The margin over the rule is 0.0003. One task more or less for either arm
moves Δ by about 0.003. Thus the result is a pass by the rule, not
evidence of a large gain. The range shows that the gain over the name
grep is real (above 0) on new repositories.

## Failures

6 tasks have `status: failed`. All 6 count against `product`.

- `IBM/sarama-3258`: the patch does not apply at the base commit. Both
  arms are empty.
- 5 tasks crashed with a segmentation fault: `OpenLiberty/open-liberty`,
  `magefree/mage`, `nearai/ironclaw`, `quarkusio/quarkus` and
  `root-project/root`. The `name` arm ran separately for these tasks.

**The crash.** Each `faulthandler` stack shows the same two threads. The
background hydration thread is in `IndexStore.save_references` or
`save_symbols`. The gateway thread is in `IndexStore.close`, from
`OperationGateway._close_stores`. `stop_hydration()` waits for 5 seconds
only. On a very large repository, the hydration thread can still be
inside a write after that time. `close()` did not take the store lock,
so it closed the SQLite connection under the write. The `suggest_tests`
answer existed before the crash, but the crash lost it.

The crash depends on timing. In a later direct run, `quarkus` did not
crash, and its `product` list had the gold test first. With that row,
Δ is about +0.103. The primary result keeps all 5 tasks as failures.

#166 makes `IndexStore.close()` and `VectorStore.close()` wait for the
write in progress. We ran the 5 tasks again with the #166 commit, each
in its own process with `faulthandler`. All 5 ended with exit code 0. In
each run, a background indexer was still running at shutdown (the log
shows "did not stop within 5s"), so the race window was open. In these 5
runs, `product` and `name` had the same Recall@5 on each task. With these
rows in place of the failures, Δ is +0.106. This is an exploratory view,
because the design keeps product failures as misses.

| Task | `product` | `name` |
|---|---:|---:|
| open-liberty-32404 | 1.0 | 1.0 |
| mage-14628 | 0.0 | 0.0 |
| ironclaw-6712 | 0.33 | 0.33 |
| quarkus-49661 | 1.0 | 1.0 |
| root-22854 | 0.0 | 0.0 |

## Runs

- RunPod CPU pod, 256 CPUs. The first run used 24 workers and finished
  374 tasks. Then one worker crashed, and the process pool stopped the 9
  tasks that were still running.
- Second run (same code, 9 workers): 2 more tasks finished, then a worker
  crashed again.
- Third run: each of the 7 remaining tasks in its own process. 2 tasks
  finished. 5 tasks crashed in their own process. This showed that the
  crash comes from these tasks, not from the pool.
- Fourth run: the 5 tasks again, directly with `faulthandler`, to get the
  stacks. 4 crashed and 1 (`quarkus`) finished.

The runs of the 9 tasks after the first pool failure are infrastructure
reruns: the pool failure stopped tasks that did not crash themselves.

## By language and source (exploratory)

The design does not set a rule for these groups. Many groups are small.

| Group | Tasks | `product` | `name` | Δ |
|---|---:|---:|---:|---:|
| Go | 71 | 0.758 | 0.695 | +0.062 |
| Python | 65 | 0.666 | 0.476 | +0.189 |
| Java | 43 | 0.581 | 0.609 | -0.027 |
| TypeScript | 42 | 0.597 | 0.405 | +0.192 |
| Rust | 41 | 0.238 | 0.128 | +0.110 |
| C# | 28 | 0.286 | 0.250 | +0.036 |
| JavaScript | 28 | 0.488 | 0.259 | +0.229 |
| C++ | 12 | 0.333 | 0.250 | +0.083 |
| C | 12 | 0.042 | 0.000 | +0.042 |
| SWE-bench-Live | 318 | 0.476 | 0.400 | +0.076 |
| Loc-Bench | 60 | 0.671 | 0.466 | +0.205 |

- Java is the only group where `name` is higher. 3 of the 5 crashes are
  Java tasks, and each crash counts as a `product` miss.
- In C, C++ and C#, `suggest_tests` often gave an empty list (7 of 12 C
  tasks, 8 of 12 C++ tasks, 6 of 28 C# tasks).
- In Rust, 15 of 69 gold files are not test paths for the test detection
  of code intel, for example source files with inline tests. Neither arm
  can suggest these files. In C, all 19 gold files are test paths, so the
  low recall there has another cause.

## What this does not show

- The gold set holds the tests that the developers changed. Other tests
  can also check a change. Recall is thus a lower bound.
- One task for each repository. The result describes many repositories,
  not the depth of any one.
- The study measures the ranking of `suggest_tests` alone. It does not
  show whether an agent gets better results with it. R4 Stage 1 asks
  that question.

## Next

- R4 Stage 1, by the R4 design: 30 R5 tasks, at most 1 from each
  repository, in hash order. Setups `native` and `intel_first`, 3 trials
  each, 180 runs. The user starts the runs. Before that, the study
  harness needs a `review` mode (`evals/study.py`).
- The empty `suggest_tests` lists in C, C++ and C# are a lead for test
  ranking. A change there needs new tasks to check it, because R5 tasks
  are now known.

## Files

In the evals store (`matrix/studies/`):

- `r5-design.md`, `r5-design.sha256`, `r5_tasks.py`, `r5_breakdown.py`
- `r5/tasks.jsonl` (sha256 `8ecbc32e…`), `r5/results-fresh.jsonl`
- `r5/quarkus-direct.json` (the direct run without a crash)
- `r5/crash5-pr166.jsonl` (the 5 crashed tasks with the #166 commit)
- `r5/logs/`: the stacks of the 4 direct-run crashes, and the error logs of
  the first two runs
