# Cockroach revalidation and 48-question retrieval cycle

The Cockroach target passed on merged `8f42054`; its margin remains narrow.
Neither retrieval candidate qualified on development, so no ranking policy or
opt-in product flag was added. All 48 frozen questions were evaluated. This
cycle does not publish a release or rerun the full release gate; PyPI remains 0.1.6.

## Cloud target

The [cloud record](2026-10-15-headroom-cloud.json) binds the exported report,
source, harness, fixtures and independent cleanup check. Eight workflow checks
produced four passes and four explicit label limitations, with zero failures or
incomplete checks. The four retrieval observations yielded 0/4 labeled Hit@5
and 1/4 Hit@24; a workflow pass is not a retrieval-quality pass.

| Measurement | Previous released-source run | This merged-source target |
| --- | ---: | ---: |
| Checks plus retrieval queries | 177.579 s | 167.970 s |
| Keyword indexing | 28.037 s | 26.582 s |
| Body indexing | 68.810 s | 66.615 s |
| Restart | 19.691 s | 19.605 s |

The unchanged pack deadline is 180 seconds. The observed margin is 12.03 seconds; workflow time
remains above the descriptive 150-second headroom target. This single
unprofiled observation does not isolate either repair or establish a general
speedup. Supervised workflow time including setup was 189.393 seconds; the
controller took 313.137 seconds, within its unchanged 90-minute limit.

One worker was used and deleted; the independent inventory found zero remaining
quality workers. All 22 ledger rows have verified cleanup and the prior 21 rows
are unchanged. This run added **$0.0145 estimated compute**, cumulative **$0.9264**
before tax, not an invoice. The second $1 reservation remains unused and cannot
be launched after a passing target. Only 47,307 report/log bytes returned locally.

## Frozen retrieval comparison

The [protocol](../designs/2026-10-15-headroom-retrieval.md) and
[48-question manifest](../designs/2026-10-15-headroom-retrieval-questions.json)
were frozen before retrieval. Each of six cached repositories contributed four
development and four validation questions. Source anchors are non-exhaustive;
repositories have prior evaluation exposure and some files occur in both splits.
No questions were replaced after results.

Candidate A used the original query with existing fusion. Candidate B combined
expanded and original-query ordered file lists using equal-weight RRF (k=60)
and existing test-intent demotion. Warmed query latency is the median of three
alternating measurements; dual-query latency includes both retrieval calls.
The [machine-readable record](2026-10-15-headroom-retrieval.json) retains the
choice frozen before validation, input hashes, pools, ordered files, label
coverage, repetitions and resource supervision.

| Development arm | Hit@5 | Hit@24 | Mean labeled Recall@5 | MRR@24 | p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Current expanded baseline | 18/24 | 23/24 | 0.646 | 0.479 | 36.59 ms |
| Original query | 18/24 | 23/24 | 0.646 | 0.485 | 37.71 ms |
| Equal-weight dual query | 18/24 | 23/24 | 0.646 | 0.486 | 74.36 ms |

Neither achieved the required three net additional hits at five. The frozen
choice is `none`; validation ran the baseline only, reaching **15/24 at five,
21/24 at 24**, with p95 **38.21 ms**. No candidate validation claim is made.
Together, the baseline reached **33/48 (68.75%) at five** and **44/48 (91.67%)
at 24**. This measures labeled source retrieval, not agent task completion.

| Repository | Development Hit@5 / Hit@24 | Validation Hit@5 / Hit@24 |
| --- | ---: | ---: |
| Express | 4/4 / 4/4 | 4/4 / 4/4 |
| ripgrep | 2/4 / 4/4 | 0/4 / 3/4 |
| Redis | 4/4 / 4/4 | 3/4 / 4/4 |
| OkHttp | 2/4 / 3/4 | 2/4 / 3/4 |
| Cats Effect | 2/4 / 4/4 | 3/4 / 3/4 |
| Phoenix | 4/4 / 4/4 | 3/4 / 4/4 |

## What the misses establish

All labels for the four top-24 misses were present in both keyword and body
indexes. Three misses had a labeled file in retained stage pools but below the
final delivered page: OkHttp decompression (final fused ranks 31/38), ripgrep
named file types (body rank 2, final fused rank 32), and OkHttp alternate
connections (body rank 34, final fused rank 39). The Cats Effect backpressure
label was indexed but absent from all retained stage pools for that question.
These are retrieval/ranking limitations; no missing-index correctness defect
was demonstrated. They motivate a separately frozen future experiment, not
post-validation tuning of this one. All questions are now consumed evidence.

## Validation and resource use

The [validation record](2026-10-15-headroom-validation.json) contains matching
source hashes, controller reports and the unchanged frozen ranking result.
The local suite passed **639 tests, eight skipped**, plus lint, scale and
lifecycle checks. The ranking gate passed all 68 query variants across five
methods against its existing tolerances. This cycle makes no product ranking
change; it does not claim exact parity with the older historical baseline.

Six bounded retrieval invocations took **33.309 seconds total**, with peak
managed storage **102.7 MiB** and sampled process-tree RSS **125.8 MiB**. Each
invocation stayed below 180 seconds, 512 MiB storage and 1.5 GiB RSS. One source
pack was materialized at a time, with a 64 MiB source cap. All task-owned source,
index and cache directories were removed; reports remain. Protected studies
and shared caches were untouched. No downloads, model calls, host MCP restart
or global tool upgrade occurred.
