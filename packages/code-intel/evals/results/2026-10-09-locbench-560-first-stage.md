# Loc-Bench V1: first-stage arms with the default search weights

**Status: The published Loc-Bench lexical numbers ran with the importance and
frecency weights at zero. The product default sets the importance weight to
0.5. With the default weights, lexical file Acc@5 is 0.532 on the full issue
and 0.498 on the title. With the weights at zero, it is 0.529 and 0.495. The
difference is not clear (5 wins and 3 losses on the full issue).** The
default mode of the `semantic_search` tool also expands the query. With the
expansion, Acc@5 is 0.509 on the full issue (3 wins and 16 losses against
the same search without the expansion).

## What we ran

- **Instances.** All 560 Loc-Bench V1 instances of the
  [first run](2026-10-08-locbench-560.md), with the full issue and the title
  as queries. Ten issues have only one line, so 1,110 queries are different.
- **Engine.** The product source of commit `5b67651` (release-gate engine
  hash `5a80b624`). Pull request #128 changes the engine hash on main. Its
  checks found the same `search_candidates` lists on 5 repositories and 6
  queries.
- **Files.** The eval matrix saves the git tree at `base_commit`. It keeps
  the files that the product indexes (1 MB or smaller, and not skipped by
  type) and the links. It builds each index in a temporary folder without `.git`.
- **Product cells.** One traced `search_candidates` call per query and
  weight setting. The call reads 400 chunks, as the published pools did. A
  cell keeps the file order before the broad-query rerank, cut to 200 files.
  The default rerank keeps this order.

| Cell | What it ranks |
|---|---|
| `product_noimp` | `search_candidates` with the importance and frecency weights at zero: the published lexical pools |
| `product` | `search_candidates` with the default weights: the `keyword` mode of the tool |
| `product_auto` | the default weights on the expanded query: the default `auto` mode of the tool without embeddings |
| `kw` | the name, path, and docstring BM25 list of the `product` call |
| `body` | the source-body FTS5 list of the `product` call |
| `filebm25` | the whole-file BM25 list of the `product` call. It is empty for a query of 20 words or fewer |
| `chunkrrf` | the fused keyword and body list of the `product` call, before the whole-file fusion |
| `grep` | `git grep -F -w` for the code terms of the query (names, dotted names, quoted strings). Files score by the sum of term IDF. Files that the query names by path come first |
| `repomap` | the order of the `repo_map_ranked` tool: PageRank over imports, with search relevance from 80 chunks. It leaves out test files |

## Results

All 560 instances. Ceil@48 is the share of instances with every gold file in
the first 48 files.

| Cell | Query | Acc@1 | Acc@5 | Acc@10 | MRR@5 | Ceil@48 |
|---|---|---:|---:|---:|---:|---:|
| `product_noimp` | full issue | 0.298 | 0.529 | 0.636 | 0.408 | 0.827 |
| `product` | full issue | 0.296 | 0.532 | 0.638 | 0.407 | 0.825 |
| `product_auto` | full issue | 0.298 | 0.509 | 0.627 | 0.401 | 0.823 |
| `kw` | full issue | 0.246 | 0.464 | 0.580 | 0.351 | 0.829 |
| `body` | full issue | 0.125 | 0.232 | 0.323 | 0.177 | 0.563 |
| `filebm25` | full issue | 0.225 | 0.457 | 0.559 | 0.329 | 0.750 |
| `chunkrrf` | full issue | 0.216 | 0.382 | 0.513 | 0.292 | 0.784 |
| `grep` | full issue | 0.289 | 0.482 | 0.554 | 0.379 | 0.689 |
| `repomap` | full issue | 0.314 | 0.548 | 0.655 | 0.428 | 0.848 |
| `product_noimp` | title | 0.277 | 0.495 | 0.600 | 0.380 | 0.779 |
| `product` | title | 0.270 | 0.498 | 0.600 | 0.380 | 0.779 |
| `product_auto` | title | 0.261 | 0.489 | 0.589 | 0.370 | 0.775 |
| `kw` | title | 0.291 | 0.450 | 0.543 | 0.376 | 0.709 |
| `body` | title | 0.198 | 0.429 | 0.527 | 0.296 | 0.754 |
| `chunkrrf` | title | 0.270 | 0.498 | 0.600 | 0.380 | 0.779 |
| `grep` | title | 0.093 | 0.225 | 0.282 | 0.142 | 0.382 |
| `repomap` | title | 0.323 | 0.539 | 0.645 | 0.429 | 0.814 |

