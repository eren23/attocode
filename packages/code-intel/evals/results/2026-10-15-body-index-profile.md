# Body-indexing diagnostic and bounded reuse

This records the second rental's diagnostic. The subsequent
[completed four-rental cycle](2026-10-15-cold-repair-cycle.md) exhausted the
allowance and still failed the unprofiled cold-index gate.

Batch `fa9080220f974141` on `776a9adffb6c50707db1aa357927545e9c2673a4`
waited for clean cloud-init completion and produced one report. CockroachDB
still failed search warmup: keyword indexing reported 46.72 seconds with
4,980 reused ASTs; body indexing was unfinished at 123.797 seconds. This
profiled run is not a clean latency comparison or release pass.

The [normalized diagnostic](2026-10-15-body-index-profile.json) records py-spy
0.4.2 at 25 Hz, nonblocking: 4,181 samples and 86 sample errors over 134.33
seconds until the worker exited. The 205,426-byte profile stays in private
managed evidence. Body-index stacks account for 54.92 sampled thread-weight
seconds. Leading self-frame weights were tokenization (17.68 + 3.92 seconds),
per-window SQLite insertion (12.84 seconds), and parser execution (4.88 seconds).
These sampled weights are not independent wall-clock savings or proof of one
cause; structural hydration and freshness scans also ran concurrently.

The implementation shares per-line tokens across overlapping windows and
whole-file search, with separate tokenization for truncated lines. Retention is
limited to one file; body discovery retains its 512 KiB file limit. Existing
structural ASTs can serve span-cache misses only through content-hash matching.
SQLite inserts use at most 64 windows per statement in the existing atomic
transaction, preserving row order. Tests compare window/file terms, FTS row
contents, BM25 scores, cancellation and injected mid-refresh failure rollback.
Ranking weights, labels, source-window limits and warmup deadlines are unchanged.

A four-file local differential check against the preceding chunk implementation
produced identical chunks and whole-file terms. Its small timing observations
are not evidence that the cloud timeout is resolved. A fresh unprofiled full gate
is still required.

Worker deletion and zero active quality workers were verified. Controller time
was 315.45 seconds; estimated compute $0.0146. The initial profiler attachment
failed before sampling because its parent work directory did not yet exist;
that directory was fixed and attachment succeeded on the same worker. Two of
the four approved cycle rentals are used; two remain. 0.1.6 is unpublished.
