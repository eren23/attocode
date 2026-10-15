# Cold-index repair cycle: release still blocked

The four additionally authorized rentals are complete. The final unprofiled full
gate on `9d3574e3b9cb978d243d6416368b6279a4188d1a` failed: 35/36 pinned source packs
passed, but CockroachDB body indexing did not finish. 0.1.6 remains unpublished.
The [normalized record](2026-10-15-cold-repair-cycle.json) preserves source,
harness, fixture, pack and archive identities, every pack status, phase times,
resources, cost estimates and cleanup verification.

| Rental | Purpose and result | Controller seconds | Estimated compute |
| --- | --- | ---: | ---: |
| `c3b32953922f469d` | Cockroach/Pandas smoke; cloud-init restarted the active service; invalid clean latency comparison | 437.86 | $0.0203 |
| `fa9080220f974141` | Profiled Cockroach diagnostic; body warmup incomplete | 315.45 | $0.0146 |
| `fc676e3912ee47cb` | Full-gate launch; provisioning timeout before product tests | 315.70 | $0.0146 |
| `9bad147e19284159` | Full unprofiled gate; Cockroach incomplete | 1567.29 | $0.0726 |

## Final full-gate observations

- Contracts: **518 passed, 22 skipped**, zero failures/errors. Lint, scale and
  lifecycle checks passed. Workflows failed; ranking was consequently skipped.
- 35/36 packs passed their contracts, including explicit capability limitations.
  Completed checks had 125 passed, 120 limited and 37 unsupported outcomes.
  Cockroach completed definition/source checks only; zero failed assertions does
  not make an incomplete pack a pass.
- 140/144 retrieval questions were observed, with 99 labeled hits in the first
  five and 127 in the first 24. Four Cockroach questions are missing. Labels are
  non-exhaustive development targets; missing questions are not zero-hit results.
  This is not agent-quality evidence or a frozen-candidate ranking comparison.
- Cockroach keyword indexing: **59.487 seconds**, 4,980 reused ASTs. Body indexing
  remained unfinished at **129.862 seconds** of warmup. The 90-second polling
  threshold is checked after a tool response; it is not hard cancellation.
- Controller: **1567.29 seconds (26.12 minutes)**, within the 90-minute limit.
  Clean bootstrap completed before setup, with one report and no observed service
  restart. The earlier 100-minute overrun did not recur; a failed product run
  within budget does not prove every deadline path correct.
- Peak managed check disk: **1,061,372,058 bytes**; peak sampled process-tree RSS:
  **687,362,048 bytes**. Both are below the 5 GiB/4 GiB caps. Exported files totaled
  **1,463,075 bytes**; source corpora and derived indexes stayed on the worker.
- All four workers were deleted, report cleanup was verified, and the independent
  provider API check found zero active quality workers.

## Repairs and their limits

[PR #188](https://github.com/eren23/attocode/pull/188) added content-verified AST
reuse, bounded Go declaration extraction and deadline enforcement controls.
[PR #189](https://github.com/eren23/attocode/pull/189) bounded apt lock waiting.
[PR #191](https://github.com/eren23/attocode/pull/191) waits for clean cloud-init
completion and prevents a maintenance restart from repeating a worker payload.
Its Linux controls exercise explicit service restart and a TERM-resistant child.
The [bootstrap record](2026-10-15-cloud-bootstrap.md) retains the triggering failure.

The [profiled diagnostic](2026-10-15-body-index-profile.md) informed
[PR #192](https://github.com/eren23/attocode/pull/192): share per-line tokens across
body windows and file search, reuse matching published ASTs for span misses, and
batch up to 64 SQLite rows per statement within the existing transaction.
Focused controls preserve terms, windows, row order, BM25, rollback and cleanup.
Its bounded local run passed 532 tests with 8 skips; the final Python 3.13 CI
product job passed 719 with 18 skips. All reported non-skipped final-head CI
checks passed before each implementation merge. The final cloud failure above
supersedes any suggestion that these changes resolved the cold-start blocker.

No ranking weights, labels, model defaults or warmup limits were relaxed. Optional
grammars were unavailable in this clean cloud environment; the separate CI grammar
matrix does not turn its unsupported outcomes into successes. Concurrent structural
hydration/freshness work is a candidate for further investigation from the retained
profile, not an established cause. A useful next diagnostic would separate its
cost from keyword/body work and check repeated repository-wide work before another
full validation. No additional rental is authorized by this completed cycle.

## Cost and release decision

The four rentals total **$0.1221 estimated compute**. All 14 ledger rentals total
**$0.6487 estimated compute**. The $14 monthly reservation is an admission cap,
not spending. The user's last dashboard observation was $0.62 before this cycle;
no fresh provider invoice was obtained. Billing API access lacked permission and
automatic approval review blocked the browser's Google sign-in redirect.

All four additional batch slots are exhausted. Release stays blocked; no 0.1.6
tag, PyPI publication, global tool upgrade or host MCP restart was performed.
R7 STOP, frozen studies and shared caches remain unchanged.