A title has 20 words or fewer, so `filebm25` is empty and `chunkrrf` equals
`product` on titles.

Paired Acc@5 on the same queries. The range is the 2.5th to 97.5th percentile
of 10,000 bootstrap draws that resample source repositories. p is a
sign-flip p-value over repositories with the Holm correction over all 40
comparisons of the report.

| Comparison | Query | Wins | Losses | Acc@5 change | Range of change | p |
|---|---|---:|---:|---:|---|---:|
| `product` against `product_noimp` | full issue | 5 | 3 | +0.004 | −0.006 to +0.014 | 1.00 |
| `product` against `product_noimp` | title | 4 | 2 | +0.004 | −0.005 to +0.012 | 1.00 |
| `product_auto` against `product` | full issue | 3 | 16 | −0.023 | −0.037 to −0.009 | 0.28 |
| `product_auto` against `product` | title | 4 | 9 | −0.009 | −0.021 to +0.004 | 1.00 |
| `repomap` against `product_noimp` | full issue | 16 | 5 | +0.020 | +0.002 to +0.039 | 1.00 |
| `repomap` against `product_noimp` | title | 26 | 1 | +0.045 | +0.022 to +0.070 | 0.01 |
| `grep` against `product_noimp` | full issue | 72 | 98 | −0.046 | −0.101 to +0.010 | 1.00 |

The importance weight changes the order of the first five files for 211 of
the 560 full issues and 219 of the 560 titles. But the hits stay almost the
same. Ceil@48 changes on 1 full issue and 2 titles. The query expansion loses
more than it wins on the full issue. The range excludes zero, but after the
Holm correction p is 0.28.

The repo map order gains on both queries. It leaves out test files, and most
Loc-Bench gold files are not tests. On the title, it also raises Ceil@48
from 0.779 to 0.814 (22 wins, 2 losses). We did not test which part of the
repo map order makes the gain.

Grep gives 0.482 on the full issue, because a full issue often names
functions and files. Its difference from `product_noimp` is not clear. Grep on
the title is weak.

## Parity with the frozen pools

The cell `product_noimp` gave the same 48-file order as the frozen lexical
pools of the first run on 1,118 of 1,120 queries. The two other queries are
the full issue and the title of `UCL__TLOmodel-1524`. This repository keeps
its data files in Git LFS. The snapshot holds the LFS pointer files, and the
checkout of the first run held the real files. So the indexed files are
different, and two files change places at rank 7 (title) and rank 9 (full
issue). Acc@5 and Ceil@48 do not change on these two queries.

On all 84 queries of the 42 dev instances, `product_noimp` and `product`
gave the same first 200 files as an earlier dump. On the
blind pack, `product_noimp` gave the same order as the frozen pool on all 36
queries.

## Limits

- The tool reads fewer chunks than 400 (`_retrieval_depth`), so its first
  files can be different from these cells.
- The stage cells come from the `product` call, so their latency is the
  latency of that call. The median `product` call took 126 ms on the full
  issue and 53 ms on the title, with three runs in parallel on one Mac.
- `grep` is a stand-in for the searches of an agent. It does not search again
  after the first results.
- Each cell ran once. Loc-Bench V1 has only Python repositories.

## Cost and time

- The snapshot stage fetched 487 commits from GitHub, one commit at a time
  per shard, and read 39 commits from local clones. The cache holds 125 MB of
  trees, 1.7 GB of file contents, and 76 MB of results.
- The retrieve stage took 166 minutes of process time in six shards, three
  at a time. A second run found all 5,550 results in the cache.

## Reproduce

`$LOCBENCH_DIR/all.json` comes from `run.py fetch`
([first run](2026-10-08-locbench-560.md#reproduce)). The stages keep their
results in `~/Documents/AI/attocode-evals/matrix/`.

```bash
.venv/bin/python -m eval.matrix.run import-legacy scores --locbench $LOCBENCH_DIR
.venv/bin/python -m eval.matrix.run run scores --stage snapshot --shard 0/3    # also 1/3 and 2/3
.venv/bin/python -m eval.matrix.run run scores --stage retrieve --shard 0/6   # also 1/6 to 5/6
.venv/bin/python -m eval.matrix.run run scores --stage rows
.venv/bin/python -m eval.matrix.run status scores
.venv/bin/python -m eval.matrix.run report scores \
  --cells product_noimp,product,product_auto,kw,body,filebm25,chunkrrf,grep,repomap \
  --baseline product_noimp --pair product:product_noimp --pair product_auto:product \
  --metric acc5 --metric ceil48
```
