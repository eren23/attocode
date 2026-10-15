# Cockroach headroom and fresh retrieval cycle

Approved scope: one Cockroach target run, with a second $1 reservation usable only after a failed target and a diagnosed, tested, merged repair. No release, model calls, global installation or host MCP restart. The first target passed; the conditional retry is unused.

## Frozen retrieval protocol (before retrieval)

The adjacent questions JSON freezes 48 new source-backed questions at six previously used pinned repositories. Each repository contributes four development and four validation questions: intent, cross-file behavior, configuration, and ambiguous terms. Native source anchors were reviewed before execution; labels are non-exhaustive file relevance judgments. Splits use distinct behavior families, but repositories and some source files overlap. This is not a repository-disjoint generalization study. No question or label may be replaced after results.

Baseline is existing expanded-query retrieval. Candidate A uses the original literal query with existing fusion. Candidate B combines the baseline and literal ordered unique file lists with equal-weight reciprocal rank fusion, k=60, applies existing original-query test-intent demotion, breaks score ties by path, and returns at most 24 files. No candidate invents files outside its retrieval lists. No other candidate or post-validation tuning.

Measure each query three times with alternating baseline/literal execution order. Retain median per-query latency; dual latency includes both retrieval calls and fusion. Report nearest-rank p95 across queries; cold index startup is separate. Save ordered files, stage pools, label index coverage, source hashes and run identity. Do not call an absent result an index omission without coverage evidence.

Choose at most one candidate using all 24 development queries: at least three net additional Hit@5 and no aggregate Hit@24 loss. Among eligible candidates choose higher mean reciprocal rank (first labeled file within 24); exact ties favor literal. Freeze the choice and implementation/question/report hashes before any validation retrieval. If neither qualifies, run baseline-only validation to complete the benchmark; no candidate validation claim.

On all 24 validation queries, the selected candidate must have at least three net additional Hit@5, gains in at least two repositories, at most one individual Hit@5 loss, zero individual Hit@24 losses, no mean labeled Recall@5 decrease, and p95 latency at most max(1.5 × baseline p95, 50 ms). All conditions are required. A pass permits an opt-in, default-off implementation only; a failure leaves product defaults unchanged. Reproducible correctness defects require regression tests and separate disclosure, without changing frozen questions or historical exclusions.

Execution uses local cached pinned source only: at most two packs per invocation, one materialized at a time, 64 MiB source cap per pack, 180-second supervised invocation, 512 MiB managed disk and 1.5 GiB process-tree RSS. Temporary source/index trees are deleted; retain only reports. No downloads, external endpoint, repository execution or models. Publish negative evidence too, run scoped tests and unchanged ranking gate, then CI and upstream merge. No full release-gate claim from this target cycle.
