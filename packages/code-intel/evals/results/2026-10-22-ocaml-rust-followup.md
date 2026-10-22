# OCaml recovery and Rust stderr ownership

The language-server client now gives stderr one owner. Both controlled reader
orders reproduce a real concurrent-read conflict on the baseline, and the
correction removes the duplicate reader. This fix is **unreleased**. The
[machine report](2026-10-22-ocaml-rust-followup.json) binds the exact source,
tests, operators and retained observations.

The historical OCaml cold-parse trigger and first-selected Rust failure remain
unexplained. This follow-up verifies existing OCaml recovery on the original
source and captures natural Rust transitions without changing parser limits,
protocol capabilities, readiness deadlines or recovery policy.

## Demonstrated client defect

`_LSPClient.start()` schedules `_drain_stderr()`, while `_read_loop()` also
scheduled a nested coroutine reading lines from the same `StreamReader`.
Depending on scheduling, either reader can wait first. The other raises a
concurrent-read `RuntimeError`: the nested reader suppresses it, whereas the
dedicated drain can terminate with an unhandled task exception. The readers can
also divide diagnostic output between different logging paths.

The new regression runs the real client startup, JSON-RPC framing, initialization
and shutdown against an in-memory peer with real streams. Events establish both
reader orders; only the external process is replaced. Both parameter cases fail
on baseline `15e0990` and pass with the correction. Source commit
`ac1def2972a5ea334c35b3ee00aae23da62ef54d` retains the existing dedicated drain
and its existing shutdown ownership, removing the nested reader and its task.

Independent process-free controls cover protocol trace on/off, long stderr data
without newlines, replacement decoding of invalid UTF-8, EOF, blocked-read
cancellation and absent stderr. The retained DEBUG logs still truncate decoded
chunks; this change does not provide lossless public tracing. No evidence
attributes the original Rust null replies to this separate ownership defect.

## Exact-source OCaml interruption and recovery

The source remains `ocaml/ocaml` at
`5fbe515aa215909e28328a059701da430bc3cff8`, file `typing/typecore.ml`, SHA-256
`c3abd2af1040c9d1ad305f76b7f6f9f2e8243d45af2b862b10906ee7bd629010`.
Two predeclared sequential workers completed in 10.195 seconds with unchanged
baseline source and verified scratch cleanup:

| Observation | Outcome |
| --- | --- |
| One natural fresh-process/index workflow | Initial search, selected source, repeated inspection and reopening pass. Four native calls return syntax-error-free trees in 19.4–22.0 ms. |
| One deliberately forced interruption | Three initial target native calls use an effective one-microsecond limit and raise `ValueError: Parsing failed`. The initial AST is minimal, with zero functions and a missing search result. |
| Existing selected recovery at the normal 100 ms limit | Finds `type_expression` at lines 7378–7392, restores 934 functions, and passes repeated inspection and reopening. |

The injection proxy records the effective one-microsecond native limit
independently; outer product diagnostics still record their declared
100,000-microsecond limit. This is explicit fault injection, not a naturally
observed timeout. Reopening reparses uncached ASTs; no fast snapshot reuse or
speed improvement is claimed. Fresh processes do not clear the OS file cache.

The pinned Python binding's
[native parse adapter](https://github.com/tree-sitter/py-tree-sitter/blob/v0.25.2/tree_sitter/binding/parser.c)
uses a generic failure exception when native parsing returns no tree. Its
message alone does not prove the old failure's cause. No additional OCaml
product patch is justified by these observations.

## Natural Rust transitions remain visible

Three fixed-source workers ran the unchanged real Rust test sequentially,
stopping on the first failure by design. All three passed; no retries or
replacement trials ran. The controller completed in 16.121 seconds under its
120-second limit, with source/binary identities unchanged and owned scratch
removed. The server identified itself as rust-analyzer
`1.94.1 (e408947b 2026-03-25)`.

Private passive tracing starts before initialize. It records capabilities and
server identity, full messages with matched request/reply IDs, document
versions and text hashes, existing stderr reads, selected target stages and
shutdown. It creates no additional pipe reader, request or wait. Synchronous
logging and informational server logging add overhead; these observations are
not uninstrumented cold-latency measurements.

All three original selections resolve the exact first declaration with its
caller at line 3. After `lib.rs` changes to version 2, all three resolve the
second declaration with its caller at line 4 and remove the original link.
Each server exits with code zero. Only the single stderr `read` owner is
observed, with no concurrent-read conflict.

Passing workflows still contain transient replies. In zero-based trial 2,
warmup request 5 and the first selection's definition/reference requests 6–7
succeed. The unused namesake's actual declaration then returns null at
definition request 8, `ContentModified` at 11 and the exact definition at 12,
with every document still version 1 and the same text hashes. In trial 1,
the same second-file definition succeeds at 7 and 10, returns `ContentModified`
at 12 and succeeds again at 13 without an edit. The existing bounded recovery
handles both; unused namesakes retain honest partial/no-reference results.
Empty references for a genuinely unused symbol are not failures.

Fetched-build-data/reload logs are adjacent to these transitions. Timing
association does not identify the server's internal cause, and no explicit
progress/server-status event was captured. The original first-selected failure
was not reproduced. No natural baseline counterfactual was run, so these passes
cannot be attributed to the stderr correction. Current permanent CI traces are
rolling and start after initialize; the fuller before-start tracing here is a
private diagnostic, not an expanded shipped tracing contract.

## Validation and limits

The complete local suite passes **4,143 tests**, with 14 skips and one expected
failure; its existing Starlette TestClient deprecation warning is retained.
Both new regressions and all 103 focused checks pass. Independent code/evidence
review found no blocker in the reviewed product and diagnostic scope.

The source-bound quality controller completed in 206.566 seconds under its
600-second limit, including the full suite, lint, scale at 100/1,000/10,000 files,
20 lifecycle cycles and the unchanged historical ranking gate. All phases retain
identities and verified cleanup. The 36-pack matrix was not repeated for this
LSP-only correction. Consumed ranking questions provide no fresh relevance claim.

Uploaded CI and installed-wheel checks remain separate integration gates. Both
new parameter cases must pass in combined and both primary Python product
reports before merging. The local SQL inventory includes one PostgreSQL skip;
CI still requires all 51 SQL cases to pass. Package version stays 0.1.14; no
publication, global upgrade, host restart, model/cloud experiment, grammar
acquisition or closed-study rerun occurred.
