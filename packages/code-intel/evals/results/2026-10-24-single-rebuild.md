# Single final index during persisted repair — 2026-10-24

Decision: **REJECT**. Median restart process lifetime changes from
28.622 to 26.718 seconds
(6.65% lower; ratio 0.933462, required ≤0.90).
Every matched restart faster: **true**.
Cold median ratio 1.011936 (guard ≤1.05).
The candidate and its test module are removed; product source remains baseline-exact.

The [unprofiled diagnostic](2026-10-24-unprofiled-stages.md) identified a full old
index load followed by construction of a replacement index during conservative
repair. This candidate reads only persisted old qualified names and reference
groups, constructs definitions once, and publishes the final index after the
existing repair checks. The reference SELECT, group/list ordering, duplicates,
metadata and LSP invalidation are preserved. Live repair uses in-memory state;
a complete cached restart retains its old full-load path. Parsing, source/parser/
schema/navigation validation, 32 MiB total / 1 MiB file summary bounds and staged
publication remain unchanged. No fingerprint skip or serialization change is used.

The adoption rule was committed before timing: median restart ≤0.90 baseline,
every same-number candidate restart faster, and median cold ≤1.05 baseline,
with complete source-bound equivalent data and all resource/cleanup checks.
The older fingerprint and bounded-JSON rejections remain unchanged.

| Matched restart round | Baseline seconds | Candidate seconds |
| --- | ---: | ---: |
| 1 | 29.124182 | 26.568481 |
| 2 | 28.073516 | 26.717969 |
| 3 | 28.622458 | 27.624763 |

| Process lifetime median | Baseline seconds | Candidate seconds | Ratio |
| --- | ---: | ---: | ---: |
| Cold | 79.521855 | 80.471043 | 1.011936 |
| Restart | 28.622458 | 26.717969 | 0.933462 |

One online attempt [40110984481](https://github.com/eren23/attocode/actions/runs/40110984481)
uses baseline `6143d0d05d296fbc1c32046952b7904f22ca0120` and candidate `a16b32ce9c3fd75a7bbfc123c143cbcb8a630e61`.
A baseline-only cold/restart consistency pair completes first, followed by
A0/B0/B1/A1/A2/B2 in six fresh workspaces: fourteen fresh processes, twelve
scored phases. Every phase reaches exact 4,980-file parse/reference readiness
before all ten existing navigation/search operations. All fourteen complete
canonical data hashes agree; physical workspace routes are checked before role
comparison. The four retrieval questions were already consumed, so this is no
fresh relevance or model study. Core grammar bytes, selected origins, source
inventories and navigation identities are independently admitted.

Primary clocks run from parent launch through process wait and owned cleanup,
without profiling. Raw admission and later validation clocks are separate from
the medians and remain within the 1,800-second aggregate budget. Per-phase
ceilings are 180 seconds cold / 120 seconds restart; aggregate RSS and disk
remain 2 GiB each, evidence 64 MiB. Every process is sequentially bound in the
parent monotonic chronology. The same GitHub runner has warm OS caches; these
results do not predict other hosts or repositories. No rerun, resume, retuning
or replacement of the scored attempt occurred.

Controls: the original full-old-index assertion fails as expected inside a
successful baseline controller. Two subsequent control attempts preserve a
mistaken new SQL-fallback phase assertion (336/350 passes respectively); the
existing fallback rebuilds complete coverage while retaining a skeleton phase.
The corrected test verifies actual re-extraction, published parse/reference
coverage, and AST equality without changing that pre-existing phase policy.
Final controls pass **351/351**: 277 maintained, 46 existing navigation/restart,
14 new regressions, and 14 trial guards. A frozen legacy restore/repair oracle
checks complete navigation state and persisted rows for partial, renamed,
added/deleted sources, LSP records, duplicates and empty qualified names.

The [machine report](2026-10-24-single-rebuild.json) and
[archive](2026-10-24-single-rebuild.tar.gz) preserve all five original Actions
ZIPs, source for every control attempt, both complete 349-file engine trees,
the executed design and independent semantic admission. Archive SHA-256:
`852d3453180c15a7ab5309a2e2b306c59bd67921dc6401ab6f013d94a5b709c4`. All archived member bytes were rechecked.
Active trial controllers, designs, choices and trial-only guards are retired.
Dependencies and version remain 0.1.17; no release or global installation occurs.
All runtime validation ran online. Local Docker and MCP state are preserved.
