# Routine OCaml native capture — 2026-10-25

The opt-in corpus evidence worker now retains actual OCaml parser outcomes before
bounded fallback/reset. The previous routine artifact retained workflow responses
and source identity, but could lose the original native exception or no-tree
result. This is a harness change: all 349 product runtime files, version 0.1.19,
dependencies, native limits and Rust startup tracing remain unchanged.

## Retained behavior

`NativeCapture` wraps the existing native observer in the OCaml evidence worker
before gateway initialization and keeps it active through shutdown. It covers the
primary cached parser and directly constructed generic fallback parsers. A scoped
context flag selects only OCaml generic calls. Capture-local generations distinguish
transient parsers without retaining them; actual parser/thread IDs and explicit
use registrations cover sequential thread handoffs. No additional native parse,
reset, retry or timeout adjustment is introduced.

The exclusive JSONL artifact has a 4 MiB total bound, 64 KiB event bound, flushed
prefix, bounded recent tail, failure checkpoint before fallback/reset, and a final
footer. It records exact capture/product sources, pinned fixture and workspace,
PID/thread/parser generation, input hash/bytes, native result/error, timeout/reset
and wall/thread CPU spans. Recording faults preserve the underlying parser outcome.
Dropped/oversized events, I/O faults, incomplete parser lifecycles or a missing
footer reject capture admission. Parent admission requires both raw trace replay
and the final producer receipt, including close failures after footer emission.
Disabled and non-OCaml workers keep their existing paths. Hooks restore on exit.

## Qualification

| Online run | Commit | Stage | Cases/scope |
| --- | --- | --- | --- |
| [40231397146](https://github.com/eren23/attocode/actions/runs/40231397146) | `50d4773` | red-1 | 370 |
| [40232339776](https://github.com/eren23/attocode/actions/runs/40232339776) | `21dad67` | green-1 | 370 |
| [40234300356](https://github.com/eren23/attocode/actions/runs/40234300356) | `e217977` | route-red-1 | 373 |
| [40234802568](https://github.com/eren23/attocode/actions/runs/40234802568) | `471cb53` | route-green-1 | 373 |
| [40234957048](https://github.com/eren23/attocode/actions/runs/40234957048) | `9942edb` | smoke-1 | one pinned worker |

Initial RED has 36 exact expected assertions and 334 positive controls; its paired
GREEN passes 370. Pre-smoke source review identified generic fallback and thread
handoff gaps: three new controls fail on the earlier implementation, then all
373 pass after repair. The final 42 maintained cases exercise actual worker and
parent admission paths with controlled native outcomes, before-reset durability,
write/flush/close loss, cap/oversize/abrupt exit, hook restoration, concurrency,
exclusive creation, disabled paths, and source/fixture/lifecycle tampering.
Maintained preflight now requires 373 controls and normal CI requires 386 relevant
regressions. Expected RED assertions are retained control data; no failed trial is
relabelled as a product success.

The separately frozen single smoke on `9942edb7e481177fa1d413508a31435e351f7c09` uses
`ocaml/ocaml@5fbe515aa215909e28328a059701da430bc3cff8`, 274 pinned source entries,
and `typing/typecore.ml` SHA-256
`c3abd2af1040c9d1ad305f76b7f6f9f2e8243d45af2b862b10906ee7bd629010`.
One routine worker completes eight raw workflow responses/checks: four passed and
four limited. Retrieval questions are omitted. The native trace contains 1,028
parses, four of the selected source, all returning trees; it is 977,405 bytes with
zero capture errors, dropped/oversized events, protocol errors or unfinished
parsers. Raw SHA-256:
`e508c9346a5e18ccfc5f84788b8779ce2cb57c4dcb9c859edb773070b5bf7970`.

The smoke completes in 18.643 seconds within the separately frozen 600-second
aggregate/180-second worker, 2 GiB RSS/disk and 64 MiB evidence bounds. Exact Git
source, actual optional-grammar before/after identity, process origins, pinned
source, raw MCP predicates/routes, trace lifecycle/counters and cleanup are admitted.
All runtime, tests, native parsing and fixture materialization run on GitHub Actions;
local verification reads retained data and existing Git blobs only.

## Limits and evidence

No native failure occurs in the actual smoke. Deterministic fault controls verify
capture of native errors/no-tree results, not the missing historical intermittent
trigger or its frequency. Clock spans include observation costs and establish no
performance benefit. Grammar hashes are source-bound online observations; host
replay does not execute native binaries. This one-pack smoke establishes neither
new full-matrix compatibility nor relevance improvement. Earlier rejected relevance
and restart candidates remain closed.

[Machine-readable result](2026-10-25-ocaml-native-capture.json) and [complete evidence archive](2026-10-25-ocaml-native-capture.tar.gz)
retain all five original ZIPs, executed sources/tests/designs/workflows, independent
admissions and both equal 349-file engine maps. Archive SHA-256
`e488d4911e3919a0815e5a453602cfadb68c3368595daab9fe358c6c192054d4` (2,935,510 bytes; 719 members).
Initial unlaunched smoke design is explicitly retained separately. Temporary
operators, experiment design and workflow choice/setup are retired; the maintained
workflow returns to its exact baseline bytes. No new publication, global tool
upgrade, MCP restart or local Docker action is part of this change.
