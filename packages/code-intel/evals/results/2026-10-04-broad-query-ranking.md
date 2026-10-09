# Broad lexical query ranking: paired local evaluation

**Conclusion: semantic ranking improvement is not proven. The experimental
rank-changing rule is off by default.** A final post-tuning holdout regressed
despite positive development packs. A separate, order-preserving file-diversity
change improved five-hit file coverage on 60 judged queries. Match
explanations, ambiguity reporting, and deterministic ties remain enabled.

The first full-concept bonus (applied to queries of 2–5 concepts) failed the
development gate: on 15 existing attocode/FastAPI source-labeled questions,
mean MRR@10 fell from 0.481 to 0.232, with 8 losses and no wins. It promoted
incidental words in documentation, examples, and large source windows. That
version was replaced before the case pack below was evaluated.

The experimental rule is deliberately narrow. It only reorders two-concept queries
when the existing top hit covers one concept, and it only boosts complete
matches in implementation source. Longer queries retain their established
ranking. Source paths in `legacy`, `lessons`, `eval`, `examples`, and
`docs_src`, along with ordinary docs/tests, do not earn the default bonus.
If the best implementation component has a complete match, the bonus stays
within that component; otherwise a complete match elsewhere can rescue an
incomplete top hit.
The evaluator explicitly enables the experimental flag for its treatment arm.
The baseline restores the pre-feature ordering function;
both arms share the same warmed local AST/FTS5 candidates and deterministic
tie-breaks. No embedding or optional model reranker was used.

The 20-case [judgment pack](../broad_query_cases.yaml) covers four two-concept
implementation questions each in attocode, FastAPI, pandas, Redis, and gh-cli.
It was written from existing source-bound judgments before its first run.
External repositories were copied to temporary workspaces so their working
trees and caches were untouched. Every gold file existed and every index
reported ready. Two fresh-build repetitions gave identical quality scores:

| Metric | Prior order | Current order | Query wins / losses / ties |
|---|---:|---:|---:|
| MRR@10 | 0.465 | 0.551 | 3 / 0 / 17 |
| NDCG@10 | 0.391 | 0.438 | 3 / 0 / 17 |
| Recall@20 | 0.650 | 0.675 | 1 / 0 / 19 |

The MRR wins moved `fastapi/routing.py` from rank 7 to 1 for “response
serialization,” `src/rdb.c` from 4 to 1 for “rdb persistence,” and
`api/client.go` from outside the first 20 to rank 9 for “api authentication.”
The [secondary 20-case pack](../broad_query_external_cases.yaml) covered
Express, Requests, Vapor, Phoenix, and ripgrep. Its first run found a
Requests win but an NDCG loss for ripgrep “glob matching”: a CLI file was
promoted between two directly relevant globset files. The component guard
fixed that regression. With the final rule, the secondary pack measured
MRR@10 0.596 → 0.633, NDCG@10 0.631 → 0.648, and recall@20 unchanged
at 0.925 (1 win, 0 losses, 19 ties for MRR).

Across both development packs (40 queries, 10 repositories), mean MRR@10 was 0.531 →
0.592, NDCG@10 0.511 → 0.543, and recall@20 0.788 → 0.800. MRR and NDCG
each had 4 wins, 0 losses, and 36 ties. These are paired development
comparisons, not a blind post-tuning holdout: the ripgrep failure was used to
refine the rule. These results did not establish generalization.

The [final frozen holdout](../broad_query_final_holdout.yaml) used 20 new
questions in Faker, Starship, spdlog, Protobuf, and Prisma. Every gold file
existed and every query had two concepts before ranking was run. It measured
MRR@10 **0.436 → 0.410** and NDCG@10 **0.482 → 0.442** (1 win, 2 losses,
17 ties); recall@20 rose 0.775 → 0.800. For Starship “config loading,” the
old order correctly put `src/config.rs` first, while the experimental rule
pushed it out of the first 20 by boosting unrelated module windows. The
holdout falsifies the proposed overall-quality claim even though the combined
mean across all 60 cases remains positive. We did not tune on this final
holdout and then relabel it as blind.

