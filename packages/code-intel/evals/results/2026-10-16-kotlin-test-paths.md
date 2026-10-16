# Kotlin test-source classification

**Decision: fix path classification, with unchanged scoring weights and models.**
Helpers under conventional Kotlin/Android test source sets were treated as
production unless their own filename matched a test convention. This put helpers
such as `MockHttp2Peer.kt` into ordinary search pages and could exclude them from
symbol-focused test suggestions. Recognition now requires an explicit supported
source-set directory immediately under `src`; arbitrary `*Test` directories,
production source sets and package names remain unchanged.

Test discovery also used inconsistent import rules: a substring check could
classify `Inspection.kt` as a test, while reverse-import distance missed Kotlin
source sets. Both now use the shared classifier. Suggestions remain candidates,
including supporting helpers, rather than proof that a file contains runnable tests.

## Contract and scope

The bounded set includes common, JVM, JS, Wasm and supported native source sets,
plus Android unit/instrumented and host/device sets. This follows the official
[Kotlin Android layouts](https://kotlinlang.org/docs/multiplatform/multiplatform-android-layout.html),
[Kotlin source-set hierarchy](https://kotlinlang.org/docs/multiplatform/multiplatform-hierarchy.html)
and [Android KMP test-source sets](https://developer.android.com/kotlin/multiplatform/plugin).
Custom target/flavor names still require build metadata and are not inferred.
Existing filename rules, including a file named `jvmTest.kt`, stay in effect.

Ordinary lexical search uses its existing stable production/test partition: it
moves recognized tests after production candidates without changing scores or
removing them from the pool. A shorter requested page can consequently omit a
test that was previously delivered. Short explicit test requests bypass that
partition. Test-suggestion task scoring keeps test candidates eligible.

## Fresh comparison

The [six questions](../designs/2026-10-16-kotlin-test-paths.json) were source-reviewed
and frozen before retrieval: four production tasks and two explicit test-helper
requests. A single warmed index of pinned OkHttp `e2061bdd146ae3ce5f097b78fa7a731dc7638510`
served both arms. Each ran three times in alternating order. The baseline
classifier was checked for AST equality with main `fab7fe20`; only the classifier
changed between arms. All keyword, body, file-BM25 and pre-partition chunk orders
matched, and repeated results/scores were stable.

| Measurement | Baseline | Fixed |
| --- | ---: | ---: |
| Production targets in first five | 4/4 | 4/4 |
| Test-helper targets in first five | 1/2 | 1/2 |
| All labeled targets at 24 | 6/6 | 6/6 |
| p95 per-question median latency | 27.25 ms | 27.07 ms |

The authentication-challenge question moved `RecordingAuthenticator.kt` out of
the first five; its labeled production target stayed first. Both explicit test
queries retained identical results and scores. The callback helper remained at
rank 12, so this fix does not solve that first-page miss. The frozen no-loss,
explicit-test, candidate-generation and latency checks all passed.

Across the pinned tree, 32 paths newly classify as test-source-set contents:
27 in `jvmTest`, two in `commonTest`, two in `androidHostTest`, and one in
`androidDeviceTest`. These include 26 Kotlin source files and six fixture/data
files. Tracked test discovery still filters out non-source data. The
[raw report](2026-10-16-kotlin-test-paths.json) retains all changed paths, results,
scores, stages and timings.

These are non-exhaustive source judgments by the implementer. The repository and
some source files were previously exposed; only these questions were fresh.
Labeled coverage did not improve. This supports a path-classification correction,
not a general relevance or agent-outcome claim.

## Validation and resource use

Seventy focused checks cover source-set boundaries, production lookalikes,
existing conventions, stable search partitioning, explicit test searches,
tracked discovery, indirect import distance, linked-symbol evidence and real MCP
suggestions. The bounded local gate passed **811 tests**, with nine explicit
environment skips, plus Ruff, scale and lifecycle checks. It took **43.172
seconds**, peaking at **128.0 MiB managed storage**; run
`20261016T125144-18f7e1f8`.

The cached comparison took **3.534 seconds**, peaking at **60.2 MiB managed disk**
and **110.4 MiB sampled RSS**. It had a 180-second deadline, 512-MiB managed-disk
limit and 1.5-GiB RSS limit. Materialized source was capped at 64 MiB. Scratch
cleanup passed. No repository/model downloads, model runs or cloud workers were
used. PostgreSQL, ranking and all remaining required upstream checks gate merge.

- Frozen questions SHA-256: `231c73945e6d47306720458397511982abb4acb96b4ff21a6aed3ca443cb19df`.
- Product/evaluation source SHA-256: `c16c6f1d7e4e54183dc28409e4d0d0a4093bb0832444b0fdd5e972c822c60222`.
- Test-fixture SHA-256: `3ce4f4a38e3b58ab3cb5075cdb48afa689a23ec180a59acf77e3e5b417798122`.

Replay with `.venv/bin/python -m eval.quality.kotlin_test_paths_trial --questions
packages/code-intel/evals/designs/2026-10-16-kotlin-test-paths.json --output
/private/tmp/kotlin-path-comparison.json` using the existing cached corpus.
The evaluator refuses to overwrite observations.
