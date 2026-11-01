# Query-rewrite trial (2026-11-01)

**Result: REJECTED at the development screen, on a partial run.** Before retrieval, the candidate sent the question to a hosted model and asked for code identifiers. These words went into one more body search, fused as a third list. The run stopped after 2 of 10 repositories. A rule was written before the candidate rows were read. Under this rule, three frozen gates fail for every outcome of the missing repositories. This change removes the candidate code. No fresh questions were written, and the validation run did not occur.

- Candidate and harness: commit `ebca0d4` (PR 303), behind `ATTOCODE_INTEL_QUERY_REWRITE=openrouter`. PR 304 removed a key-limit check from the trial workflow. PR 305 changed the parser to keep the first 12 names of a longer reply.
- Model: `anthropic/claude-haiku-5.5` through OpenRouter, 1,500 ms timeout, at most 12 names. The request held only the redacted question text.
- Design: [`designs/2026-10-17-test-source-slot-development.json`](../designs/2026-10-17-test-source-slot-development.json), SHA-256 `c001108186956cc4cfc49bef969ec4abf85015677a8c4755c79450fbb06bc02e`. These 68 questions were consumed in earlier trials, so this result is development evidence only.
- Runs: [41315510319](https://github.com/eren23/attocode/actions/runs/41315510319) (head `4af4368`) and [41317095737](https://github.com/eren23/attocode/actions/runs/41317095737) (head `7bb35df`). The decision uses the second run only.
- Raw data: [`2026-11-query-rewrite.tar.gz`](2026-11-query-rewrite.tar.gz) (SHA-256 `786fcf33dc23d12c2b05422a42d57d1a75196adb5a597a16647058cb878e87c0`). It holds the observations of both runs, the key usage records, the partial-data rule, `recompute.py` and `partial-decision.json`. The compact record is [`2026-11-query-rewrite.json`](2026-11-query-rewrite.json).

## Candidate

The miss census of the test-recall trial found 7 of 12 judged test misses outside the candidate pool. In these misses, the question words do not occur in the code, for example "accepting" in the question and `req.accepts` in the code. A rerank cannot fix such a miss, because it only reorders the pool.

The candidate asked the model for at most 12 function, class, method, file or config names that code answering the question likely contains. Words already in the query were removed. The other words fed one more body search, fused with the weight of the body list. The keyword, body and file lists did not change. Without the variable, the candidate made no request.

## What happened

1. **Run 1 (41315510319)** completed Express (9 questions). The preflight of the next repository, ripgrep, then got `invalid_response`, `timeout`, `invalid_response` and stopped the run. The parser rejected replies with more than 12 names. PR 305 changed it to keep the first 12. The plan allowed a fix and a new dispatch only for a preflight failure before the first scored question. This failure came after Express, so the second dispatch was outside that allowance. The Express rows of run 1 were not read before the second dispatch, and the decision does not use them.
2. **Run 2 (41317095737)** completed Express and ripgrep (18 questions). The preflight of Cats Effect got `timeout` and then `busy` twice. A call that times out keeps the one in-flight slot until its thread ends, and the preflight retried at once. This is a harness fault. The run was not repeated.
3. `precommit.md` in the archive records a rule, written before any candidate row of run 2 was read. A frozen gate decides only if it fails for every outcome of the 8 missing repositories. Otherwise the screen is incomplete.

## Results (run 2, Express and ripgrep, 18 questions)

| Metric (labels found) | Baseline | Candidate |
|---|---|---|
| Judged files, first 5 | 20 | 22 |
| Judged files, first 24 | 25 | 26 |
| Visible quotes, first 5 | 5 | 4 |
| Visible quotes, first 24 | 2 | 1 |
| Scoped search: files / visible | 18 / 8 | 18 / 6 |

Each candidate page was scored as the worst of 3 samples: a label counts only if all three samples found it.

- Gained at 5: `lib/application.js` (express:usefulness-development-3), `tests/feature.rs` (ripgrep:usefulness-development-1 and ripgrep:usefulness-validation-2). The two ripgrep gains also hold at 24.
- Lost: `tests/feature.rs` at 5 (ripgrep:usefulness-development-2) and `crates/core/flags/hiargs.rs` at 24 (ripgrep:usefulness-development-3). Visible quotes were lost on express:test-intent-3 (5 and 24) and on the scoped pages of ripgrep:test-intent-3 and ripgrep:usefulness-validation-2.
- Express `test/req.accepts.js`, the miss that motivated the trial, is not among the gains.

Rewrite outcomes: 162 recorded of 612 planned. 106 `ok`, 35 `invalid_response`, 15 `busy`, 6 `timeout`, so 56 searches ran without extra words. Six rewrites took more than 1,500 ms. No search took more than 2 seconds. The harness recorded only the status, so the cause of each `invalid_response` is not known.

## Gates

| Gate | Frozen limit | Partial result |
|---|---|---|
| Fallback rate | ≤ 5% of 612 rewrites (30) | **fail** (56) |
| No file loss, first 24 | 0 | **fail** (1) |
| Scoped results | no individual loss | **fail** (2) |
| First-five file gain | net ≥ 2, in ≥ 2 repositories | not decided (+1 in each of 2) |
| File losses, first 5 | ≤ 1 | not decided (1) |
| Rewrite p95 | ≤ 1,500 ms | not decided (6 of 162 above) |
| Search p95 | ≤ 2.0 s | not decided (0 above) |
| Spend | ≤ $1 | not decided ($0.013 measured on the key) |

The three failures do not depend on the missing repositories. The result is a rejection.

## Independent check

`recompute.py` in the archive uses only the Python standard library. It reads the run 2 rows and checks the design SHA and one engine and one evaluator per arm. It checks that no rerank call and no baseline rewrite call occurred. It checks that each worst-of-3 page is the intersection of its samples. It recomputes the totals, losses, statuses and fallbacks, and asserts that the certain failures are exactly the three above. Its output equals `partial-decision.json` byte for byte.

## Spend

The trial key had a $2 limit. The OpenRouter usage counter of the key rose by $0.013: $0.004 in run 1 and $0.009 in run 2. This is the key counter, not an invoice.

## Limits

- 18 of 68 consumed questions, in 2 repositories, with non-exhaustive labels. They are not independent users or agent outcomes.
- The model can know these public repositories. A gain can come from that knowledge and not from the question words.
- Worst-of-3 scoring counts sampling variance as loss. Each call was separate, with no cache.
- The harness retry fault and the unknown `invalid_response` causes make the fallback rate partly a harness and parser result. The frozen gate counts every fallback, whatever its cause.
