# Attocode Intelligence 0.1.20

0.1.20 improves native syntax and conservative workspace navigation for OCaml,
Perl and Crystal. The package remains `attocode-code-intel`.

```sh
uv tool install --force attocode-code-intel==0.1.20
```

Restart the MCP connection after upgrading to load the new package. Publication
does not upgrade a global installation or restart an existing host.

## Language navigation

OCaml application nodes and Perl function-call nodes now contribute native call
candidates, preserving actual source lines and excluding declaration, comment and
string decoys. OCaml native `open_module` nodes contribute their static module path.
Conservative import candidates cover OCaml implementation/interface files in the
workspace root or source directory, Perl namespace modules at the root or `lib`,
and Crystal explicit relative `.cr` requires. Competing roots, dynamic imports,
unsupported forms and escaping paths retain uncertainty. Python import-root aliases
cannot masquerade as physical files for these language conventions.

These are syntax/import candidates, not compiler or load-path proof. Test discovery
remains heuristic. Native timeouts, retries, source/cache validation, ranking,
retrieval, global exclusions and package dependencies remain unchanged.

Perl's existing scoped inclusion works with the narrow project recipe documented
in the [quality guide](intelligence-quality.md). The original pinned Perl fixture
under `dist` remains excluded by default. Crystal's configured definitions also
already worked; explicit disposable Linux CI setup now builds a pinned standalone
grammar. Product navigation never downloads it, no Git dependency enters published
metadata, and no new cross-platform grammar binary support is claimed.

[Causal native controls and original evidence](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-29-optional-language-depth.md)
retain the initial failed hypothesis/control, focused RED/GREEN, review RED/GREEN
and first documentation failure. All 406 final controls pass: 384 maintained and
22 dedicated depth cases. Three authored workspaces each pass eight workflow
checks, independently replayed from native inputs and raw MCP responses. Dedicated
optional CI requires an exact 75-case unskipped inventory, including 53 prior
capability cases. Its permanent gate rejects incomplete collections and skips even
when pytest exits zero. Normal CI retains 397 required regression identities.

## Release verification

Publication requires one fresh full 36-pack matrix with 288 operational contracts
and 144 existing consumed observations on this exact versioned tree, plus same-head
384-case Linux preflight. Keep the 1,200-second aggregate, 180-second per-pack,
2 GiB RSS/disk and 64 MiB evidence limits. Limited and unsupported outcomes retain
their labels; failed or incomplete contracts hold publication. This is operational
compatibility evidence, not a fresh relevance, performance or agent study.

All 17 normal CI checks, Python 3.12/3.13, 397 required regressions, PostgreSQL/HTTP,
four real servers, image contracts, candidate installs and the acquired 75-case
optional artifact remain required. The immutable tag workflow requires all 18 jobs,
actual PyPI clean-install/0.1.19-upgrade verification, installed Python and METADATA,
CLI/init/doctor/continuation checks, source-bound wheel/sdist and verified GitHub
assets. Reviewed, full-matrix, actual CI, merged and tagged trees must match.
Published 0.1.19 remains immutable.

Historical native failure causes remain unproven. Existing rejected relevance and
restart candidates stay rejected; consumed questions are not relabeled as fresh.
