# Breadth cloud validation: release blocked

The final full run on `deaa836db43f04bbc6120c78845d4a7ed678b2fd` failed:
35 of 36 source packs completed, but CockroachDB search indexing exceeded the
90-second warmup wait. Standalone 0.1.6 remains unpublished. All six authorized
workstream rentals are used; no additional rental is scheduled.

The [normalized six-run record](2026-10-15-breadth-cloud.json) includes source,
harness, fixture and manifest identities, archive hashes, checks, pack outcomes,
missing queries, resources, estimates and cleanup evidence. Raw bounded reports
remain in the controller's private managed storage.

## Final full run

- Batch `8f4da7e1a253425a`, report `20261015T033604-e6632a52`.
- Lint, 492 contract tests (18 skipped), scale and lifecycle passed.
- Workflows: 125 passed assertions, 120 limited, 37 unsupported. No assertion
  failed before interruption, but CockroachDB is incomplete. Check-level
  `incomplete: 0` does not count interrupted packs and does not establish a pass.
- 140 of 144 retrieval questions observed; 100 known-target hits at five and
  127 at 24. The four missing CockroachDB questions are not zero-hit observations.
  Labels are non-exhaustive development targets, not agent-outcome judgments.
- Ranking did not run because the workflow gate failed. The implementation's
  separate CI ranking check passed; it does not complete this cloud run.
- Optional grammars were absent on this worker. Completed packs can contain
  unsupported and limited checks; completion does not imply full language support.

The new timeout diagnostics identify the current stage as `body`: keyword
indexing took 85.343 seconds, importance scoring 0.003 seconds, and warmup had
elapsed 122.927 seconds when observed. Body indexing was not ready. These clocks
describe the warmup attempt, not an ETA or proof of a single root cause. The
90-second polling threshold is checked after a tool call returns and is not a
hard cancellation deadline for that call.

Earlier fixes reduced redundant parsing, persistence commits, repeated symbol-name
copies and tokenizer allocations. Their correctness controls and required CI
passed, but repeated cold failures mean they have not established acceptable
end-to-end startup on this pack. Pandas, which timed out in the first full run,
completed in the final run. No ranking weights, labels or timeout limits changed.

## Resources and cleanup

The final worker's recorded checks took 1,084.941 seconds, peaking at 768.0 MiB
managed disk and 674.3 MiB sampled process-tree RSS. Its export was 1,442,824 bytes;
no source corpora or indexes were downloaded to the controller. These measurements
exclude protected shared caches.

The final controller recorded about 100 minutes between creation and completion,
exceeding its configured 90-minute duration and reported phase durations. Its SSH
test phase exited 255; collection still recovered a complete failed remote report.
The discrepancy's cause is unestablished. Do not claim this run demonstrates the
controller wall-clock bound; deadline enforcement needs separate investigation.

All six workers were deleted, each cleanup verified, and the final independent
API check found zero active quality workers. Total estimated compute: **$0.4487**;
monthly reservations: **$9**, including three earlier unrelated batches. Estimates
are not a provider invoice. The third run was profiled; the intended fifth-run
profile never attached. All failures are retained.

## Remaining work

Investigate keyword/body indexing cost using the retained timing/profile evidence,
and controller deadline behavior separately. Preserve the frozen labels and
correctness controls. A fresh complete cloud gate is still required before
publication and would require additional rental authorization because this
workstream's six-batch allowance is exhausted. There is no new model study,
Claude usage check, model download, default change or evidence of agent benefit.
