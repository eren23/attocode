# Attocode Intelligence 0.1.19

0.1.19 restores source text into spare space after fitting a complete compact search
page. The package remains `attocode-code-intel`.

```sh
uv tool install --force attocode-code-intel==0.1.19
```

Restart the MCP connection after upgrading to load the new package. Publication
does not upgrade a global installation or restart an existing host.

## Compact search evidence

A small serialized-response overflow could halve a source snippet and leave spare
space unused. The correction keeps the complete already fitted page and its
continuation as the floor, then checks bounded expansions from the original
selected source windows. All delivered hits, order, scores, matched terms,
previously visible text and source-line coverage remain protected. Every accepted
page fits the same full serialized token budget, with correct snippet coordinates
and truncation/omission flags. Caller data is not mutated.

At most 12 additional candidate windows are attempted per response, globally.
Tokenization and anchored windows are not monotone: this is a verified improvement
over the already fitted page, not a maximal or globally optimal packing claim.
Long workspace paths still consume response space, so path-independent excerpts
are not promised. Ranking, retrieval, parsing, model policy, source/cache guards
and dependencies are unchanged.

[Four causal boundary cases and 380 online controls](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-25-snippet-budget.md)
retain the source-bound failure and corrected delivery checks. All 16 previous
no-crowding variants remain; their guard permits larger excerpts only with identical
non-preview hit data, all previous text and nonshrinking source spans. Nineteen
new cases cover full page/continuation protection, actual budgets, a global probe
bound, nonmonotone counts, source coordinates, repeated text, truncation and caller
identity. Maintained preflight has 305 cases; required regressions total 318.
Temporary control wiring is retired and all original evidence is retained.

The optional file-context candidate remains rejected and removed. Its 24 validation
questions remain unissued. There is no new relevance, native-cause, agent-benefit
or speedup claim. Existing source judgments are exposed and non-exhaustive.

## Release verification

Publication requires one fresh full 36-pack matrix with 288 operational contracts
and 144 existing consumed retrieval observations on this exact versioned tree,
including 305 same-head Linux controls. Keep the 1,200-second aggregate,
180-second per-pack, 2 GiB RSS/disk and 64 MiB evidence limits. Limited and unsupported
outcomes retain their labels; any failure or incomplete contract holds publication.
This is operational compatibility evidence, not a fresh relevance/performance study.

All 17 normal CI checks, Python 3.12/3.13, 318 required regressions, PostgreSQL/HTTP,
four real language servers, image contracts and candidate clean/previous-version
installs remain required. The tag workflow requires all 18 jobs plus actual PyPI
clean-install/0.1.18-upgrade verification of source/wheel/sdist/installed Python and
METADATA, CLI/init/doctor/continuation behavior. The merged and tagged full tree
must equal the reviewed candidate and matrix source. GitHub release assets are
verified against the published artifacts. Published 0.1.18 remains immutable.
