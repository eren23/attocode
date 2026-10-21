# Two test-search misses: scoring, fusion and delivery (2026-10-20)

**Diagnosed; no product change.** The Express accepts test falls outside the
24-candidate pool. The Mojo timeout test reaches that pool at rank 17, but a
2,000-token response drops it. Executing the existing advertised 4,352-token
follow-up delivers the Mojo test and its exact assertion. These are different
failure points, not evidence for another helper-demotion rule.

This follows the [rejected support-order experiment](2026-10-20-test-support.md).
Both questions and all relevance labels are consumed. There is no new candidate,
fresh validation, relevance improvement claim or agent-outcome measurement.

## Boundaries located

All ranks below are one-based **result-row positions**, not unique-file ranks.
The raw SQLite column counts source windows; the body column is after owner
coverage and per-file caps. Fusion columns use each target's first occurrence.

| Target test | Best raw body window | Body generation | Fused, before test preference | After test preference | Selected at 24 | Delivered with 2,000 tokens |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Express `test/req.accepts.js` | 170 | 64 | 75 | 44 | No | No; page contains 16 rows |
| Mojo `t/mojolicious/longpolling_lite_app.t` | 87 | 37 | 68 | 17 | Yes | No; page contains 8 rows |

Neither target has a metadata keyword hit. Both have zero occurrences of the
retrieval tokens in their indexed metadata document, which contains paths,
imports and named symbols rather than assertion bodies. Their only fusion vote
comes from body search:

- Express: `1.15 / (20 + 64) = 0.013690` after rounding.
- Mojo: `1.15 / (20 + 37) = 0.020175` after rounding.

There is no rare-token pruning here: the two body queries have 10 and 19 tokens,
below the threshold of 20. Whole-file BM25 is inactive for both. The index is
ready with full indexed-file coverage for each materialized source scope; no
stale-body fallback or model ranker was involved.

## Why competing results score higher

For Express, the best accepts window (lines 29–60) matches only `expect`
(0.4229 BM25) and `types` (2.8921), totaling 3.3150. The judged assertion at line
73 is in a different window, raw rank 182, with those same two matching terms.
The query's `accepting` does not match the source's `accepts` or `acceptable`.

The other judged file, `test/res.format.js`, already ranks first after test
preference. Its best body window matches `assert` (2.8226), `format` (4.2632) and
`types` (4.2590), totaling 11.3448. It also has a keyword vote at rank 8, producing
a fused score of 0.090476. Its top window does not contain the separate judged
assertion at line 197: finding a file is not the same as showing its evidence.

For Mojo, the target's lines 309–333 contain the judged line-319 assertion and
match `error` (3.6141), `once` (3.1662) and `request` (3.6008), totaling 10.3811.
The query describes an overall time limit; its retrieved tokens contain neither
`timeout` nor `request_timeout`.

The query expansion adds generic exception terms. For example, the helper
`t/mojo/lib/Mojo/LoaderException2.pm` has a short `throw_error` window matching
`error` (3.5635), `exception` (5.4217) and `throw` (8.1302), totaling 17.1153.
The first `exception.t` window gets 10.3762 of its 19.9816 score from `raise`.
These are observed score contributions, not a controlled estimate of what
removing expansion would achieve.

The helper also has two **distinct** `throw_error` metadata definitions, at lines
12–15 and 21–23, in different Perl packages. Current name-owner aggregation sums
their keyword votes at positions 19 and 20 with body position 5:
`1/39 + 1/40 + 1.15/25 = 0.096641`. This explains another part of its prominence.
It is not a duplicated retrieval row. Changing definition aggregation is a
separate ranking hypothesis; this trace does not establish that such a change
would recover the timeout test at five.

## Existing follow-up checked

After observing the budget cutoff, a separate bounded diagnostic executed the
exact follow-up advertised by each first page: same query, `top_k=24`,
`max_tokens=4352`, current index. No parameters were searched or tuned.

- Mojo delivers all 24 rows, including the timeout test at 17, its enclosing
  range and the literal `Request timeout` assertion.
- Express delivers all 24 rows and still misses `req.accepts.js`. Its
  `res.format.js` file remains present, but the judged line-197 quote is absent.

The compact 2,000-token responses correctly report 8 and 16 omitted rows for
Express and Mojo respectively. Budget trimming is therefore observable, and the
existing follow-up resolves the Mojo delivery miss. It does not solve either
query's first-page relevance problem.

## Verification and reproduction

The engine is the committed `d2a6d2933091d659ce9b2ea82035668ecb767afd` snapshot,
with product-source SHA-256
`6d230c206725a0c6ea3838bcb31588ef9efb878158ff988318f34e7d064f5219`,
identical to the previous baseline. Express is pinned to
`6c4249feec8ab40631817c8e7001baf2ed022224`; Mojo to
`19fc4f19a0d83204a458ae4a19d192b7eaf4ba81` with only `lib` and `t`.
Source hashes and literal label lines were checked before querying.

The passive recorder observes the real daily-profile compact MCP pipeline.
For both page sizes on both packs, ordinary searches before and after the trace
produce exactly the same delivered rows, generated candidates and pre-hydration
rows. All generated candidates and delivered identities, scores and ranges also
match the historical baseline. One historical Express snippet ends two lines
earlier; its envelope differs, so historical snippet bytes are not a passivity
control. Same-run controls retain the strict equality check.

An independent replay reconstructs every fused owner-head score and order from
the two generated lists, checks the 24-result cutoff and service selection,
verifies delivered-prefix order and omission counts, and sums SQLite's
single-phrase BM25 contributions back to each observed full-query score.
Six deliberate artifact corruptions—score, cutoff and budget count for each
pack—are rejected by the checker.

The existing MCP-evaluation, chunk-identity and query-ranking suites pass
60 tests. The strict documentation build, scoped Python undefined/unused-name
checks and tracked-diff whitespace check pass. The product source is unchanged;
no new ranking-gate run is claimed or needed to validate a changed engine.

The [compressed evidence](2026-10-20-retrieval-trace-observations.json.gz)
contains the frozen questions, operators, passive recorder, complete traces,
ordinary controls, follow-up responses, replay checker and resource logs.
The [decision](2026-10-20-retrieval-trace-decision.json) binds its hash and records
the replayed ranks. To replay, extract the archive's `files` mapping to a fresh
directory and run `PYTHONPATH=. .venv/bin/python <directory>/verify.py` from this
checkout. The checker also reads the prior support-order archive. For a live
rerun, adjust the archived operators' absolute repository, output and scratch
paths, retain the source pins, and use fresh output directories. No source-pack
dependencies are installed.

The initial and follow-up experiments together took 8.53 seconds. All four
processes passed the 180-second, 512-MiB scratch and 1.5-GiB RSS limits; maximum
sampled RSS was 150.8 MiB. Managed storage stayed below 32 MiB, including retained
outputs, against a 1-GiB bound. Both scratch roots were removed and all owned
process cleanup checks passed. No downloads, models, cloud workers, source-pack
test suites or host MCP restart were used.

## Decision

No deviation from the implemented scoring, partitioning, truncation or budget
contracts was demonstrated, so there is no justified product bug fix in this
batch. Preserve the ranking defaults. Use advertised follow-ups when diagnosing
budget-trimmed output; a fixed-budget evaluation should continue to report its
actual delivered evidence rather than count hidden candidates as successes.

Further first-page work needs a distinct mechanism addressing vocabulary
coverage or generic-term/owner scoring, with fresh held-out judgments. Do not
retry the rejected helper ordering or disable expansion globally on the strength
of these two consumed examples.
