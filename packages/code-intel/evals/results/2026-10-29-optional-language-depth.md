# Optional language navigation: Perl, OCaml and Crystal — 2026-10-29

Development now retains OCaml and Perl native call candidates and resolves
conservative workspace-local imports for OCaml, Perl and Crystal. OCaml's native
`open_module` nodes now contribute their static module path. No parser limit,
retry, reset, source/cache validation or global ignore policy changes. Existing
parser and navigation byte fingerprints invalidate persisted results when these
three extraction/resolution files change. The product correction is **unreleased**;
version 0.1.19 and published assets remain unchanged.

## Demonstrated failures and corrections

OCaml `application_expression` and Perl `function_call_expression` were absent
from call-candidate traversal. Their actual trees contain the call, while the
baseline returns no candidates. Language-scoped recognition preserves the target's
source line and excludes the declaration, comment and string decoys. Native
OCaml `open_module` was also absent from its configured import-node list.
Perl and Crystal imports were extracted correctly but had no workspace resolver.

The new resolvers offer static candidates: OCaml module implementation/interface
files in the workspace root or current source directory; Perl namespace `.pm`
files under the root or `lib`; Crystal explicit relative `.cr` requires. Competing
roots, malformed/dynamic modules, external Crystal requires, wildcard paths and
root escapes yield no claimed target. Prefix-stripped Python import aliases are
rejected: a relative Crystal require cannot silently bind a file under an unrelated
Python source root. The same physical-path boundary applies to OCaml and Perl. These are syntax/conventional-workspace
candidates, not compiler load-path or type-resolution proof. Test discovery remains
heuristic, and absence is not proven from an unresolved import.

Perl's project override already worked. The new real-Perl scenario verifies a
narrow `dist/Carp` override, unchanged generated/build exclusions, restart and
removal of the override. The original pinned Perl pack remains excluded by default;
its historical unsupported checks are not rewritten into passes.

Crystal's configured definition extractor also already worked. Its missing
language-pack artifact is handled by explicitly building the individual
[upstream Python binding](https://github.com/crystal-lang-tools/tree-sitter-crystal/tree/50ca9e6fcfb16a2cbcad59203cfd8ad650e25c49)
in disposable online setup. Normal optional CI and future broad setup pin that
revision and never acquire it through product navigation. No direct-Git dependency
is added to published metadata and no global tool or MCP host is upgraded/restarted.
This source-built route was verified on Linux; no new cross-platform binary claim
follows.

## Causal online evidence

- [Initial baseline40843508338](https://github.com/eren23/attocode/actions/runs/40843508338)
  remains **failed/retained-incomplete**: 383 cases, 378 passed and five real native
  failures, zero errors/skips. Its controller incorrectly required Crystal
  definition failures, although both definitions passed. The generic-node hypothesis
  was wrong because configured Crystal handling already existed. The first result
  and original artifact are retained; its verdict is never promoted.
- [Focused RED40844593593](https://github.com/eren23/attocode/actions/runs/40844593593)
  corrects that control and adds three direct import cases before product changes:
  386 cases, 378 passed and eight exact desired assertions, no errors/skips. All 375
  existing/core controls pass. Original native trees pinpoint the omitted nodes
  and missing resolvers. Workflow fail-fast exceptions are preserved as causes of
  the explicit failing assertions, with raw MCP responses retained first.
- [Paired GREEN40845549531](https://github.com/eren23/attocode/actions/runs/40845549531)
  passes all 394 controls in 25.949 seconds: 375 maintained controls and 19 dedicated
  depth controls, including eight path/ambiguity guards. Each authored OCaml, Perl
  and Crystal workspace passes all eight workflow checks: definition, source,
  scoped search, caller, dependencies, impact, tests and restart. All five defect
  native ASTs and source bytes exactly match their baseline counterparts.

- Whole-branch review found Python source-root aliases could be mistaken for real
  optional-language paths, and pytest exit zero alone could accept skipped grammar
  checks. [Review RED40851465962](https://github.com/eren23/attocode/actions/runs/40851465962)
  reproduced exactly 12 new assertions with all 394 earlier cases passing: three
  real file-index alias boundaries and nine coverage-receipt controls.
- [Review GREEN40852212232](https://github.com/eren23/attocode/actions/runs/40852212232)
  passed all **406 unskipped cases** in 27.586 seconds: 384 maintained controls and
  22 dedicated depth cases. Physical targets still resolve; misleading Python
  aliases do not. Coverage receipt checks reject missing, skipped, failed, errored,
  duplicated, renamed, empty and unsafe XML. The three authored eight-check
  workflows were independently replayed again from all 27 raw MCP responses,
  including three explicitly recorded warming responses.
- The first draft's optional CI artifact separately passed 72 unskipped cases.
  Its strict documentation build failed on an external-tree relative link; that
  original failure is retained, and the link now uses the repository URL. No
  overall first-draft CI pass is claimed.

Qualification uses real acquired native grammars and actual gateway responses,
within 600 seconds / 2 GiB RSS and disk / 64 MiB evidence. No runtime, native parser,
test, build, installation or source fixture runs locally. Grammar source/cache and
distribution hashes stay equal before/after each run; those remain source-bound
online observations rather than independent host binary replay. Existing 100 ms
native and bounded recovery policy stay unchanged.

Scoped inclusion and coverage-admission controls stay in maintained preflight
(384 cases). Normal CI retains 397 required regression identities. The dedicated
optional job explicitly acquires grammars and requires an exact 75-case inventory:
53 prior capabilities plus 22 depth cases. Its permanent completion receipt rejects
skipped, missing, duplicate, unexpected or failed cases; exit zero alone cannot
certify coverage. XML/native inputs/raw MCP/source/grammar/origin/cleanup evidence
is retained. Default opt-out skips do not count as native verification. Temporary
controller/design/choice are retired.

[Machine-readable result](2026-10-29-optional-language-depth.json) and [original evidence archive](2026-10-29-optional-language-depth.tar.gz)
retain six original ZIPs (five bounded controls and the first optional CI artifact),
seven executed Git source maps, both 349-file engine maps (three changed files),
upstream pin/license, the explicit first-failure admission and original strict-doc
failure log. Archive SHA-256 `6961ee493f8d8e4da0c73dace22b47334e63087a937d98b56eeb73c3cf6fa575`
(3,320,382 bytes; 755 members). Old source packs,
consumed questions, earlier relevance/restart rejections and historical native
causes are unchanged. No relevance, performance, frequency or agent-benefit claim.
