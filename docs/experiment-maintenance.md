# Bounded intelligence experiments

The 0.1.16 maintenance batch starts by making failed experiments inspectable.
Manual diagnostic runs must retain responses before validating them, bind the
selected engine and source identities, and report incomplete observations without
a quality verdict. Runtime work runs on disposable GitHub Actions runners.

Use the manual **Intelligence experiments** workflow with a committed design.
`preflight` runs synthetic harness controls. `native`, `preview`, `restart` and
`broad` require their separately reviewed designs and operators before dispatch;
a missing design fails closed. The broad operator now retains every raw MCP
response, validates each worker's evidence before the next pack, and stops on
the first failed or incomplete check/pack. Each attempt gets a new directory
and an artifact even when validation fails.

The payload ceiling includes the supervising controller and its descendants:
2 GiB aggregate RSS, 2 GiB managed disk and 64 MiB retained evidence. Payload
deadlines are 600 seconds for preflight/preview, 1,200 for native/broad and 1,800
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

Before advancing to the next preview worker, the controller admits every journal
reference by content hash and size, binds each capture to its preceding request,
and recomputes delivered identities, data hashes and source judgments from raw
responses. Full materialized source inventories are checked against committed Git
blobs before retrieval and checked again afterward; only the generated root
`.attocode` index directory is excluded. Missing captures or fixture drift stop
the attempt without a quality verdict.

The [2026-10-23 frozen trial](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-23-preview-windows.md)
rejected the preview rule: zero judged excerpt gains, one distinct question lost
in every round, and one changed exact control. Product previews remain unchanged.

## Restart fingerprint trial

The restart design uses the committed baseline after the preceding maintenance
changes. A fresh baseline-only cold/restart pair must first return identical
canonical navigation and search evidence. Only then may the six alternating
baseline/candidate workspaces run, each with two fresh phase processes. Every
phase is replayed and admitted before the next starts; the canonical result
lists retain their original order.

The archived candidate adds at most 2 MiB of complete structural fingerprints and
keeps the existing 32 MiB AST-summary limit. A matching source, installed direct
grammar, navigation identity and full healthy FileAST may avoid redundant index
repair after a missing summary is reparsed. Missing, malformed, failed, changed,
capped and legacy evidence conservatively follows the existing repair path.

All 12 scored canonical hashes must match the admitted baseline pair. Retention
also requires median restart time at most 75% of baseline and median cold time
at most 105%. Phase elapsed times include subprocess startup/shutdown, evidence
I/O/admission and source/engine rechecks. Fixture copy/setup is outside phase
medians and inside the shared 1,800-second payload; one workspace is removed
before creating the next. The observation uses one runner with warm OS caches,
without a general host-performance or fresh-relevance claim. Any incomplete
capture stops the comparison with no performance verdict or scored retry.

The [restart observation](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-23-restart-fingerprints.md)
stopped with incomplete baseline evidence before any candidate benchmark phase.
The optimization is omitted. The completed preview and restart wrappers have
been removed to prevent scored relaunches; their frozen designs and responses
remain archived. A future trial needs a new approved design. The maintained
canonical comparison retains all data fields except semantic index readiness
metadata; result order, visible counts and ranking evidence remain comparable.

## Final compatibility admission

The versioned broad design fixes the existing 36-pack manifest and its 144
consumed development questions. It runs the complete fresh set without resume,
shards or ranking experiments. Optional grammars are acquired during the bounded
online setup, then copied into the managed cache before payload use. Every
worker checks the selected package and all loaded children at start and end.

Full pinned Git inventories must match the materialized tree before evaluation
and the unchanged source afterwards. All compact, warming and paginated MCP
responses are fsynced once before budget, JSON, source or result validation.
Primary symbol source follows replacement UTF-8/universal newlines with complete
LF-joined lines. Semantic previews follow their observed producer policies;
metadata descriptions never count as source spans.

Before starting the next pack, the controller checks every raw reference hash,
request sequence, source policy, response budget, gateway shutdown, origin and
source identity, and recomputes check outcomes and retrieval summaries. A first
failure leaves its raw capture and checkpoint, then stops the matrix. Limited
and unsupported checks retain those labels. The final source remains unchanged
after dispatch; the release verification asset records the independently
admitted result and exact source-tree equivalence rather than changing the
candidate to add a passing report. This is compatibility evidence, not fresh
relevance, performance or agent-benefit evidence.

The final operational matrix targets the standard GitHub-hosted `ubuntu-latest`
x86_64 runner, with an explicit Linux/x86_64 assertion and a separate five-minute
277-control preflight gate before the 1,200-second payload. Its control artifact
is separate and bound to the same source head. Ordinary product CI, real servers,
Docker and published-install verification retain their Linux runner contracts.
A successful matrix does not establish any cross-platform speed improvement.

The first Linux attempt stopped after twelve packs because its shallow checkout
lacked the pinned historical frontend commit. Exact-commit setup corrected that
fault. The second Linux attempt hit the 600-second deadline after twenty-five
admitted packs (200 checks: 109 passed, 84 limited, seven unsupported) and 100
retrieval observations. A subsequent Mac attempt also hit the deadline after
twenty-two admitted packs (176 checks: 101 passed, 72 limited, three unsupported)
and 88 observations. All three attempts remain incomplete, with raw artifacts
and cleanup evidence retained; the platform change did not solve the ceiling.

The [resource-observer investigation](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-23-maintenance-cost.md)
then measured substantial monitor CPU cost and separately compared metadata
counters on one pinned source-only tree. The retained traversal uses fresh
directory entries, preserves conservative logical/allocated byte accounting and
includes directory-link objects without following targets. Median counter CPU
time falls 153→54 ms across eight alternating pairs, with matching byte totals;
this is no full-matrix speed prediction. Real filesystem RED/GREEN controls and
all failed diagnostic setups are archived. Temporary diagnostic entry points
were removed after use. The resulting Linux retry preserves all source anchors,
fresh processes, request grids, resource caps and first-failure rules; it does
not enable the withheld structural-fingerprint optimization.

The corrected counter retry also reached the original 600-second deadline after
twenty-six admitted packs (208 checks: 113 passed, 88 limited, seven unsupported)
and 104 observations. It remains incomplete, with cleanup verified. The complete
matrix uses a separately approved 1,200-second overall window; its 180-second
per-pack timeout, full fresh manifest, first-failure stopping, source/origin/raw
admission and RSS/disk/evidence ceilings remain unchanged. Earlier attempts are
not reclassified. This budget change is not a product performance improvement.
