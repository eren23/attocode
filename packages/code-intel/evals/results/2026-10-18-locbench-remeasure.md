# Loc-Bench re-measure (2026-10-18)

**Status: Product search on `main` (`a9c0f7e`) gives file Acc@5 0.566 on
the full issue of Loc-Bench 560. R1 (`72872ed`) gave 0.532 (+0.034, 38
wins and 19 losses). With the title as the query, the gain is +0.063
(Holm p 0.003). On SWE-bench Lite, `product` goes from 0.659 to 0.711. A
Jev rerank of the first 48 files of `rrf(product+dense)` gives 0.823. A
function-level CodeRankEmbed run on the SweRank corpora gives 74.82, and
SweRank reports 74.29. On our own snapshots with the same corpus rule,
the run gives 73.93. Thus the harness reproduces the published number.
The 13-point gap of the R1 `dense` cell comes from its unit and its
corpus, not from a harness fault.**

## What we ran

- **Code.** The product source of `main` at `a9c0f7e` (release-gate engine
  hash `44dc90a86537`). The R1 rows come from `72872ed`. A second baseline
  comes from `92b9d87`: main after the name-order walk of #138, run on a
  Linux pod for the plural-word trial.
- **Instances.** Loc-Bench V1 (560 instances, 165 repositories) and
  SWE-bench Lite (274 instances, 12 repositories). One Lite snapshot
  failed, as in R1, so the Lite comparisons use 273 instances.
- **Queries.** The full issue and the title.
- **Cells.** The free first-stage cells of the product family: `product`,
  `product_noimp`, `product_auto`, `kw`, `body`, `filebm25` and
  `chunkrrf`. The fused cell `rrf(product+dense)` uses the cached `dense`
  results of R1 (Loc-Bench only).
- **Computer.** One RTX 4090 pod made the snapshots and the retrieve stage
  for 799 snapshot groups in 21.8 minutes. The same pod ran the
  function-level embeddings. The Jev calls went from the Mac through
  OpenRouter.
- **Metric.** The LocAgent file Acc@k: a list is a hit when its first k
  files hold min(|gold|, k) gold files. Gold is the set of files of
  `edit_functions`. Ranges and p-values resample source repositories, with
  10,000 draws and the Holm correction.

## Product search now and at R1

Loc-Bench 560, Acc@5, paired on the same 560 instances:

| Cell | Query | R1 `72872ed` | `a9c0f7e` | Δ | Wins / losses | p (Holm) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `product` | full | 0.532 | 0.566 | +0.034 | 38 / 19 | 0.069 |
| `product` | title | 0.498 | 0.561 | +0.063 | 50 / 15 | 0.003 |
| `product_noimp` | full | 0.529 | 0.559 | +0.030 | 34 / 17 | 0.104 |
| `product_auto` | full | 0.509 | 0.557 | +0.048 | 42 / 15 | 0.008 |
| `kw` | full | 0.464 | 0.495 | +0.030 | 56 / 39 | 0.882 |
| `body` | full | 0.232 | 0.259 | +0.027 | 28 / 13 | 0.047 |
| `filebm25` | full | 0.457 | 0.464 | +0.007 | 23 / 19 | 1.000 |
| `chunkrrf` | full | 0.382 | 0.414 | +0.032 | 49 / 31 | 0.276 |
| `rrf(product+dense)` | full | 0.679 | 0.713 | +0.034 | 33 / 14 | 0.146 |
| `rrf(product+dense)` | title | 0.586 | 0.634 | +0.048 | 34 / 7 | 0.003 |

The `92b9d87` baseline also gives 0.532 for `product` on the full issue.
Against it, the same +0.034 has Holm p 0.028, because that report tests
fewer comparisons. Thus the walk order of #138 did not change this
number, and the gain comes from the search changes after `92b9d87`.

SWE-bench Lite, Acc@5, paired on 273 instances (12 repositories):

| Cell | Query | R1 `72872ed` | `a9c0f7e` | Δ | Wins / losses | p (Holm) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `product` | full | 0.659 | 0.711 | +0.051 | 22 / 8 | 0.347 |
| `product` | title | 0.557 | 0.619 | +0.062 | 26 / 9 | 0.395 |
| `product_noimp` | full | 0.652 | 0.711 | +0.059 | 25 / 9 | 0.347 |
| `product_auto` | full | 0.637 | 0.692 | +0.055 | 22 / 7 | 0.230 |
| `kw` | full | 0.549 | 0.615 | +0.066 | 31 / 13 | 0.493 |

Lite has only 12 repositories, so no Lite comparison passes Holm. The
three `product` cells gain on both datasets.

## Jev over 48 files

The `jev-choice` arm reranked the first 48 files of two pools on the full
issue of Loc-Bench 560:

| Cell | Acc@5 | Ceiling@48 | Δ against the pool | Wins / losses | Δ against `product` | Wins / losses |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `product>jev-choice.48` | 0.788 | 0.852 | +0.221 | 130 / 6 | +0.221 | 130 / 6 |
| `rrf(product+dense)>jev-choice.48` | 0.823 | 0.896 | +0.111 | 70 / 8 | +0.257 | 151 / 7 |

All three comparisons have Holm p 0.0007. On 2026-10-08, Jev over 48
files of a different pool (attocode lexical fused with BM25) gave 0.757.
SweRank reports 82.14 for SweRankEmbed-L alone and 86.61 with its LLM
reranker. Their corpus keeps only Python files that are not tests, and
ours keeps every file. Thus these numbers do not compare directly.

