# Attocode Intelligence 0.1.17

0.1.17 delivers bounded recovery for a temporarily failed selected-file native
parse. The standalone package remains `attocode-code-intel`.

```sh
uv tool install --force attocode-code-intel==0.1.17
```

Restart the MCP connection after upgrading so it loads the new package.
Publication does not upgrade a global installation or restart an existing host.

## Recovery behavior

A failed recovery attempt used to remain cached for the same source and parser
identity. Even after the parser became healthy, another explicit inspection
could keep returning the old partial result.

A later explicit inspection can now retry after a one-second cooldown.
Immediate repeated requests reuse the failure without starting more native work.
Source, parser and workspace-generation guards still prevent stale navigation
from being published after edits. The native 100 ms parse limit and Rust
two-second/four-attempt precision bounds remain unchanged.

The [paired regressions and pinned OCaml recovery observation](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-23-native-recovery-cooldown.md)
demonstrate the cached-failure defect and recovery with the unchanged native
limit after a deliberately forced interruption. They do not establish the
original historical OCaml/Rust exception or scheduling trigger.

## Maintenance and measured limits

Pinned source admission resolves aliases through the captured fixture inventory,
with path-order, missing-target, escape and cycle checks. Navigation comparisons
require full parse/reference readiness and validate actual continuation routes
before comparing workspace roles. Raw responses and unsuccessful attempts remain
available in the tagged repository; archived results stay outside distributions.

The [completed relevance comparison](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-23-file-coverage-routed.md)
rejects its candidate: 438 pages yield one distinct judged-file gain per round
(required two), zero judged losses and 30 exact-question control changes. Its
24 reserved validation questions remain unissued.

The [matched restart comparison](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-23-restart-routed.md)
also rejects its candidate: median restart is 36.67→35.60 seconds, below the
required 25% improvement. The fingerprint shortcut is omitted. No ranking,
preview, dependency, profile or general performance improvement is claimed.

## Release verification

The release gate requires the full fresh 36-pack/144-question compatibility
matrix on the exact versioned source, with same-head 277-case Linux platform
controls. The existing 1,200-second overall, 180-second per-pack, 2GiB RSS/disk
and 64MiB evidence bounds remain. Limited and unsupported outcomes retain those
labels; failed or incomplete contracts prevent publication.

Normal CI, real language servers, image contracts and clean/previous-version
upgrade checks run on GitHub runners. The upgrade baseline is 0.1.16. Actual
PyPI verification compares source, wheel, sdist, installed Python files and
metadata, plus CLI/init/doctor and bounded search continuation. The GitHub
release records the admitted matrix, workflow jobs, actual install proof and
downloaded asset hashes. Its final source tree must equal the tested candidate.
