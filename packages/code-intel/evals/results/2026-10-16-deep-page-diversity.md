# Deeper search page delivery

The default broad-query page now keeps the first hit from each available file
before filling remaining slots with repeated chunks. This fixes the all-or-nothing
fallback identified in the [earlier audit](2026-10-16-cross-file-audit.md).
Retrieval scores, candidate generation and the experimental reranker are unchanged.

The old behavior required enough distinct files to fill the entire requested
page. With 120 leading chunks from one file and 87 other files, asking for 24
hits returned 24 files, but asking for 96 hits returned only one. The repaired
96-hit page contains all 88 files, followed by eight remaining chunks. Hit count,
first-hit file, first-occurrence order, original scores and candidate objects are
preserved. Scoped, single-concept and test-seeking queries keep chunk order.
For a fixed pool, the distinct-file prefix is stable across page sizes; real
follow-ups rerun wider retrieval and are still not stable cursors.

## Frozen fresh comparison

[Six questions](../designs/2026-10-16-deep-page-questions.json), two each on pinned
ripgrep, OkHttp and Cats Effect sources, were source-reviewed and frozen before
retrieval. Each has two relevant-file labels. The questions cover configuration
precedence, regex literal acceleration, settings propagation, DNS resolution,
sleep scheduling and secure UUID construction. Earlier questions were not used
as fresh validation. Repositories and some source files had been exposed before;
these are non-exhaustive judgments by the implementing agent, not independent
annotations or evidence of agent success.

Questions SHA-256:
`51a03c476bddc3b1248875059acfd3aec6a13140786f8b44c4f18326091c3cc3`.
Product/evaluation source fingerprint:
`d0286614642914fd36657f380cae925e8f101b0dbf057768cf3e853cd4f684f5`.

The [operator](../../../../eval/quality/deep_page_trial.py) captures the actual
provider-free lexical pool once per question/depth and compares the historical
`112dab66` delivery rule with the candidate on that same pool. Source-free chunk
identities, source-text hashes, pool hashes and returned pool indices are retained
in the [raw report](2026-10-16-deep-page-diversity.json). Thirty local controls
checked the baseline adapter against the function extracted from that commit.
Each arm's delivery time is the median of 101 calls; this is a small in-process
measurement, not an end-to-end latency benchmark.

The predeclared acceptance rule required unchanged counts and first files,
first occurrences before repeats, no labeled-file loss at five or the requested
depth, median delivery below 5 ms, and the 88-file controlled regression. All
checks passed. No candidate tuning followed validation.

| View (unique-file ranks) | Baseline | Candidate |
| --- | ---: | ---: |
| Any labeled file in first five, depth 24 | 5/6 | 5/6 |
| All labeled files in first five, depth 24 | 1/6 | 1/6 |
| All labeled files at depth 24 | 5/6 | 5/6 |
| Labeled file-question pairs at depth 24 | 11/12 | 11/12 |
| All labeled files at depth 96 | 6/6 | 6/6 |
| Labeled file-question pairs at depth 96 | 12/12 | 12/12 |

Only the configuration question's depth-96 delivery changed: 96 hits represented
37 distinct files before, and 86 after, exposing every available file. Both
labeled targets were already delivered. The other eleven question/depth pools
produced identical deliveries. Candidate median delivery was at most 0.022 ms.
The measured gain is file coverage; labeled relevance did not improve.

## Bounded validation

Three sequential cached-source runs took 6.763 seconds in total, with peaks of
38.2 MiB managed storage and 105.1 MiB sampled RSS. Each had a 180-second,
512-MiB disk and 1.5-GiB RSS bound; source materialization was capped at 64 MiB.
All source/cache scratch was removed. No downloads, models, cloud workers or
agent runs were used.

Five assertions failed before the fix; the focused suite passed 76 checks after
it. The bounded local gate passed 719 tests (nine explicit environment skips),
Ruff, scale and lifecycle checks in 43.803 seconds, peaking at 127.3 MiB managed
storage. Run: `20261016T104416-333bb3a0`; fixture fingerprint:
`251ad7e97a42759c84f6e51b79563765b19bcb72f3745aef2631f577c6c3fe68`.
The separate local ranking regression gate passed in 41.826 seconds. Upstream
ranking and PostgreSQL checks are required before merge.

Both six-question sets are now consumed. Next relevance work still needs fresh
judgments; this fix provides no evidence of better intent understanding. The
separate Rust intermittency and Cockroach timing margin remain open. This change
does not cut a release or restart an existing host MCP process.
