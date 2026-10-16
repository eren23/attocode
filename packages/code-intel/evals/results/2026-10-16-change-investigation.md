# Diff-aware change investigation

The source build adds one workflow across Git, caller navigation, test candidates,
MCP/HTTP and the CLI. This is product correctness/workflow evidence, not a model
study, search-quality experiment or general speed claim. No model, corpus download,
cloud worker, release or global tool upgrade was used for this package.

## Delivered behavior

- `changes` / full local MCP `change_context`: working, staged, unstaged and
  merge-base branch comparisons, changed definitions with before/after source
  ranges/hashes, renames/deletions, current caller evidence, import impact and tests.
- `trace` / `trace_flow`: selected-definition caller paths with call sites and
  binding evidence, ambiguity handling, cycles, depth/node/edge limits and
  unresolved candidates. Same-directory Go package calls now have conservative
  package binding; other packages/directories and arbitrary receivers do not.
- Private JSON/Markdown exports, snapshot/source freshness checks and refresh of
  the original request. No overwrites. Stale source, index, revision/branch or
  untracked changes invalidate the saved report; modified JSON fails integrity.

Daily/lean advertisements and ranking defaults are unchanged. Remote catalogs
omit these local working-tree operations. Published 0.1.6 remains unchanged.
See the [usage and limits guide](../../../../docs/guides/change-investigation.md).

## Validation

`test_change_investigation.py` has 29 cases. Four real Git source workflows cover
Python, TypeScript, Go and Rust: changed symbols, two-hop caller/test evidence,
saved report checks, branch comparisons/switches and new gateways after shutdown.
A second sequence covers staged-only edits, renames and deletion in all four.

Other controls cover index-only versus working-tree source, import/non-symbol
changes, overloads, arbitrary receivers, different Go package directories and
test packages, cyclic graphs, ambiguity, bounded omissions, same-size edits,
untracked/index changes, branch-name-only switches, integrity failures, filesystem
escapes/symlinks, source/output/time/path-count limits, unborn repositories,
configured Git filters, and a concurrent edit during collection.

Actual full-profile stdio is started twice; both processes return the same
complete report with the expected caller site. Authenticated HTTP returns usable
reports and rejects unauthenticated/invalid requests. CLI subprocesses verify
JSON creation/check/refresh, stale exit status, Markdown and overwrite rejection.

The final bounded local gate (`20261016T201843-ff330c36`) passed **927 tests**, with
nine explicit environment skips, plus Ruff, 100/1,000/10,000-file scale and 20
lifecycle cycles. Supervised checks totaled **63.073 seconds**, peak sampled
process-tree RSS **923,959,296 bytes**, managed disk **146,724,482 bytes**; scratch
cleanup passed. The unchanged 68-query/five-method ranking gate separately passed
in **43.045 seconds** (`20261016T202000-64e6fad1`). An earlier local pass is retained;
the final gate includes the last coverage/omission corrections.

A cached local CLI trace of this repository's `scope_exclusion_terms`, depth two
and maximum 12 nodes, finished in **1.358 seconds** and exported **53,346 bytes**.
It returned 12 nodes/28 edges, explicitly omitted six more nodes, and kept 32
unresolved rows with 49 further rows omitted. Its saved report checked current.
This is one warm operational example, not a cold benchmark or exhaustive graph
validation. Later source/commit changes correctly make that saved report stale.

Hash-bound local reports, JUnit/logs and the repository trace remain private under
`.attocode/quality/runs/20261016-change-investigation`. Upstream CI, including real
PostgreSQL, is the merge gate and is recorded in the implementation PR.

## Limits

Caller paths remain structural and partial, not execution order or complete
control/data flow. Historical/index-only definitions receive no current callers.
Overload dispatch is not guessed. Test suggestions remain candidates; Rust inline
test annotations are a lexical heuristic. Same-name declarations are paired in
source order. Ignored files outside recorded anchors are outside freshness checks.

Git executable filters are disabled and recorded; raw-source comparisons can
differ from filtered Git/LFS views. Collection has file/path/byte/output bounds and
a between-operation deadline guard, not parser preemption. Symlinks, unusual modes,
unmerged paths and unborn repositories do not become successful source assertions.
