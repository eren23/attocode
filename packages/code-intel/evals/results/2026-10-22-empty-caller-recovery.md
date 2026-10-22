# Precision recovery without static callers

Precision enrichment previously stopped after unresolved definition and reference
responses when static analysis found no callers. Those responses can be transient
even after a successful server warmup. Recovery now continues within the existing
two-second deadline and four-attempt cap. A resolved unused declaration still
takes the fast path; persistent null responses remain partial.

The [machine report](2026-10-22-empty-caller-recovery.json) records source and
evidence hashes. Five gateway regressions use a framed subprocess peer after a
successful external definition warmup. They verify recovery with and without a
dynamic caller, a resolved unused declaration, persistent nulls, deadline expiry,
cached outcomes and shutdown. Static callers are actually absent. Against the
base implementation, four behavior cases fail and the ready-unused control passes;
all five pass after the fix. The cache clock is frozen independently of the real
asyncio deadline to avoid scheduler-dependent cooldown assertions.

One natural Rust observation before the fix passed in 5.480 seconds and had one
static caller, so it did not exercise this edge. A later installed Rust workflow
also passed. Neither observation explains the historical intermittent Rust failure.
An earlier observer setup import error started no server; an initial regression
fixture accidentally supplied a static import reference. Both unsuccessful setup
attempts remain in the private evidence and are excluded from behavioral proof.

The existing full local result is 4,157 passed, 14 skipped and one expected failure.
Its source-bound controller completed in 162.749 seconds, with sampled peak RSS
936.1 MiB and managed scratch 537.0 MiB; owned scratch was removed. Lint, scale at
100/1,000/10,000 files and 20 lifecycle cycles passed. Local SQL checks were 50
passed and one PostgreSQL-dependent skip; CI must independently pass all 51 on
both supported Python versions. These local runs preceded the user's correction
to keep broad testing online. No additional local test run is authorized by this
report; remaining validation uses GitHub CI.

The separate OCaml check used two predeclared fresh processes on the exact
historical source. Three native calls returned clean trees in 18.5–20.1 ms with
similar thread CPU times under the unchanged 100 ms limit. The initial AST and
published index already contained the target before selected inspection. No
OCaml patch follows from these successful observations. Historical no-tree
results occurred before extraction, but their suppressed exception and absent
CPU measurements prevent attribution to a specific trigger. Direct execution
preceded the gateway worker, so filesystem and library caches may have warmed.

Independent review found no remaining implementation issue. The CI evidence gate
additionally requires all 11 precision-recovery identities alongside the prior
154 regressions, all SQL cases and all four real-server workflows. No publication,
installation change, MCP restart or ranking improvement is claimed.
