# Attocode Intelligence 0.1.9

0.1.9 fixes three defects that we found when we used Attocode on its own
repository. The standalone distribution remains `attocode-code-intel`.

```sh
uv tool install --force attocode-code-intel==0.1.9
```

Restart the MCP connection after you upgrade.

## Fixes

- **Python docstrings and parameter types.** The tree-sitter parser now keeps
  Python docstrings for functions, methods and classes. It also keeps annotated
  parameter types for Python, TypeScript and Java. Before, the conventions
  report showed 0% docstrings and 0% typed parameters for Python projects, and
  the keyword index did not include Python docstrings.
- **Impact order.** `impact_analysis` now lists impacted files by import depth,
  nearest first. This applies to the local service, the text report and the
  database provider. Before, the list was alphabetical, so a token budget
  removed direct dependents first.
- **Prose words in search.** "into", "onto" and "one" are no longer search
  terms. Before, "one" in a question matched identifiers such as
  `SystemOneChoiceReranker`.

The keyword cache schema changes from 3 to 4. Existing keyword caches rebuild
once, on the first search after the upgrade. Client configurations do not
change.

## Measured effect

On a frozen snapshot of `packages/code-intel`, the conventions report changes
from 0% to 87% typed parameters. With a 1,200-token budget, impact analysis of
`output.py` delivers all 14 direct dependents instead of 3. The ranking gate
MRR@5 goes from 0.530 to 0.555, and the docstring fix gives most of this gain.

On 12 fresh validation questions, no file or quote judgment changes. The
docstring fix moves two pandas workflow labels out of the first five, and two
earlier regression questions lose a visible quote. See the
[search batch](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-17-search-batch.md)
for every measurement and its limits.

## Rejected search candidates

Three search candidates did not ship: per-chunk concept coverage, file-level
concept coverage and "tested" test intent. Each failed its predeclared rules on
new frozen questions. The search order does not change because of them. See the
[file coverage report](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-17-file-coverage.md).

Release-specific install, upgrade and publication results are recorded in the
GitHub release after publication. No cloud benchmark, agent study or model
download is part of this release.
