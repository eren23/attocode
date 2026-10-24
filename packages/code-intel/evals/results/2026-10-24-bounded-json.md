# Bounded snapshot JSON comparison — 2026-10-24

**Decision: reject and remove the bounded serializer.** In the single unprofiled matched Cockroach
attempt, median process lifetime on restart changes from 30.332
to 30.034 seconds (candidate/baseline 0.990178);
median cold changes from 88.441 to 88.548 seconds
(ratio 1.001210). The second candidate restart round is also slower than its baseline
(30.385 versus 30.332 seconds), so both restart adoption guards fail. The cold
guard passes. These are descriptive same-runner
measurements, with warm OS caches, not a general-host performance guarantee.

## Mechanism and prospective rule

The [earlier attribution](2026-10-24-startup-cost.md) found repeated bounded AST
summary encoding during conservative repair. This candidate prepares builtin JSON
values while accounting exact escaped ASCII bytes, stops early on overflow, then
uses standard C-backed JSON encoding. The candidate changed only `ast_snapshot.py`. Source/parser/
schema/navigation checks, cache eligibility, conservative repair and the 32 MiB total /
1 MiB per-file bounds remain. No dependency or version changes.

Before any candidate timing, this distinct serialization design froze a restart
median ratio ≤0.90, every candidate restart round faster than its same-number baseline,
and cold median ratio ≤1.05. The 10% target was a prospective judgment for this narrow
encoding mechanism. The old fingerprint candidate's 25% gate and rejection remain
unchanged; this is no rerun or retuning of that candidate.

## Online controls

Baseline control 40085099232 records 23 correctness passes and one exact expected
work assertion inside a successful workflow. Candidate 40085392879 passes 301 controls;
final 40085956816 passes 315 unskipped controls, including 14 clock, threshold, individual-
round and failure-metadata guards. Exact bytes, escaped Unicode/control/surrogate
strings, typed dictionary keys, nested real ASTs, file/total boundaries, early
traversal stopping and malformed/cyclic input are covered.

The fixed 1,000-function AST encodes to the same 338,866 bytes, SHA-256
`cf44df0600c5086a4dd0418b3713e297b987b84a770faeb10c886843554b8acf`.
Total cProfile calls, including builtins, change 822,346→179,155 (ratio 0.217858).
This is a work proxy; the separate unprofiled trial below is the timing evidence.

## One frozen trial

[Actions run 40086508652](https://github.com/eren23/attocode/actions/runs/40086508652)
uses exact baseline `e0c345d6f1a7b0d52cd8f5f11b6ce3ee3153ab4e` and candidate `b2e9441e41e01677d1fbdcc44d841f5a83cff7bb`.
The pinned Cockroach source is commit 53aadff3cedde4d810c72b69ddd96e6a735d93e7,
9,758 entries / 133,715,342 logical bytes, with all 4,980 parse/reference counts ready.
A baseline-only cold/restart pair completes before any candidate phase. Then
A0/B0/B1/A1/A2/B2 each gets a fresh workspace and cold→fresh-process restart.
All 14 phases have distinct launched PIDs; all ten operation data hashes agree,
with exact source, loaded engine origins, grammar identities and physical
continuation routes independently replayed. The four retrieval queries are
consumed operational anchors, not new relevance judgments.

Primary time is parent launch through process wait and owned cleanup, without a
profiler. Raw admission and post-validation are separate clocks and remain within
the aggregate budget. Replay checks clock arithmetic/order within each phase and
chronology across all 14; 26 overlap/reordering tamper controls reject. The actual
semantic-search workspace route is checked before normalization to a logical role;
only its physical workspace and diagnostic `ranking.index` are normalized/excluded.
Visible data, result order/counts and all other follow-up fields are preserved.

| Round | Baseline cold s | Baseline restart s | Candidate cold s | Candidate restart s |
| --- | ---: | ---: | ---: | ---: |
| 1 | 88.441 | 30.181 | 88.291 | 29.829 |
| 2 | 90.609 | 30.332 | 88.548 | 30.385 |
| 3 | 87.189 | 30.685 | 88.749 | 30.034 |
| Median | 88.441 | 30.332 | 88.548 | 30.034 |

The source-bound payload completes in 910.920 seconds, under the 1,800-second /
2 GiB RSS / 2 GiB disk / 64 MiB evidence caps;
observed peaks are 1003094016 RSS bytes,
1501487412 disk bytes and 22528000 evidence
bytes. Per-process cold 180 / restart 120 second ceilings remain inside that aggregate
budget. Owned remote scratch is removed and cleanup verified. No attempt is rerun,
resumed, replaced or retuned.

## Retained result and evidence

Product, tests and maintained dispatch are restored to the baseline. The
candidate and all trial scaffolding are omitted. Reducing profile call counts
did not establish a useful restart improvement on this fixture. Further cost
isolation should use unprofiled stage clocks before choosing another optimization.
Version 0.1.17 and its immutable published artifacts remain unchanged. All product
execution/tests/builds/installs/fixtures ran online. Local Docker, global tools and
MCP were untouched. No fresh relevance, agent/model outcome or historical-native-
cause claim follows from this result.

The [machine report](2026-10-24-bounded-json.json) and
[archive](2026-10-24-bounded-json.tar.gz) retain the four original Actions ZIPs,
raw journals, profiles from the work controls, executed designs/operators/tests,
both complete 349-file engine sources, admission and per-member hashes.
Archive SHA-256 `da2cd0f1c94cbd9f429826a3fa385182b1c036b91433d2a88fb0bd25b99e0150`; 4547555 bytes / 738 members.
