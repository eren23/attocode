# Blind graded rerank trial and Loc-Bench check

**Status: Jev `choice` reranking improved both new blind packs. The adapter
stays opt-in. The default candidate count changes from 12 to 24.** These are
exploratory results on fixed queries from six repositories per pack. The local
Bosun 0.6B model shows no clear gain, also with GPU access. A local 4-bit
Clef-flash comes close to Jev on graded relevance, but it takes 8–10 s per
query on a base M5. On four of six
repositories, a lexical+CodeRankEmbed fused pool gave the best result with
Jev, mostly on vocabulary-mismatch queries. Dense retrieval is not in the
product yet.

## What we compared

Two packs were new to every arm.

- **Graded blind pack** ([`graded_blind_pack.yaml`](../graded_blind_pack.yaml)).
  It has 36 queries over six repositories that no earlier pack used: okhttp
  (Kotlin), sqlite (C), ggplot2 (R), postgrest (Haskell), rails (Ruby), and
  crystal. Each repository has three `source` queries and one each of
  `vocab_mismatch`, `multi_file`, and `test`. Labelers read only the source
  code. They did not use attocode tools, and they wrote all labels before
  any arm ran. Grades are 3 (primary implementation), 2 (directly involved),
  1 (context), and 0 (judged not relevant).
