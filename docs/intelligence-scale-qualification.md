# Published intelligence scale qualification

The 2026-10-29 campaign is closed. [Results and permanent evidence](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-29-scale.md) record the search boundary failure, native parser limits, passed lifecycle/soak contracts and exact-byte exporter repair. The dedicated workflow is disabled; normal CI and the independent reaper remain enabled. All three approved reservations are spent. Any future campaign needs a distinct admitted design and allowance.

The manual **Published scale qualification** workflow tests the immutable
0.1.20 wheel on disposable DigitalOcean workers. Product source, dependency
metadata, native limits and the published release remain unchanged. The
maintained controller is `eval/quality/scale_campaign.py`; workload and evidence
code live alongside it. Nothing runs on the operator's Mac except metadata,
Git operations and retained-evidence analysis.

The campaign has three ordered, distinct batches:

1. Generate 10k, 50k and 100k Python source files with known imports/calls;
   measure cold startup, full hydration/search readiness and persisted reopen
   in separate processes. Preserve the configured 100000-file limit, including
   any reported truncation at the boundary; never infer complete coverage.
2. Materialize the full admissible pinned CockroachDB, pandas and Deno trees
   from the maintained source manifest. Retain original Git entry inventories,
   stored-source hashes and actual parseable eligibility. Files above 1 MB,
   excluded blob types, submodules, hidden/ignored paths and unsupported parser
   languages do not earn parsed coverage. Markdown discovery is separate from
   AST parsing. No upstream repository builds, installs or tests run.
3. Offer 1/4/8 concurrent gateway clients to one shared workspace, exercise
   edits/adds/renames/deletes and `.gitignore` refresh, compare with a fresh
   index, run a fixed eight-client burst every ten seconds, and test graceful
   plus forced restart with SQLite integrity checks. The product serializes
   workspace execution; offered concurrency is not parallel CPU execution.
   Include four existing OCaml/Rust/Perl/Crystal compatibility packs with no
   scored queries. OCaml retains the existing bounded passive native trace;
   other packs retain raw gateway and grammar identities, without claiming a
   new LSP/native trace or historical cause attribution.

Each worker is the explicitly selected `s-8vcpu-16gb-amd` in `ams3`, with a
live quoted hourly rate no higher than $0.16667 before tax. Shared CPU timing
is configuration-specific. The controller has 90 minutes, the test payload
60 minutes and setup 600 seconds. The payload cgroup has 12 GiB memory and no
swap; source/index scratch has 20 GiB, remote evidence 256 MiB. Process-tree
RSS is conservative and can count shared pages more than once. CPU/RSS samples,
monitor overhead, disk and elapsed-time observations accompany results.

All cases in one batch share its deadline. Capacity or resource failure stops
that family; unissued cases remain explicit. Real repositories are independent
cases and may continue after a correctness failure only when process cleanup
is verified and no resource/deadline reason was raised. There is no automatic
replacement or rerun. The soak uses only its frozen case budget remaining after
native/lifecycle checks; report its actual duration, not a promised hour.

Only evidence leaves a worker: at most 20 MiB overall, 2 MiB per exported file.
Large JSON and JSONL are split losslessly and bound by `export-manifest.json`;
reconstruction must verify part hashes and original hashes before interpretation.
Source corpora, indexes and package caches stay remote. Every product process
checks its installed files against the published wheel's 272 Python files.

Admission reconciles the exact eligible, parsed and reference-indexed path sets,
and separately rejects missing native grammars, fallback parser tiers and native
parse failures. Requests are recorded before dispatch so interrupted operations
remain visible. If complete export cannot fit, a bounded failure bundle keeps
original case outcomes, diagnostic prefixes/tails and explicit omitted-byte/hash
receipts. Such a bundle is incomplete and cannot earn a scale pass.

Before a billed dispatch, hosted controls exercise failure admission/cleanup,
real small gateway operations, lossless export, exact dispatch binding and a
live crash checkpoint. A separate hosted smoke runs the exact worker installer
and the published wheel through small synthetic, pinned-source and native/
lifecycle cases without cloud credentials. `access-check` verifies the live
quote, the existing bootstrap registration and creation-request validation
without provisioning a worker. No account SSH-key writes are required.

The approved October campaign adds precisely three $1 reservations to the
original 23 rows: $26 monthly allowance, one worker at a time. This is admission
authority, not an invoice or a provider-enforced billing ceiling. Reservations
are retained even for failed or unissued attempts. The private canonical ledger
is preserved and locked before dispatch. A temporary repository secret
`QUALITY_SCALE_RESERVATION` carries its exact snapshot and one reserved row;
older private history never appears in public workflow inputs or result artifacts.
The existing generic controller's $23 ceiling is unchanged.

The controller requires the frozen qualified source tree, manual main dispatch,
first run attempt, exact batch/reservation identity and no earlier dispatch with
the same run title. It generates a fresh job-only SSH key and creates one worker using an existing
bootstrap registration. Cloud-init appends only the disposable public key inside
that worker; the existing private key is never read or transferred. Provider
credentials remain on GHA. `finally` verifies worker deletion and removes the
disposable controller key files, also removing the in-VM authorization. A lost
create response is reconciled by its unique tag; unresolved state blocks another
launch. Workers also carry `attocode-quality-v1` for the existing independent
two-hour TTL reaper. Provider/GitHub outages can delay deletion. Temporary
reservation/bootstrap-metadata secrets and controller key files are removed after
the campaign. The existing registered bootstrap key and provider secret remain
unchanged.

Results are operational/source-based qualification, not held-out relevance,
exhaustive semantic correctness, agent benefit, a speedup or proof of historical
native failure causes. Missing receipts, incomplete coverage, capture loss and
unfinished operations remain visible even when a workflow process exits zero.

The [2026-10-30 search coverage follow-up](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-30-search-coverage.md) corrects the reproduced request discovery mismatch at 10,001 paths and records the retained causal evidence. The original paid campaign remains incomplete; 50k/100k qualification remains unissued. The [native parser follow-up](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-30-native-causes.md) diagnoses the exact captured inputs, qualifies an OCaml interface grammar correction, and distinguishes two current budget-sensitive files from nonreproductions. Historical native causes remain unproven.
