# Additional cloud batch: setup failure

The additional authorized full batch on `aeb1f7ba291ebeb81f1ee3e7a8e9fd512fd555f8`
failed during setup. Another `apt-get` process held the dpkg frontend lock;
installation exited 100. Product tests never started. This run supplies no new
indexing, retrieval or ranking result, and 0.1.6 remains unpublished.

Batch `7b6d17ef54f5425c` finished in 77.59 controller seconds. The worker was
deleted and a subsequent independent API check found zero active quality workers.
Estimated compute was $0.01, bringing the seven workstream rentals to $0.4587.
These estimates are not invoices or reservation refunds. Monthly reservations are
now $10, including three earlier unrelated batches; both the authorized seven-run
allowance and monthly reservation cap are exhausted. No further worker is scheduled.

The [normalized setup record](2026-10-15-cloud-setup-lock.json) preserves phase
statuses, timings, source and cleanup evidence. The earlier
[six-run record](2026-10-15-breadth-cloud.md) remains historical evidence of the
cold-indexing failure, not a result for the latest fixes in PR #188.

Setup now configures apt to wait at most 120 seconds for a dpkg lock, within the
existing 600-second setup deadline. It leaves the competing process and lock
files alone. Linux regression checks use an isolated package database and actual
fcntl contention to exercise successful lock release and bounded failure when
the lock remains held. macOS skips these Linux-only checks explicitly.

A fresh full 36-pack gate, including ranking, is still required before publication.
The setup failure does not establish whether the merged AST reuse, Go traversal
and deadline fixes resolve the previous full-run blockers.
