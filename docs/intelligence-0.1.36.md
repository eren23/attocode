# Attocode Intelligence 0.1.36

Version 0.1.36 corrects the displayed identity of selected class-source search
windows. A window spanning adjacent classes could previously show the right code
under a neighboring class's name. This fix applies to local search; it requires
no remote server or optional model.

## Upgrade

```sh
uv tool install --python 3.12 'attocode-code-intel==0.1.36'
attocode-code-intel --version
```

Restart your host's MCP connection after upgrading so a new process uses the
installed package. The CLI version alone does not identify an existing session.

## Search source identity

After all ranking and selection, a class-labeled source window is checked against
current source. If the whole window belongs to one unique innermost parsed class,
that class provides its display name. A window crossing class boundaries,
module-level code or an ambiguous class span displays file identity instead.
Ownership is based on the whole source window, rather than the query's snippet
anchor. Indexed windows ending on a blank line remain eligible for validation.

The correction preserves input objects, candidate order, scores, source text and
window coordinates. Raw retrieval/cache identities and the ranking algorithm
remain unchanged, so existing indexes need no format migration. Function/method
and metadata-only behavior remain unchanged.

Validation is bounded to eight files and two MB per selected page, with a one-MB
per-file limit. Missing, escaping, oversized, unstable, invalid UTF-8,
text-mismatching or budget-excluded source retains its prior evidence. This is a
bounded presentation correction, not a universal metadata-accuracy guarantee,
first-page relevance improvement or speed claim.

## Verification

Synthetic Actions controls reproduced the original mismatch before correction;
independent review also found and qualified the trailing-blank-line edge before
its fix. Twenty-two cases cover real indexing, class containment, cross-class
windows, source binding/refusal, read bounds and unchanged selection/order/scores.
Service and gateway plain/compact output paths are covered.

Maintained release gates cover Python 3.12/3.13, PostgreSQL, engine/product suites,
native grammars, real language servers, macOS wheels, and clean installs/upgrades
from published 0.1.35. Actual public artifacts are verified against tagged source.

The optional HTTP cancellation features introduced in
[0.1.34](intelligence-0.1.34.md) and the opt-in client bridge from
[0.1.35](intelligence-0.1.35.md) retain their existing authentication, affinity,
enqueue-only budget and cooperative cancellation limits. Defaults stay unchanged;
this release adds no host UI, disconnect, restart or total-request latency guarantee.
