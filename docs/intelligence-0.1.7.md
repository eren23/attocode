# Attocode Intelligence 0.1.7

0.1.7 brings the change-investigation workflow and the navigation, search-evidence,
incremental-index and service fixes merged after 0.1.6. The repository is now
intelligence-first; the archived agent is preserved at `agent-archive-2026-10-16`.
The published product remains the standalone `attocode-code-intel` distribution.

## Change investigation

```sh
uv tool install --force attocode-code-intel==0.1.7
cd /path/to/project
attocode-code-intel changes
attocode-code-intel changes --mode staged
attocode-code-intel changes --mode branch --base main
attocode-code-intel trace work --file src/worker.py --depth 2
attocode-code-intel changes --output /tmp/change-evidence.json
attocode-code-intel changes --check /tmp/change-evidence.json
attocode-code-intel changes --refresh /tmp/change-evidence.json
```

Reports combine changed definitions, current caller evidence, bounded import
impact and candidate tests. JSON and Markdown exports preserve source locations;
JSON reports can detect stale Git/source state and refresh the original request.
Renames, deletions and staged source that differs from the working tree have
explicit handling. Static caller paths keep ambiguous matches and overload
dispatch unresolved. Tests remain candidates, not complete coverage.

Local full-profile MCP adds `change_context` and `trace_flow`. Daily keeps its
16 advertised tools and lean remains opt-in. Existing client profiles are
preserved by an upgrade. Restart the MCP connection after upgrading; select a
full-profile configuration to advertise the new tools. The
[workflow guide](guides/change-investigation.md) covers evidence, limits and APIs.

## Other changes since 0.1.6

- Preserve distinct overloaded definitions and body windows through retrieval,
  fusion, hydration and keyword-cache rebuilds. Deep broad pages retain available
  distinct files before repeated windows; explicit test requests prioritize tests.
- Match query-expansion tokens at whole-word/plural boundaries. Recognized action
  clauses such as `without leaking credentials` stop penalizing relevant source,
  while explicit component exclusions retain their behavior. Noun-based and
  unknown behavioral clauses remain outside the bounded fix.
- Publish importance before keyword-ready to avoid duplicate discovery work.
  File-scoped navigation excludes same-named definitions elsewhere. Kotlin test
  source sets and conservative same-package Go call binding improve navigation.
- Retry transient precision replies within the existing deadline, expire failed
  precision caches, and share document open/edit versions across LSP callers.
- Incremental references survive edit/rename/delete and failure/retry sequences.
  Database full reindexing replaces references idempotently; branch-aware hotspot
  normalization and navigation HTTP schemas have SQL/PostgreSQL controls.
- Scoped fast-search indices stay owned by their workspace and close on shutdown.
  Legacy local searches discard indices from other roots instead of returning
  false empty results. A combined-suite PR gate and clean-wheel regression cover
  the cache leak caught by the first, unpublished 0.1.7 release attempt.

The prior broad negation rewrite and several retrieval candidates remain rejected.
Source-authored evaluation results do not establish improved agent outcomes or
general relevance/speed gains. Experimental model rerankers remain opt-in; the
release does not acquire a model or change ranking weights.

## Release validation

The release workflow runs engine/product suites on Python 3.12 and 3.13,
migrated PostgreSQL, bounded local quality, the unchanged ranking gate, four real
language servers, Linux/macOS standalone wheels, Docker, dashboard and isolation
checks. Clean-wheel verification now exercises the new full-profile MCP tools
and CLI export/check/refresh in addition to existing daily/lean navigation.

The merged feature package passed 927 local tests with nine environment skips,
29 new workflow cases, all 16 required CI checks and actual PostgreSQL controls.
Its bounded local checks took 63.073 seconds with 140 MiB peak managed storage;
the separate ranking gate took 43.045 seconds. See the
[feature evidence](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-16-change-investigation.md).
Release-specific results are recorded in the GitHub release after publication.

No new cloud run is included. The 36-pack/144-question cloud matrix and tight
Cockroach timings are historical 0.1.6/follow-up measurements, not fresh 0.1.7
validation. This release makes no agent-speed claim or new Cockroach timing claim.

Derived structural/search caches can rebuild once for schema changes. User source,
knowledge, existing configurations and the archived agent are retained.
