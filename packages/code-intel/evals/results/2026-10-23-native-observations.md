# Fresh-process OCaml and Rust observations

The historical intermittent failures were not reproduced. This diagnostic adds
evidence without changing parser limits, precision limits, retries or ranking.
The causes remain open; these observations do not establish a failure frequency.

The frozen design at `ffdaa6b56b4507e579c1d252028693a8a23a1402` ran in
[Actions 39879850033](https://github.com/eren23/attocode/actions/runs/39879850033).
All runtime work used the disposable Linux runner. The payload and its controller
completed in 44.211 seconds, with sampled aggregate peak RSS 1,143,422,976 bytes,
managed disk 14,045,184 bytes and evidence 3,645,440 bytes. The 1,200-second,
2 GiB RSS/disk and 64 MiB evidence ceilings held; owned scratch and processes
were cleaned up. Setup has a separate five-minute bound.

| Observation | Result |
| --- | --- |
| Six fresh direct OCaml processes | All found `type_expression` at line 7378 |
| Six fresh daily, non-watching gateway processes | All found the selected definition and source |
| Actual native parse calls | 18 trees, no native exception or missing tree |
| Native parse wall time | 28.576–30.142 ms |
| Native parse thread CPU time | 28.576–30.142 ms |
| Six fresh Rust fixture processes | All six source-bound protocol captures admitted |

OCaml uses `ocaml/ocaml@5fbe515aa215909e28328a059701da430bc3cff8`, only
`typing/typecore.ml`, SHA-256
`c3abd2af1040c9d1ad305f76b7f6f9f2e8243d45af2b862b10906ee7bd629010`.
The observer records real parser/thread identity, exact input hash, wall/thread
CPU duration and the native result before `bounded_parse` handles it. The
100,000-microsecond timeout and reset are forwarded unchanged. Timing on this
runner does not explain a previous failure on another machine, and wall minus
thread CPU time cannot identify a particular scheduling cause.

Rust uses the existing called/unused helper fixture and explicit version-2 edit.
Each process independently passed selected caller, unused namesake, moved caller,
old-target and clean-shutdown checks with rust-analyzer 1.94.1. Each capture is
admitted before the next process starts, including complete protocol/stderr,
source identities, JUnit, engine origins and actual loaded Rust grammar hashes.
The unused namesake may remain partial. The fixture's bounded warmup is distinct
from unchanged production precision limits of two seconds and four attempts.

The first native attempt,
[39879638024](https://github.com/eren23/attocode/actions/runs/39879638024), failed
during setup because the optional grammar extra was missing. No payload or
diagnostic worker ran. Its logs and null verdict are retained. Installing the
locked extra corrected setup; the payload design was unchanged.

Four observer controls failed before implementation and then passed. Review
identified that a zero-exit Rust worker could have invalid capture evidence;
five additional controls reproduced missing admission and missing fail-fast
behavior before the fix. The final online synthetic preflight passed 76/76.
No local native parse, server, test, build or installation was run.

The adjacent JSON records source and resource identities. The compressed archive
retains both native attempts, content-addressed responses, traces and frozen
operators with a per-member manifest. Full maintenance CI is a separate gate;
these diagnostics do not replace it. No additional native experiment is needed
for this batch; continue to the separately frozen preview evaluation.
