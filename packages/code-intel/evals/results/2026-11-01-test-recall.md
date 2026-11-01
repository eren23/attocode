# Test-recall trial (2026-11-01)

**Result: REJECTED at the development screen.** For short queries that contain "test" or "tests", the candidate added one more body search that is limited to test paths. It did not add a judged file to any first page. This change removes the candidate code. No fresh questions were written, and the validation run did not occur.

- Candidate and harness: commit `73a7fff1a2db94dd2e97154a237baf5dd9f52e8f` (PR 301), behind the trial flag `ATTOCODE_INTEL_TEST_RECALL=1`.
- Design: [`designs/2026-10-17-test-source-slot-development.json`](../designs/2026-10-17-test-source-slot-development.json), SHA-256 `c001108186956cc4cfc49bef969ec4abf85015677a8c4755c79450fbb06bc02e`. These 68 questions were consumed in earlier trials, so this result is development evidence only.
- Run: [Test-recall trial 41303464174](https://github.com/eren23/attocode/actions/runs/41303464174), attempt 1, head `73a7fff`. One dispatch, no tuning, no retry.
- Raw data: [`2026-11-01-test-recall.tar.gz`](2026-11-01-test-recall.tar.gz) (SHA-256 `f4149881601d140b9d2f5a37dd24951186a7351c9ab0bbf3dc8b9b2a1b70006e`). It holds the per-pack observations of both arms, `decision.json` and the independent recompute. The compact record is [`2026-11-01-test-recall.json`](2026-11-01-test-recall.json).

## Candidate

The default body search sends one query to SQLite FTS and keeps 576 rows (8 per file, 72 hits). Source files and test files compete for these rows. In earlier traces, a judged test file sometimes ranked outside the pool, for example Express `test/req.accepts.js` at body rank 170.

The candidate ran a second body search with the same terms, filtered to test paths (`is_test_path`) before the row limit. Its results went into the rank fusion as a third list, with the same weight as the body list. Queries without "test" or "tests" did not run the second search.

## Setup

- 68 questions on 10 pinned repositories (Express, ripgrep, Cats Effect, OkHttp, Requests, Gson, Rails, SwiftFormat, spdlog, ggplot2). 24 questions contain "test" or "tests". The other 44 are controls.
- Both arms used the same engine (`6d5e71a0…`) and the same evaluator (`3e83ef96…`), local only, through real MCP delivery at a 2,000-token budget. The arms differ only by the trial flag.

## Results

| Metric (labels found) | Baseline | Candidate |
|---|---|---|
| Judged files, first 5 | 71 | 71 |
| Judged files, first 24 | 90 | 91 |
| Labeled ranges, first 5 | 34 | 34 |
| Visible quotes, first 5 | 22 | 22 |
| Labeled ranges, first 24 | 41 | 40 |
| Visible quotes, first 24 | 13 | 14 |
| Scoped search: files / ranges / visible | 66 / 56 / 29 | 66 / 55 / 29 |
| Inspection: visible quotes | 11 | 11 |
| Search p95 (seconds) | 0.186 | 0.197 |

The candidate changed the delivered results of all 24 test queries. The net first-five file gain was 0 in all 10 repositories.

On the first-24 page:

- Gained: `tests/regression.rs` (ripgrep:usefulness-validation-1) and `tests/feature.rs` (ripgrep:usefulness-validation-2).
- Lost: `okhttp/src/jvmTest/kotlin/okhttp3/HeadersTest.kt` (okhttp:test-intent-1). Other test files moved above it.

Express `test/req.accepts.js`, the miss that motivated the candidate, stayed outside the first 24.

## Gates

| Gate | Frozen limit | Result |
|---|---|---|
| First-five file gain | net ≥ 2, in ≥ 2 repositories | **fail** (net 0) |
| No file loss, first 5 | 0 | pass |
| No file loss, first 24 | 0 | **fail** (1) |
| Controls identical | every control page unchanged | **fail** (1) |
| File and visible totals | no loss | pass |
| Scoped results | no individual loss | pass |
| Inspection | no net loss | pass |
| Latency | candidate p95 ≤ max(0.1 s, 1.5 × baseline) | pass |

The changed control is express:test-intent-3. On its first-24 page, the snippet of `lib/express.js` ends at line 19 instead of line 18. The candidate code does not run for this query, so the cause is elsewhere in delivery. The frozen gate counts it, but the result is a rejection without it too.

## Independent check

`recompute.py` in the archive uses only the Python standard library. It reads the raw rows of both arms and gives the same totals, per-repository net, file loss and changed control. It asserts that each gate agrees with `decision.json`.

## Limits

- 68 consumed questions with non-exhaustive labels. They are not independent users or agent outcomes.
- One run per arm. Both arms are deterministic apart from the one snippet difference above.
- This trial tests only the pool-entry miss. Misses where the 2,000-token page budget removes a test file that is already in the pool stay out of scope.
