# Lexical SQL persistence under contention

The first follow-up cloud run on `4f33254` still timed out on CockroachDB:
keyword indexing took 55.955 seconds, and body indexing was unfinished at
98.125 seconds of warmup. Structural batching alone did not clear the gate.

Keyword cache writes now use at most 64 rows (576 parameters) per statement.
Body refresh deletes stale/deleted paths in groups of at most 64, including
orphan rows. Existing transactions, cancellation rollback, replacement order,
ranking, source limits and the 90-second warmup threshold remain unchanged.

Five controls check exact cached rows and row IDs against the preceding SQLite
operations, duplicate IDs across groups, reload parity, SQLite's 999-variable
limit, second-group SQL/encoding failures, cancellation, body-delete rollback
and successful retry with unchanged rows preserved. The focused suite passed
52 tests. Bounded local run `20261015T124801-6da77b64` passed 545 tests with
8 skips, lint, scale and lifecycle checks; scratch cleanup was verified.

The [probe](../lexical_sql_probe.py) loads preceding methods from the locally
available baseline commit and removes its temporary databases. Run from the
repository root with `.venv/bin/python packages/code-intel/evals/lexical_sql_probe.py`.
It uses 2,048 keyword documents/256 files and deletes 132 of 133 body-indexed
files, with or without one CPU-bound Python thread (20-second maximum).

| Checked-in probe | Before | After |
| --- | ---: | ---: |
| Keyword cache, no competitor | 0.00600 s | 0.00541 s |
| Keyword cache, CPU competitor | 4.25354 s | 0.60987 s |
| Body deletion, no competitor | 0.01123 s | 0.01062 s |
| Body deletion, CPU competitor | 2.45547 s | 0.56262 s |

Stored rows matched in every case; the competitor stayed active throughout
each contended observation. Body metadata comparison excludes fixture mtimes.
The [raw record](2026-10-15-lexical-sql-contention.json) includes source/probe
hashes, environment, row hashes and an earlier exploratory observation (whose
uncontended keyword case became slower). These are individual, scheduling-sensitive
component measurements, not cloud latency, proof of the timeout's cause, or
evidence that the release gate now passes. The final full cloud run is pending.
