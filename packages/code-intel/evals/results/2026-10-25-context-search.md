# Optional local file-context search — development rejection

The completed development comparison rejects this candidate. No context-search
feature is enabled or published. All 349 product files, product tests, maintained
experiment harness, workflows, dependencies and version are restored to the
published 0.1.18 baseline. The 24 validation questions remain unissued.

## Frozen capability and judgments

The candidate added optional `context_file` to local MCP/HTTP semantic search.
It used the context file plus direct resolved imports/importers, at most 32 files,
and one masked lexical pool alongside global retrieval. Context relationships
were explicit; remote and vector context were unsupported. Ordinary requests
were intended to preserve their existing behavior and payload.

The implementer authored 48 source-only questions on the existing pinned
FastAPI, Requests, Express and Prisma packs: 24 development and 24 conditional
validation. Every pack/stage had two implementation, two test and two ordinary
control questions. Context files were distinct from judged targets. These are
non-exhaustive labels on previously exposed source, **not blind judgments**.
A tracked-query audit found no exact or ≥0.8 term-set collisions; it does not
prove semantic freshness or independence. Development questions are now consumed.

Three fresh roles per pack compared baseline, candidate without context and
candidate with context. Three rounds alternated primary order with the ordinary
candidate between them. Requests used depths 5/24, budgets 2,000/8,000 and exact
scopes. Every round required at least two distinct new top-five files with visible
judged excerpts across at least two repositories, zero individual file/excerpt
losses at either depth or scope, unchanged ordinary controls, and warm p95 at
most max(250 ms, twice baseline). No gate was relaxed after results.

## Original attempts and correctness controls

The first development dispatch,
[40209109644](https://github.com/eren23/attocode/actions/runs/40209109644), remains
**incomplete with null quality decision**. It aborted after 0.591 seconds while
importing `context_search_experiment`; the committed operator was named
`context_experiment`. Original archive/Git replay confirms no fixture, worker or
query started. A real dispatcher regression reproduced this exact import failure;
a name-mapping repair passed that regression and all 337 online controls.
The user explicitly approved one corrected launch; the original was not erased
or relabeled successful. Candidate, questions, labels, operator and gates stayed
unchanged; only dispatcher and synthetic control wiring were repaired.

Earlier retained causal controls cover missing feature support, compact context
budgets, unsupported HTTP vector requests, keyword-mode continuations and empty
SQLite masks. Initial test setup/assertion failures are preserved alongside their
diagnosed corrections. Read-only review findings were covered before the corrected
study. The final qualification
[40209436905](https://github.com/eren23/attocode/actions/runs/40209436905)
passed 337/337 checks in 29.992 seconds. All actual tested execution was on GHA.

## Completed corrected development

[Run 40209678957](https://github.com/eren23/attocode/actions/runs/40209678957)
on `24529ec200ed3eb1b99af2d0f254d1bfe720e877` completed in 234.215 seconds.
Independent retained-data replay admitted all 1,080 original scored pages,
360 paired triples, 12 distinct worker PIDs, 7,434 pinned source entries and their
Git trees, request/role/order binding, module origins, source policies/coordinates,
visible quotes, graph observations, resource limits and cleanup.

| Frozen guard | Observed result |
| --- | --- |
| ≥2 distinct new visible-file gains in ≥2 repos, every round | **Fail:** one file in one repository in each round, Prisma `packages/client/src/runtime/utils/deep-set.ts` |
| Zero individual file/excerpt losses | **Fail:** six visible-excerpt loss observations on two questions across three rounds; no judged file loss |
| Ordinary candidate/control payload unchanged | **Fail:** three ordinary candidate pages differ on one Requests question |
| Warm p95 ≤max(250 ms, 2×baseline) | Pass: baseline 234.023 ms, contextual candidate 221.540 ms |
| 600 seconds / 2 GiB RSS+disk / 64 MiB evidence | Pass: 234.215 s / 825,511,936 B RSS / 365,490,424 B disk / 41,226,240 B evidence |

The excerpt losses affect Requests `development-requests-test-1` and Express
`development-express-test-2` at depth 24, budget 2,000 in every round. The ordinary
Requests differences affect that same setting/question. Original raw comparison
shows only the final snippet shortening from `tly throw an InvalidHeader error if multiple`
(with newline) to `w an InvalidHeader err`. Role workspaces have different-length
physical paths and normalization occurs after budget rendering. This does **not**
independently attribute the difference to a ranking regression. The frozen control
gate still fails; the insufficient distinct-file gains independently reject adoption.
No post-hoc route adjustment, rescoring, retuning or scored replacement follows.

Latency is only the frozen gate result, not evidence of general speed or agent
benefit. No validation retrieval was issued after rejection.

## Evidence and limits

The [machine-readable report](2026-10-25-context-search.json) records the complete
decision and resource data. The [retained archive](2026-10-25-context-search.tar.gz)
contains 17 unique original ZIPs, 18 retained attempt records, original admissions,
frozen questions, both complete baseline/candidate engine maps and immutable
public operator/test/config source from 16 commits. Content-addressed source blobs
avoid duplicating unchanged files. Every archived member was replayed against its
original retained bytes or Git source before retirement.

Archive SHA256: `dc8031709bbb5d274a2592eed004208ef395776b6360b84a8a770c56a8ba1679`
(9,928,493 bytes; 819 members). Corrected-run original ZIP SHA256:
`515f1d15fe95387894671ee9edf231fbc682ee053a94a496d07c3a2cc7caabaa`.
Original aborted-run ZIP SHA256:
`fdba72ecf320946c73afd508b26a0186050d693ac48b869f9b109c2ceb910812`.

Host replay used private stdlib/Git/blob data analysis only, with 54 adversarial
data controls. It imported no tested product/operator and materialized no local
fixtures. Token counting remains a source-bound online admission. Graph edges and
eligibility are observations of unchanged source-bound AST behavior, not independent
compiler resolution or complete absence proof. Source/label exposure, non-exhaustive
judgments and task information supplied by context limit generalization.

The candidate, new regressions, operators, stage designs and dispatch choices are
retired. Published 0.1.18 is unchanged; no 0.1.19 publication, global tool upgrade,
MCP restart or local Docker action follows this rejection. Future work requires
a distinct prospective mechanism/design; these development questions are consumed.
