# Paired source for "test" questions (2026-10-18)

A short search with "test" or "tests" puts test hits first. On earlier
frozen questions, this order found 0 of 8 implementation labels at five.
This batch tests one way to keep the implementation file on the page: put
the source file that the best test hit is named for in second place. The
candidate (P) met every development rule. On new frozen validation
questions, it changed no judged result, so it does not ship. The search
code does not change.

| Id | Change |
| --- | --- |
| P | Short queries with "test" or "tests" keep test hits first. If the best test hit has a test affix (`FooTest.java`, `test_foo.py`, `foo_spec.rb`) and a source hit in the pool has that name, the source hit moves to second place. |
| Pf | Like P, but a test file without a test affix also pairs by its own name (`tests/lsp/folding_range.zig` with `src/folding_range.zig`). |

Both candidates change only `demote_tests` in `query_ranking.py`. Candidate
generation and the delivery of every query without "test" or "tests" do
not change.

## Questions

The [validation set](../designs/2026-10-18-paired-source-validation.json)
has 16 new questions on four pinned packs that no earlier trial used:
crystal (Crystal), dart-sdk (Dart), postgrest (Haskell) and ring (Clojure).
Each pack has three test questions and one exact-symbol control. The three
test questions use "Which tests cover X?", "Where is the test for X?" and
"Find the tests for X". Each test question has two labels: the test file
and the implementation file.

We did not choose the test files. A seeded shuffle drew three test files
per pack, from distinct folders, before we wrote any question and before any
search on these packs. The first draw used `*_test.clj` for ring and found
no file, because Ring keeps tests as `test/.../test/*.clj`. We corrected the
rule before we wrote any question. The other packs drew the same files. The
manifest records the seed, the method and both draws.

Source-reading subagents then picked one test case per drawn file and found
the code that it exercises, without search. We checked every line and quote
against the pinned source. The
[freeze record](../designs/2026-10-18-paired-source-freeze.json) holds the
acceptance rules. We wrote it before the first search on these packs.

The [development set](../designs/2026-10-18-paired-source-development.json)
merges 84 consumed questions on 14 packs: the 68 development questions and
the 16 validation questions of the previous batch. It is not fresh
evidence. We changed the candidate on development only. The
[candidate record](../designs/2026-10-18-paired-source-candidate.json) binds
the P patch and engine hash. We wrote it before the one validation run.

Every observation is the real daily MCP delivery: 5, 24 and scoped results,
2,000 tokens, auto mode. A supervisor bounded each pack run to 180 seconds,
512 MiB of disk and 1.5 GiB RSS. No run used a model, a download or a cloud
worker.

## Results

Judged files found at 5, 24 and scoped, visible quotes at 5 and inspection
quotes. B is the head of #235 (`d33dd08`), which adds Swift test folders to
`main` (`25f7540`).

| Set | Arm | Files 5 / 24 / scoped | Visible 5 | Inspection | Individual losses |
| --- | --- | --- | --- | --- | --- |
| Development (84) | B | 90 / 104 / 82 | 33 | 16 | |
| | Pf | 91 / 106 / 82 | 33 | 16 | 1 |
| | P | 92 / 106 / 82 | 33 | 16 | 0 |
| Validation (16) | B | 13 / 13 / 16 | 8 | 2 | |
| | P | 13 / 13 / 16 | 8 | 2 | 0 |

Every candidate run kept every control and every question without "test"
or "tests" identical to B on every page. Candidate generation was identical
for every question.

On development, P moved a source file into the first five on 7 questions.
Two were judged implementation files, both in aspnetcore:
`SetCookieHeaderValue.cs` and `ServerSentEventsResult.cs`. The other five
questions had only test labels. Pf also paired the ripgrep test helper
`tests/util.rs` with a source `util.rs`, and the judged `tests/feature.rs`
left the first five. Development rejects Pf.

P fails the frozen validation rules:

- `compare` passes, and no individual judged file or quote is lost.
- Judged files at 5 stay at 13. The rule needs a net gain of at least 2,
  with gains in at least 2 packs.

## Why P gains nothing on validation

P fired on 4 of 12 validation test questions. Each time it moved a source
file into second place, but none was the judged implementation:

- crystal, IPv6-only mode on an IPv4 socket: P showed `udp_socket.cr`. The
  check is in the base class, `ip_socket.cr`.
- crystal, condition wait with a timeout: P showed
  `src/sync/condition_variable.cr`. That file is a different class. The test
  covers `Thread::ConditionVariable`, which
  `pthread_condition_variable.cr` implements.
- crystal, special variables, and dart-sdk, file watching: the best test hit
  was a different test file (`status_spec.cr`, `pub_test.dart`). P showed
  the source for that file.

Name pairing could not have found the judged implementation on this set:

- Only 1 of 12 test files has a test affix that names its implementation
  file. That test is `pkg/analyzer/tool/generators/ast_generator_test.dart`,
  and `is_test_path` does not count it as a test: `_test.dart` is not a
  recognized name, and the file is not in a test folder.
- Ring names tests after their source (`test/ring/util/test/async.clj` for
  `src/ring/util/async.clj`) without an affix. P skips these. Pf pairs them,
  but on B the best test hit was the judged test in none of the ring
  questions.
- The best test hit was the judged test file in only 4 of 12 questions.

Many tests check behavior that another file implements: a base class, a
platform layer, a request handler or a verifier. B delivers 0 of 12
implementation labels at 24. A reorder of the pool cannot add a file that
the test hits do not name. A fix needs a different signal, for example a
source hit that matches the query terms, not the test name.

## Limits

- The labels are author-written, source-bound and not exhaustive. A moved
  file can be relevant without a label: `udp_socket.cr` holds the UDP socket
  class. The labels are not user or agent outcomes.
- The development questions from earlier sets have test labels only, so
  five of the seven development moves had no label to gain or lose.
- The latency numbers are descriptive.
- All 16 validation questions are now consumed.

## Runs

We made 64 supervised pack runs:

- 14 development runs of B that stopped at once. The runner passed a
  relative manifest path from the arm folder. We kept these records and
  excluded them.
- 14 development runs each of B, P and Pf, and 4 validation runs each of B
  and P.

All 50 runs in the results passed inside the bounds. The largest RSS was
572 MiB and the largest disk use was 331 MiB.

## Artifacts

- [Decision record](2026-10-18-paired-source-decision.json): `compare()`
  output for every arm and set, identity checks, rule outcomes and hashes.
- [Observations](2026-10-18-paired-source-observations.json.gz): the 50
  observations in the results. This file omits the per-stage generation lists
  for size. The private full observations confirm generation identity.
- Candidate patches: [P](../designs/2026-10-18-paired-source-p.patch.gz) and
  [Pf](../designs/2026-10-18-paired-source-pf.patch.gz).
- `test_paired_source_decisions_replay_from_hash_bound_observations`
  recomputes every comparison and identity check from these files.
