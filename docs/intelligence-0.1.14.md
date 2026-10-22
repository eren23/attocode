# Attocode Intelligence 0.1.14

0.1.14 makes local navigation recovery safer, repairs guarded Elixir definitions,
and identifies the server connection checked by doctor. The standalone package
remains `attocode-code-intel`.

```sh
uv tool install --force attocode-code-intel==0.1.14
```

Restart the MCP connection after upgrading so it loads the new package.

## Changes

- **Bounded selected-file recovery.** Native parse failures carry outcome,
  elapsed time and configured limit. A selected missing definition gets one
  recovery attempt per unchanged source/parser generation; unsuccessful recovery
  reports partial evidence and the existing file-refresh command. The parser
  limit stays at 100 ms.
- **Safe navigation publication.** Recovery stages definitions, references and
  diagnostics, checks the workspace generation before and after snapshot writes,
  and publishes only consistent state. Failed reference parses are excluded from
  reusable summaries; changed extractor identity triggers conservative repair.
- **Elixir and Ruby corrections.** Guarded Elixir declaration heads now produce
  definitions, while declaration names are excluded from calls. Ordinary Ruby
  calls and dynamic relative imports no longer fabricate literal import paths.
- **Doctor identifies its probe.** Output names the configured executable and
  version returned by a new server connection. It cannot certify an already
  running host session.
- **Maintained release verification.** A public verifier compares artifacts,
  source and installed Python/metadata identities, checks clean and previous-version
  upgrade environments, and exercises CLI/MCP/init/doctor and bounded continuation.
  Verification itself never publishes or restarts another host connection.

## Verification and limits

The merged implementation passed 4,140 local tests, with 14 skipped and one
expected failure. All 36 pinned compatibility packs completed: 157 passed,
124 limited and seven unsupported checks, with no failed or incomplete checks.
Scale, lifecycle, historical ranking and installed development-wheel checks pass.
The native-source workflow packet contains 12 positive cases and four negative
controls passing across six languages, with two dynamic/macro controls limited.
See the [milestone evidence](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-22-local-reliability.md)
and [native workflows](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-22-local-workflows.md).

The intermittent native cold-parse trigger and Rust readiness cause remain
unproven. A structural-fingerprint restart shortcut is omitted because remote
capacity admission failed before its required benchmark. Conservative repair
can still add restart work when AST summaries are missing. There is no measured
restart-speed gain.

The single callback-span search candidate was rejected on consumed development:
first-page labeled file matches fell 15→11. Initial invalid operator evidence is
retained separately. Ranking defaults remain unchanged; no agent-benefit or fresh
relevance gain is claimed. Daily and lean tool profiles are unchanged.

The GitHub release records release-workflow evidence, actual PyPI clean install,
upgrade from 0.1.13 and artifact verification after publication. A release does
not upgrade a global installation or restart an existing MCP connection.
