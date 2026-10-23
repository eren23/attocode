# Corrected file-coverage comparison — 2026-10-23

The comparison is complete and rejects this ranking candidate. It delivers one
additional distinct judged file in each round, below the required two, and
changes exact-question control results. No judged file or visible source anchor
is lost. The candidate and temporary study operators are removed; all 349
product files match the merged native-fixed baseline. Published 0.1.16 is
unchanged.

| Development gate | Observed | Required | Outcome |
| --- | --- | --- | --- |
| Distinct judged-file gains at five, each round | 1 | ≥2 | Reject |
| Individual judged-file / visible-anchor losses | 0 / 0 | 0 / 0 | Pass |
| Changed control pages | 30 | 0 | Reject |
| Warm p95, baseline → candidate | 341.607 → 348.214 ms | Candidate ≤512.410 ms | Pass |

The [online development run](https://github.com/eren23/attocode/actions/runs/39981842460)
uses baseline `a2c91df` and frozen candidate `c613670`. The candidate's
`query_ranking.py` SHA256 remains
`feb344afbddd7fb0f8e2166b8b100f6ef1946dd799f560ec088714e1dd55fcf9`,
identical to the original `1dc9189` candidate. Its recipe, questions, labels,
thresholds and request grid are unchanged after observed outputs.

Eight fresh engine workers complete 438 scored pages / 219 paired comparisons:
twelve **consumed** development questions over pandas, Prisma, Starship and
GitHub CLI; AB/BA/AB rounds; depths 5/24; budgets 2,000/8,000; and exact-file
scopes. Repeated settings and rounds cannot multiply a gain. The only distinct
gain in every round is Starship's `src/modules/utils/directory.rs` for the
second behavior question. All scoped controls remain unchanged.

The thirty changed controls are substantive returned-result changes across
three exact questions, repeated over rounds and settings:

| Exact question | Example visible change | Changed pages |
| --- | --- | ---: |
| Prisma `visitQueryResult` definition/use | First result changes from `jsdoc.ts::where` to `visitQueryResult.ts::visitQueryResult` | 12 |
| Starship `truncate_text` definition/use | Second result changes from `segment.rs::TextSegment` to `modules/meson.rs` | 12 |
| GitHub CLI `ValidAliasExpansionFunc` definition/use | At depth 24, result 15 changes from `pr/shared/params.go::ValidURL` to `issue/lock/lock.go` | 6 |

These are control changes under the frozen unchanged-control rule; they are
not described as thirty judged losses. Some snippets and continuation budgets
also change. No control is relabeled or excluded after scoring. Failure of the
gain gate alone also rejects the candidate.

The reserved 24 Gson/Redis questions are **unissued** because development rejects.
They were source-authored and precommitted before the original development
outputs, with implementer/source exposure and prior public archiving disclosed.
They are not newly authored or blind. No validation, replacement, retuning,
variant sweep or scored retry follows this result.

The [original source-alias attempt](2026-10-23-file-coverage.md) remains
**incomplete/null**, preserving all 126 pages. The corrected protocol uses the
maintained pinned-inventory alias resolver and validates the actual physical
workspace in every raw page and continuation before comparing a fixture role.
It excludes only the four previously named `ranking.index` timing fields plus
that validated continuation workspace value. Every other data field, result
order, count, score and tool argument stays in control comparisons; full raw
hashes are retained separately. No old phase is resumed or reclassified.

The corrected protocol's [preflight](https://github.com/eren23/attocode/actions/runs/39981351386)
passes all 404 unskipped controls in 29.954 seconds, including actual source
aliases, real continuations, completed parse/reference readiness, source and
origin ordering, and the full-input development-to-validation admission guard.
The original paired functional proof remains in the original study archive.

Development takes 254.146 seconds under the unchanged 600-second stage limit,
with peak aggregate RSS 956,608,512 bytes, disk 665,141,248 bytes and evidence
23,953,408 bytes, all within the 2GiB / 2GiB / 64MiB bounds. Every owned worker
and scratch directory is cleaned up. Initialization, one-second readiness polls,
raw capture, admission and shutdown remain charged inside the stage limit.

Independent retained-data replay binds the original ZIP and every extracted
byte, both 349-file Git engine inventories, each pinned fixture receipt and
source hash, decoding policies, snippet coordinates, judged anchors, eight
unique worker PIDs, exact routes, request order, final source identities after
shutdown, all 438 page summaries and the complete decision/latency arithmetic.
Full serialized MCP token counting is delegated to the frozen online checks.
No tested engine or operator is imported on the Mac.

The [machine-readable decision](2026-10-23-file-coverage-routed.json) and
[source/raw archive](2026-10-23-file-coverage-routed.tar.gz) preserve the complete
rejection, controls and frozen source. The archive is 5,182,092 bytes / 727
members with SHA256
`29c681b4afece81f9f215a51153cdde0d0bc9f1e022c9bf34f9ae17ef975392b`.
The development ZIP SHA256 is
`af4fd15fc5d04d521712390d1557ce5536c03aa018019de1befe950bc9ec1778`.
This is non-exhaustive labeled file/excerpt evidence; no general relevance,
agent-completion or performance benefit is claimed.
