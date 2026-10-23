# Resource-observer cost, 2026-10-23

The disk counter is retained after a frozen same-runner comparison. On the pinned
Cockroach source-only tree, its median CPU time is 152.952→54.474 ms and wall time
152.973→54.474 ms across eight alternating pairs. Both counters report
156,958,874 bytes for all 9,758 entries. Ratios 0.3562 CPU and 0.3561 wall pass the
frozen 0.70/0.80 limits. This measures the counter, not product or full-matrix speed.

The old `os.walk` implementation constructed `Path` objects and called `lstat`
for every file. The replacement uses fresh directory entries and their metadata.
It preserves `max(logical_size, allocated_blocks × 512)`, counts hard-linked names
separately, excludes real-directory metadata, and includes symlink objects without
following their targets. Unreadable paths fail closed; disappearing paths are
handled during owned cleanup. Sampling frequency and resource ceilings are unchanged.

A real filesystem control first demonstrated omitted directory-link allocation:
1,048,576 bytes observed versus 1,052,672 expected. After correction, both file-link
and directory-link controls pass with the other maintained controls. The benchmark
tree itself has no directory links, so its two expected totals are equal.

## Diagnostic and evidence boundaries

Three full-matrix attempts remain incomplete. The first lacked a pinned historical
frontend commit; bounded acquisition corrected that setup defect. A Linux attempt
then reached its 600-second deadline after 25 admitted packs; a Mac attempt reached
the same deadline after 22. Neither partial result is a complete compatibility pass.

One corrected Cockroach diagnostic completed its eight checks and four existing,
consumed development retrieval observations. It retained 52 raw MCP responses and
106 executor profiles. The monitor consumed 94.685 CPU seconds during a 188.273-second
supervised command. Its retained source-blob cache differs from the full matrix, so
that magnitude cannot be projected directly into a matrix speed improvement.

CPython 3.12's global monitoring callbacks can include concurrent-thread activity;
cProfile attribution is not isolated CPU time. Separate executor-thread CPU and
scope-wall counters exclude profile serialization, while profiling itself changes
timings. Native internals are not independently sampled. These limits preclude a
product restart-speed or causal conclusion from the profile alone.

An initial observer-clock control failed before its correction. The initial
profiler then stopped before the first product operation because simultaneous
profilers competed for the global monitoring ID. A real-interpreter regression
reproduced that setup failure, then passed with one profiler in the serial executor.
All failed attempts and their corrected controls are retained separately. Temporary
profiling and comparison entry points are removed after archiving.

## Reproduction identities

- Profile source: `8db85eb0006b4cfa975b90ad3b091624c7256155`,
  [workflow 39907601223](https://github.com/eren23/attocode/actions/runs/39907601223).
- Counter comparison source: `f826bfeace21944204bdb0694b6face1e3e1c5cd`,
  [workflow 39908894535](https://github.com/eren23/attocode/actions/runs/39908894535).
- Baseline counter function SHA-256:
  `5231093c02984ab9ea1a15ab2db9267feacd6177f0a521818436057f00e11a71`.
- [Decision JSON](2026-10-23-maintenance-cost.json) and
  [source/artifact archive](2026-10-23-maintenance-cost.tar.gz), SHA-256
  `53ada823c40915f73733e28fd760f66a26bbb78a1e8197d98e69550b1c8daad7`.

The archive preserves nine original GitHub Actions artifact ZIPs, failed and
passing operator versions, selected source/configuration, measurement requests
and results, and a per-member hash manifest. No third-party fixture is materialized
in the archive. Independent retained-data checks rebind artifact bytes and source
functions, replay request order and profile summaries, and recompute medians and
gates. Physical filesystem allocation and complete pinned-fixture equality remain
source-bound online observations; the host analysis does not recreate fixtures.

This work changes the resource observer only. Product ranking, parser limits,
recovery attempts and cache limits are unchanged. No full-matrix pass, fresh
relevance gain, agent benefit or product speedup is established by this report.
