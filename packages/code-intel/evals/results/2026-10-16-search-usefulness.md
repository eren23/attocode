# Search usefulness: test-page diversity rejected

The single candidate is **rejected**. It produced more distinct files in some
explicit-test searches, but no extra judged relevant files in the first five
slots on either set, and displaced a relevant code range from each set's larger
page. Product source, ranking defaults and package version are unchanged.

## Frozen comparison

The [design](../designs/2026-10-16-search-usefulness.json),
[development questions](../designs/2026-10-16-search-usefulness-development.json)
and [held-out questions](../designs/2026-10-16-search-usefulness-validation.json)
were frozen before any observations. Each set contains twelve questions across
Express, Requests, ripgrep and Gson: eight test requests and four implementation,
configuration, caller or error-handling controls. Each question has two source
file judgments with pinned commits, hashes, quotes and line anchors.

These are implementer-authored, non-exhaustive judgments from previously exposed
repositories. New questions and behaviors were held out from candidate feedback;
this is not independent user research, an agent outcome study or a proof of general
relevance. No upstream repository code was executed. No models, downloads or cloud
workers were used.

The hypothesis was that duplicate chunks crowd explicit-test result pages because
they bypass the existing first-file diversity rule. The candidate extends that
rule only to short, unscoped explicit-test queries. It preserves first-file order,
scores and candidate generation, fills remaining slots with repeated chunks, and
leaves production and scoped queries unchanged. No second candidate, sweep or
post-observation tuning was permitted. After development failed, the predeclared
held-out diagnostic ran once; it could not authorize adoption.

## Actual page results

Five-slot and 24-slot lexical-engine searches were executed separately, using their actual
candidate depths. The comparison invokes `search_candidates` with the normal query
expansion; it does not time MCP serialization, client rendering or token-budget trimming. Files are counted within the delivered slots; the evaluator
does **not** deduplicate a larger page and relabel its first five files as a
five-result page. Source anchors inside returned chunk ranges are a separate
conservative check, not a claim that every anchor was visible in a client's UI.

| Measure | Development before → after | Held-out before → after |
|---|---:|---:|
| Judged file pairs in five slots | 17/24 → 17/24 | 18/24 → 18/24 |
| Questions with any judged file in five | 11/12 → 11/12 | 11/12 → 11/12 |
| Questions with both judged files in five | 6/12 → 6/12 | 7/12 → 7/12 |
| Judged file pairs in 24 slots | 21/24 → 21/24 | 20/24 → 21/24 |
| Anchors within delivered chunk ranges at 24 | 8 → 7 | 9 → 8 |
| Warm query p95, milliseconds | 20.026 → 18.830 | 20.915 → 20.728 |

Timings are the nearest-rank p95 of per-query medians from three alternating arm
orders, measured on one Mac with the same warmed index. Setup/indexing time is
recorded separately. These small differences are descriptive, not a speedup claim.
All production and file-scoped control results were identical, as were generation
traces. Neither set met the required two first-page gains across two repositories;
both failed the no-anchor-range-loss rule. The candidate did not lose a previously
judged file at five or 24, but file-only metrics would have hidden the lost chunks.

## Concrete before and after

For **“Find tests for chunked request uploads and malformed chunked responses”**:

| Slot | Before | Candidate |
|---|---|---|
| 1 | `tests/test_lowlevel.py` | `tests/test_lowlevel.py` |
| 2 | `tests/test_lowlevel.py` | `tests/test_requests.py` |
| 3 | `tests/test_lowlevel.py` | `tests/testserver/server.py` |
| 4 | `tests/test_requests.py` | `tests/test_testserver.py` |
| 5 | `tests/test_requests.py` | `tests/test_adapters.py` |

Both labeled files were already present. The larger baseline page contained
`test_chunked_encoding_error` at slot 7 (lines 39–60); the candidate's 24-slot page
omitted that range. In the held-out JSON encoding question,
`TestGuessJSONUTF.test_guess_by_bom` at slot 11 (lines 435–437) was likewise omitted.
The one added held-out file at 24 was Gson's `LeniencyTest.java`, which does not
compensate for the missing first-page gain and these individual losses.

## Retrieval versus ordering

Across the two baseline five-slot sets, thirteen labeled file pairs were missing:
seven were present deeper in the observed fused candidate pool, while six were
absent from that pool. This diagnoses the current query depths, not an exhaustive
index or search recall ceiling. Development split: four present/three absent;
held-out split: three present/three absent. No relevance label was changed after
seeing these results.

Examples: Requests' redirect session implementation appeared first in both keyword
and body file traces but eighth in the fused file order; Express' request-accepts
test was absent from the observed pool. These are different failure modes.
Distinct-file delivery alone addresses neither one. They can motivate separately
frozen future work, but these 24 questions are now consumed and cannot be reused
as fresh validation.

## Evidence and validation

[Decision and diagnosis JSON](2026-10-16-search-usefulness-decision.json) includes
all criteria and misses. Eight adjacent `2026-10-16-search-usefulness-<split>-<pack>.json`
files preserve every before/after page, score, name, range, bounded excerpt,
stage trace and timing sample. Their serialized public copies are value-identical
to the private raw observations.

The eight bounded comparison processes took **11.067 seconds** combined, peaking
at **33.6 MiB managed disk** and **62.3 MiB sampled RSS**. Each had a 180-second,
512 MiB disk and 1.5 GiB RSS limit. Nineteen acceptance/replay checks verify actual
page scoring, every rejection condition, candidate scope and both frozen decisions.
Product and ranking checks run separately; CI and merge evidence are linked by the
pull request. No release or default change is warranted by this rejected trial.

Local verification additionally passed 829 product contracts (nine environment
skips), Ruff, synthetic scale/lifecycle and the unchanged frozen ranking gate.
[Validation measurements](2026-10-16-search-usefulness-validation-checks.json)
record their bounds and results. A fresh stdio MCP process from the configured
editable entrypoint returned the fixture's symbol successfully. Existing client
processes predated the merge; their reconnect remains a separate client action.

One judgment warrants caution: the ripgrep NUL query's regression-file anchor
checks rejection of a NUL-matching pattern with binary detection, whereas its
binary-file anchor checks a NUL byte before a match. The regression label is related
but less direct. It remains frozen and reported; excluding that pair as a sensitivity
check leaves held-out first-five counts at 18/23 in both arms and leaves both rejection
reasons intact. This post-hoc caveat is not a replacement validation set.
