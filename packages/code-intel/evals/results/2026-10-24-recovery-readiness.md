# Completed snapshot-fallback readiness — 2026-10-24

A failed snapshot restore resets hydration to `skeleton`. The fallback could then
successfully rebuild every AST, reference and dependency, save a healthy
checkpoint, and return that stale phase. Readiness consumers still saw `skeleton`
at full parse/reference coverage; lazy service initialization could unnecessarily
start background hydration.

The fix publishes `ready` at the end of a completed full fallback, after existing
graph and persistence work, only when actual parsed and reference-indexed counts
both equal the total eligible source count. Successful cached restoration keeps
its early return. Incomplete recovery after a restore exception, restricted
skeleton budgets, minimal initialization and interrupted persistence do not gain
an unconditional ready flag. Empty completed recovery retains the existing
empty-index semantics; the experiment barrier still requires a nonempty fixture.
Unrelated cold-start phase behavior is unchanged.

The [baseline control](https://github.com/eren23/attocode/actions/runs/40115985938)
first proves complete reconstruction of three real files and their navigation,
plus a valid checkpoint, then fails exactly at the stale phase assertion.
The expected failure is retained as data inside a successful Actions controller.
The [fixed controls](https://github.com/eren23/attocode/actions/runs/40116296386)
pass **313/313**: 277 maintained controls, 27 existing restart/hydration controls,
and nine new regressions. The new cases cover SQLite read failure, malformed/null
checkpoints, exact reconstructed AST/navigation state and healthy subsequent
reopening, partial parse/budget fallback, minimal and empty initialization,
interrupted writes, and the public service avoiding redundant hydration.

All runtime validation runs on GitHub Actions under the existing 600-second,
2 GiB RSS/disk and 64 MiB evidence envelope. Exact original XML, selected source,
engine origins and cleanup are independently admitted. The two original ZIPs,
executed test/controller/design sources and both complete 349-file engine trees
are retained in the [archive](2026-10-24-recovery-readiness.tar.gz); all member
bytes were rechecked. SHA-256: `87f6aecdf217ad6401b3ba625d4ebb83bf9b756f7f4007b04a611ad01b99477a`.
The [machine report](2026-10-24-recovery-readiness.json) records source revisions
and the original control identities.

Temporary control wiring is retired. The nine regressions remain in maintained
preflight (286 cases), with 299 required regressions in final CI admission.
This is a readiness correctness fix, not a restart speed, retrieval quality or
historical native-cause result. Parsing, retries, native limits, source validation,
cache eligibility, 32 MiB / 1 MiB summary bounds and staged publication remain.
Version and dependencies stay at 0.1.17; the change is unreleased. Local Docker,
global tools and MCP state are preserved.