## Function-level CodeRankEmbed

The R1 harness check gave 61.4 for `dense` with only Python files, against
74.29 in SweRank Table 2. `dense` embeds 40-line windows of every source
file and scores with cosine. SweRank embeds functions:

1. The corpus is one document for each non-async `def` in a `.py` file.
   A path that contains "test" is not in the corpus. For pytest-dev
   repositories, only the file name counts.
2. A method document is the id, then `class X:`, then the method source.
   A function document is the id, then the function source.
3. The model is CodeRankEmbed at revision `3c4b608`, in bf16, with up to
   1,024 tokens. The score is the dot product.
4. The first 100 functions give the files, in the order of their first
   function.

We ran this protocol on two corpora. The first is the SweRank processed
data (`datasets.zip`, SHA-256 `92c1ce5c…`). The second is our own
snapshots, with the same rule in `eval/matrix/function_dense.py`. The
SweRank script does not show the query prefix of this cell. We ran with
and without the CodeRankEmbed prefix "Represent this query for searching
relevant code: ".

| Corpus | Prefix | Acc@5 | Acc@10 |
| --- | --- | ---: | ---: |
| SweRank Table 2 (published) | | 74.29 | 80.36 |
| SweRank corpora | yes | 74.82 | 81.07 |
| SweRank corpora | no | 75.00 | 81.25 |
| Our snapshots | yes | 73.93 | 80.71 |
| Our snapshots | no | 74.46 | 81.07 |

The scores are in fp32. Scores in bf16 change at most one instance. All
560 SweRank queries equal the problem statement, and all 560 SweRank gold
lists equal the `edit_functions` files. Our snapshots give 3.07 million
documents and the SweRank corpora give 3.19 million. 91.7% of the SweRank
document ids are also in our corpus. The SweRank builder for these
corpora is not public, so we did not find the cause of every difference.
Between the two corpora, the paired Acc@5 difference is 3 wins and 8
losses (Holm p 0.226).

Inside the matrix, the cell `fn-dense` holds the lists of our snapshots
with the prefix. On the full issue:

| Cell | Baseline | Baseline value | Value | Δ | Wins / losses | p (Holm) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `fn-dense` | `dense` | 0.602 | 0.739 | +0.138 | 91 / 14 | 0.0003 |
| `rrf(product+fn-dense)` | `rrf(product+dense)` | 0.713 | 0.745 | +0.032 | 35 / 17 | 0.031 |

Thus function units explain the R1 gap. A fusion with `product` adds only
0.005 to `fn-dense` alone. The pod embedded 709,135 unique texts in 19
minutes (669 texts each second). This cell is a measurement, not a
product feature: it reads only Python, it skips async functions and test
files, and it needs a GPU.

## Cost

- **RunPod.** One on-demand RTX 4090 pod for about 42 minutes, about
  $0.62 at about $0.89 each hour. We did not check the invoice. The cap
  was $6.
- **OpenRouter.** $0.8358 by the usage counter of the provider, for 1,120
  Jev calls. The matrix ledger counted $0.6702. The cap was $1.

## Limits

- **Latency.** The pod ran 16 retrieve workers in parallel, and R1 ran on
  the Mac and on other pods. Thus the latency columns do not compare.
  `product` gives p50 491 ms on the pod and 189 ms in R1.
- **R1 platforms.** The R1 rows mix the Mac and a pod, and R1 came before
  the name-order walk of #138. The `92b9d87` baseline was made after
  #138 and gives the same `product` value.
- **Jev.** The training data of Jev can overlap with these repositories.
  We do not know the overlap.
- **Prefix.** The query prefix of the published cell is inferred, not
  confirmed. Both settings are in the table.
- **Function units.** `fn-dense` does not see async functions, test files
  or non-Python files. Loc-Bench gold has no test files, so this rule
  removes no gold file and helps every list.

## Reproduce

1. On a pod with the matrix cache, run the snapshot stage, then the
   retrieve stage:
   `python -m eval.matrix.run run OUT --stage retrieve --arms product,product_noimp,product_auto`.
2. Write the rows: `python -m eval.matrix.run run OUT --stage rows`.
3. Run the rerank with an entry for `jev-choice` over 48 files of the
   `product` and `rrf(product+dense)` pools:
   `python -m eval.matrix.run run OUT --stage rerank --config JEV.yaml --budget-usd 1`.
4. On a GPU pod with `sentence-transformers==3.4.1` and
   `transformers==4.51.3`, run
   `python eval/matrix/function_dense.py WORK CODE CACHE INSTANCES [ZIP]`.
5. Add the `files` lists of `fn-results.json` as rows of `fn-dense`.
6. Score each dataset with `python -m eval.matrix.run report OUT --ids IDS`,
   with `--partial` for Lite.

`eval/matrix/function_dense.py` is the run script (SHA-256 `ab0ed9e1…`)
with a new usage text, four lint fixes that do not change the output and
a lazy import of `torch`.

## Artifacts

- [Summary](2026-10-18-locbench-remeasure.json): every comparison row of
  the six reports, all function-level arms, the corpus checks, the pins,
  the spend and the SHA-256 of the private result files.
- The rows and the reports stay in the private matrix run folders
  `lb-2026-10-18` and `lb-2026-10-18-vs-r1`.
