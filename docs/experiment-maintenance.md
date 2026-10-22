# Bounded intelligence experiments

The 0.1.16 maintenance batch starts by making failed experiments inspectable.
Manual diagnostic runs must retain responses before validating them, bind the
selected engine and source identities, and report incomplete observations without
a quality verdict. Runtime work runs on disposable GitHub Actions runners.

Use the manual **Intelligence experiments** workflow with a committed design.
`preflight` runs synthetic harness controls; `broad` runs the pinned compatibility
packs. `native`, `preview` and `restart` require their separately reviewed designs
and operators before dispatch; a missing design fails closed. Each attempt gets
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
