# Bounded intelligence experiments

The 0.1.16 maintenance batch starts by making failed experiments inspectable.
Manual diagnostic runs must retain responses before validating them, bind the
selected engine and source identities, and report incomplete observations without
a quality verdict. Runtime work runs on disposable GitHub Actions runners.

Use the manual **Intelligence experiments** workflow with a committed design.
`preflight` runs synthetic harness controls. `native`, `preview`, `restart` and
`broad` require their separately reviewed designs and operators before dispatch;
a missing design fails closed. The broad runner also needs response journaling
and fail-fast admission before its design can be enabled. Each attempt gets
a new directory and an artifact even when validation fails.

The payload ceiling includes the supervising controller and its descendants:
2 GiB aggregate RSS, 2 GiB managed disk and 64 MiB retained evidence. Payload
deadlines are 600 seconds for preflight/preview/broad, 1,200 for native and 1,800
for restart. CI dependency setup has a separate five-minute limit. Monitoring is
sampled; these bounds are admission/termination limits, not OS allocation quotas.

Responses are fsynced before validation and stored once by content hash. Source
checks declare strict/replacement UTF-8 and raw/universal newline handling to
match the producing operation. Metadata-only hits do not count as source excerpts.
Parent and worker origins, committed design, engine, operator, test and fixture
identities are retained. Partial attempts always have `decision: null`; a complete
payload is not itself a relevance or performance verdict. Existing normal CI
gates and release checks remain required.

The next image contract checks the dashboard, authenticated MCP navigation, CLI
entrypoints and writable service state, then requires the runtime image to omit
the package build source. The historical comparison may explicitly allow that
old build tree; the candidate and ordinary image gate require its absence.

The image build now separates package installation from its runtime stage and
allows only required frontend/package inputs into the build context. Runtime
base layers, service dependencies, entrypoints and writable directories remain
part of the comparison contract. Python bytecode is compiled on demand rather
than retained from the package build stage.

The image job compares the historical recipe and candidate on one runner,
retaining complete installed-file inventories once in logs and comparing their
fingerprints, versions, base layers and dashboard content. It adopts only a
strictly smaller image with identical runtime identity and passing smoke checks.
Image/layer byte counts and BuildKit's rounded context-transfer measurements are
retained with source identities. Actual eligible context file counts, logical
bytes and source hashes are measured inside dedicated context captures; transfer
counts alone can reflect BuildKit cache reuse. A real membership check rejects
extra files and includes disposable private/cache exclusion sentinels. Parent
cleanup verifies no smoke container with its unique ownership label remains.
A measured passing baseline is required before
the ordinary image guard can enforce its 5% growth ceiling; baseline changes
require a reviewed explanation and source commit.
