# Restore summaries before discovery builds imports

The first approved Cockroach retry, batch `e7003de3c3e440ea` on `e97f986`, still
failed the unchanged 180-second pack deadline. Definition/source/scoped search
passed in 35.353/35.517/86.707 seconds; four relationship checks were limited by
missing labels. All four retrieval questions were observed (0 hits at five,
1 at 24). The restart was unfinished. Controller elapsed was 323.892 seconds;
collection, hash checks and deletion passed. Estimated compute was $0.015,
bringing all 19 workers to $0.8371 before tax, not an invoice.

The failure prompted an audit of the previous no-reparse claim. Discovery builds
an import graph for inventories with fewer than 5,000 recognized source files.
It called `codebase_ast.parse_file` **before** structural restoration loaded the
summaries. The earlier tests and component counters intercepted only the later
`ast_service.parse_file` entry point. Their zero count did not mean that the
whole restart avoided parsing. The historical timings remain observations of
their stated fixture; the full-path no-reparse claim is withdrawn.

The repair source-validates the existing bounded summaries before discovery and
passes them into the existing graph builder. Restoration then reuses the same
summaries, rechecks the completion-record binding and the before/after filesystem
identity, and parses cache misses normally. Inventory order, importance scores,
graph construction, cache byte caps and deadlines are unchanged. An edit during
discovery cannot bless a completed snapshot. No corpus was downloaded to the Mac.

## Generated component evidence

`restart_discovery_probe.py` freezes initialization/save/restore from `e97f986`
and counts **both** parsing entry points. Each workload has two alternating
observations per arm, fresh directories and identical evidence hashes. Medians:

| Workload | Arm | Cold | Restart | Combined | Restart parses |
| --- | --- | ---: | ---: | ---: | ---: |
| 160 Go files, short bodies | Baseline | 0.494 s | 0.205 s | 0.699 s | 160 |
| Short bodies | Candidate | 0.442 s | 0.078 s | 0.520 s | 0 |
| 160 Go files, longer bodies | Baseline | 1.321 s | 0.474 s | 1.795 s | 160 |
| Longer bodies | Candidate | 1.525 s | 0.163 s | 1.688 s | 0 |

Cold time includes the summary write. The longer-body cold observation regressed;
these tiny samples with uncontrolled OS caches are not a fixed speedup claim.
All 34,394,112 bytes of generated work were removed. The complete Cockroach
workflow still needs its approved final target retry; a full gate remains
conditional on that target passing with coherent inputs.

## Verification

Final bounded local run `20261015T170423-55a2ea39` passed **605 tests, 8 skips**,
lint, scale and lifecycle checks (54.038 seconds summed check time). Peak managed
check disk was 127,972,944 bytes and sampled process-tree RSS 729,579,520 bytes;
owned scratch cleanup and input hashes passed. Python/Go/TypeScript and fresh
child-process restart checks intercept both parse paths. Additional controls
preserve inventory/order/importance/graph and reject edits or completion-record
changes during discovery. Disabling the handoff fails the strengthened controls.
The [raw record](2026-10-15-restart-discovery-repair.json) binds these observations
to the candidate source hashes. No model, ranking or timeout default changed.
