# Native parser state isolation between threads

Cached native parsers now belong to the thread using them. This fixes a
demonstrated timeout-continuation leak between concurrent workers. The correction
is unreleased; the published 0.1.14 artifact is unchanged. The
[machine evidence](2026-10-22-parser-thread-isolation.json) binds the source,
test, diagnostic operator and validation reports.

## Reproduced defect and correction

The parser cache previously held one stateful parser per language for the whole
process. After a timeout, tree-sitter retains continuation state until reset.
The existing `finally` reset does not prevent another thread from obtaining that
same parser before the reset completes. Tree-sitter documents the requirement
to reset before parsing a different document in its
[parser API](https://tree-sitter.github.io/py-tree-sitter/classes/tree_sitter.Parser.html#tree_sitter.Parser.reset).

The new regression delegates to a real installed native Python parser. It forces
only the first worker's timeout to one microsecond and pauses that worker at the
reset boundary. A second worker parses this independent two-line document:

```python
def fresh(value):
    return value + 1
```

On baseline commit `44efdf68878aadb6f8abf7ece77c1465052b36fd`, the AST incorrectly
reports a function named `fresh(value)` spanning lines 1–9. Its `tree_sitter`
parsing tier does not reveal the contamination. The expected result is `fresh`
at lines 1–2, with no parse failures attached to the second document.

The same final regression fails against an isolated copy of that committed
baseline and passes with the correction. The cache uses `threading.local()`;
each thread still reuses its parsers by language, and terminated threads do not
leave their caches rooted in a global registry. Installed/cached grammar lookup,
missing-grammar caching and TSX selection are preserved. The generic extractor
already constructs a fresh parser for each call.

The production 100 ms parse limit, native reset, context-isolated diagnostics,
selected-file recovery policy and snapshot identity checks remain unchanged.
Parser instances may increase with active parsing threads; no performance or
memory reduction is claimed.

## Local validation

Validation binds source commit `768fbc8d09302d9276f2cb5c62f450aa92469c08` and the
machine summary's source/test fingerprints. The shared controller completed in
569.746 seconds under its unchanged 600-second limit, with source and fixtures
unchanged throughout and all owned scratch removed.

| Check | Outcome |
| --- | --- |
| Complete local suite | 4,141 passed, 14 skipped, one expected failure |
| Focused parser/recovery checks | 62 passed, one skipped |
| Independent parser review checks | 103 passed, one skipped; no material finding |
| Scale and lifecycle | 100/1,000/10,000 files and 20 cycles pass |
| All 36 pinned compatibility packs | 157 passed, 124 limited, seven unsupported; no failed or incomplete checks |
| Historical ranking gate | Pass on its existing consumed questions; no fresh relevance claim |

The largest sampled worker RSS was approximately 890.1 MiB and managed storage
1,226.1 MiB, within the 2 GiB caps. Limited/unsupported checks are not verified
support. Single workflow timings are not matched performance comparisons.
Uploaded CI, real-server traces and installed-wheel checks remain separate
integration gates; these local totals do not certify a published artifact.

## Separate investigation limits

Before the correction, three predeclared fresh-process/fresh-index OCaml source
observations all passed their definition, source and restart checks. All twelve
target native parses returned trees without syntax errors in approximately
18.3–19.7 ms, under the unchanged 100 ms limit. Native exception/message and
thread CPU/wall observation were enabled, but no failure or same-parser overlap
was captured. These are fresh processes, not a cleared operating-system cache.
They do not establish the historical cold miss's cause or frequency.

An independent read-only Rust audit found no request-ID collision in the retained
traces, and method-first dispatch and document-version/order controls pass. Two
historical traces resolve a declaration, then return null for the same position
after a workspace reload without a document edit. Non-monotonic readiness is a
hypothesis; these are not reproductions of the original first-selected failure.
No new Rust language-server trial or speculative Rust patch was made in this
investigation. Current CI real-server checks remain a separate integration gate.

Neither historical intermittent cause is attributed to the demonstrated shared
parser defect. No ranking policy, agent study, default profile, dependency or
parser deadline changes follow. The earlier pilot and rejected candidates stay
closed. No model/cloud execution, grammar download, global installation change
or host MCP restart occurred.
