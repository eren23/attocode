# Structural writes under interpreter contention

The retained Cockroach diagnostic includes structural persistence running alongside
lexical indexing. Its `save_analysis_batch` self-frame weights were 13.8 and 3.88
sampled thread-seconds. These are not wall times or proof of the release failure's
cause. Inspection found one SQLite insertion step per symbol/reference row despite
the existing 100-file transaction batching.

Structural writes now insert at most 64 rows per SQL statement (576 parameters
for references), retaining the surrounding atomic transaction and row order.
Lazy row construction bounds temporary parameter storage. Failures in SQL or row
generation propagate and roll back earlier groups and earlier files in the same
transaction. No schema, freshness check, source limit, ranking or deadline changed.

The [reproducible probe](../structural_write_probe.py) compares the frozen preceding
method with the current method on 40 files, each with 32 symbols and 32 references.
It optionally adds one CPU-bound Python thread. Temporary databases are deleted.
From the repository root, run:

```sh
.venv/bin/python packages/code-intel/evals/structural_write_probe.py
```

| Observation | Existing method | Bounded statements |
| --- | ---: | ---: |
| Exploratory, no competitor | 0.00517 s | 0.00468 s |
| Exploratory, CPU competitor | 13.24161 s | 0.84762 s |
| Checked-in probe, no competitor | 0.00510 s | 0.00850 s |
| Checked-in probe, CPU competitor | 4.08917 s | 0.50947 s |

Every case stored identical complete symbol/reference rows, including generated
IDs and definition keys. The CPU competitor remained alive through both contended
cases in the checked-in probe. These small, single observations vary with scheduling;
the uncontended probe was slower after the change. They support addressing native
call overhead under contention, not a fixed speedup, an overall indexing claim or
a claim that freshness/structural concurrency caused the cloud timeout.
The [raw observations](2026-10-15-structural-write-contention.json) include source
and probe hashes, Python/platform, fixture size and row digests.

Five new controls verify 133-row partial tails under SQLite's 999-variable limit,
every persisted field and ID order, empty/partial updates, and second-group SQL or
iteration failures followed by rollback and successful retry. The focused suite
passed 46 tests. The final bounded local gate `20261015T113931-b905addf` passed
537 contracts with 8 skips, lint, scale and lifecycle; source/fixture hashes stayed
unchanged during the run and scratch cleanup was verified. Peak managed disk was
180,966,931 bytes and peak sampled RSS 849,264,640 bytes. The new tests are included
in future local/broad gates.

No cloud worker or model request was started. The existing four-batch allowance is
exhausted, and the [last full gate](2026-10-15-cold-repair-cycle.md) still failed.
0.1.6 remains unpublished pending a passing full validation on the repaired source.
