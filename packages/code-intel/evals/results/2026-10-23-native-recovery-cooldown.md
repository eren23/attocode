# Later explicit inspections recover after transient native failures

A selected-file recovery failure previously stayed cached for the same source
and parser identity. If the parser became healthy afterward, further inspections
still returned a partial `not_found` until an edit, refresh or new process.
The candidate permits one new attempt on a later explicit inspection after a
one-second monotonic cooldown. Immediate repeats reuse the partial result;
there is no background retry, sleep or unbounded loop in the product.

The 100 ms native parse limit, source/parser identity guards and staged navigation
repair remain. The cooldown starts after each attempt finishes. A changed
source/parser identity retains its existing path, and unrelated edits cannot be
blessed by an expired cooldown. Healthy missing names do not cause reparsing.

## Online baseline and candidate evidence

[The paired control](https://github.com/eren23/attocode/actions/runs/39953820545)
runs the same frozen tests against the exact published 0.1.16 engine and candidate
in separate processes. Baseline has two required assertion failures and one passing
source-safety control; candidate passes all three. Persistent failure is limited
to one attempt per cooldown, and later healthy recovery restores definitions and
references. All 172 maintained preflight checks pass. The expected baseline failures
are admitted data inside a successful workflow, not separate failed workflows.
The job took 28.808 seconds and verified cleanup.

[The pinned OCaml diagnostic](https://github.com/eren23/attocode/actions/runs/39955155607)
uses two fresh gateways on identical `ocaml/ocaml@5fbe515aa215909e28328a059701da430bc3cff8`
`typing/typecore.ml` bytes (SHA256 `c3abd2af1040c9d1ad305f76b7f6f9f2e8243d45af2b862b10906ee7bd629010`).
A clearly labeled one-microsecond diagnostic fault first produces an actual failed
selected recovery in both arms. The production 100,000-microsecond limit is then
restored, followed by a 1.1-second wait outside the product and a new explicit request.
Baseline remains `not_found`; candidate finds `type_expression` at line 7378 with
source coordinates verified against the pinned Git bytes. Candidate's recovery
produces real native trees at the normal limit. The entire diagnostic took
11.425 seconds, within 1,200 seconds / 2 GiB RSS and disk / 64 MiB evidence, and
verified owned cleanup.

Raw responses precede validation. Child package origins, both engine inventories,
actual native outcomes/resets, source and grammar identities, limits and shutdown
are retained and independently checked as data. No local native parser, test,
installation or benchmark ran.

## Attribution and retained failures

This proves the persistent partial-result mechanism and its recovery correction.
The injected fault is not a reproduction of the original operating-system or
scheduling trigger. The historical OCaml record lacks the underlying native
exception and thread CPU observations, so this result does not attribute those
missing fields retrospectively.

The historical Rust wire trace already shows a successful caller lookup followed
by null native replies for unchanged source. Its original cause inside the server
is not established. This change does not modify Rust requests, its existing
two-second/four-attempt precision recovery, or claim a new Rust causal fix. The
normal real-language-server gate remains required.

The first paired run39953263811 failed in pytest scratch-directory setup before
any native case or candidate process ran. Its three fixture errors and null verdict
are retained; the missing parent directory was corrected before the successful
paired run. Full normal CI is a separate exact-head PR gate, not replaced by
these diagnostic totals. This follow-up is unreleased; the immutable 0.1.16 tag
and published artifacts remain unchanged.

The adjacent [machine report](2026-10-23-native-recovery-cooldown.json) and
[archive](2026-10-23-native-recovery-cooldown.tar.gz) retain every original artifact,
frozen operator and both source engines with a per-member hash manifest. Temporary
paired-control and fault-injection operators are retired after admission.
