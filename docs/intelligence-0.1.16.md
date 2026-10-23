# Attocode Intelligence 0.1.16

0.1.16 stabilizes tied symbol-search pages, reduces the Docker image and maintains
bounded online compatibility evidence. The standalone package remains
`attocode-code-intel`.

```sh
uv tool install --force attocode-code-intel==0.1.16
```

Restart the MCP connection after upgrading so it loads the new package.

## Changes

- **Stable symbol pages.** Equal scores use a complete source-location tie-break
  before the result limit. Match scores, language-server priority and kind filters
  remain primary. Fresh-process reopening checks cover the ordering defect.
- **Smaller Docker image.** A separate build stage and restricted context remove
  package build source from the runtime. The reviewed same-runner comparison
  measures 879,136,629 → 775,865,818 bytes (11.7% smaller), with equivalent installed
  files, dependencies, service configuration and six runtime contracts. CI guards
  growth above 5% of that measured baseline. This does not remove local images.
- **Bounded online maintenance.** Experiments retain raw tool responses before
  validation, source identities and decoding policies, loaded package origins,
  first failures, resource observations and owned-workspace cleanup. The full
  compatibility operator uses these checks without changing ordinary output.
  The full matrix targets GitHub-hosted Linux with a same-source platform
  preflight. Three initial attempts remain incomplete: missing fixture history,
  then Linux and Mac deadlines after twenty-five and twenty-two packs.
  The 600-second ceiling remains unchanged.
- **Less expensive resource observation.** Disk accounting uses directory-entry
  metadata and includes directory symlinks themselves without following their
  targets. On one pinned source-only tree, median counter CPU time falls
  153→54 ms while byte totals match. This is a counter measurement, with no
  full-matrix speed forecast or product performance claim. The
  [diagnostic report](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-23-maintenance-cost.md)
  preserves the failed setups, real filesystem controls and frozen comparison.
- **Bounded distributions.** Source distributions exclude archived evaluation
  results; the tagged repository retains those public reports and raw archives.
- **Installation verification.** Candidate and actual PyPI checks compare source,
  wheel, sdist and clean/upgraded installed files, plus CLI/MCP/init/doctor and
  bounded search continuation. The upgrade baseline is 0.1.15.

## Experiments and limits

The [fresh preview comparison](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-23-preview-windows.md)
is rejected: 720 pages yield no distinct judged gains, twelve individual excerpt
losses and six exact-control changes. Its 24 questions are consumed.

The [restart comparison](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-23-restart-fingerprints.md)
stops incomplete when a scored baseline cold run differs from its self-pair in
reference candidates and their count. No candidate benchmark phase starts, and
no structural fingerprint optimization ships. The archived trial's legacy
canonical projection omitted some visible fields; the maintained validator now
retains all operation data except nested semantic-search index readiness.

The [native diagnostic](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-23-native-observations.md)
records twelve successful fresh OCaml observations and six Rust captures. These
observations do not establish the historical intermittent causes or their
frequency. Existing parser/recovery limits, dependencies, profiles and search
ranking defaults remain unchanged. No relevance, agent-benefit or restart-speed
gain is claimed.

The GitHub release records the exact release workflow, uploaded test evidence,
actual PyPI verification and artifact hashes. Publication does not upgrade a
global installation or restart an existing host connection.
