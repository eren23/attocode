# Search discovery provenance and Go/Rust fallback correctness —2026-10-30

The deferred supplied-context diagnostic mismatch is corrected. Go/Rust fallback now excludes comment/string declarations and calls, preserves ordinary multiline source ranges, and labels its definitions/call evidence as `regex`. Production native parsing retains the100ms limit. These changes are qualified and unreleased against published0.1.20.

## Problems and corrections

Search selected files from a caller-supplied context correctly, but `discovery_max_files` reported the manager's limit. Keyword discovery now snapshots the actual supplied context setting with the completed generation. Later context mutation does not rewrite that receipt. Before discovery/after invalidation, the configured manager setting is reported; a SQL-read invalidation clears the old cap and counts together. Selection, cap rules, ranking and scoring are unchanged.

When native parsing aborts, existing Go/Rust regex adapters previously scanned comment/raw-string lines as declarations. Brace counting could lose multiline function ranges or stop on literal braces. Reference fallback counted a function declaration as its own caller and included comments/raw strings; the retained controls show five `Target` references where the literal source has one real call. Those references also inherited a `tree-sitter` label. Definition locations similarly inherited a native label despite their regex parsing tier.

A small lexical mask now preserves source line/column shape while hiding Go comments/quoted/rune/backtick literals and Rust nested comments, quoted/byte/raw/hash literals and chars. Rust lifetimes/labels remain code. A separate import-literal view retains ordinary quoted Go import paths without exposing raw-literal interior lines. Original source bytes and content hashes are preserved. Existing fallback patterns consume the filtered view; no native retry or dependency was introduced.

Ordinary declaration bodies are scanned within the existing500-line window, ignoring non-code braces and handling multiline signatures. Bodyless/new declarations and overbound/incomplete spans retain conservative start-line fallback. Go anonymous struct return types are processed through the full line so a type's closing brace cannot end the function early. Regex call scanning excludes the declaration's own name while retaining real calls on that same line and their enclosing function. Only Go/Rust fallback definitions and regex-generated call references gain the `regex` provenance label; actual native results retain their native source.

## Causal online verification

All actual tests, native imports, fixture creation, build/install and runtime ran on GitHub Actions. Native error injection replaces only the parser boundary with the already observed `ValueError`; real `bounded_parse`, reset/error recording, regex parsing and definition/reference indexing execute. This verifies handling of that error boundary. It does not reproduce a timed100ms abort or establish historical timeout causes/frequency.

| Original run | Stage | Cases | Observed result |
|---|---|---:|---|
| [41116468603](https://github.com/eren23/attocode/actions/runs/41116468603) | red | 424 | 8 expected failures, 416 positives |
| [41117203792](https://github.com/eren23/attocode/actions/runs/41117203792) | green | 424 | 0 expected failures, 424 positives |
| [41118027226](https://github.com/eren23/attocode/actions/runs/41118027226) | boundary-red | 425 | 1 expected failures, 424 positives |
| [41118402134](https://github.com/eren23/attocode/actions/runs/41118402134) | provenance-red | 427 | 3 expected failures, 424 positives |
| [41118824974](https://github.com/eren23/attocode/actions/runs/41118824974) | final-green | 427 | 0 expected failures, 427 positives |

The initial RED was independently admitted before production changes. The first GREEN passed424 cases. Static inspection then found the Go anonymous-return-type range edge case; its separate425-case RED reproduced exactly that failure. Two further definition-provenance assertions produced the expanded427-case RED. Only after those original failures were admitted were the range/provenance boundaries corrected. The final427-case GREEN passes every case without errors/skips; final production and regression source remains exact `b7dd5b16fa7b27441b62056218e57f4f9b7eb534`.

The sixteen new cases comprise three discovery-provenance cases and thirteen fallback cases. Literal fixtures cover lower/higher supplied caps, post-build context mutation and SQL-read invalidation; Go/Rust comment/raw-string decoys, Rust nested comments/lifetimes, quoted/rune braces and multiline ranges, real inline calls/self-call exclusion, native-error receipts/provenance, ordinary symbols and the500-line bound. Expectations are hand-derived, not computed with the new mask/span helpers.

Each trial is source-bound and supervised under600s aggregate,2GiB RSS,2GiB scratch and64MiB evidence; original source/origins/XML/archive bytes and owned cleanup are independently admitted. Expected RED assertions are successful protocol observations, not product passes. Durations include infrastructure/instrumentation and support no speed comparison. Temporary controller/design/workflow choice were retired after admission. Permanent gates now include427 preflight cases and443 required regressions; the79 acquired optional cases/26depth and standard17 checks remain required independently.

## Evidence and limits

The [machine report](2026-10-30-fallback-provenance.json) contains exact run/source/archive receipts. The [evidence archive](2026-10-30-fallback-provenance-evidence.tar.gz) preserves all five original ZIPs, distinct label+run keys, admission/dispatch records, complete committed producer/design/test/product source snapshots and qualified Git history. Every internal payload has a byte-count/SHA256 manifest. Archive SHA256 `0619b7a0b4d7bb916fc7de9dd5e7e00385c98319f2bef01dec84c14b6021adca`; 2928805bytes/726members/7source snapshots. Evidence remains Git-tracked and export-ignored so bounded source exports retain all349 product files and worker inputs.

This remains lexical/heuristic fallback, not a complete Go/Rust grammar or type-resolved relationship proof. Complex headers, macros/raw identifiers and unsupported syntax can remain limited. The100ms native limit, reset/thread/cache policy, native grammars, other-language fallback semantics, dependency/version files, source eligibility and ranking/scoring are unchanged. No original paid/native/scored campaign was rerun; no package/tag was published and no DO worker/reservation was created. Historical native abort causes,50k/100k qualification, broad failure rates, relevance and restart/throughput improvements remain unclaimed. The prior OCaml/search corrections and all original evidence remain preserved.

Language references: [Go comments and literals](https://go.dev/ref/spec), [Rust literal tokens](https://doc.rust-lang.org/reference/tokens.html), [Rust nested comments](https://doc.rust-lang.org/stable/reference/comments.html).
