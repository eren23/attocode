# Source hit after the first five tests (2026-10-18)

A short search with "test" or "tests" puts test hits first. The paired-source
batch showed that the test name rarely names the implementation file. This
batch tries a signal from the query words instead: the best source hit for
the query. The candidate (S1) held every judged rule on development and on
new frozen validation questions. It failed the frozen p95 latency limit in
the one validation run, so it does not ship. A second trial (S2) kept the S1
order, made it cheaper and used a latency rule over three rounds. On 20 more
new questions, S2 passed the latency rule but lost a judged test file and
gained nothing. The search code does not change.

| Id | Change |
| --- | --- |
| QN | Short queries with "test" or "tests" keep the first five test hits first. The best N distinct source files come next, then the other test hits, then the other source hits. |
| S1 | The short form of Q1: one source hit after the first five test hits. |
| S2 | The S1 order. S2 checks each candidate once with `is_test_path`. |

All arms change only `demote_tests` in `query_ranking.py`. Candidate
generation and the delivery of every query without "test" or "tests" do not
change.

## Diagnosis

We used the 20 consumed questions that have an implementation label. The
diagnosis read the candidate order of the search engine, not the MCP pages.
Without "test" in the query, the source order is the same as with it. The judged
implementation file is the best source hit in 3 of 20, in the first 3 in 9,
and in the first 5 in 11. So the query words alone do not find the
implementation file, but they often put it near the top of the source hits.

The first five results stay tests in every arm. At 2,000 tokens, the "24"
page holds about 8 results. A source hit in slot 6 takes the place of a test
hit, so each extra source slot can push a judged test file off the page.

## Questions

The [validation set](../designs/2026-10-18-query-source-validation.json) has
20 new questions on five pinned packs that no earlier trial used: julia, Nim,
deno, fsharp and perl5. Each pack has three test questions and one
exact-symbol control. The three test questions use "Which tests cover X?",
"Where is the test for X?" and "Find the tests for X". Each test question
has two labels: the test file and the implementation file.

We did not choose the test files. A seeded shuffle drew three test files per
pack, from distinct folders, before we wrote any question and before any
search on these packs. The manifest records the seed, the method and two
corrections:

- The first draw for julia picked a test helper and a fixture file. Neither
  holds a test case. The rule now also needs a test case marker. We made
  this change before we wrote any question.
- Three drawn files had no implementation inside the pack. The next file in
  the shuffle order replaced each one, and the manifest keeps the reason:
  two julia files (the code is in C or in a build script) and one fsharp
  file (all its cases sit in a disabled block).

Source-reading subagents found the code that each test case exercises,
without search. We checked every line and quote against the pinned source.
The [freeze record](../designs/2026-10-18-query-source-freeze.json) holds the
acceptance rules. We wrote it before the first search on these packs.

The [development set](../designs/2026-10-18-query-source-development.json)
merges 100 consumed questions on 18 packs: the 84 development questions and
the 16 validation questions of the paired-source batch. It is not fresh
evidence. We changed the candidate on development only. The
[candidate record](../designs/2026-10-18-query-source-candidate.json) binds
the selection rule, every development arm and the S1 patch and engine hash.
We wrote it before the one validation run.

Every observation is the real daily MCP delivery: 5, 24 and scoped results,
2,000 tokens, auto mode. A supervisor bounded each pack run to 180 seconds,
512 MiB of disk and 1.5 GiB RSS. No run used a model, a download or a cloud
worker.

## Results

Judged files found at 5, 24 and scoped, visible quotes at 5 and inspection
quotes. The baseline is the head of #238 (`4a1464f`), which adds more test
file names to `main` (`e153f86`). The observation records name this arm D.

| Set | Arm | Files 5 / 24 / scoped | Visible 5 | Inspection | Individual losses |
| --- | --- | --- | --- | --- | --- |
| Development (100) | D | 103 / 117 / 98 | 41 | 18 | |
| | Q1 | 103 / 120 / 98 | 41 | 18 | 0 |
| | Q2 | 103 / 121 / 98 | 41 | 18 | 1 |
| | Q3 | 103 / 124 / 98 | 41 | 18 | 1 |
| | Q5 | 103 / 124 / 98 | 41 | 18 | 3 |
| | S1 | 103 / 120 / 98 | 41 | 18 | 0 |
| Validation (20) | D | 12 / 20 / 19 | 8 | 6 | |
| | S1 | 12 / 22 / 19 | 8 | 6 | 0 |

Every candidate run kept every control and every question without "test"
or "tests" identical to D on every page. Candidate generation was identical
for every question.

The frozen selection rule picks the largest N with zero individual
development losses and a net gain of at least 2 judged files at 24 in at
least 2 packs. Q2, Q3 and Q5 each lose a judged test file at 24
(`gson:usefulness-validation-2`). Q5 also loses an express test file and a
luarocks visible quote. Q1 gains 3 implementation files at 24, in
aspnetcore, crystal and dart-sdk, with no loss. S1 gives the same
development pages as Q1, with shorter code.

On validation, S1 gains 2 implementation files at 24:
`lib/std/private/underscored_calls.nim` (Nim) and `ext/web/02_event.js`
(deno). Both move into slot 6. S1 fails one frozen rule:

- `compare` fails on latency only. The limit is max(0.1 s, 1.5 × D). The p95
  goes from 0.065 to 0.110 seconds, over the limit of 0.1 seconds. The other
  four `compare` checks pass.
- No individual judged file or quote is lost at 5, 24 or scoped.
- Judged files at 24 gain 2, in 2 packs. The rule needs this.

## Why the latency failed

We recorded the decision before any other run. Then we ran a diagnosis that
cannot change it.

