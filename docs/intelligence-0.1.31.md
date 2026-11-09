# Attocode Intelligence 0.1.31

Version 0.1.31 makes live vector refresh safer and gives native Go receiver
methods consistent identities across navigation and search. It also preserves
source spans during optional vector fusion and refuses future cache formats
before changing their files.

## Live edits and durable replacement

Local file notifications, queued changes, watch callbacks, service updates and
automatic freshness now use one update contract. Existing-file changes retain
prior vectors until a complete replacement succeeds. Dirty vectors remain on
disk for retry, but cannot appear as fresh search results or count toward
readiness. Current keyword/body evidence remains available when optional vector
writes fail. Notifications never initialize an embedding provider.

Deleted paths lose vectors and file metadata together. Durable generations fence
in-flight work so a notified deletion or rename cannot resurrect an old path.
An edit arriving while its file is already pending causes a follow-up pass;
relative queued paths resolve against the selected workspace.

Indexing captures the source used for chunks, checks its revision before
publication, and commits each file's vectors and successful metadata together.
Incomplete responses, invalid dimensions, SQL failures and incomplete supported
native/Python parses retain prior data. Nonblank unvalidated fallback output
cannot certify an empty replacement. Valid empty replacements are explicit;
ordinary duplicate vector IDs keep the existing last-wins behavior.

Already-open readers observe other connections' successful replacements. A local
dirty marker can reconcile another manager's newer verified clean revision.

## Go identity and source evidence

Standalone native Go receiver methods retain their qualified names and method
kinds when their receiver type is declared in another file. Pointer, generic,
parenthesized and Unicode receiver identities remain distinct from ordinary
functions. Diffs and whole-file deletion notifications preserve those identities
and the method's actual file and source range.

Keyword, body and optional vector search now agree on labels such as `A.M` and
`B.M`. Unchanged legacy Go keyword/body caches receive targeted repair when
native evidence is available. Missing native parsing keeps conservative output
and remains retryable. Explicit vector-index maintenance repairs older bare Go
receiver IDs without source edits.

Optional vector fusion retains distinct overload spans and body windows. It
joins a vector to one best window only when the definition is unambiguous;
ambiguous overloads retain their lexical evidence. Actual source windows keep
their text and coordinates. A metadata-only match retains vector text instead
of replacing it with a keyword summary. Persisted vector ID format, tokenization,
ranking configuration and output budgets remain unchanged.

Existing future keyword/body cache formats are inspected read-only before
writable opening, journal configuration or permission changes, including caches
using DELETE journaling. Their contents and modes remain intact on refusal.

## Verification and limits

Release CI runs Python 3.12/3.13 product and combined suites, synthetic preflight,
95 required native cases, real language servers, Linux/macOS installation and
the existing ranking gate. Source-pinned navigation, cache restart, failure,
concurrent-edit and source-range controls retain original evidence. Candidate
and actual-PyPI verification check clean installation, upgrade from the published
0.1.30 baseline, installed source identity and owned cleanup.

Atomicity is per file. Source rechecks do not create a filesystem transaction
against an unnotified edit in the final check/publication window. Nonempty
regex/ctags fallback extraction remains approximate, and duplicate declarations
do not acquire separate persisted vector IDs. Written Go member syntax does not
prove runtime binding. Slow Rust reloads can still return partial evidence within
the existing five-second precision budget; custom Perl runtime load paths remain
limited.

These are correctness and installation contracts, without a new first-page
relevance, latency, agent-speed or broad-compatibility claim. Embeddings remain
optional. Default keyword/body search needs no model or API key; hosted features
remain opt-in and off by default.

## Install or upgrade

Install or upgrade to this release with
`uv tool install attocode-code-intel==0.1.31`. Reinstalling with this version
replaces any older exact pin; `uv tool upgrade` preserves existing constraints.
Restart the MCP server after upgrading so its running process loads the new version. See the
[release guide](intelligence-release.md) for publication verification.
