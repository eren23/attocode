# Attocode Intelligence 0.1.18

0.1.18 corrects readiness after a failed snapshot restore followed by a successful
full fallback rebuild. The package remains `attocode-code-intel`.

```sh
uv tool install --force attocode-code-intel==0.1.18
```

Restart the MCP connection after upgrading to load the new package. Publication
does not upgrade a global installation or restart an existing host.

## Recovery readiness

A caught snapshot restore error reset hydration to `skeleton`. The fallback could
rebuild all parsed files, references and dependencies, save a healthy checkpoint,
and still return that stale phase. Clients saw incomplete readiness at full
coverage, and service initialization could schedule redundant hydration.

Publish `ready` after the existing full fallback work only when actual parsed and
reference-indexed counts both equal the eligible source count. Partial recovery
after a restore exception, minimal initialization and interrupted persistence do
not gain an unconditional ready flag. Empty completed recovery retains its existing
semantics. Successful cached restoration and unrelated cold-start phase policy
remain unchanged. Parsing, retries, native 100 ms / Rust 2 s and four-attempt bounds,
source/cache eligibility, 32 MiB / 1 MiB summary caps and staged publication remain.

[Nine regressions and313 online controls](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-24-recovery-readiness.md)
retain the causal failure and corrected reconstruction, navigation, checkpoint,
healthy reopening and service-hydration behavior. The temporary control channel
is retired; maintained preflight has 286 cases and required regressions 299.

## Maintenance and limits

[Unprofiled startup attribution](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-24-unprofiled-stages.md)
separates nested startup scopes. Both the bounded-JSON and single-final-index
candidates miss their frozen adoption rules and remain removed. The latter
reduces the same-runner median 28.62→26.72s (6.7%, required 10%); this release
claims no general restart speed, relevance or agent-quality improvement.
Original failed/incomplete/rejected evidence remains in the tagged repository
and stays excluded from package distributions. Dependencies remain unchanged.

## Release verification

Publication requires a fresh 36-pack matrix, 288 operational contracts and 144 existing observations
on the exact final versioned source tree, with 286 Linux platform controls on the same head.
Keep the 1,200-second overall, 180-second per-pack, 2 GiB RSS/disk and 64 MiB evidence limits. Limited and
unsupported outcomes retain their labels; any failed or incomplete contract holds
publication. This is compatibility evidence on consumed anchors, not a new
relevance or performance study.

Normal CI requires all 17 checks, both Python versions, PostgreSQL/HTTP, real language
servers, image contracts and candidate clean/previous-version installs. The tag
workflow requires all 18 jobs and actual PyPI clean-install/0.1.17-upgrade verification,
including source/wheel/sdist/installed Python and METADATA and CLI/init/doctor/continuation
checks. The final tag tree must equal the matrix and reviewed candidate. The GitHub
release records workflow evidence and verified downloadable assets.
