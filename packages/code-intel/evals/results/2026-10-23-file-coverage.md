# File-level coverage study: incomplete, candidate withheld

The development study stops on a source-admission harness error. It has no
ranking-quality verdict. The file-coverage candidate is removed; all 349 product
files equal the merged native-fixed baseline `3bcce24`.

The candidate grouped the first 24 files using concept coverage across each
file's retained search windows. It preserved the original hits and scores and
excluded narrow queries. The frozen design, source and original artifacts are
in the [archive](2026-10-23-file-coverage.tar.gz); its SHA-256 is
`09a3374693386e599e6a5d8d7d1a613a05c3f6e44033c34aa6c89777f85ceca7`.
The [machine-readable result](2026-10-23-file-coverage.json) records identities,
resources and admission limits.

The paired functional run [39961832265](https://github.com/eren23/attocode/actions/runs/39961832265)
records exactly three expected baseline assertion failures and twelve passes,
then fifteen candidate passes and 207 maintained control passes. The separate
operator run [39963391839](https://github.com/eren23/attocode/actions/runs/39963391839)
passes all 240 controls, including fifteen real toy-gateway pages from a fresh
process. Expected baseline assertions are data in a successful workflow.

The single development run [39963795700](https://github.com/eren23/attocode/actions/runs/39963795700)
retains 126 scored pages: 54 per pandas arm, then eighteen Prisma baseline pages.
It stops before Prisma candidate scoring or either remaining repository. Prisma's
`CLAUDE.md` is a symlink to `AGENTS.md`. The observed source hash matches that
pinned 22,011-byte target exactly; admission incorrectly looks for `sha256` on
the symlink record, which contains its target instead. This is a harness error,
not evidence that the product returned incorrect source.

The attempt lasts 156.93 seconds, with peak aggregate RSS 996,536,320 bytes,
disk 655,900,672 bytes and evidence 22,458,368 bytes. It stays inside the frozen
600-second, 2 GiB RSS/disk and 64 MiB evidence limits. Owned cleanup verifies.
Independent retained-data replay checks all original raw hashes, engine/Git
identities, fixture receipts, observed source policies, coordinates, judgments
and per-arm request order. Interrupted Prisma arms have no final identity or
close admission. Actual serialized token counting remains delegated to the
source-bound online checks.

The twelve development questions were already consumed in earlier studies;
this attempt makes no freshness claim for them. Twenty-four source-authored
Gson/Redis validation questions were frozen before scoring. A 36,190-record
query/structured-anchor audit finds no collisions after retiring one previously
used topic during authoring; one JSONC record is unparsed. Author source exposure
is disclosed. No validation query is issued, and there is no scored retry,
replacement, tuning or retrospective quality decision.

The retained harness correction resolves source aliases through the captured
fixture inventory, following symlinks before parent components. It rejects root
escapes, absolute paths, missing targets, cycles, regular-file traversal,
chains beyond forty links and paths beyond 4,096 characters. A shared readiness
barrier requires exact completed parse/reference counts before new navigation
measurements. Neither change introduces a product ranking or speed claim.
