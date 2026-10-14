# Fresh MCP validation and representative-chunk diagnosis

The search-preview patch passed a fresh local stdio MCP smoke test against this
checkout. Local diff review found no blocking issue. The patch remains
uncommitted; CI has not run on these changes. No ranking change, model run,
Claude launch, browser check, or release occurred during this follow-up.

## Fresh process

A new `.venv/bin/attocode-code-intel` process used the lean profile with file
watching off. It exposed the expected eight tools. Precision, model rankers,
remote ranking, and embedding activation were disabled for the check.

| Query | Scope | Delivered hits | Estimated serialized tokens |
| --- | --- | ---: | ---: |
| search snippet window | `search_evidence.py` | 3 | 861 |
| result output budget | checkout | 5 | 1,336 |
| index warming | checkout | 5 | 1,125 |

Every source snippet matched the indicated lines of its actual file, remained
inside its original chunk, retained symbol identity, and stayed within the
2,000-token response budget. Delivered counts agreed with the payload. The
complete process check took 3.87 seconds using existing local caches and shut
down cleanly, with no stderr errors. This is not a cold-start benchmark or an
agent outcome. The previously connected MCP session was not replaced.

See [the smoke responses](mcp-smoke.json) and [the archived script](mcp-smoke-script.txt).

## Frozen local pools

Before analysis, five predetermined development queries were retrieved at depth
24: `search snippet window`, `result output budget`, `index warming`,
`message routing`, and `cache generation`. An isolated process observed the
existing pre-diversity candidates without changing the selector. Pools held
134–138 chunks each; analysis considered the first five selected hits per
query. Model and experimental ranking remained off.

The [pools](chunk-pools.json) preserve all captured chunks, scores, selection,
readiness diagnostics, and relevant source hashes. The [analysis](chunk-analysis.json)
was computed only after freezing them. These are five development queries on
one repository, with no relevance labels or held-out quality claims.

- **0/25 displayed hits were constructors.** The R3 constructor case does not
  establish that constructors are a pervasive current problem.
- **1/25 had a same-file source alternative with more query-term overlap.**
  For `result output budget`, that alternate covered result-type declarations,
  while the selected chunk executed the budget check. More word overlap does
  not establish a better representative; no promotion rule was enabled.
- **7/25 were metadata-only.** None of those seven had source from the same
  file in the captured pre-diversity pool. Changing the per-file selector alone
  therefore cannot supply their missing source evidence.

## Locate the missing source

A read-only SQLite transaction checked those seven hit cases (six distinct
files). Every file had indexed source and query-matching source windows; stored
file size and modification time also matched the current source. Replaying the current body
stage limits—576 SQL rows, 72 unique symbol hits, at most eight per file—excluded
all seven cases. Some were below the SQL window; others were inside it but below the
selected body stage. This narrows the mechanism to bounded source candidate
retrieval, rather than missing indexing or discarding a richer same-file chunk
at the final diversity step.

| Query | Metadata-only file | Matching source windows | First global FTS row |
| --- | --- | ---: | ---: |
| index warming | `src/attoswarm/protocol/models.py` | 5 | 322 |
| index warming | `src/attocode_core/ast_index/indexer.py` | 5 | 197 |
| message routing | `src/attocode/types/messages.py` | 3 | 1,548 |
| cache generation | `src/attocode/types/messages.py` | 4 | 539 |
| cache generation | `src/attocode/tricks/kv_cache.py` | 13 | 119 |
| cache generation | `src/attoswarm/coordinator/cache.py` | 5 | 109 |
| cache generation | `src/attocode/integrations/context/file_cache.py` | 17 | 365 |

The [snapshot observations](metadata-source-probe.json) preserve indexed and
matching counts, first matching source windows, and cap-replay results. The
entire mutable SQLite database was not archived; these are debugging
observations, not a reproducible benchmark ranking score.

## Next bounded target

Investigate supplying bounded source evidence for a metadata-only selected hit
without changing which file wins, file order, or retrieval scores. Start with
the exact selected symbol; another symbol's code must retain its own identity
and cannot masquerade as that definition. Add a development fixture before
choosing a policy, and measure response size/file preservation. This remains a
candidate improvement, not an implemented default or proven agent benefit.

The archived scripts use local paths and write separate temporary artifacts.
Choose fresh output paths when rerunning them. [Artifact hashes](artifact-hashes.json)
bind the saved responses, pools, analysis, probe, and scripts. No new production
code or test changes were required by this follow-up; the preceding 190-test
focused pass remains the validation record for the unchanged patch.
