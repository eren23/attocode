# Hosted embedding screen (2026-11-01)

**Result: both models PASS the frozen gates. voyage-code-4 is the winner.** Each model embedded every function and method of 50 public Loc-Bench tasks through OpenRouter. The model list, fused with the product list, finds the gold files at five in 40 of 50 tasks. The product list alone finds them in 28. Stage 2 (a product opt-in, then fresh questions) can start for voyage-code-4. This change adds no product code.

- Design: [`designs/2026-11-hosted-embed-screen.json`](../designs/2026-11-hosted-embed-screen.json), SHA-256 `03144ca0ae0c67ae34ba178730d316bc8c4410dddff30cdcd99c4be2e94622ea`, and [`designs/2026-11-hosted-embed-screen.md`](../designs/2026-11-hosted-embed-screen.md). 50 tasks, sampled with seed 20261101 from the 560 Loc-Bench tasks.
- Harness and workflow: commit `9568bea` (PR 307), `eval/matrix/embed_screen.py` and `.github/workflows/embed-screen.yml`.
- Runs: [41336572221](https://github.com/eren23/attocode/actions/runs/41336572221) and [41337571267](https://github.com/eren23/attocode/actions/runs/41337571267), both at head `9568bea`. The decision uses the second run only.
- Raw data: [`2026-11-hosted-embed-screen.tar.gz`](2026-11-hosted-embed-screen.tar.gz) (SHA-256 `e17b1fa435da6a55ea5ab72ac345f4193ea5868893132dd6edb09f35b6819b47`, 18 files). It holds the artifacts of both runs, `recompute.py` and `corrected-decision.json`. The compact record is [`2026-11-hosted-embed-screen.json`](2026-11-hosted-embed-screen.json).

## Why this screen

The miss census of the test-recall trial found 7 of 12 judged misses outside the candidate pool. In these misses, the question words do not occur in the code. A rerank or a query rewrite did not fix this (see the [query-rewrite result](2026-11-query-rewrite.md)). On Loc-Bench, function-level CodeRankEmbed reached .739 Acc@5, but it needs a GPU. This screen asks whether a hosted embedding model gives the same gain without a GPU.

## What happened

1. **Run 1 (41336572221)** prepared all 50 tasks. The key usage step then got status 401, because the environment secret was empty. No embedding request was sent. The design permits a fix and a new dispatch when a run stops before scored work.
2. **Run 2 (41337571267)** completed both models on all 50 tasks.

| | voyage-code-4 | codestral-embed-2505 |
|---|---|---|
| Tasks complete | 50 | 50 |
| Unique units embedded | 191,334 | 191,334 |
| Requests / retries / splits / refused inputs | 6,155 / 0 / 0 / 0 | 6,155 / 0 / 0 / 0 |
| Request variant | `input_type` and `data_collection: deny` | same |
| Dimensions | 1,024 | 1,536 |
| Tokens | 34,142,439 | 36,749,636 |
| Seconds | 355.5 | 966.4 |
| Spend (harness) | $4.097 | $5.512 |

The design estimated 191,451 unique units. The harness counts 191,334, because it removes duplicates after it cuts each text to 3,584 characters.

## Results (Acc@5 on gold files, 50 tasks)

| List | Hits at 5 |
|---|---|
| Product (reference) | 28 |
| Product fused with voyage-code-4 | **40** |
| Product fused with codestral-embed-2505 | **40** |
| voyage-code-4 alone | 45 |
| codestral-embed-2505 alone | 44 |
| CodeRankEmbed function units, local GPU (reference) | 41 |
| Product fused with CodeRankEmbed (reference) | 39 |

Paired counts, each written as [first list hits and second misses, second hits and first misses]:

| Pair | voyage-code-4 | codestral-embed-2505 |
|---|---|---|
| Fused against product (gated) | 13 / 1 | 13 / 1 |
| Model alone against product | 18 / 1 | 17 / 1 |
| Model alone against CodeRankEmbed | 4 / 0 | 3 / 0 |
| Fused against CodeRankEmbed | 3 / 4 | 3 / 4 |
| Model alone against fused | 5 / 0 | 4 / 0 |

- The two models agree closely: 44 tasks are hits for both, and 45 for at least one.
- **The fusion lowers the result.** Each model alone is better than its fused list, and the fusion never adds a hit. In the 5 voyage tasks that the fusion loses, voyage ranks the gold file at 0 to 4 and the fused list at 7 to 13. Equal-weight RRF lets the weaker product list push these files down. Stage 2 must not copy this fusion without a new check.
- For voyage-code-4, the one loss against product is `vllm-project__vllm-10076` (`vllm/entrypoints/openai/serving_engine.py`). Both the fused list and the model alone miss it.

## Gates

| Gate | Frozen limit | voyage-code-4 | codestral-embed-2505 |
|---|---|---|---|
| Complete | at most 2 incomplete tasks | pass (0) | pass (0) |
| Net gain of the fused list | ≥ 5 | **pass** (+12) | **pass** (+12) |
| Sign test against product | one-sided p ≤ 0.05 | **pass** (13 / 1, p = 0.0009) | **pass** (13 / 1, p = 0.0009) |

Winner rule: most fused hits (tie, 40 and 40), then most model-alone hits (45 against 44). The winner is **voyageai/voyage-code-4**.

## Harness fault and correction

`run_model` built each row with `tid, row = task["id"], {"model": model_id, "id": tid}`. Python evaluates the right side before the assignment, so the row id is the id of the previous task. Thus row *i* of each rows file carries the id of task *i−1*, and the first row carries the id of the last task. The content of each row (units, files, fused list, hits) is correct for task *i*, in design order.

- Effect: `decision.json` of the run pairs each task with the product result of a different task. Its counts 18 / 6 and p = 0.011 are wrong. Its totals and net gain are correct, because they do not depend on the labels. Its verdicts and winner are the same as the corrected ones.
- Correction: `recompute.py` asserts that the ids are shifted by exactly one position, relabels the rows by position, and checks again each fused list and each hit against its relabeled task. The corrected decision is `corrected-decision.json` in the archive.
- Fix: this change splits the assignment in `eval/matrix/embed_screen.py` and adds a test assertion on the row ids. The run data is not changed.

## Independent check

`recompute.py` uses only the Python standard library. It checks the design SHA, rebuilds each fused list from the product list and the model list, recomputes each Acc@5, the paired counts, the sign tests, the verdicts and the winner. The extracted archive gives output equal to `corrected-decision.json` byte for byte.

## Spend

The OpenRouter usage counter of the key rose from $0 to $9.610 (limit $20). The harness counted $4.097 + $5.512 = $9.610. This is the key counter, not an invoice. Run 1 spent nothing.

## Limits

- The Loc-Bench problem statements and repositories are public. A hosted model can have seen this code and these issues, so the gain can partly come from that knowledge.
- 50 tasks, all Python, scored by Acc@5 on gold files. They are not agent outcomes.
- The units are top-level functions and class methods outside test paths, cut to 3,584 characters. Files with no function get no vector.
- Stage 1 sends source text to a hosted provider. A product opt-in must ask for the same consent as the hosted rerank.

## Next

Stage 2, as frozen in the design: a product opt-in for voyage-code-4, off by default, with the hosted-rerank consent. Then a development screen and one validation on new, source-checked questions, with gates frozen before any call. Before the freeze, choose between the model list alone and a fusion, with the 5 / 0 result above as development evidence only.
