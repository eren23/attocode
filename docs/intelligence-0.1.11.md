# Attocode Intelligence 0.1.11

0.1.11 counts more test file names as tests. The standalone distribution
remains `attocode-code-intel`.

```sh
uv tool install --force attocode-code-intel==0.1.11
```

Restart the MCP connection after you upgrade.

## Changes

- **More test file names.** These file names now count as tests:
  `_test.dart`, `_test.exs`, `_test.ts`, `_test.h`, `_tests.erl`, `Test.m`,
  `Tests.m` and Perl `.t` scripts. Before, a test outside a test folder, such
  as `pkg/analyzer/tool/generators/ast_generator_test.dart`, ranked as
  source. `Test.php` and `_test.js` do not count, because Laravel and Deno use
  these names for source code.
- **Perl `t/` folders.** Perl modules and scripts (`.pm`, `.pl`) in a `t/`
  folder now count as tests. Other files in a `t/` folder do not count,
  because a `t/` folder can hold data. For example, cosmopolitan keeps
  terminfo entries in `usr/share/terminfo/t/`.

Indexes and caches do not change. Both changes apply when a search runs.
Client configurations do not change.

## Measured effect

In the cached repositories at their pinned commits, the file-name rule adds
3,245 test files in six repositories and removes none. The Perl rule adds 276
test files in perl5 and mojo. On 28 consumed questions in dart-sdk, otp,
phoenix, perl5 and mojo, no judged file or quote changed. In the dart-sdk
workflow, `suggest_tests` now also finds `tool/element/element_test.dart`.

Two unjudged pages changed. A "where is it defined" control in perl5 no
longer shows the test helper `TestConnectProxy.pm` in the first five. On one
mojo "test" question, the fixture `LoaderException2.pm` is now the first test
hit, because its function `throw_error` matches "error".

## Rejected candidates

- For "test" searches, two trials put the best source hit for the query after
  the first five test hits. The first failed its frozen latency limit, and the
  second lost one judged test file on new questions. See the
  [query source report](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-18-query-source.md).
- BM25 over function units did not beat BM25 over 40-line windows on
  Loc-Bench 560, so product search does not add function-body documents. See
  the
  [function units report](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-19-function-bm25.md).

The [Loc-Bench re-measure](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-18-locbench-remeasure.md)
gives file Acc@5 0.566 for product search on `main`, against 0.532 at R1.

Release-specific install, upgrade and publication results are recorded in the
GitHub release after publication. No cloud benchmark, agent study or model
download is part of this release.
