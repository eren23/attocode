# R3 search evidence audit

Offline analysis of existing traces; no client calls or rescoring.

Study: `d1ff449e8661c2d2345158f559f5fb2d1f907819c28bdbf097ceba1b6e5520cf`. Model: `claude-sonnet-5-5`.

Audited 60 runs across 10 tasks, with 30 recorded search calls.

All labels were delivered in 18/30 treatment runs. A delivered label was omitted from the answer in 14/30 runs. No label was delivered in 9/30 runs.

## Task observations

| Task | Native answers containing every label | Intel answers containing every label | Intel runs omitting a delivered label |
| --- | ---: | ---: | ---: |
| lca_edgedb__edgedb-5785-5725 | 0/3 | 0/3 | 0 |
| lca_libgdx__libgdx-856-798 | 1/3 | 0/3 | 3 |
| lca_openbb-finance__openbbterminal-410-409 | 0/3 | 0/3 | 0 |
| lca_theopenconversationkit__tock-1040-1039 | 2/3 | 0/3 | 3 |
| lca_tweepy__tweepy-1262-1261 | 3/3 | 2/3 | 0 |
| lca_vert-x3__vertx-web-1779-1778 | 0/3 | 0/3 | 3 |
| live_spring-projects__spring-boot-50119 | 0/3 | 0/3 | 0 |
| locbench_CWorthy-ocean__roms-tools-227 | 2/3 | 3/3 | 0 |
| locbench_TransformerLensOrg__TransformerLens-333 | 0/3 | 0/3 | 3 |
| polybench_google__gson-2158 | 2/3 | 1/3 | 2 |

## Delivered labels omitted from answers

There are 20 omitted labeled hit occurrences, including 8 truncated snippets. 0 have an explicit successful Read after the search result. This does not exclude inspection through Grep.

| Path | Occurrences | Delivered ranks | Truncated snippets | Reported terms outside preview |
| --- | ---: | --- | ---: | --- |
| `bot/xray/src/main/kotlin/XrayService.kt` | 3 | 2, 3 | 3 | attachment |
| `extensions/gdx-tools/src/com/badlogic/gdx/tools/particleeditor/EffectPanel.java` | 3 | 5 | 0 | none |
| `gson/src/main/java/com/google/gson/Gson.java` | 2 | 2 | 2 | none |
| `transformer_lens/HookedEncoder.py` | 3 | 8 | 0 | none |
| `transformer_lens/utils.py` | 3 | 2 | 0 | none |
| `vertx-web/src/main/java/io/vertx/ext/web/FileUpload.java` | 3 | 10 | 0 | none |
| `vertx-web/src/main/java/io/vertx/ext/web/impl/FileUploadImpl.java` | 3 | 4 | 3 | file, http, server, upload |

## Interpretation

Delivered-but-omitted paths are observations, not proof that the agent ignored them or that output caused failure. Explicit Read calls are recorded separately from Grep and Glob; a path can be seen without a Read call.

Missing from the delivered page does not establish a candidate-pool miss. Full pools and historical source chunks are unavailable in these traces. Reported terms absent from snippets can match symbol identity or omitted source, so that diagnostic alone is not a source-loss judgment.

Labels are developer-changed files, not exhaustive relevance judgments. Native comparisons are observations on the same tasks, not causal explanations for individual tool-assisted failures.

The ledger binds the manifest, original scores, run metadata and traces to SHA-256 hashes. Raw records and scores are unchanged. These cases are development evidence, not a fresh held-out evaluation.
