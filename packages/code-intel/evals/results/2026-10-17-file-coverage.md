# File-level concept coverage and "tested" test intent (2026-10-17)

This batch tests two search changes on new frozen questions. Neither change
met its predeclared rules, so neither ships. The search code on `main` does
not change.

| Id | Change |
| --- | --- |
| T | Test intent also recognizes "tested" and "testing". Today only "test" and "tests" put test files first. |
| C2 | In default broad search, count query concepts per file instead of per chunk. Files within one concept of the best-covered file go first. A cleaner filler list applies only to this count. C2 skips queries with an exact identifier (`readTree`, `read_tree`, `Foo::bar`). |

The previous batch rejected a per-chunk version of C2. Its failure case was a
file that split two concepts over two chunks. C2 counts concepts per file to
fix that case.

## Questions

The [development](../designs/2026-10-17-file-coverage-development.json) and
[validation](../designs/2026-10-17-file-coverage-validation.json) sets each
have 16 new questions. They cover four pinned packs that no recent trial used:
rails (Ruby), SwiftFormat (Swift), spdlog (C++) and ggplot2 (R). Each pack and
split has four questions:

- two natural-language implementation questions without exact identifiers
- one exact-symbol control ("Where is X defined and where is it called?")
- one test-intent question that uses the word "tested"

We declared disjoint subsystems for each split before we wrote any question.
Source-reading subagents drafted the questions without any search. We then
reviewed every label and removed duplicate-file and weak supporting labels.
The [freeze record](../designs/2026-10-17-file-coverage-freeze.json) holds the
acceptance rules. We wrote it before the first search on these packs.

C2 could change before validation. We tuned it on the new development set and
on the 24 questions of the previous batch, which were already consumed. T was
fixed at freeze time.

Every observation is the real daily MCP delivery: 5, 24 and scoped results,
2,000 tokens, auto mode. A supervisor bounded each pack run to 180 seconds,
512 MiB of disk and 1.5 GiB RSS. We made 64 pack runs, including 16 runs of
an earlier C2 form (`f_min2`). All runs passed inside these bounds. No run
used a model, a download or a cloud worker.

## Results

Judged files found at 5, 24 and scoped, visible quotes at 5 and inspection
quotes. B is `main` (`3085a3b`).

| Set | Arm | Files 5 / 24 / scoped | Visible 5 | Inspection | Individual losses |
| --- | --- | --- | --- | --- | --- |
| Development (16) | B | 11 / 14 / 15 | 2 | 1 | |
| | T | 12 / 15 / 15 | 4 | 2 | 2 |
| | C2 | 15 / 15 / 15 | 2 | 2 | 1 |
| | T + C2 | 15 / 15 / 15 | 4 | 3 | 3 |
| Validation (16) | B | 15 / 16 / 15 | 5 | 2 | |
| | T | 16 / 17 / 15 | 4 | 1 | 5 |
| | C2 | 15 / 18 / 15 | 5 | 2 | 1 |
| | T + C2 | 17 / 19 / 15 | 4 | 1 | 5 |
| Previous development (12) | B | 12 / 15 / 12 | 3 | 1 | |
| | C2 | 14 / 17 / 12 | 3 | 1 | 1 |
| Previous validation (12) | B | 13 / 14 / 12 | 4 | 3 | |
| | C2 | 14 / 15 / 12 | 5 | 3 | 0 |

A loss counts each judged file or quote that B delivered and the arm did not,
per page. Every candidate arm kept each exact-symbol control response
identical to B. C2 kept candidate generation identical in every set, so it changes only
delivery order.

## Why C2 fails

C2 had a net gain of four first-five files on development and two on the
previous development set. On validation it gained one file at 5 and lost one, so the
net first-five gain is zero. Its rules require zero individual losses and at
least one validation gain at 5. It lost judged files in three of the four
sets:

- `ggplot2` development question 2: `R/scale-.R` left page 24.
- `ggplot2` validation test question: `R/stat-bin.R` left the first five.
- `pandas` previous development question 1: `pandas/core/indexers/objects.py`
  left the first five.

The filler list does not remove enough generic words. A long question keeps
words such as "end", "start", "number", "given" and "time". Large files and
prose match many of these words. For the pandas question, `generic.py` (9
concepts) and `groupby.py` (10) outranked the judged `objects.py` (7). We
simulated other forms of C2 offline on the development data: two or more
concepts (`f_min2`), raw count (`f_count`), rare concepts only (`f_rare1`,
`f_rare2`) and inverse document frequency (`f_idf`). Each form gained fewer
files or also lost judged files. The decision record lists the results.

## Why T fails

T changes only questions that contain "tested" or "testing". All other
questions kept identical delivery and generation. None of the 73 ranking-gate
queries contains these words without "test" or "tests", so T cannot change
the gate.

T moved the primary test file into the first five on 5 of the 8 test-intent
questions. On 3 of them, it also pushed the implementation file out of the
page:

- `ggplot2` development: `R/scale-hue.R` left pages 5 and 24.
- `ggplot2` validation: `R/stat-bin.R` left pages 5 and 24.
- `rails` validation: `ssl.rb` left pages 5 and 24, with its visible quote.

T uses the existing test partition for "tests" queries. That partition puts
every test chunk before every source chunk, and it skips file diversity. On
one SwiftFormat validation question, four chunks of the same file filled the
first five. The rule for T required zero individual losses, so T fails.

## Next step

A test-intent change that keeps the best source file in the first five can
keep both answers. It needs new frozen questions. All 32 questions in this
batch are now consumed.

## Artifacts

- [Decision record](2026-10-17-file-coverage-decision.json): `compare()`
  output for every arm and set, identity checks, rule outcomes and hashes.
- [Observations](2026-10-17-file-coverage-observations.json.gz): 48 MCP
  observations. This file omits the per-stage generation lists for size. The
  private full observations confirm generation identity.
- Candidate patches: [T](../designs/2026-10-17-file-coverage-t.patch.gz),
  [C2](../designs/2026-10-17-file-coverage-c2f.patch.gz) and
  [T + C2](../designs/2026-10-17-file-coverage-tcf.patch.gz). The C2 and
  T + C2 patches name the baseline file with a `../B/` prefix. The decision
  record binds each patch by hash.
- `test_file_coverage_decisions_replay_from_hash_bound_observations`
  recomputes every comparison and identity check from these files.

## Limits

The labels are author-written, source-bound and not exhaustive. They are not
independent user or agent outcomes. A 16-question set has a p95 equal to its
slowest question. One rails question took about 1.5 seconds in B, while most
questions took 20 to 140 ms. The latency numbers are descriptive. We did not
run the 40 earlier regression questions, the ranking gate or the workflow
suite on the rejected arms.