- The p95 is the 19th of the 20 page-5 latencies. Each latency is the median
  of three warmed samples.
- In the validation run, one S1 question
  (`fsharp-t:query-source-2`) had a median of 0.110 seconds. In D it was
  0.045 seconds. In two more runs of D and S1 on the same packs, it was 0.045
  and 0.047 seconds.
- The perl5 control has no test word, so the S1 code cannot run for it. Its
  median still went from 0.065 seconds in D to 0.086 seconds in the S1
  validation run. This shows the host noise in one run.
- Both repeats pass `compare`, with the same gain of 2 and no loss. The p95
  goes from 0.068 to 0.088 seconds and from 0.065 to 0.065 seconds.
- A microbenchmark of `demote_tests` on a 300-row pool gives 409
  microseconds per call for D and 812 for S1. S1 calls `is_test_path` twice
  per row. This cost is real but small.

The most likely cause of the failure is run noise. The latency rule uses one
run per arm, so one slow sample can decide it. The frozen rule still
decides: S1 does not ship.

## Second validation: S2

S2 gives the same order as S1 on 5,000 seeded pools. On a 300-row pool, one
call costs 607 microseconds for D, 1,199 for S1 and 609 for S2. The
[equivalence record](../designs/2026-10-18-query-source-s2-equivalence.json)
holds these numbers.

The [second validation set](../designs/2026-10-18-query-source-s2-validation.json)
has 20 new questions on five repositories that no earlier trial used:
vapor (Swift), protobuf (C++), spring-boot (Java), mojo (Perl) and elixir
(Elixir). Each pack pins the HEAD commit of its cached local clone and keeps
one source area and its tests. The draw, templates and label checks are the
same as above. No drawn file needed a replacement.

The [freeze record](../designs/2026-10-18-query-source-s2-freeze.json) holds a
new latency rule. We wrote it before any search on these packs:

1. Run every pack in three rounds: D then S2, S2 then D, D then S2. Each run
   is a fresh process with a cold index.
2. For each question, take the median of the three round medians of the
   page-5 latency.
3. Take the p95 over these values. The limit stays max(0.1 s, 1.5 × D).

The judged rules use the round-1 delivery and are the same as above.

| Set | Arm | Files 5 / 24 / scoped | Visible 5 | Inspection | Individual losses |
| --- | --- | --- | --- | --- | --- |
| Validation 2 (20) | D | 18 / 20 / 19 | 10 | 3 | |
| | S2 | 18 / 19 / 19 | 10 | 3 | 1 |

S2 fails two frozen rules:

- `compare` fails on the file totals: judged files at 24 go from 20 to 19.
  The latency check passes. The p95 is 0.064 seconds in both arms, and the
  three rounds agree within 3 ms.
- On a vapor question, the judged test `ApplicationCreationTests.swift` was
  in slot 8 of the 8 delivered results. The source hit in slot 6 pushed it
  off the page.
- S2 gains no judged file, so the rule for a gain of 2 in 2 packs fails.

Controls, questions without a test word and candidate generation stay
identical. Delivery is identical in all three rounds for both arms.

After the decision, we looked at the source hits that S2 put in slot 6. None
was the judged implementation. In the body stage, the judged implementation
had a median rank of 7.5 among source hits, and one was absent. It was the
first source hit in a stage on 1 of 15 questions. On one mojo question, slot 6 held
`t/mojo/lib/Mojo/LoaderException2.pm`, a fixture in the Perl `t/` test
folder. `is_test_path` does not count that folder.

## Limits

- S1 and S2 do not change the first five results. They help only the "24"
  page, and only when the best source hit is the implementation.
- Over both validation sets, the source slot gained 2 judged files and lost
  1 in 30 test questions. The query words do not rank the implementation
  first among the source hits.
- The labels are author-written, source-bound and not exhaustive. They are
  not user or agent outcomes. The latency numbers are descriptive.
- All 40 validation questions are now consumed.

## Runs

We made 177 supervised pack runs:

- 8 diagnosis runs of D on consumed packs, before any candidate.
- 108 development runs: 18 packs each for D, Q1, Q2, Q3, Q5 and S1.
- 1 Q2 spdlog run that stopped on the harness check "Unstable warmed
  delivery". We kept the record and excluded it. One rerun passed.
- 10 validation runs of D and S1.
- 20 repeat runs of D and S1 on the validation packs, after the decision.
- 30 runs of D and S2 on the second validation packs, in three rounds.

All 176 other runs passed inside the bounds. The largest RSS was 591 MiB
and the largest disk use was 331 MiB.

## Artifacts

- [Decision record](2026-10-18-query-source-decision.json): `compare()`
  output for every arm and set, identity checks, the frozen rule outcomes,
  the diagnostics after the decision and hashes.
- [Observations](2026-10-18-query-source-observations.json.gz): the 138
  observations in the results and the repeats. This file omits the
  per-stage generation lists for size. The private full observations
  confirm generation identity.
- Candidate patches: [Q1](../designs/2026-10-18-query-source-q1.patch.gz),
  [Q2](../designs/2026-10-18-query-source-q2.patch.gz),
  [Q3](../designs/2026-10-18-query-source-q3.patch.gz),
  [Q5](../designs/2026-10-18-query-source-q5.patch.gz) and
  [S1](../designs/2026-10-18-query-source-s1.patch.gz).
- S2: [decision record](2026-10-18-query-source-s2-decision.json),
  [observations](2026-10-18-query-source-s2-observations.json.gz) of the 30
  runs and the [patch](../designs/2026-10-18-query-source-s2.patch.gz).
- `test_query_source_decisions_replay_from_hash_bound_observations` and
  `test_query_source_s2_decision_replays_from_hash_bound_observations`
  recompute every comparison and identity check from these files.
