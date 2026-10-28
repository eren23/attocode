# Routine compatibility with native capture — 2026-10-28

One maintained full compatibility run exercises the routine OCaml capture added
in [PR #280](https://github.com/eren23/attocode/pull/280). All 349 product runtime
files, harness/tests, version 0.1.19, dependencies, workflows and native policy are
unchanged. The run uses commit `5d34e37c114ba2f05d76b91905086b310e6aab18`,
tree `27ad76209a104a56461a0d001349394a0f330343`. This report adds documentation and evidence;
it makes no package publication or product optimization.

## Result

[Run 40750355272](https://github.com/eren23/attocode/actions/runs/40750355272)
completes all 36 pinned packs and 288 workflow checks:
157 passed, 124 limited,
7 unsupported, 0 failed and
0 incomplete. Limited and unsupported outcomes do not
establish verified support. All 144 existing source-bound operational questions
are observed; they remain consumed questions and are not fresh relevance evidence.
The same-run Linux x86_64 preflight passes all 373 controls before the matrix.
There are 521 raw workflow responses, 36 worker origins and
one controller origin, with distinct worker processes independently admitted.

The full matrix completes in 820.996 seconds within the unchanged
1,200-second aggregate/180-second pack, 2 GiB RSS/disk and 64 MiB evidence bounds.
Observed peak RSS is 1,144,848,384 bytes, disk
1,305,215,130 bytes and evidence
50,528,256 bytes. These are resource-admission facts,
not a performance comparison. Same-run preflight completes in
27.951 seconds under its existing bound.

## OCaml capture

The schema2 trace contains 1,047 native parse calls,
5 of the selected pinned source, and
0 native failures. It is 1,000,162 bytes within 4 MiB.
Raw SHA-256: `706739f24fd3df8a0fa9b8f46b8a83f92b307c1c345ad2d0d57d88d010bb66fe`.
Every observed native parse returns a tree. The run does not reproduce the historical intermittent failure or establish its absence.

Admission requires the original trace plus final producer summary: exact
capture/product sources, pinned fixture and workspace, actual worker PID, parser
generations/threads, ordered clocks, 100,000-microsecond timeout and parse/reset
lifecycle. Capture errors, dropped/oversized events, protocol errors and unfinished
parsers are all zero. Full raw MCP/source/pinned Git/decoding/physical-route,
process-origin, outcome, resource and owned-cleanup checks remain mandatory.
Source-bound online policy and token admission are retained; host replay does not
run the tokenizer, parser or tested operator. The unchanged routine workflow does
not retain native binary/cache hashes, so no independent native-binary replay or
before/after grammar-byte identity is claimed.

Native observations alone establish neither the original scheduling/exception
trigger nor failure frequency. Observer spans include observation work and provide
no uninstrumented speed claim. Historical OCaml/Rust causes remain unproven.
Rust already has separate startup-through-shutdown diagnostics. Earlier rejected
relevance/restart candidates remain closed.

## Original evidence

Both original ZIPs were preserved before interpretation:

- Payload: `cc228c8885ce84646b5aefca37e4ae85eb014fddab81d5c043cdf537023e3dfe`.
- Same-run 373-control preflight: `4f4c2ed98015b16a4ca7429604044c4d7944880f4c9d72adbdec746556f2082d`.

[Machine-readable result](2026-10-28-native-compatibility.json) and [evidence archive](2026-10-28-native-compatibility.tar.gz)
retain both ZIPs, executed source/tests/configuration/workflow bytes, independent
admissions and equal 349-file published019/executed engine maps. Archive SHA-256
`29df04710e651aaf180d7c01534e47757708aa6853df5cbf2b3bad75d9b437d8` (8,403,209 bytes;
702 members). Exact source and original members were replayed.
There was one attempt, without shards, resume, replacement, retuning or budget
waiver. All runtime/tests/native/build/install/fixture materialization occurred on
GitHub Actions; local verification reads retained data and existing Git/compressed
blobs in memory. Local Docker, global tools, MCP processes and earlier proof stay
untouched.
