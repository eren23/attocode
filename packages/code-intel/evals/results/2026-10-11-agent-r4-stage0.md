# Agent study R4, Stage 0: tests for a change

**Status: The rule for Stage 1 is not met, so no agent runs. On 123 dev
tasks, `suggest_tests` of code intel 0.1.1 had a test Recall@5 of 0.469.
A file-name grep had 0.477 (Δ -0.008, range -0.117 to +0.101).** In 19
tasks, `suggest_tests` failed with `RuntimeError: dictionary changed size
during iteration`. #161 fixes this race. With the fix, the 19 tasks ran,
and Recall@5 was 0.545 against 0.477 (Δ +0.068, range -0.020 to +0.158).
That is also below the rule. By the rule, the next work is better test
ranking, not agent runs.

**Update after the ranking change (#164): the holdout check also does not
meet the rule.** On the 56 holdout tasks, `suggest_tests` had Recall@5
0.640 and the name grep 0.586 (Δ +0.054, range -0.047 to +0.167). On the
dev tasks, which we used to make the change, Δ was +0.213. Thus no agent
runs. The section [After the ranking change](#after-the-ranking-change)
gives the details.

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

## After the ranking change

The user approved these steps on 2026-10-11 (`studies/r4-addendum.md` in
the evals store). Because we used the dev results to make the change, the
holdout tasks decide. Each holdout task ran once, with the final version.

- **Change.** PR #164 at commit `381ece4`. `suggest_tests` finds tests by
  name in the whole repository, and any folder that holds a top-level
  Python package is an import root.
- **Setup.** The same script, arms and metric, on a new RunPod CPU pod
  (128 CPUs). Dev and holdout ran at the same time, with 12 workers each.
  The pod ran for about 0.5 hours and cost about USD 0.45.
- **Two record-only fields.** `product_detail` holds the priority of each
  candidate. `name_v011` is the name grep with the test detector of 0.1.1.
  The `name` arm uses the detector of the installed version, and #164 adds
  .NET, C# and C/C++ test names to it.

| Set | Tasks | Failed | `product` R@5 | `name` R@5 | Δ | Range of Δ (95%) | `product` Hit@5 | `name` Hit@5 | Higher / lower | Rule met |
|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---|
| Dev (tuning) | 123 | 1 | 0.694 | 0.481 | +0.213 | +0.139 to +0.286 | 0.740 | 0.520 | 33 / 1 | Yes |
| Holdout (decides) | 56 | 1 | 0.640 | 0.586 | +0.054 | -0.047 to +0.167 | 0.696 | 0.625 | 6 / 3 | No |

With the 0.1.1 detector, the name grep had 0.477 on dev and 0.580 on the
holdout. The Δ changes by less than 0.01. Each set has one task whose
patch does not apply at the base commit (dubbo-3317 and dubbo-4678).

**Reading.** On dev, `suggest_tests` improved on 21 tasks against the fix
view, and no task got worse. All 7 matplotlib tasks had no test before.
After the change, their Recall@5 is 0.50. On the holdout, the gain is
small, and the range includes 0. By the rule, this is no evidence that
the product names the tests for a change better than a file-name grep.
The name grep is strong on the holdout. Both arms had a Hit@5 on 33 of
55 tasks, because the developers changed the test that has the name of
the source file.

**Holdout misses.** These are leads only. The holdout tasks cannot check
a fix for them.

- `suggest_tests` found no test on 8 tasks.
- In coreutils, the changed file is `src/uu/cp/src/cp.rs`. The name
  finder skips names with fewer than 3 letters, so it did not find
  `tests/by-util/test_cp.rs`.
- In grommet and decap-cms, the gold set holds a Jest snapshot file
  (`.snap`). `suggest_tests` gives only test source files, and the name
  grep also gives data files.

## Next

1. Merge #164 as a product change. Its claims are the numbers above, not
   a measured gain on new tasks.
2. No R4 agent runs. This also gives no new evidence for the cut of the
   daily tool list.
3. Any new test-ranking study needs new tasks, because we know the results
   of all 179 tasks now.

**Update (2026-10-12): R5 checked the released ranking (0.1.3) on 383 new
tasks and met the rule (Δ +0.1003).** By the R4 design, Stage 1 can now
start, on R5 tasks. See the [R5 results](2026-10-12-r5-test-suggestions.md).

**Update (2026-10-12): Stage 1 found no evidence that the server helps a
review (Δ -0.097, range -0.220 to +0.002, 29 tasks).** See the
[Stage 1 results](2026-10-12-r4-stage1-review-agents.md).
