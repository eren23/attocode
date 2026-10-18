# Test intent for "tested" questions (2026-10-17)

The previous batch rejected "tested" test intent. It found the test file but
pushed the implementation file out of the page. This batch tests a test-intent
order that keeps both files. One candidate (T3) met every predeclared rule on
new frozen questions and ships. The first form (T2) failed on development.

| Id | Change |
| --- | --- |
| T2 | Test intent also recognizes "tested" and "testing". For a short test search, test hits still go first, but the best source hit moves to second place. |
| T3 | Short queries with "test" or "tests" keep the current order: test hits first. Short queries with "tested" or "testing" (and no "test" or "tests") keep the default source-first order and file diversity, and the best test hit moves to second place. |

T3 changes only `demote_tests` in `query_ranking.py`. Candidate generation and
the delivery of every other query do not change.

## Questions

The [validation set](../designs/2026-10-17-test-source-slot-validation.json)
has 16 new questions on four pinned packs that no earlier trial used:
aspnetcore (C#), luarocks (Lua), zls (Zig) and otp (Erlang). Each pack has
one exact-symbol control and three test questions. The three test questions
use "tested", "tests" and "test" once each. Each test question has two
labels: the test file and the implementation file.

We declared three disjoint subsystems per pack before we wrote any question
and before any search on these packs. Source-reading subagents drafted the
questions without search. Before we wrote any luarocks question, we replaced
one declared subsystem (`vers.lua`) with `fun.lua`, because `vers.lua` has no
spec. The [freeze record](../designs/2026-10-17-test-source-slot-freeze.json)
holds the acceptance rules. We wrote it before the first search on these
packs.

The [development set](../designs/2026-10-17-test-source-slot-development.json)
merges 68 consumed questions from five earlier sets on ten packs. It is not
fresh evidence. We changed the candidate on development only. The
[candidate record](../designs/2026-10-17-test-source-slot-candidate.json)
binds the T3 patch and engine hash. We wrote it before the one validation run.

Every observation is the real daily MCP delivery: 5, 24 and scoped results,
2,000 tokens, auto mode. A supervisor bounded each pack run to 180 seconds,
512 MiB of disk and 1.5 GiB RSS. No run used a model, a download or a cloud
worker.

## Results

Judged files found at 5, 24 and scoped, visible quotes at 5 and inspection
quotes. B is `main` (`77dc6fd`).

| Set | Arm | Files 5 / 24 / scoped | Visible 5 | Inspection | Individual losses |
| --- | --- | --- | --- | --- | --- |
| Development (68) | B | 69 / 81 / 66 | 21 | 12 | |
| | T2 | 71 / 85 / 66 | 22 | 12 | 5 |
| | T3 | 73 / 85 / 66 | 23 | 12 | 0 |
| Validation (16) | B | 14 / 16 / 16 | 8 | 4 | |
| | T3 | 16 / 18 / 16 | 9 | 4 | 0 |

A loss counts each judged file or quote that B delivered and the arm did not,
per page. Every candidate run kept every control and every question
without a test word identical to B on every page. Candidate generation was
identical for every question.

T3 meets every frozen validation rule:

- `compare` passes. The p95 latency goes from 0.236 to 0.296 seconds, under
  the limit of 0.353 seconds.
- No individual judged file or visible quote is lost at 5, 24 or scoped.
- Judged files at 5 go from 14 to 16. The gains are in two packs:
  `MultipartReaderTests.cs` (aspnetcore) and `fun_spec.lua` (luarocks, with
  its visible quote). Both move into the second slot.

## Why T2 fails

T2 lost five judged items on development:

- On three "Find tests ..." questions, both labels are test files. The
  source hit in slot 2 pushed a labeled test file, or its visible quote, out
  of the first five.
- On one ggplot2 "tested" question, the labeled source `R/stat-bin.R` was the
  third source hit. T2 put tests first, so `stat-bin.R` left pages 5 and 24.

T3 leaves "test" and "tests" queries unchanged, so the "Find tests ..."
questions cannot lose. For "tested" and "testing" it keeps the default
source order and adds one test hit in slot 2. On the first page, only the
previous fifth hit leaves.

## Limits

- T3 helps only "tested" and "testing" questions. On the 8 validation
  questions with "tests" or "test", the order does not change. B and T3 both
  find 0 of their 8 implementation labels at 5, because test hits fill the
  first page. T2 tried to fix this and lost judged test files on development.
- T3 moves the best test hit, not the judged test. On zls and otp, the best
  test hit was another file, so these questions did not gain.
- `is_test_path` does not recognize the Swift `Tests/` folder or
  `*Tests.swift` names. The SwiftFormat test questions therefore cannot
  change. This batch does not fix that.
- The labels are author-written, source-bound and not exhaustive. They are
  not user or agent outcomes. The latency numbers are descriptive.
- All 16 validation questions are now consumed.

## Runs

We made 60 supervised pack runs:

- 20 development runs (B and T2) in a first attempt. That attempt copied the
  shell environment, so precision language servers were on. Two ripgrep runs
  stopped at the 1.5 GiB RSS bound. We kept these records and excluded them.
  The earlier file-coverage batch used the same environment copy.
- 20 development runs (B and T2) with the standard bounded environment. The
  host slept during both SwiftFormat runs (wall time 705 and 912 seconds for
  4 and 12 measured seconds). We kept these records and ran SwiftFormat again
  in both arms.
- 10 development runs of T3 and 8 validation runs of B and T3.

All 38 runs in the results passed inside the bounds. The largest RSS was
588 MiB and the largest disk use was 331 MiB.

## Artifacts

- [Decision record](2026-10-17-test-source-slot-decision.json): `compare()`
  output for every arm and set, identity checks, rule outcomes and hashes.
- [Observations](2026-10-17-test-source-slot-observations.json.gz): the 38
  observations in the results. This file omits the per-stage generation lists
  for size. The private full observations confirm generation identity.
- Candidate patches: [T2](../designs/2026-10-17-test-source-slot-t2.patch.gz)
  and [T3](../designs/2026-10-17-test-source-slot-t3.patch.gz). The shipped
  source is byte-identical to the measured T3 arm.
- `test_test_source_slot_decisions_replay_from_hash_bound_observations`
  recomputes every comparison and identity check from these files.
- `test_tested_question_keeps_source_order_and_shows_best_test_second` checks
  the new order.
