# Rust CI startup diagnostics

The Rust real-server gate now retains diagnostic history from before initialize
through shutdown. Its older rolling protocol artifact began after initialize and
could discard startup or workspace reload evidence needed to investigate an
intermittent failure. This change is test infrastructure; production package
source and version are unchanged. The [machine report](2026-10-22-rust-ci-diagnostics.json)
binds source commit `3e83a7bc43586f556cd127a6f0eff71f76ed27c9`, test identities and
the retained local observations.

## Capture contract

Only the Rust fixture with `QUALITY_LSP_TRACE_DIR` set enables
`lsp-diagnostic-rust.jsonl`. Class hooks are installed before the server starts,
filter by the fixture workspace and are restored after cleanup. They observe the
existing send/receive calls and decorate the existing stderr consumer. They add
no pipe reader, protocol request, capability, retry or wait. The original
assertions, 30-second warmup, 15-second edit check, production precision deadline
and legacy per-language artifacts remain intact.

Records include raw protocol messages and IDs, client document versions and text
hashes, full fixture edit messages, server identity, stderr bytes, inspection
results and all seven workflow stages. The first failure is saved before outer
cleanup changes the active stage to shutdown. CI enables informational Rust
workspace logs with `RA_LOG=rust_analyzer=info`.

The file is bounded to 4 MiB, with a flushed startup prefix and a byte-bounded
recent tail. A normal exit appends an outcome footer exposing dropped events,
oversized events and capture errors. Oversized payloads become byte-count/hash
records. Missing footer means incomplete capture; truncation is explicit. Files
are created exclusively, preserving earlier attempts. Logging adds overhead;
this is not an uninstrumented timing measurement.

## Verification

The regression first ran the existing workflow successfully against an in-memory
framed peer, then failed because the new startup artifact was absent. An earlier
fixture setup error placed streams on the wrong event loop; its timeout evidence
is retained separately and is not counted as the regression's RED result.

All nine final regressions pass. They exercise the actual gateway/client flow,
forced initialize and selected-definition failures before and after editing,
failure-stage preservation through cleanup, document generations, bounds,
oversized payloads, exclusive files, disabled capture and unrelated-workspace
passthrough. Independent controls verify that an actual abrupt process exit
leaves readable startup rows without a footer, a trace write error preserves the
underlying send and return value, and concurrent records remain ordered and
bounded. Independent code review found no material implementation issue.

One predeclared installed Rust attempt passed in 5.490 seconds, with no retry or
replacement attempt. Rust-analyzer identified itself as
`1.94.1 (e408947b 2026-03-25)`. The 385,511-byte capture contains 301 events,
including 82 protocol events, 163 stderr chunks, all seven stages and four actual
inspection results. The original selection and edited selection are verified;
both unused-symbol inspections remain honest partial results. Shutdown returns
zero; the footer reports no omission or capture error. A warmup `ContentModified`
reply is retained within the passing workflow.

The complete product suite passes **4,152 tests**, with 14 skips and one expected
failure. Lint, scale at 100/1,000/10,000 files, 20 lifecycle cycles and strict docs
also pass. The source-bound local controller completes in 168.207 seconds under
its 600-second limit. Sampled peak scratch use is 534.1 MiB and process-tree RSS
900.7 MiB; adding all retained evidence to peak scratch remains below 2 GiB.
These are sampled supervision limits, not instantaneous quotas. Both elapsed
clocks, final source identities and owned scratch cleanup were checked.

## Limits

The original intermittent Rust failure was not reproduced or explained. Reload
logs and transient replies alone do not establish a server-internal cause. The
historical OCaml cold-parse trigger also remains open. No ranking study, consumed
question or 36-pack matrix was rerun for this test-only change. This report makes
no upstream CI, publication, global installation or host MCP restart claim;
integration observations are recorded separately after the exact-head gates.
