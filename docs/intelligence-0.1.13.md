# Attocode Intelligence 0.1.13

0.1.13 improves compact search delivery and repairs stale navigation indexes
after successful restart parsing. The standalone distribution remains
`attocode-code-intel`.

```sh
uv tool install --force attocode-code-intel==0.1.13
```

Restart the MCP connection after upgrading so it loads the new package.

## Changes

- **Compact search uses spare budget.** Pages fill a consecutive ranked prefix
  while preserving evidence already fitted into the response. Delivered counts
  and truncation describe the final page. An oversized optional follow-up no
  longer makes an otherwise usable page fail.
- **Bounded deeper search.** A full retrieval pool can offer a new search with
  more results. A verified path requests 5, 24, 48 and then 50 results, where
  automatic expansion stops. Hints must fit without displacing protected
  evidence; this is not a stable cursor. Remote retries retain the resolved
  revision. Ranking defaults are unchanged.
- **Navigation recovers after reparsing.** When an AST summary is missing or
  invalid, a successful restart parse now reconciles persisted definitions and
  references, including when source bytes are unchanged. Valid retained
  summaries keep the fast restart path.

## Verification and limits

Before this version bump, the merged implementation passed 4,073 local tests,
with 14 skipped and one expected failure. All 36 pinned compatibility packs
completed: 157 passed, 124 limited and seven unsupported checks, with no failed
checks. Limited and unsupported cases are not verified language support.
Scale checks, 20 edit/restart cycles, the existing ranking gate and installed
wheel checks also passed. See the
[compatibility report](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-20-search-repair.md#compatibility-and-restart-recovery--2026-10-21).

Repairing reparsed files adds work when AST summaries cannot be retained. A
single Cockroach restart observation increased from 5.84 to 11.76 seconds;
this is not a stable performance comparison. An intermittent OCaml cold-parse
miss remains open. Its diagnostic is consistent with a parser timeout, and an
explicit single-file refresh recovered the definition, but this release does
not fix the cold-parse trigger or change the parser limit.

The evaluated ranking candidates were rejected. There is no new first-page
relevance or agent-speed claim, model download, cloud benchmark or agent study.

The GitHub release records the release workflow, clean PyPI install, upgrade
from 0.1.12 and artifact verification results after publication.
