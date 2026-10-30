# Current native parser causes and OCaml interface correction — 2026-10-30

OCaml `.mli` files used the implementation grammar. An exact-byte, same-provider comparison confirms that this produces error recovery where the interface grammar returns a clean tree. The qualified correction selects the interface grammar in structure, syntax/reference and generic parsing, keeps public language `ocaml`, and records `val` declaration names and ranges. This fix is unreleased; published0.1.20 is unchanged.

## What was tested

A distinct diagnostic inspected16 previously failing files:13 from pinned Cockroach,2 from pinned Deno, and OCaml `typing/env.mli`, totaling7,355,332 raw bytes. Repository commits, paths, original byte counts and SHA256 identities match the retained campaign evidence. Raw and production-canonical UTF8/replacement/universal-newline identities are recorded separately. Sources were acquired and removed on GitHub Actions; upstream build/install/test commands were never executed.

The original [diagnostic41106006284](https://github.com/eren23/attocode/actions/runs/41106006284), source `fc847d2cf5fe37bb8fed9a054caa8d71ca0d4aa2`, first passed397 maintained controls. Sixteen separate workers then issued72 native attempts: four fresh/reset parsers per input at100/500/500/100ms, four additional OCaml interface attempts, and four tiny implementation/interface controls. The500ms setting belongs only to isolated diagnostic parsers. Production parsing ran once per input at its unchanged100ms bound. Parser/thread/process identity, actual limit, source bytes/hash, return/exception, root coverage/error flag, wall/threadCPU and reset records are retained.

All72 attempts,609 linked Journal blobs and exact original blob hashes/lengths were independently replayed. Installed tree-sitter0.25.2/language-pack1.1.2 distributions and native library/cache hashes were recorded before and after. The diagnostic completed in14.989s under600s aggregate,2GiB RSS,2GiB scratch and64MiB evidence; owned workers/scratch were cleaned. These instrumented durations support no speed comparison.

## Findings and limits

| Input group | Paired native observation | Interpretation |
|---|---|---|
| OCaml `typing/env.mli` (20,928B) | All four implementation trees cover the input but have errors. All four interface trees cover it without errors. | A grammar routing defect, distinct from proving the old abort cause. |
| Cockroach `proj_const_left_ops.eg.go` (680,822B) | Both100ms attempts raise `ValueError`; both500ms attempts return clean full-input trees. Production falls back to regex with one recorded failure. | Repeatable budget sensitivity in this condition. |
| Deno `tests/integration/lsp_tests.rs` (536,828B) | Both100ms attempts raise `ValueError`; both500ms attempts return clean full-input trees. The subsequent production call returns native tier without failure. | Near-boundary behavior varies even within this worker; no deterministic production failure-rate claim. |
| Remaining13 large inputs | All four attempts return clean full-input trees, including both100ms attempts. | Previous aborts did not reproduce on this runner. |

For OCaml, the selected product language equals the cached pack implementation language: the variant comparison has no provider substitution. Implementation library SHA256 is `8759d523990654774903fc9a58ba1747f40cabbf9d0a729962d6a07cb365606e`; interface is `69c0d4e11e6dfec1191362972a40656846b7a574fd708f1dc0ad9ba131ed602c`. Both expose ABI15/semantic grammar0.25.0. Each tiny control is clean with its intended variant and contains errors with the crossed variant.

The original OCaml100ms exception did not reproduce here: the wrong grammar returned error trees instead. This demonstrates a current syntax-routing defect, not the historical cause of every captured exception. Different execution conditions, compiler/grammar origins and load were not controlled against the old DigitalOcean runs. Generic `ValueError` alone does not distinguish them. The two budget-sensitive files provide no justification to raise production limits or add retries; fallback remains bounded and observable.

## Correction and causal tests

After the diagnostic was admitted, fourteen default routing/provider/cache/no-download controls and four acquired native cases were written before changing production code. The [RED41107000398](https://github.com/eren23/attocode/actions/runs/41107000398), source `c178aee17a9ed0fe6aec54720b07797ef15a61e9`, produced exactly9 expected failures plus406 positives across415 cases, without errors/skips. It records the wrong grammar/error trees on all three native routes and missing interface value declarations.

The minimal two-product-file correction at `024f367f3f891d121eb1b75adfda612bdf808230` passed the [same415 cases in GREEN41107319484](https://github.com/eren23/attocode/actions/runs/41107319484), without errors/skips. Standalone OCaml functions select `language_ocaml_interface` when installed; otherwise only explicitly cached interface grammar is eligible. Implementation/interface caches remain separate. Missing interface grammars retain conservative fallback and never acquire or substitute the implementation grammar. `.ml`, existing TSX routing, thread ownership,100ms timeout and reset policy are preserved.

The fourteen default regressions join the411-case maintained preflight and427 required regression inventory. Four native cases join the79-case acquired optional gate, including26 depth cases; explicit optional/broad setup acquires `ocaml_interface`. The nine named regressions remain tested after the temporary diagnostic launchers/designs/choices are retired. All other347 product files, dependency/version files, ranking policy and existing language fixtures remain unchanged against the completed search fix. Normal17 checks, source/install/image/raw-protocol/real-server and postmerge gates remain independently required.

The correction exposes interface declarations through the existing function-like symbol API. It does not resolve an interface declaration to an implementation, infer type-resolved references, or remove existing ambiguous workspace-import limits.

## Reproduction and retained evidence

The [machine report](2026-10-30-native-causes.json) contains every source identity and native outcome. The [evidence archive](2026-10-30-native-causes-evidence.tar.gz) preserves all four original artifact ZIPs from three runs, their source-bound admission data, retained input metadata, complete committed producer/design/test/product snapshots, and the qualified Git history bundle. Every archive payload is covered by the internal byte-count/SHA256 manifest. Its producer is recoverable from the source snapshots/bundle; no corpus download or product runtime is needed to replay recorded bytes.

Archive SHA256: b07a5bdca9e5d534388dc61b3bcbfb6fcc2c8124a7b8f4af451c2e930e4bfe8d. Size: 2600139 bytes; 712 members. Large evidence archives remain tracked but export-ignored so source exports preserve their100MiB bound. No private ledger, provider credentials, new paid worker, package release, Docker cleanup, global upgrade or MCP restart was involved.

The original paid campaign remains incomplete.50k/100k capacity, broad failure frequencies, historical native attribution, relevance, restart performance and general throughput remain unclaimed. These observations are not replacement qualification results for that campaign.

Primary references: [OCaml implementation/interface grammars](https://github.com/tree-sitter/tree-sitter-ocaml), [pinned0.25.2 parser binding](https://github.com/tree-sitter/py-tree-sitter/blob/v0.25.2/tree_sitter/binding/parser.c). The pinned binding raises `ValueError` when its native parser returns no tree; exception text alone does not identify the underlying reason.