## Default file-page diversity

After disabling the experimental promotion, the default was changed only for
small pages of unscoped multi-concept queries: take the first hit from each
file in the original file order when enough distinct files exist to fill the
page. If not, return the original page. The first-hit file and relative order
of first file occurrences are invariant. This cannot make file-level recall
at that page size worse, although it can omit a second useful symbol from
the same file; exact, scoped, and test-seeking queries are exempt.

Using the same three frozen case packs with `--top-k 5 --treatment default`
gave 60 paired questions across 15 repositories:

| Metric | Prior page | Diverse page | Query wins / losses / ties |
|---|---:|---:|---:|
| Distinct files in five hits | 3.97 | 5.00 | 35 / 0 / 25 |
| File recall@5 | 0.533 | 0.575 | 5 / 0 / 55 |
| File MRR@5 | 0.480 | 0.491 | 3 / 0 / 57 |
| File NDCG@5 | 0.450 | 0.471 | 5 / 0 / 55 |

This proves a narrow file-coverage gain on these labels, not better intent
understanding. For example, the default “cache generation” top hit remains
unrelated lifecycle code and its five-hit page still lacks the code-intel
cache implementation. The ambiguity indicator tells the caller to narrow
the query; the experimental promotion finds that implementation but fails
the independent safety check above.

Thirty longer, independently authored queries from the existing source-label
files had identical paired scores with the experimental rule. With that flag
enabled, a local product call ranked the code-intel source cache
implementation first for “cache generation” and reported ambiguity. “Source
cache generation” still ranked unrelated lifecycle code first. Neither
observation justifies enabling the experimental reranker by default.

The treatment added roughly 5–11 ms to median paired lexical search in
representative runs, though machine timing varied substantially. The 100/1,000/10,000
file daily bootstrap gate passed. Its last 10,000-file run emitted a
source-body indexer shutdown warning and took 12.3 seconds for warm
bootstrap, so this is not a clean resource/performance pass. Relevance labels are incomplete, and the
isolated lexical test does not measure end-to-end developer task success. A
stronger candidate reranker needs independent judgments and real user-query
replay before an overall-quality or release claim.

Reproduce with the commands below. Commit `5b67651` is the last commit with
`eval/ranking_pair.py`. Run the commands in a checkout of that commit:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/code-intel/src .venv/bin/python -m eval.ranking_pair \
  --repos attocode fastapi pandas redis gh-cli \
  --case-pack packages/code-intel/evals/broad_query_cases.yaml \
  --json /private/tmp/attocode-ranking-pair.json

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/code-intel/src .venv/bin/python -m eval.ranking_pair \
  --repos faker starship spdlog protobuf prisma \
  --case-pack packages/code-intel/evals/broad_query_final_holdout.yaml \
  --top-k 5 --treatment default \
  --json /private/tmp/attocode-ranking-file-page.json
```

The case-pack SHA-256 was
`c9b22a7a6be11067cf8bab61798af31f9dab9c2367592ea5cfebd9c96f4ddc9d`.
Raw repeated outputs from this run are
`/private/tmp/attocode-ranking-stable-a.json` and
`/private/tmp/attocode-ranking-stable-b.json`. Final paired outputs are
`/private/tmp/attocode-ranking-judged20-v3.json` and
`/private/tmp/attocode-ranking-external20-v2.json`. The final holdout SHA-256
is `ea2151f99e6fec0ddbaa210de9b50428e7f2f78e196cc529c6f20147d1913589`;
its raw result is `/private/tmp/attocode-ranking-final-holdout.json`.
The default file-page results are
`/private/tmp/attocode-ranking-file-page-a.json`,
`/private/tmp/attocode-ranking-file-page-b.json`, and
`/private/tmp/attocode-ranking-file-page-holdout.json`.