- **Loc-Bench title pack** ([`locbench_title_pack.yaml`](../locbench_title_pack.yaml)).
  It has 42 instances from
  [Loc-Bench V1](https://huggingface.co/datasets/czlll/Loc-Bench_V1), which
  contains 2025 GitHub issues. The query is the issue title. The labels are
  the `.py` files in the fix (`edit_functions`). We did not write these
  labels. The selection rule was fixed before any run: six repositories
  (yt-dlp, dask, sqlglot, prefect, mypy, sentence-transformers), and the
  first seven instances by ID with a 3–12 word title. Each instance runs at
  its own `base_commit` in a separate worktree.

`eval.ranking_pair --top-k 400 --pool-files 48` froze one lexical candidate
pool per query. Commit `5b67651` is the last commit with this script. The eval
matrix cell `product_noimp` now gives the same file order (36 of 36 blind
queries). Every arm reranks the first 12, 24, or 48 files of that same
pool, with the same 1,350-character query-focused excerpts.

**Pooled judging.** Graded NDCG refuses to score unjudged files. After the
arms ran, the scorer listed 234 unjudged files from the first five of any
arm (now `eval.matrix.run report --unjudged`). Three judges graded them on
the same scale. The judges did not know which arm returned a file. They
found no new grade-3 file and 23 new grade-2 files. A third round graded 46
files from the two
local models (Bosun 1.7B and Clef-flash): 24 got 0, 22 got 1, and none got 2
or 3. Every first-five file of every arm below is judged.

## Graded blind pack

| Arm | gNDCG@5 | Wins / losses | Range of gain | Primary MRR@5 | Recall@5 | Median / p95 |
|---|---:|---:|---:|---:|---:|---:|
| Lexical baseline | 0.476 | — | — | 0.565 | 0.312 | — |
| Jev `choice`, 12 files | 0.652 | 28 / 3 | +0.118 to +0.235 | 0.843 | 0.376 | 409 / 528 ms |
| Jev `choice`, 24 files | 0.701 | 31 / 2 | +0.131 to +0.315 | 0.870 | 0.390 | 454 / 587 ms |
| Jev `choice`, 48 files | 0.741 | 31 / 1 | +0.165 to +0.362 | 0.876 | 0.399 | 517 / 627 ms |
| Bosun v3.1 0.6B, 12 files | 0.488 | 21 / 13 | −0.073 to +0.100 | 0.568 | 0.336 | 4.57 / 5.90 s |
| Bosun v3.1 1.7B, 12 files (local) | 0.541 | 23 / 10 | −0.010 to +0.136 | 0.664 | 0.353 | 3.15 / 3.92 s |
| Clef-flash 4-bit, 12 files (local) | 0.636 | 28 / 6 | +0.106 to +0.219 | 0.766 | 0.398 | 7.88 / 10.23 s |

Primary MRR@5 counts grade 2 and 3 files. Recall@5 counts grade 1–3 files.
Each judging round adds grade-1 files, so Recall@5 goes down for every arm.
The values above use all three rounds. The range of gain is the 2.5th to
97.5th percentile of a 10,000-draw bootstrap that resamples the six
repositories. With six clusters, it describes these fixed queries. It is not
a significance test, and it does not predict other repositories. The wins and
losses are not independent either, because each repository adds six related
queries. In this document, "clear gain" means that the range excludes zero.

gNDCG@5 by intent:

| Arm | source | multi_file | test | vocab_mismatch |
|---|---:|---:|---:|---:|
| Lexical baseline | 0.618 | 0.563 | 0.330 | 0.108 |
| Jev, 24 files | 0.818 | 0.834 | 0.650 | 0.269 |
| Jev, 48 files | 0.854 | 0.846 | 0.735 | 0.302 |
| Bosun, 12 files | 0.589 | 0.563 | 0.443 | 0.153 |
| Jev, 12 files | 0.768 | 0.764 | 0.598 | 0.248 |
| Bosun 1.7B, 12 files | 0.709 | 0.678 | 0.307 | 0.133 |
| Clef-flash 4-bit, 12 files | 0.758 | 0.745 | 0.595 | 0.201 |

Vocabulary-mismatch queries stay weak with every reranker. A reranker cannot
fix a file that the lexical pool does not contain.

**48 against 24 files.** Jev at 48 files had 18 gNDCG wins and 7 losses
against Jev at 24 files (range +0.031 to +0.048). The Recall@5 range includes
zero (−0.006 to +0.024). The 48-file request sends twice the
source excerpts, about 65 KB against 32 KB per query.

## Loc-Bench title pack

| Arm | MRR@5 | Wins / losses | Range of gain | Recall@5 | Median |
|---|---:|---:|---:|---:|---:|
| Lexical baseline | 0.353 | — | — | 0.571 | — |
| Jev `choice`, 12 files | 0.719 | 23 / 0 | +0.226 to +0.498 | 0.762 | 393 ms |
| Jev `choice`, 24 files | 0.735 | 26 / 1 | +0.238 to +0.524 | 0.833 | 423 ms |
| Jev `choice`, 48 files | 0.762 | 26 / 0 | +0.291 to +0.518 | 0.833 | 519 ms |
| Bosun v3.1 1.7B, 12 files (local) | 0.450 | 16 / 9 | −0.020 to +0.209 | 0.571 | 3.24 s |
| Clef-flash 4-bit, 12 files (local) | 0.510 | 16 / 7 | −0.002 to +0.314 | 0.738 | 9.69 s |

Gold-file recall in the first 5, 12, 24, and 48 pool files is 0.571, 0.762,
0.833, and 0.857. The interval clusters on the six source repositories, not on
instances. These labels are narrow: most instances have one gold file. Jev
could have seen these public issues in training.

The [full 560-instance run](2026-10-08-locbench-560.md) found that these
42 instances are easier than the full set.

## Pool depth

Share of the known grade 2–3 files in the first *k* pool files (graded pack).
Judging stopped at each arm's first five files, so a relevant file deeper in
the pool can be unknown. These values are known-positive capture, not
exhaustive recall.

| k | 5 | 12 | 24 | 48 |
|---|---:|---:|---:|---:|
| Known primary capture | 0.397 | 0.595 | 0.700 | 0.818 |

The product reranked distinct files from only `max(top_k, 24)` chunks. That
often gave fewer files than the ranker could accept. Retrieval at 400 chunks
had a median of 24 ms and a maximum of 143 ms on these repositories.

## Local decision models

Three models ran on this machine (Apple M5, 24 GB) on loopback port 8765.
They used the same frozen pools, the same 12 files, and the same adapter
(`systemone-http`). No run had a fallback.

- **Bosun v3.1 0.6B and 1.7B** ran in `jev-compatible-server` 0.1.1 with torch
  2.14.1 and MPS. The server needed `peft`, and it downloaded the public
  adapter weights. Do not send `--model-id`: the server answers with
  `Hanno-Labs/bosun-v3.1-0.6b`, and the adapter rejects a different echo as
  `invalid_response`.
- **Clef-flash 4-bit** is the
  [MLX port](https://huggingface.co/mlx-community/clef-flash-4bit) of
  Cloudflare's Clef-flash (9B). It ran with its own `clef_mlx.py serve`,
  mlx 0.32.3, and mlx-vlm 0.7.6. Its server binds 127.0.0.1 by default.

| Model | Blind gNDCG@5 | Blind primary MRR@5 | Loc-Bench MRR@5 | Median per query |
|---|---:|---:|---:|---:|
| Lexical baseline | 0.476 | 0.565 | 0.353 | — |
| Bosun 0.6B | 0.488 | 0.568 | — | 4.6 s |
| Bosun 1.7B | 0.541 | 0.664 | 0.450 | 3.2 s |
| Clef-flash 4-bit | 0.636 | 0.766 | 0.510 | 7.9–9.7 s |
| Jev (hosted), for reference | 0.652 | 0.843 | 0.719 | 0.4 s |

**Clef-flash is the first local model with a clear gain on the blind
pack.** Against Jev at 12 files, it had 14 gNDCG@5 wins and 16 losses, so the
two are close on graded relevance. Jev puts a primary file first more often.
On Loc-Bench, Clef-flash gets the fixed file into the first five almost as
often as Jev (Recall@5 0.738 against 0.762), but at a lower rank. Its
Loc-Bench range includes zero.

**Bosun 1.7B is better than 0.6B, but its gNDCG@5 range includes zero.**
It is weak on `test` queries (0.307 against 0.330 for the baseline).

**Latency.** Clef-flash took 8–10 s per query here. The model card reports
0.31 s at 1k tokens on an M5 Max. Our requests have about 4,000–5,000 tokens,
and the machine was 17–27 GB into swap during the runs. These numbers are an
upper bound for this machine. Local Clef-flash is a candidate for background
ranking, for example `bootstrap` or a prefetch. It is too slow for each
interactive search on a base M5.

## Dense retrieval

`eval.dense_pool` embeds every tracked text file in 40-line windows with
[CodeRankEmbed](https://huggingface.co/nomic-ai/CodeRankEmbed) on MPS. It
writes a dense-only ranking and a lexical+dense pool fused with reciprocal
rank fusion (k=60). **This arm covers four of six repositories** (okhttp,
sqlite, ggplot2, postgrest, with 24 queries). The machine ran out of memory (33 GB
in swap) while it embedded rails, so we stopped the run. The rows below
compare all arms on the same 24 queries. A second judging round graded 68
new first-five files: 31 got 0, 37 got 1, and none got 2 or 3.

| Arm (24 queries) | gNDCG@5 | Wins / losses vs. lexical | Range of gain | vocab_mismatch gNDCG@5 |
|---|---:|---:|---:|---:|
| Lexical baseline | 0.530 | — | — | 0.130 |
| CodeRankEmbed only | 0.666 | 15 / 8 | +0.088 to +0.201 | 0.272 |
| Lexical + dense RRF | 0.653 | 17 / 5 | +0.102 to +0.158 | 0.116 |
| Jev, 24 files, lexical pool | 0.701 | 20 / 2 | +0.079 to +0.287 | 0.301 |
| Jev, 24 files, fused pool | 0.772 | 22 / 1 | +0.189 to +0.333 | 0.494 |

Known primary capture in the first *k* files (same 24 queries):

| Pool | 5 | 12 | 24 | 48 |
|---|---:|---:|---:|---:|
| Lexical | 0.481 | 0.644 | 0.725 | 0.836 |
| CodeRankEmbed only | 0.527 | 0.667 | 0.752 | 0.795 |
| Lexical + dense RRF | 0.544 | 0.715 | 0.834 | 0.886 |

Jev on the fused pool against Jev on the lexical pool: gNDCG@5 had 13 wins
and 9 losses (range +0.025 to +0.117). The Recall@5 range includes zero.
The fused pool helps most on vocabulary-mismatch queries. The query-time cost
is about 20 ms, but embedding a repository took 4 to 28 minutes on this
machine (3,885 to 18,483 chunks). Product dense retrieval needs an index
that updates in the background before it can be a default.

## Product changes

- `ATTOCODE_INTEL_RANKING_MAX_CANDIDATES` defaults to 24 (was 12). 48 is the
  quality setting.
- With the SystemOne provider on, search retrieves `8 × max_candidates`
  chunks before ranking, so the ranker usually gets the files that it can
  accept. Some result sets stay smaller: even at 400 chunks, 3 of 36 blind
  pools held 24, 34, and 43 distinct files.
  The default path keeps `max(top_k, 24)`.
- With the SystemOne provider on, `_task_file_scores` ranks its candidates
  through the same adapter. This reaches the `task_hint` paths of
  `relevant_context`, `find_related`, `search_symbols`, `explore_codebase`,
  `repo_map_ranked`, and `suggest_tests`. `bootstrap` already used the adapter.
- `bug_scan` sends its findings through the confidence scorer, as the rule
  pipeline does. This is a no-op unless `ATTOCODE_FLAG_CONFIDENCE` is set.
- The Jev scorer's local backend uses a non-loopback `JEV_BASE_URL` only when
  the value comes from the process environment and local-only mode is off. A
  repository `.env` can no longer send the machine's `OPENJEV_API_KEY` to a
  host that the repository picked.

## Limits

- Claude agents wrote the graded labels and the pooled judgments. The labels
  came before any arm ran. The judgments came after, without arm identity.
  An LLM judge can share an LLM ranker's idea of relevance.
- The judges did not grade tests the same way. Two judges capped tests at 1
  for non-test queries. One judge gave 2 to tests and docs whose main topic
  was the query. The second-round judge capped all of them at 1. This
  affects a few files in ggplot2 and postgrest.
- Each arm ran once. API cost was not captured.
- The trial chose excerpt lines with every query word. The product drops the
  words after an exclusion such as "avoid". This changed 29 of 1,685 excerpts
  in the blind pools, all for one query (`random jitter to avoid
  overplotting`). That query was not rerun with product excerpts.
- Loc-Bench V1 issues are public 2025 issues. A hosted model may have seen
  them in training.
- Loc-Bench queries are issue titles, not short navigation queries. Most
  instances have one gold file.

## Reproduce

The first command needs `eval/ranking_pair.py`. Run it in a checkout of commit
`5b67651`, or start from the frozen `pool.json`. The trials of this run came
from `eval/model_rerank_trial.py`, and commit `1386961` is the last commit
with that script. Now the rerank stage of the eval matrix runs them. The other
commands run on the current code.

```sh
PYTHONPATH=packages/code-intel/src .venv/bin/python -m eval.ranking_pair \
  --repos okhttp sqlite ggplot2 postgrest rails crystal \
  --case-pack packages/code-intel/evals/graded_blind_pack.yaml \
  --top-k 400 --pool-files 48 --treatment default --json pool.json
.venv/bin/python -m eval.dense_pool --pool pool.json --out coderank --cache embcache
.venv/bin/python -m eval.matrix.run import-legacy scores --pack graded_blind=.
.venv/bin/python -m eval.matrix.run run scores --stage snapshot
.venv/bin/python -m eval.matrix.run run scores --stage rerank --config eval/matrix/configs/legacy.yaml \
  --dataset graded_blind --arms jev-choice --budget-usd 0.10
.venv/bin/python -m eval.matrix.run report scores --cells 'lexical,lexical>jev-choice.24' \
  --baseline lexical --unjudged unjudged.yaml
```

The import reads every pool and trial output in the folder. `pool.json` gives
the cell `lexical`, and each other file gives a cell with its file name, such
as `jev24`. A cell that covers only some queries, such as the four-repository
dense arm, needs an `--ids` file with the ids of those queries.

The import also loads the Jev answers of the trials into `cache.db` in the
matrix cache. The rerank stage makes the cell `lexical>jev-choice.24`, and a
request that is in the cache costs nothing. The stage reads the excerpts from
the snapshot, which is the HEAD of each repository.

On 2026-10-09, 35 of the 36 requests came from the cache. The trial scored
the excerpt lines with all query terms. The current excerpt drops a negated
term, as the product does.
Thus `random jitter to avoid overplotting` got a new excerpt and one new call
($0.0006). The cell gave the same gNDCG@5 as `jev24` (0.701), with no wins
and no losses.

To make the lexical pool again with the current code, run the matrix stages
after the import:

```sh
.venv/bin/python -m eval.matrix.run run scores --stage retrieve --arms product_noimp
.venv/bin/python -m eval.matrix.run run scores --stage rows --arms product_noimp
.venv/bin/python -m eval.matrix.run report scores --cells lexical,product_noimp --baseline lexical
```

For a local model, start its server on loopback. The `systemone-http` entry
of `legacy.yaml` sends 12 files to port 8765, with a 30-second limit and no
model ID:

```sh
python clef_mlx.py serve --port 8765   # in the clef-flash-4bit snapshot, mlx-vlm>=0.7.4,<0.8
.venv/bin/python -m eval.matrix.run run scores --stage rerank --config eval/matrix/configs/legacy.yaml \
  --dataset graded_blind --arms systemone-http
```

The stage sends one query at a time. When a call times out, the stage waits
for the call to end before it sends the next query. A first call can time out
while the server loads the model. To send the failed queries again, run the
stage again with `--retry-failed`.

For Loc-Bench, pass each instance as `name=/path/to/worktree` to
`--repos`, and import the folder with `--pack locbench_title=DIR`. Then run
the rerank stage with `--dataset locbench_title`. The title-pack table
compares MRR@5, so add `--metric mrr5` to the report. On 2026-10-09, all 42
requests came from the cache. The Loc-Bench 560 run sent 27 of the same
requests again, and the cache keeps the answer that it loaded first. With the
560 answers loaded first, MRR@5 was 0.729, against 0.735 for `jev24`.

Raw outputs are outside `/private/tmp`, under
`~/Documents/AI/attocode-evals/2026-10-08-blind/` and
`~/Documents/AI/attocode-evals/locbench/`.
