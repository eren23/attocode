# Focused changes and class summaries

The source build adds exact file/symbol selection and defaults changed classes to
a bounded member summary. Changed methods keep their caller graphs. Explicit
`class_mode="expand"` retains class-wide traversal. This is unreleased source
behavior, not a change to the installed/PyPI 0.1.7 distribution.

## Before and after on real changes

Replayed the same [three historical fixes and selected labels](../designs/2026-10-17-change-workflow-replays.json)
with the published 0.1.7 environment and then the candidate in the same local
environment. These are consumed, familiar examples, not a held-out task study.
Both arms reconstruct actual parent trees with only the selected production and
regression files changed. No input-project code is executed.

| Replay | Baseline combined JSON | Candidate combined JSON | Change | Non-class flows with identical resolved edges |
|---|---:|---:|---:|---:|
| Workspace cache ownership | 101,679 B | 102,039 B | +0.35% | 11/11 |
| Behavioral negation | 257,931 B | 174,205 B | −32.46% | 14/14 |
| Overload source recovery | 406,914 B | 212,152 B | −47.86% | 20/20 |

The cache replay has no changed class; its extra bytes are scope/limit metadata.
The other cases replace class-wide graphs with one and three summaries. Every
resolved edge in all **45 non-class flows** is identical to the baseline. All
eight labeled caller sites, three changed targets and four labeled test files
remain delivered. All nine source/stage/branch stale→refresh→current sequences
pass in each arm, as do full-profile stdio portability checks.

Seven caller labels are production sites and one is a new regression test. Three
test files are themselves patch inputs; only the unchanged remote-fallback test
is a preexisting-test discovery example. Thus the four delivered tests do not
establish broad discovery or test sufficiency. Unresolved diagnostic counts and
some suggestion ranks varied between arms; these changes are not presented as
precision or relevance gains.

The baseline's three first-report times were 6.283, 4.668 and 5.089 seconds.
All individual candidate timings and warm samples are preserved in the decision
and observations. The arms ran sequentially without isolation of OS caches or
temperature. No general speedup, stable tail latency or agent benefit is claimed.

Baseline supervision: **80.079 s**, peak managed storage **197,632,054 B**, peak
sampled process-tree RSS **430,686,208 B**. Final candidate: **74.804 s**,
**206,155,830 B** managed peak and **459,620,352 B** RSS peak. Each arm remained
within 300 seconds, 1 GiB storage and 2 GiB RSS. Snapshots were removed. An earlier
candidate is retained privately; review then added source-range containment for
duplicate class names and clarified selected-member wording. The final candidate
was rerun on the unchanged labels, with its exact source hashes frozen.

## Selection and limits

`changes --file src/worker.py --symbol Worker.work` and local full MCP
`change_context(files=[...], symbols=[...])` select exact names before caps.
File/symbol scopes intersect, match either before/after version or rename side,
and report unmatched selectors separately from intentional exclusions and capped
results. Simple symbol names can match several owners; qualified names narrow
them. Callers/tests remain eligible outside the selected files.

Saved reports retain scope and class mode through refresh. Their full-workspace
Git snapshot remains part of freshness checking, even for excluded dirty files.
A symbol selection refuses incomplete scans over 256 changed files or 16 MiB
before/after source, rather than issuing an unsupported no-match result.

Class summaries preserve before/after identities and up to 12 changed lexical
children, total/omitted counts, and a current-source trace follow-up when valid.
Repeated class names use source containment to avoid mixing children. Removed or
index-only classes have no current caller follow-up. Selected method flows remain
separate. Top-level `bounded` also reflects nested caller/impact/test/summary caps;
`omitted.files` and `omitted.symbols` keep their existing meanings.

Summaries intentionally do not collect class-wide caller evidence. Call sites
into a constructor/class may therefore be absent from the default combined
report; use expand or a focused trace. This is a documented scope change, not
proof of unchanged class-level coverage. Inheritance, dynamic dispatch and
overloads remain partial.

## Verification

The new `test_change_focus.py` contributes **22 passing cases**. Fixed Python,
TypeScript and Go Git workflows verify exact scope before caps, preexisting test
paths and cross-file caller sites, restart recovery and full-snapshot freshness.
Class summary/expand cases cover Python and TypeScript; the Go cases exercise
function selection/callers. These language inputs are authored fixtures, not
additional real repositories or executed repairs.

Other controls cover literal names, multiple owners, duplicate class names,
both rename sides, historical/index-only classes, preview and caller caps,
selection bounds, CLI saved-request preservation and override rejection, two
actual full-profile stdio starts and authenticated HTTP. Existing 29 workflow
cases, including Rust, also remain in the local gate.

Bounded local gate `20261017T154806-568a7b0c`: **952 passes / 9 environment skips**,
Ruff, scale through 10,000 files and 20 lifecycle cycles. Supervised checks totaled
**80.227 s**, with **152,737,374 B** managed peak and **869,728,256 B** RSS peak.
The unchanged 68-query/five-method ranking gate `20261017T154809-841dc66c` passed
in **44.133 s**. The clean development wheel passed all four build/install/check
phases, including real MCP class summary/expand and filtered CLI refresh, in
**17.507 s**, managed peak **268,992,623 B**. No installed tool was replaced.

Upstream Python 3.12/3.13, PostgreSQL, combined suites and pinned language servers
remain the PR merge gates. Their exact uploaded results are recorded with the PR;
the local environment skips are not described as passes.

## Reproduction artifacts

- [Decision and source/observation hashes](2026-10-17-change-focus-decision.json)
- [Complete baseline reports and samples](2026-10-17-change-focus-baseline.json.gz)
- [Complete final candidate reports and samples](2026-10-17-change-focus-candidate.json.gz)
- [Candidate product patch](../designs/2026-10-17-change-focus-candidate.patch.gz)
  against `7b09e28946dad07448d4f8a155fa2be8c6defb4d`

The exact runner/manifest hashes are frozen in the decision. The comparison uses
the same runner as the original real-change replay. Candidate engine SHA-256 is
`b4f6cfd5598db38e7e0137ba0cd4dce21f705b43b457aad009087d707ee50ddb`.
Private supervision, prior observations and cleanup proofs stay in the ignored
local quality directory. Daily/lean advertisements, ranking/model defaults,
version numbers and release/global-client configuration are unchanged. No new
model calls, cloud workers, corpus downloads or input-project executions occurred.
