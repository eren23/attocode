# Attocode Intelligence 0.1.39

Version 0.1.39 fixes stale raw search results on the first query after a quiescent
restart. In 0.1.38, an offline tracked edit or branch switch could leave a saved
trigram index excluding current content even though a clean cache found it.

## Upgrade

```sh
uv tool install --python 3.12 'attocode-code-intel==0.1.39'
attocode-code-intel --version
```

Restart your host's MCP connection after upgrading so a new process uses the
installed package. The CLI version alone does not identify an existing session.

## First raw search after reopening

Saved raw trigram indexes must agree with the current eligible source paths and
file identities before reuse. Their lookup and postings artifacts and ordered
file map must also match the saved proof. Changed, old or unverifiable snapshots
rebuild before raw search uses them. Verified unchanged snapshots remain reusable.

Direct regex and scoped raw readers preserve their existing indexed scope while
rejecting stale state. A replacement must read its complete eligible input set
before it can be published with a reusable proof. Ordinary cold builds retain
best-effort behavior. Persistent replacement errors retain the existing selective
fallback scope, so threshold-sensitive searches can have narrower scope until a
later rebuild succeeds.

## Verification and limits

Twelve maintained cases cover offline edits and branch switches, preserved-mtime
edits, eligible additions/deletions and path replacement, unchanged-cache reuse,
old cache recovery, mismatching artifacts and saved maps, replacement read
failures, direct-regex scope and ordinary cold builds. Controlled failing cases
preceded the implementation and review corrections. The cases passed in the
combined suite and both Python product suites on the reviewed and merged source.

A bounded Ubuntu no-watch stdio witness recorded 48 public tool responses across
18 distinct cleanly exited processes. Changed first raw searches returned current
literal/path evidence, while the unchanged control reused its verified cache.
This qualifies the recorded orderly reopen cases with supported file identities.
Continuous mutation, competing publishers, host UI behavior and broad latency
remain outside this evidence.

Maintained release gates cover Python 3.12/3.13, PostgreSQL, engine/product suites,
native grammars, real language servers, macOS wheels and clean installs/upgrades
from published 0.1.38. Actual public artifacts are checked against tagged source.

The live-session correction in [0.1.38](intelligence-0.1.38.md), file-path
correction in [0.1.37](intelligence-0.1.37.md), source-display correction in
[0.1.36](intelligence-0.1.36.md) and optional HTTP features in
[0.1.34](intelligence-0.1.34.md)/[0.1.35](intelligence-0.1.35.md) retain their
existing boundaries. Hosted features remain opt-in.
