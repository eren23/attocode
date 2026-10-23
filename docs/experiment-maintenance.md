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
The passing same-runner comparison at `4233a2f` (Actions run `39874866186`)
measured 879,136,629 → 775,865,818 image bytes, saving 103,270,811 bytes (11.7%).
All 101 installed distribution identities and the runtime checks matched.
Eligible context fell from 40,957,156 to 4,120,661 logical bytes. These are
uncompressed image and logical input sizes, rather than registry transfer sizes.
Earlier incomplete attempts remain diagnostic evidence and do not set the budget.

Ordinary image CI now enforces the reviewed baseline in
`docker/code-intel/image-budget.json` with a 5% growth ceiling, while retaining
runtime, source-absence and context checks. A change to that baseline requires
a new measurement, source commit and reviewed explanation. Reproduce a historical
comparison online with `--compare-ref <exact-commit>`; normal CI uses the guard.

## Native diagnostic design

The manual `native` design observes six fresh direct OCaml processes and six
fresh selected-symbol gateway processes against the historical pinned
`typing/typecore.ml` source. A CI observer forwards the parser's unchanged
100 ms limit and reset while retaining actual native outcomes, parser/thread
identities, source hashes, wall time and thread CPU time before fallback.
Wall minus thread CPU time is not evidence of a particular scheduling cause.

Six separate Rust pytest processes use the existing real-server fixture and
protocol/stderr consumer. They check the selected caller, unused namesake,
version-2 edit, moved caller and shutdown. The unused symbol may remain partial.
The fixture's bounded server warmup is recorded separately from production's
unchanged two-second precision limit and four attempts. Tools and the optional
OCaml grammar are acquired only on the disposable runner before the payload.

Fresh workspaces, engine origins, grammar/tool identities, raw responses and
partial failures are retained under the shared limits. A complete diagnostic
run establishes observations, rather than the historical intermittent cause
or a failure frequency. A demonstrated defect requires a focused regression
before a product fix; otherwise the cause remains open and maintenance proceeds.

## Frozen preview evaluation

The preview design freezes 24 new source-bound questions across pandas and
ripgrep. Each development/validation split has eight behavior questions, two
exact queries and two unrelated controls. Recorded query/anchor manifests were
checked for prior consumption; implementer source exposure is disclosed.

The candidate is the previously unmeasured whole-line window rule: it may
replace a preview only with a strict superset of its positive query terms,
within the same character cap. Files, scores, result identities and order stay
part of the no-loss comparison. Three alternating baseline/candidate rounds
cover depths 5/24, budgets 2,000/8,000 and exact-file scopes. Both splits must
gain two distinct visible judged excerpts at five, with a gain in each
repository in every round. Individual file/excerpt losses, delivered identity
changes, changed controls or excessive warm p95 latency reject the candidate.
Missing, duplicate or misbound captures are incomplete and have no verdict.
There is no tuning, replacement or scored relaunch after a failed gate.

The request pipeline retains full MCP responses by content hash before token,
JSON, source or label validation. Internal render inputs retain fingerprints
and pinned-fixture lineage rather than copies of undelivered whole files.
Actual providers select replacement UTF-8/universal newlines for indexed bodies,
strict UTF-8/raw newlines for hydrated metadata, or replacement UTF-8/raw
newlines for exact scoped fallback. Metadata text without source coordinates
does not count as an excerpt. Passive provider controls include actual MCP
delivery of invalid UTF-8/CRLF source and unchanged uninstrumented result rows.

Per-request timing includes the MCP call and passive source fingerprinting.
Response retention and validation are outside that measurement and inside the
full 600-second payload ceiling, along with startup, shutdown and evidence I/O.
The same aggregate 2 GiB RSS/disk and 64 MiB evidence bounds apply. A complete
run remains a bounded, non-exhaustive excerpt observation, without a ranking or
agent-completion claim. An accepted rule still needs normal product verification.
