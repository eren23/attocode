# Agent study R4, Stage 0: tests for a change

**Status: The rule for Stage 1 is not met, so no agent runs. On 123 dev
tasks, `suggest_tests` of code intel 0.1.1 had a test Recall@5 of 0.469.
A file-name grep had 0.477 (Δ -0.008, range -0.117 to +0.101).** In 19
tasks, `suggest_tests` failed with `RuntimeError: dictionary changed size
during iteration`. #161 fixes this race. With the fix, the 19 tasks ran,
and Recall@5 was 0.545 against 0.477 (Δ +0.068, range -0.020 to +0.158).
That is also below the rule. By the rule, the next work is better test
ranking, not agent runs.

R4 follows the R3 rule: after the localization studies, test a review
task. The [R3 results](2026-10-10-agent-r3.md) give the background.

## Rules

We wrote these rules before Stage 0 ran, and the user approved them on
2026-10-11. The design file is `studies/r4-design.md` in the evals store
(sha256 `17b80ae0…`). We did not change it after results existed.

- **Question.** When an agent reviews a change, does code intel help it
  name the existing tests that check the change?
- **Tasks.** R1 core-mix tasks whose `test_patch` changes 1 to 5 test
  files that exist at the base commit. These files are the gold set. The
  change is the `patch`, applied to the base commit and not committed.
- **Stage 0 arms.** Each arm gets the changed files of the patch.
  - `product`: the first 10 paths of `suggest_tests(files=changed)`, code
    intel 0.1.1 from PyPI.
  - `name`: the test files whose file name contains the stem of a changed
    file, in path order.
- **Metric.** Test Recall@5: the share of gold files in the first 5 paths.
  Also Hit@5: at least one gold file in the first 5.
- **Rule.** Go to Stage 1 (agent runs) only if `product` Recall@5 on dev
  is 0.10 or more above `name`. Also, the 95% range from a repository
  bootstrap must be above 0. If not, improve test ranking first.
- **Failures.** A task where `suggest_tests` fails keeps an empty
  `product` list. Thus a failure counts against the product.

The design file gives 121 repositories for the 179 core-mix tasks. The
correct count is 100. The dev split has 123 tasks from 78 repositories.

## Setup

- A RunPod CPU pod, 12 workers, one repository group for each worker.
- For each task: a blobless clone at the base commit, `git clean`, then
  `git apply` of the patch. The `product` arm polls `suggest_tests` every
  5 seconds until the index phase is `ready`, for at most 900 seconds.
- Two tasks failed in the first pass because `git clone` failed. We
  removed their rows and ran them again. One task (dubbo-3317) failed
  because its patch does not apply at the base commit. It stays in the
  results as a failure.
- The fix view ran the 19 failed tasks again with the #161 branch. All
  other rows are the same as in the primary view.

The pod ran for about 1.3 hours and cost about USD 1.15.

## Results

| View | Tasks | Failed | `product` R@5 | `name` R@5 | Δ | Range of Δ (95%) | `product` Hit@5 | `name` Hit@5 | Rule met |
|---|---:|---:|---:|---:|---:|---|---:|---:|---|
| Primary (0.1.1) | 123 | 20 | 0.469 | 0.477 | -0.008 | -0.117 to +0.101 | 0.496 | 0.512 | No |
| Fix view (#161) | 123 | 1 | 0.545 | 0.477 | +0.068 | -0.020 to +0.158 | 0.577 | 0.512 | No |

The range comes from 10,000 repository bootstrap draws. In the primary
view, `product` was higher on 18 tasks and `name` on 17. In the fix view,
the counts are 22 and 10.

**Reading.** The primary view is the result of the study. Its Δ is near 0
and its range includes 0. The fix view shows the product as it will ship
in the next release. Its Δ is positive, but it is below 0.10, and its
range includes 0. The race fix does not change the decision.

## Where each arm finds the tests

These counts use the fix view and the 122 tasks that ran. They are leads
for the ranking work, not results of the rule.

| Language of the change | Tasks | `product` R@5 | `name` R@5 | Empty `product` list |
|---|---:|---:|---:|---:|
| Python | 67 | 0.59 | 0.50 | 11 |
| JavaScript/TypeScript | 23 | 0.78 | 0.61 | 3 |
| Java | 12 | 0.31 | 0.51 | 6 |
| Go | 6 | 0.83 | 0.67 | 0 |
| Rust | 6 | 0.17 | 0.00 | 1 |
| C# | 5 | 0.00 | 0.20 | 5 |
| C/C++ | 3 | 0.00 | 0.00 | 3 |
| No code file | 1 | 0.00 | 0.00 | 1 |

- Both arms had a Hit@5 on 53 tasks. Only `product` had one on 18 tasks,
  and only `name` on 10. Neither arm had one on 41 tasks.
- `suggest_tests` gave an empty list on 30 tasks. On 3 more tasks, a gold
  file was at rank 6 to 10 and not in the first 5.
- **Python test folders.** All 7 matplotlib tasks got an empty list. For
  example, the change is `lib/matplotlib/figure.py`, and the gold test is
  `lib/matplotlib/tests/test_figure.py`. The name rules do not look in a
  `tests/` folder next to the source file. The imports do not link either,
  because the resolver does not know the `lib/` source root. Prefect
  (`<package>/tests/test_worker.py`) and pylint (`unittest_misc.py`) are
  similar.
- **Java.** The name rule maps only `src/main/` to `src/test/` with the
  same package. Gold tests in another package (dubbo `version/VersionTest`)
  or in another module (javaparser `javaparser-core-testing`) are not
  found.
- **C# and C/C++.** `suggest_tests` has no name rule for these languages,
  so it found no test in 8 tasks.
- **Neither arm.** Many of the 41 tasks have gold tests whose name does
  not contain a changed stem. For example, a change to `figure.py` has the
  gold test `test_constrainedlayout.py`. Only import or reference evidence
  can find these.
- **The `name` arm.** Its list also holds files that are not tests, such
  as baseline images below `tests/`. These files fill some of its first 5
  places.

## What this does not show

- The gold set holds the tests that the developers changed. Other
  existing tests can also check the change. Recall is thus a lower bound,
  and the study does not measure precision.
- The `name` arm is a strong baseline for this gold set. Developers often
  change the test file that has the name of the source file.
- Stage 0 measures the tool output only. It does not show how an agent
  uses that output.
- We now know the dev tasks. A ranking change that we tune on them needs
  a check on tasks that we did not look at.

## Next

1. Release the race fix (#161) as code intel 0.1.2.
2. Improve test ranking. Close the name-rule gaps above: a `tests/`
   folder next to the source, Java packages and modules, C# and C/C++.
   When the graph gives no test, use file-name matches as a fallback.
3. Measure the change on the dev tasks, then once on the 56 holdout
   tasks. The holdout tasks have not run yet, so they stay a clean check.
   Stage 1 runs only if the change meets the rule.
