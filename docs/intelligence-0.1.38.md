# Attocode Intelligence 0.1.38

Version 0.1.38 fixes stale content-search results after tracked source changes
in a live local gateway session. A previously ready trigram snapshot could miss
new content after an edit, rename or Git branch switch even after the watcher
or the next operation had refreshed the workspace.

## Upgrade

```sh
uv tool install --python 3.12 'attocode-code-intel==0.1.38'
attocode-code-intel --version
```

Restart your host's MCP connection after upgrading so a new process uses the
installed package. The CLI version alone does not identify an existing session.

## Live snapshot freshness

Tracked eligible changes invalidate the workspace's raw and semantic trigram
readers, including before AST initialization. Stale persisted snapshots are not
reloaded while that workspace is dirty. Content searches rebuild on their next
use before deciding whether the pattern can use trigrams or exceeds the
selectivity threshold. Existing `fast_search` build diagnostics and the behavior
of a workspace that has never built an index are preserved. Index enumeration
skips nonregular entries.

If an optional rebuild fails, extractable-trigram queries conservatively scan
index-eligible regular text files until a later rebuild succeeds. A pattern
that would normally exceed the index's selectivity threshold can therefore
have narrower scope during that failure. Queries without extractable trigrams
keep their ordinary full-scan behavior. Existing tracking eligibility and size
limits remain; there is no new persisted format or ranking policy.

## Verification and limits

Twenty-two maintained cases cover public content searches after edits, renames,
additions and branch switches; semantic reloads; pre-AST invalidation; hidden,
binary, ignored and never-indexed file scope; failed rebuilds; short/threshold
modes and nonregular entries. Eighteen qualified failing assertions preceded
the source repair and review corrections; the short `fast_search` control was
already correct. Three existing workspace-ownership controls remain passing.

A frozen synthetic Git fixture exercised edits, renames, deletions and switches
to another branch and back. All 132 public responses passed using both a real
Linux watcher and the per-operation stat fallback. All five watcher callbacks
completed with the expected generation and manifest before public queries;
owned workers, watcher and fixture resources were cleaned up. This is a bounded
fixture witness, not a macOS watcher, host UI, continuous-mutation, cross-process
or restart-delivery guarantee. No broad relevance or latency claim is made.

Maintained release gates cover Python 3.12/3.13, PostgreSQL, engine/product suites,
native grammars, real language servers, macOS wheels and clean installs/upgrades
from published 0.1.37. Actual public artifacts are verified against tagged source.

The file-path correction in [0.1.37](intelligence-0.1.37.md), source-display
correction in [0.1.36](intelligence-0.1.36.md) and optional HTTP features in
[0.1.34](intelligence-0.1.34.md)/[0.1.35](intelligence-0.1.35.md) retain their
existing boundaries. Hosted features remain opt-in; no total-request SLA is added.
