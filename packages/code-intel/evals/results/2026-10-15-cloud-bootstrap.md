# Cold smoke interrupted by first-boot maintenance

Batch `c3b32953922f469d` on `80e62df0838d5c1f5866c969d41ea2b231942d95`
failed. The worker journal records cloud-init restarting services while the
quality test service was active. That service stopped after 46 seconds and
started again, leaving an interrupted report alongside the later failed report.
This is diagnostic evidence, not a clean cold-performance or release pass.

In the restarted run, CockroachDB reused 4,980 structural ASTs; keyword warmup
reported 40.535 seconds. Body indexing was still unfinished at 119.335 seconds
and the workflow failed. Pandas completed its four retrieval questions. The
startup interruption and competing maintenance prevent a clean comparison with
the prior 85.343-second keyword measurement. Ranking was not selected.

The [normalized record](2026-10-15-cloud-bootstrap.json) retains both report
statuses and the failed outcome. Controller duration was 437.86 seconds; worker
deletion and zero active quality workers were verified. Estimated compute was
$0.0203. One of the four newly approved batches is used; three remain.

The controller now waits for clean cloud-init completion before setup and adds
an activation guard so maintenance cannot silently rerun a phase or reset its
worker runtime limit. Body indexing still needs profiling and a fresh complete
36-pack/ranking gate. Standalone 0.1.6 remains unpublished.
