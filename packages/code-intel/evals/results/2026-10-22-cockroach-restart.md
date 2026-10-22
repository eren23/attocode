# Cockroach restart comparison: incomplete, optimization withheld

The frozen structural-fingerprint optimization was **not retained**. The first
scored baseline trial failed the required cold/restart evidence agreement gate;
no candidate performance phase ran. There is no speed or relevance verdict.

The baseline is `eb3b21d6925d27c1addfe106cbc23b828e2bf4cc` (0.1.15). The candidate
adds bounded fingerprints of healthy complete extracted ASTs, permitting an
unchanged reparse to reuse verified navigation without redundant repair. All
missing, failed, changed, capped or legacy records retain conservative repair.
The parser and AST-summary limits are unchanged. The archive contains exact
source bytes, full engine inventories, the frozen protocol and both attempts.

The [initial online precheck](https://github.com/eren23/attocode/actions/runs/39839300553)
stopped before fixture acquisition or scored trials: 65 tests passed and two
harness assertions failed. One injected definition changed its name without its
qualified name; one fresh child imported the checkout instead of the selected
source installation. Both were corrected without changing either product file.
The corrected run charges that first 9.084 seconds against the same total bound.

The [corrected online attempt](https://github.com/eren23/attocode/actions/runs/39839922444)
admits the baseline's expected regression failure and all 67 candidate controls.
It verifies the pinned Cockroach commit, scoped 9,758-entry fixture and exact
`NewServer` source. The first baseline trial completes ten operations in each of
two fresh Python processes sharing only the persisted workspace/index.

The selected definition/source and other eight operations match. The unscoped
`search_symbols` page differs: 30 rows in each, 23 in common, with seven rows
replaced at the equal score 0.53. The seven exact `NewServer` definitions also
reorder. The complete response journals and canonical results are retained.
Source inspection finds a score-only sort followed by the limit, allowing index
insertion and set order to select different tied rows. A separate correctness
follow-up addresses deterministic ordering; this comparison remains closed.

The corrected attempt uses 137.755 seconds, or 146.839 including the prior
precheck. Sampled aggregate peaks are 934,522,880 bytes RSS, 1,489,010,996 bytes
owned disk and 3,514,368 bytes evidence. No resource gate is violated; owned
scratch and workers are removed. Both baseline phase durations include Python
startup/shutdown and checkpoint I/O with warm OS caches. They cannot establish
the unmeasured candidate's median ratio. There was no replacement or rerun of a
scored trial, threshold change, local runtime test, model or cloud rental.

See [decision data](2026-10-22-cockroach-restart.json) and
[frozen evidence archive](2026-10-22-cockroach-restart.tar.gz), SHA256
`07171be3945857e48a115c106215e200cfe36938d39cc7caa17b193a97988a5c`.
The archive's `replay.py` checks saved bytes, XML and agreement arithmetic using
only the standard library. It does not execute product code or reproduce timings.
