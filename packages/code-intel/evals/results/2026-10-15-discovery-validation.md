# CockroachDB confirmation: search ready, pack still incomplete

The unprofiled target run reached a ready body index and passed scoped search,
but exceeded the unchanged 180-second pack deadline before the final restart
check completed. The target gate failed. The conditional full-matrix rental was
not launched, and 0.1.6 remains unpublished.

The [normalized record](2026-10-15-discovery-validation.json) binds the collected
archive, product/harness/fixture/pack hashes, source commit, complete query
observations and resource measurements. This is one targeted observation, not a
controlled speed comparison or a complete release gate.

## What completed

Worker `f27f6586875c4418` used source `ba16a4056f70bce0174a163b5988f0e041c5603f`
(the [discovery/body repair](2026-10-15-discovery-body-repair.md) plus the approved
admission change), on the same Amsterdam shared 8-vCPU/16-GiB size. CockroachDB
revision `53aadff3cedde4d810c72b69ddd96e6a735d93e7` and all source inputs were pinned.
The command was `cloud run --pack cockroach --suite workflows`; index profiling,
model ranking and broad reranking were off.

| Observation | Result |
| --- | ---: |
| Definition check | passed, 37.284 s |
| Source inspection | passed, 36.656 s |
| Scoped search | passed, 87.298 s |
| Keyword stage | 29.936 s; 9,736 files |
| Body stage | 75.702 s; 9,718 files, coverage 0.998 |
| Index-reported total warmup | 123.790 s; ready |
| Retrieval questions observed | 4/4 |
| Final restart check | unfinished at pack deadline |
| Controller elapsed | 340.407 s (5.67 min) |

Search-call wait and index-reported warmup have different start points; they are
not interchangeable or additive. The index reused 4,980 structural ASTs. The
previous full run recorded 57.280 seconds for keywords and an unfinished body
index at 132.860 seconds of warmup, but differences in source, run selection and
shared-worker scheduling prevent treating this pair as a measured speedup.
The direct result here is that the body index became ready and served searches.

Completed checks total 168.408 seconds, and the four retrieval calls total
3.137 seconds. Four relationship checks report explicit limitations, not positive
relationship evidence. The last checkpoint includes all four queries but no
`restart` check; the log records a second AST-service initialization at 13:33:59Z.
This supports investigating restart/freshness work and the accumulated startup
cost. It does not establish which restart subphase dominates or that a restart
alone requires 180 seconds.

The descriptive retrieval labels hit **0/4 at five and 1/4 at 24**. The server
construction target is rank 13; the other three labeled files are outside the
returned 24. These are non-exhaustive development labels, not exhaustive relevance
judgments. Earlier incomplete runs lacked these observations; they cannot serve
as a zero-hit comparison. No ranking or agent-quality improvement is claimed.

## Bounds, cleanup and cost

- Workflow phase: 202.819 seconds including source preparation and supervision;
  the individual evaluation process retains its 180-second limit.
- Peak managed check disk: **1,490,403,482 bytes**; sampled process-tree RSS:
  **690,970,624 bytes**, below 5 GiB/4 GiB caps.
- Export: **41,004 uncompressed report/log bytes**. Corpora and indexes remained
  on the worker; owned scratch cleanup was verified.
- Worker deletion is verified, with an independent provider check finding zero
  active quality workers. All 18 ledger entries have verified cleanup, and the
  prior 17 entries are unchanged. Bootstrap completed without recorded errors.
- This rental cost **$0.0158 estimated compute**; all 18 total **$0.8221 estimated
  compute**, before tax and not an invoice. Eighteen $1 monthly reservations remain
  retained under the approved $19 admission cap. A spare reservation is not
  authorization to bypass the target-pass prerequisite.

The approved sequence stops after this failed target. Its second rental remains
unused; no full matrix, ranking gate or release was run. The earlier full gate
still failed 35/36 packs. CI and local parity checks for the repair remain valid
within their scope; they do not convert this incomplete target to a pass.

## Next technical work

Use retained evidence and local fixtures to examine the fresh gateway restart:
which discovery, metadata validation, structural loading and source reads repeat,
and whether cached state can be reused without losing edit/ignore freshness.
Require exact navigation results plus changed-file, deletion, policy, cancellation
and restart controls before another cloud confirmation. Preserve both the
180-second pack deadline and the 90-second search-polling rule. Do not simply
extend limits to declare success. No extra rental or model experiment is included
in this follow-up recommendation.
