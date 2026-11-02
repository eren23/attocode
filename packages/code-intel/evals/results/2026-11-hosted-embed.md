# Hosted embeddings in product search (2026-11-02)

**Result: REJECTED at the development screen.** The candidate fused a voyage-code-4 dense file list into the product file list. It found 10 more judged files at five (71 to 81), but it lost judged files at 24, visible quotes and one inspection quote. Four frozen gates fail. This change removes the candidate code. No fresh questions were written, and the validation run did not occur.

- Stage 1: [`2026-11-hosted-embed-screen.md`](2026-11-hosted-embed-screen.md). voyage-code-4 passed the screen on 50 Loc-Bench tasks.
- Candidate and harness: commit `d3bcd67` (PR 309), behind `ATTOCODE_INTEL_EMBEDDING=openrouter`. PR 310, PR 311 and PR 312 fixed faults that stopped runs before the first scored question (see "What happened"). The candidate diff against `91f02de` is `candidate.patch` in the archive.
- Model: `voyageai/voyage-code-4` through OpenRouter, 1,024 dimensions, `data_collection: deny`.
- Design: [`designs/2026-10-17-test-source-slot-development.json`](../designs/2026-10-17-test-source-slot-development.json), SHA-256 `c001108186956cc4cfc49bef969ec4abf85015677a8c4755c79450fbb06bc02e`. These 68 questions were consumed in earlier trials, so this result is development evidence only.
- Runs: [41347466026](https://github.com/eren23/attocode/actions/runs/41347466026), [41400830542](https://github.com/eren23/attocode/actions/runs/41400830542), [41405042110](https://github.com/eren23/attocode/actions/runs/41405042110) and [41407001519](https://github.com/eren23/attocode/actions/runs/41407001519). The decision uses the last run only.
- Raw data: [`2026-11-hosted-embed.tar.gz`](2026-11-hosted-embed.tar.gz) (SHA-256 `3f386c95b8e1c73b177072124baaf1d6fb1eec010be086df9b7565796863edb4`, 65 files). It holds the observations and key usage records of all four runs, the failed-step logs of the first three runs, `candidate.patch`, `recompute.py` and its output. The compact record is [`2026-11-hosted-embed.json`](2026-11-hosted-embed.json).

## Candidate

The miss census of the test-recall trial found 7 of 12 judged misses outside the candidate pool. In these misses, the question words do not occur in the code. Stage 1 found that a hosted code embedding model finds such files on Loc-Bench.

The candidate added an OpenRouter embedding provider. It used the same consent as the hosted rerank: an opt-in, and a workspace that is equal to the project directory. An explicit index call embedded every chunk of the project into a separate vector file. At search time, the candidate embedded the raw question and took the first 48 distinct files of the vector search. These files were fused into the product file list with equal-weight RRF (k 60), after the BM25 file fusion. Keyword, scoped and inspection searches made no remote call. Without the variable, the candidate made no request.

## What happened

1. **Run 1 (41347466026)** stopped at the start of the candidate arm, before any request. Before each pack, the workflow counts the calls and the spend of the completed packs. When no pack was complete, this count was not a valid number, and the shell arithmetic failed. PR 310 fixed this.
2. **Run 2 (41400830542)** indexed the Express pack, but the preflight query returned 0 files three times. The run stopped before the first scored question. PR 311 added the store row count and the cosine range to the preflight error.
3. **Run 3 (41405042110)** stopped at the same preflight. The new diagnostic showed 331 Express rows, with all cosines between -0.271 and -0.061. The NumPy search path of the vector store cut each list at a cosine of 0, so the list was empty. PR 312 kept negative cosines for the hosted provider only.
4. **Run 4 (41407001519)** completed all 10 packs and 68 questions in both arms. Each fix came before the first scored question, so the plan permitted a new dispatch.

## Results (run 4, 68 questions)

| Metric (labels found) | Baseline | Candidate |
|---|---|---|
| Judged files, first 5 | 71 | 81 |
| Judged files, first 24 | 90 | 95 |
| Label ranges, first 5 | 34 | 30 |
| Label ranges, first 24 | 41 | 34 |
| Visible quotes, first 5 | 22 | 18 |
| Visible quotes, first 24 | 12 | 13 |
| Scoped search: files / ranges / visible | 66 / 56 / 29 | 68 / 56 / 29 |
| Inspection: visible quotes | 11 | 10 |
| Search p95 (seconds) | 0.193 | 0.597 |

Each candidate page was scored as the worst of 3 samples: a label counts only if all three samples found it.

Net judged files at five, by pack: Express +3, requests +2, gson +2, SwiftFormat +2, spdlog +2, ggplot2 -1, the other four 0.

- Gained at 5 (14): `Sources/Arguments.swift`, `Sources/CommandLine.swift` and `Sources/Singularize.swift` (SwiftFormat); `test/req.subdomains.js` and `lib/application.js` twice (Express); `JsonWriterTest.java` and `JsonReaderTest.java` (gson); `HeadersTest.kt` (OkHttp); `activejob/lib/active_job/exceptions.rb` (Rails); `src/requests/utils.py` and `src/requests/exceptions.py` (requests); `daily_file_sink.h` and `mpmc_blocking_q.h` (spdlog).
- Lost at 5 (4): `Sources/CommandLine.swift` (SwiftFormat development-impl-1), `R/position-jitterdodge.R` (ggplot2 validation-control), `FormBodyTest.kt` (OkHttp test-intent-2), `activerecord/lib/active_record/encryption/key.rb` (Rails validation-control).
- Lost at 24 (4): `Sources/Rules/PreferForLoop.swift` (SwiftFormat), `R/scale-manual.R` (ggplot2), `activejob/lib/active_job/core.rb` (Rails), `include/spdlog/details/thread_pool-inl.h` (spdlog).
- Express `test/req.accepts.js`, the miss that motivated this work, is now in the first 24 (it was not before), but it is not in the first 5.
- Visible quotes were lost on 6 pages: ggplot2 validation-control, OkHttp test-intent-2, Rails validation-control and requests usefulness-development-1 at 5, and Rails development-test and ripgrep test-intent-2 at 24. The visible total at five fell from 22 to 18. The dense files moved other chunks off the page, so fewer label ranges were delivered.

Dense outcomes: 612 of 612 query embeddings returned `ok`. Dense p95 was 508 ms. Hosted search p95 was 0.698 s.

## Gates

| Gate | Frozen limit | Result |
|---|---|---|
| First-five file gain | net ≥ 2, in ≥ 2 repositories | pass (+10, in 5) |
| File totals | no loss at 5, 24 or scoped | pass |
| Visible totals | no loss at 5, 24 or scoped | **fail** (22 to 18 at 5) |
| Scoped results | no individual loss | pass |
| Inspection | no net loss of visible quotes | **fail** (11 to 10) |
| File losses, first 24 | 0 | **fail** (4) |
| File losses, first 5 | ≤ 1 | **fail** (4) |
| Dense fallback rate | ≤ 5% | pass (0 of 612) |
| Search p95 | ≤ 2.0 s | pass (0.698 s) |
| Packs indexed, pinned model, consent | all packs, every call | pass |
| Baseline remote calls | 0 | pass |
| Spend | ≤ $5 | pass ($0.289) |

## Independent check

`recompute.py` in the archive uses only the Python standard library and imports no code from this repository. It reads the run 4 rows. It checks the design SHA, the pinned commit of each pack, and one engine and one evaluator hash for both arms. It checks that each worst-of-3 page is the intersection of its 3 samples, and that both arms sent the same requests. It recomputes the totals, the individual losses, the net gain by pack and all checks. Its output ends with `decision.json matches`.

## Spend

The trial key had a $20 limit. Its OpenRouter usage counter rose by $0.29083: $0 in run 1, $0.00081 in run 2, $0.00081 in run 3 and $0.28921 in run 4. In run 4, the harness counted 3,301 posted calls and $0.289209 from the reported `usage.cost`. This is equal to the key counter. Indexing the 10 packs took 2,679 requests, 2,400,764 tokens and about 235 seconds. Rails alone took $0.164. The key counter is not an invoice.

## Limits and disclosures

- 68 consumed questions in 10 repositories, with non-exhaustive labels. They are not independent users or agent outcomes.
- The product chunker differs from the stage 1 screen. It also embeds tests and file summaries, and cuts function bodies at 400 tokens. Stage 1 embedded every function and method in full.
- The product chunker made only 2 chunks for the ggplot2 pack, so the dense list held almost no ggplot2 file.
- voyage-code-4 gave negative cosines for every row of the Express pack. The cut at 0 in the NumPy search path emptied the list until PR 312.
- The model can know these public repositories. A gain can come from that knowledge and not from the question words.
- Worst-of-3 scoring counts sampling variance as loss. Each page was sampled 3 times with no cache.
- A foreground index embeds the full pack again. The candidate had no incremental cost reuse.
- Separate finding, not fixed here: when `OPENAI_API_KEY` is set, the existing embedding auto-detection sends source text to OpenAI after an explicit index call.

## What stays

The shared consent function `workspace_consent` in `systemone_ranker.py` and the `max_bytes` argument of `post_json` stay. The hosted rerank uses the consent function. The provider, the retrieval branch, the harness and the trial workflow are removed. Ranking defaults do not change.
