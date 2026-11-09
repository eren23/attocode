# Attocode Intelligence 0.1.30

Version 0.1.30 improves Java, C and Go syntax metadata, persisted-index startup
and live refresh. It also hardens release provenance, source archives and the
MCP Registry install probe.

## Signatures and Go ownership

- Java preserves literal dollar-sign call names such as
  `$Gson$Types.canonicalize`, varargs names/component types/rest flags, return
  types and trailing array dimensions. Method chunks receive those signatures;
  constructors keep an empty return type.
- C named parameters preserve source order and written pointer, array and
  callback types through nested declarators. Comments, declaration attributes
  and storage classes do not become type annotations. Abstract or ambiguous
  parameter syntax does not invent a binding name.
- Go signatures retain grouped parameter names, variadic component types/rest
  flags and written results for functions, receiver methods and interfaces.
  Blank and unnamed parameters add no binding names.
- Go module variables/constants include every declared name in grouped blocks.
  Function/receiver locals, blank identifiers and initializer contents stay out
  of module bindings.
- Go named types and aliases keep individual source ranges and documentation,
  including grouped declarations and inline interface ownership. Local types
  stay out of module symbols. Simple, generic and parenthesized receiver methods
  bind to their same-file named type, including declarations written later in
  the file. Type arguments cannot become owners.

## Imports, refresh and restart

Go's checked-in standard library declares `module std` while importing package
paths such as `sync/atomic`. Those imports now resolve through the caller's
nearest enclosing declared standard-module root and actual indexed package
files. Separate checkouts and nested target modules retain their boundaries,
including empty, invalid or temporarily inaccessible indexed `go.mod` files.
Configuration-only edits update the dependency graph.

AST diffs compare detailed parameter metadata alongside legacy name lists.
Refresh also checks the decoded source hash, so body-only edits update cached
source and caller edges even when size, mtime and signatures stay unchanged.
Such edits do not create structural signature-change events.

Both direct and readiness-first startup check parser/indexer identity before
reusing persisted symbols. Upgrades rebuild stale indexes even when the source
timestamps are unchanged. Explicit forced indexing still rebuilds the index.

## Release and grammar acquisition

Published verification accepts an explicitly selected immutable retry tag under
`refs/tags`, with the original canonical tag preserved. Source archives exclude
generated `.attocode` state while retaining the tracked rule fixture used by
tests.

The Registry install probe uses disposable cache/config state and a shared
300-second budget for at most eight attempts. It retries only temporary failure
to resolve the exact package version. Wrong versions, other install errors and
timeouts stop publication; attempt reports are retained.

Linux CI acquisition for the locked optional grammar pack uses the canonical
upstream release API after the repository move, checking the original asset
sizes and SHA-256 digests. The grammar binaries and navigation's installed/cache
policy are unchanged.

## Validation and limits

The maintained native gate requires 92 cases with no skips. Source-pinned Gson,
Redis, Go CLI, Go AST and Go atomic files exercise real signatures, declarations,
calls, imports and selected test relationships. Complete AST/symbol/count cache
checks guard restarts without calls through either parser entry point. The
standard-module fixture includes the unchanged upstream module and license,
raw public responses, actual import-bound test evidence and owned cleanup.

Release CI runs Python 3.12/3.13 product and combined suites, synthetic preflight,
Linux/macOS wheel checks, language servers and the existing ranking gate. The
candidate and actual-PyPI verifiers check clean installs and upgrades from
0.1.29, installed source identities and cleanup.

These are syntax, navigation and installation contracts. Written member calls
remain candidates where the resolver cannot prove their binding. Receiver
ownership is scoped to same-file named types; C type-name ambiguity and custom
Perl runtime load paths remain limited. This release makes no new first-page
relevance, agent-speed or fresh broad-compatibility claim. Hosted features remain
opt-in and off by default.

## Install or upgrade

Install with `uv tool install attocode-code-intel==0.1.30`, or upgrade an existing
installation with `uv tool upgrade attocode-code-intel`. Restart the MCP server
after upgrading so its running process loads the new version.
