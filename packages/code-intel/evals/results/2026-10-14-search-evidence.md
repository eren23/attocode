# R3 trace audit and search preview fix

This pass used existing traces and local fixtures. It made no model calls,
opened no Claude browser pages, and changed no ranking configuration or scores.
The patch remains local and has not been released.

## Existing evidence

The [offline audit](2026-10-14-search-evidence-audit/report.md) covers all 60 R3
runs: 10 tasks, three trials, native and forced `semantic_search` setups. The
[ledger](2026-10-14-search-evidence-audit/ledger.json) binds the manifest, original
scores, run metadata, and event streams to 122 input hashes.

- All 30 tool responses reported a ready index, a 24-candidate pool, and 10
  delivered hits. No response reported files omitted by the output budget.
- Every labeled file was delivered in 18/30 treatment runs. In 9/30, no labeled
  file was delivered; the remaining 3/30 delivered only some labels. The unseen
  portion of each pool is unavailable, so these are page observations.
- In 14/30 treatment runs, an answer omitted a labeled file that search showed.
  Those omissions cover seven distinct paths and 20 hit occurrences. Eight
  occurrences had truncated previews; twelve did not. No omitted labeled path
  received an explicit successful Read after search. Grep can still expose code.

The failure patterns differ. `FileUploadImpl.java` appeared at rank 4 in all
three trials, with a preview containing only license text. `XrayService.kt`
previews omitted a reported `attachment` term. In contrast, libgdx showed the
complete `EffectPanel` constructor, and TransformerLens showed complete small
helpers or properties. A prefix fix cannot repair an unhelpful representative
chunk or a file absent from the delivered page.

These observations do not establish why an agent omitted a file. Changed-file
labels are not exhaustive relevance judgments, and the historical full source
chunks and complete candidate pools are unavailable. This pass does not rescore
R3 or claim an improvement in agent outcomes.

## Verified defect and patch

A regression test failed against the original formatter: a source chunk with
long license boilerplate followed by `cleanupUpload()` showed only boilerplate.

Previews now anchor on the earliest line with the most distinct positive query
terms. They include one preceding line when it fits, then following lines within
the character cap. With no overlap, or for metadata-only hits, they keep a
prefix. Long lines may be partial. Selection stays inside the retrieved chunk.

MCP hits retain `name` and `chunk_type`, and expose actual snippet coordinates
separately from the original chunk coordinates. Final budget trimming shortens
previews before dropping files and keeps coordinates and truncation flags
accurate. Match explanations still cover the original hit. A shared header
stripper also avoids dropping a real first source line when no location header
is present. Retrieval, ranking, and scores are unchanged.

The [controlled fixture replay](2026-10-14-search-evidence-audit/fixture-replay.json)
uses the exact old prefix/field rule and the new formatter on the same ten
candidates, with identical normalized metadata and a 4,000-token budget:

| Presentation | Delivered files | Previews showing `cleanupUpload` | Estimated wire tokens |
| --- | ---: | ---: | ---: |
| Old prefix rule | 10 | 0 | 1,464 |
| New source window | 10 | 10 | 994 |

The new preview is the closing comment and `void cleanupUpload() {}` at source
lines 54–55; the original chunk remains lines 41–55. This is a synthetic
presentation regression, not reconstruction of historical source or an agent
evaluation. Token counts use the product estimator and do not measure provider
billing. The artifact records the baseline revision and relevant source hashes.

## Reproduction

Run from the repository root, choosing a new output directory:

```sh
.venv/bin/python packages/code-intel/evals/search_evidence_audit.py \
  --study /Users/eren/Documents/AI/attocode-evals/matrix/studies/r3 \
  --output /private/tmp/search-evidence-audit-fresh
```

The command only reads study inputs and writes new analysis artifacts. It
rejects output inside the study, overwrites, duplicate runs, incomplete declared
task/trial/setup pairs, and escaping input paths. Missing, conflicting, failed,
or malformed tool responses remain unknown rather than becoming empty results.

Validation covers late matches, ties, exclusions, metadata-only hits, long
lines, line endings, source headers, final trimming, actual source-index search,
fixed-pool order/score/file preservation, and audit integrity. All 190 focused
tests and Ruff passed. Restart the MCP process before expecting this source change in an
existing session; the local tests load the current editable source.

A subsequent [fresh MCP smoke and chunk audit](2026-10-14-search-followup/README.md)
validated the patch through stdio on this checkout and narrowed the next source
evidence problem to metadata-only hits whose matching body candidates fall
below global retrieval caps. The previously connected session was not replaced.
