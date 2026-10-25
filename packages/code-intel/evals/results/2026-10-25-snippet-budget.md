# Compact search snippet budget restoration

This correction restores source text lost to coarse output halving while preserving
the entire already fitted compact-search page. It is unreleased on 0.1.18 development.
Ranking, retrieval, source selection, parsing, dependencies and output budgets stay
unchanged. The prior context-search candidate remains rejected.

## Reproduced boundary and change

The legacy fitter halves a selected long snippet after the serialized MCP envelope
exceeds its budget. A small overflow can therefore discard much more evidence than
needed. Workspace/provenance and continuation strings share that budget. The earlier
trial's path-length/snippet difference motivated this check; these controls do not
prove the historical difference's cause.

Changing the early fitter could consume space used by later prefix recovery or
continuation delivery. Instead, keep the final fitted page as the floor. Only after
those existing decisions, try restoring source text from the corresponding already
rendered original window. Preserve all delivered hits, order, scores, identifiers,
match evidence, routes, continuation and currently visible snippet text. Accepted
windows cover the existing source lines and retain accurate coordinates/truncation.
Caller data is not mutated, and a page with no validated improvement is unchanged.

There are at most 12 additional candidate-window attempts globally per response,
not per hit. Every accepted candidate passes the existing full serialized MCP token
count. Try the complete original window, then bounded midpoint caps. Tokenization
and anchored windows are not monotone: this is bounded restoration of a verified fit,
not a maximal or globally optimal packing claim. Long workspace routes still consume
budget, so equal excerpts across different physical paths are not promised.

## Online causal evidence

| Attempt | Original result |
| --- | --- |
| [40218132299](https://github.com/eren23/attocode/actions/runs/40218132299) | Expected RED: 368 cases, 364 passes and four exact excessive-source-loss assertions; 33.112 s |
| [40218361154](https://github.com/eren23/attocode/actions/runs/40218361154) | Retained incomplete: the four new boundary cases pass; four old exact-snippet assertions fail on larger excerpts that contain all prior text |
| [40218793000](https://github.com/eren23/attocode/actions/runs/40218793000) | GREEN: all 380 unskipped controls pass; 32.577 s |

The four fixed boundary fixtures combine Unicode/escaped text with short/long
workspace paths. At a budget one token below the original serialized response,
baseline delivery loses at least half the original window; corrected delivery keeps
more than three quarters, including the previous visible text and its source lines.
This is synthetic source-delivery regression evidence, not a relevance study.

All 16 existing no-crowding variants remain. Their assertions now preserve full
non-preview hit identity, earlier text containment and nonshrinking source spans;
requiring an identical snippet would forbid the intended evidence extension.
No failing case was removed to hide a loss. Additional checks cover the full fitted
prefix/continuation at four budgets, a global serialization-probe limit, conservative
nonmonotone token counts, accurate truncation/other omissions, repeated source rows,
actual gateway/source/budget behavior, existing fit byte identity and no mutation.
The temporary dispatcher boundary guard passed and is retired with its operator;
19 meaningful new cases remain in maintained preflight, bringing it to 305 cases.

## Retained evidence and scope

The [JSON report](2026-10-25-snippet-budget.json) records source identities and limits.
The [archive](2026-10-25-snippet-budget.tar.gz) contains all three original ZIPs,
original admissions, both complete 349-file engine maps and immutable public
operator/test/config source from four commits. Every archived member was compared
with its original retained bytes or Git source before retiring temporary wiring.

Archive SHA256: `232435490969266f5be82168f27b9f0334249018a5e491c2f98c7054c05e21c1`
(2,400,764 bytes; 695 members). Qualified runtime source:
`5e8e0197884193d5be8edfdd0c561623e8a467ea`.

All actual execution ran online on GHA. Local work used static/private stdlib
retained-data/Git/XML/tar analysis, with no tested imports, local fixtures, Docker,
global tool upgrade or MCP restart. There is no new corpus query, held-out judgment,
agent benefit, native cause or performance claim. Publication requires separate
versioned compatibility and actual installed-artifact verification.
