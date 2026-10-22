# Native cross-file workflow evidence

Independent labels from six pinned cached projects exposed a guarded Elixir
extraction defect that the synthetic fixtures missed. The original static
navigation run produced **13 passed, 2 limited, 3 failed**. After a minimal
Elixir definition-head correction, the same labels and source files produced
**16 passed, 2 limited, 0 failed**. Original failures remain in the archive.

| Language / pinned project | Original | Corrected | Verified positive scope |
|---|---:|---:|---|
| Python / FastAPI | 3 passed | 3 passed | Encoder and Swagger UI definitions, imports, calls and linked tests |
| TypeScript / Prisma | 3 passed | 3 passed | Casing helpers, relative imports, calls and linked tests |
| Go / CLI | 3 passed | 3 passed | Error helpers through package imports, caller and test paths |
| Rust / ripgrep | 2 passed, 1 limited | Unchanged | Escape helpers through direct cross-file imports and calls |
| Ruby / Rails | 2 passed, 1 limited | Unchanged | Inquirer class definitions/source and literal `require` edges only |
| Elixir / Phoenix | 3 failed | 3 passed | Guarded Token definitions, alias imports, calls and linked tests |

The corrected 16 comprise **12 positive relationships and four unrelated-call
controls**. Ten positives include explicit imported calls; the two Ruby
positives establish definitions/source and literal imports. Ruby constructor
anchors in tests are source facts, without receiver-type or linked-caller claims.
Rust calls inside macro token trees and Ruby predicate dispatch through
`method_missing` remain the two explicitly limited controls. No wrong link was
reclassified as a pass. The initial Elixir negative control also failed because
its selected definition was unavailable; an empty call list alone could not pass it.

Labels were written before product navigation and frozen with exact paths,
lines, quotes, source SHA256, repositories and revisions. The input contains
31 unchanged native source/configuration files, 138,119 bytes. These are small,
non-exhaustive slices; Rails is rooted at its native `activesupport` package.
All navigation ran through the local gateway with precision disabled. Project
code was never executed; no model, download or cloud worker was used.

The Phoenix `sign` and `verify` heads contain `when` guards. Tree-sitter parsed
them successfully, but the definition extractor accepted only a call or identifier
head and silently skipped the guarded binary-operator form. The correction
unwraps only the left declaration head of `when`, preserving original definition
spans, visibility and name representation. Two regressions failed before the
edit and passed afterward, including true guard/body-call controls. The focused
parser/navigation/workflow suite passed 128 tests; Ruff and whitespace checks
passed. These are separate from the native-case counts; the owned synthetic
suite now contains 22 tests.

The original/corrected supervised runs took 2.776/10.527 seconds, with peak
sampled RSS 140,771,328/136,921,088 bytes and managed storage
3,629,056/3,780,608 bytes. Both stayed within 180 seconds and 2 GiB RSS/storage,
verified worker cleanup and removed owned scratch. Source fingerprints were
stable during each observation. These timings are resource checks, not a
performance comparison.

## Replay and identities

The [decision](2026-10-22-local-workflows-decision.json) binds the
[88,388-byte archive](2026-10-22-local-workflows.tar.gz), both product-source
fingerprints, full pinned revisions, and original/normalized evidence hashes.
Extract outside the checkout and run `python replay.py`; it uses only Python's
standard library. Native fixture bytes and source coordinates are hash-checked,
and decisive definition/source/call/dependency/test/negative judgments are
recomputed from stored responses. Captured service AST import-line flags are
retained observations; the archive does not reconstruct those original AST
objects. Native import coordinates and gateway dependency edges are independently
checked. This replay establishes arithmetic/source agreement, not a fresh
product execution or agent-completion benefit.

Original frozen labels SHA256:
`0f3c4d649b44025fb6532d975ccc9bd981d562d5e85a44b1029e4d59d2d795c9`.
Original source-manifest SHA256:
`6874080f3a17961adc2bce32649c139a471b0b8c103ba59b6fda5d62f194dd50`.
Only the label's temporary fixture-root field is normalized in the public copy;
semantic labels and native source bytes are unchanged. Private workspace/operator
metadata is omitted. Archive replay passed after extraction; a control that
removed a required Phoenix call, even with a recomputed payload checksum, was
rejected by the judgment replay.

Static ripgrep evidence is separate from Rust LSP readiness. This batch launched
no real Rust LSP trial. Read-only review of existing October 20 traces found
request IDs/replies, document versions and edit generations, plus timestamped
workspace-loading stderr; no explicit server-status readiness notification was
captured. Those six historical passing checks bind an older source/toolchain,
and establish neither a current readiness fix nor the intermittent server's
internal root cause.
