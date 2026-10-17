# Investigate a change

Connect a Git diff to changed definitions, current caller paths, potential import
impact and candidate tests in one local report. No model or project execution is
needed. Available since 0.1.7; focused reports and class summaries require 0.1.8.

## CLI

Start from a Git repository root with at least one commit:

```sh
# HEAD to working tree, including staged edits and untracked files
attocode-code-intel changes --project .

# Index versus HEAD, or working tree versus index
attocode-code-intel changes --mode staged --project .
attocode-code-intel changes --mode unstaged --project .

# Merge-base with main to working tree, including uncommitted edits
attocode-code-intel changes --mode branch --base main --project .

# Version 0.1.8: select changes before result caps apply
attocode-code-intel changes --file src/worker.py --symbol Worker.work --project .

# Version 0.1.8: include class-wide callers as well as methods
attocode-code-intel changes --class-mode expand --project .

# Static caller paths into one definition
attocode-code-intel trace work --file src/worker.py --line 12 --depth 2 --project .

# Keep full JSON outside the checkout or in a Git-ignored directory
attocode-code-intel changes --project . --output /tmp/change-evidence.json
attocode-code-intel changes --project . --check /tmp/change-evidence.json
attocode-code-intel changes --project . --refresh /tmp/change-evidence.json \
  --output /tmp/change-evidence-refreshed.json
attocode-code-intel changes --project . --format markdown
```

Output files are private and never overwrite existing files. Saving in an
unignored source directory changes the workspace and makes the report stale.
JSON is the portable format; Markdown is a readable view. Refresh reuses the
original request on current source, preserving the original report.
`changes --check` also accepts JSON exported by `trace`.

Freshness checks compare workspace, HEAD, branch name, index, dirty and untracked
source hashes, selected base revision, and every recorded evidence file. Same-size
edits, renames, deletions, staging and branch switches invalidate the report.
Exit 0 means recorded inputs match; 1 means stale; 2 means invalid input or
collection failure. The digest is not a signature or proof of complete impact or
test coverage. Ignored files outside the recorded evidence are not checked.

## Focused reports and changed classes (0.1.8)

File/symbol filters and class summaries are available in 0.1.8.

Repeat `--file` or `--symbol` to select several exact paths/names. File and symbol
filters intersect. Paths match either side of a Git rename; symbol names match
either before or after source. A simple name can select several distinct owners
or overloads; use the qualified name to narrow it. These are literal selections,
without glob/substring matching. Directories and paths outside the repository are
rejected. File selection precedes parsing and caps; symbol selection precedes file
and definition caps, so an unrelated earlier file cannot use up the result slots.

`selection` distinguishes intentionally excluded scope, unmatched selectors and
matching files from `omitted` results. `no_matches` means the selected comparison
has no matching changed definitions/files; it is not evidence that a definition
or its callers do not exist elsewhere. No filters preserves the broad comparison.
Filtered reports still check the complete Git snapshot: editing an excluded dirty
file makes the saved report stale too. Refresh retains the filters and class mode;
check/refresh reject replacement collection arguments.

Changed classes default to a summary of their before/after identity and up to
12 changed child definitions, with total/omitted counts. Changed methods retain
their own caller graphs. Class-wide callers are explicitly not collected in this
mode; use `--class-mode expand` for the previous traversal behavior, or a focused
`trace` of the class. Removed/index-only classes receive no current caller
follow-up. Summary members describe lexical child identities in the same file,
without inferring inheritance or overload dispatch.

Top-level `bounded` also reflects capped caller flows, impact reachability,
test candidates and summary previews. `limits` names those categories; the
existing `omitted.files` and `omitted.symbols` retain their narrower meanings.

## MCP

Start a local full-profile session with
`attocode-code-intel --project . --profile full`.

- `change_context(mode="working", depth=2)` combines source comparison, callers,
  import impact and tests. Branch mode requires `base`; other modes reject it.
- `trace_flow(symbol_name="work", file_path="src/worker.py", line=12, depth=2)`
  follows caller evidence backward into a selected definition.

Since 0.1.8, `change_context` additionally accepts exact
`files=["src/worker.py"]`, `symbols=["Worker.work"]`, and
`class_mode="summary"` (default) or `"expand"`. These selections do not scope
the caller traversal: callers and tests can remain outside the selected files.

Daily and lean advertised lists stay unchanged. Remote catalogs omit these
working-tree operations. Full MCP returns structured `data` alongside its readable
result. Save the complete data object for checking with the CLI. Budget-trimmed
data fails its integrity check; prefer the CLI for a complete JSON artifact.

## Reading the evidence

Definitions carry before/after paths, exact source ranges and hashes. A pure line
shift does not mark an unchanged function modified. File rows retain non-symbol
changes, binary/unsupported outcomes and renames. Same-name declarations are
paired in source order; this does not establish overload dispatch.

Each caller edge contains two definition identities, a call-site file/line and
its binding evidence: same-file identity, explicit import, or Go package binding.
Same-name candidates stay unresolved. Cycles terminate; depth/node limits are
explicit. Overloads without precise dispatch evidence are not followed. Paths
are not runtime execution order, data flow, or proof of complete reachability.

Removed definitions remain historical, without current caller attribution.
Staged definitions that differ from the working file also receive no current
callers. Import impact is bounded potential reachability. Test candidates reuse
name/import heuristics and add test files reached through linked callers; Rust
inline annotations use a lexical heuristic. No tests are executed and the list
is not complete coverage.

## Bounds

Defaults: 24 changed files, 32 definitions, two hops, 16 caller nodes per changed
definition, and 20 delivered test candidates. Maximums: 32 files/48 definitions,
three hops, 64 nodes for standalone traces. Each flow caps edges at 128 and
unresolved rows at 32. Omission counts describe caps; depth is a requested scope,
not proof of no further dependents.

Collection rejects source files over 512 KiB, more than 256 dirty/untracked paths
or evidence files, and dirty/evidence source totals over 16 MiB. Git commands have
an 8 MiB output cap and 15-second deadline. A 45-second collection guard runs
between analysis operations; it cannot preempt a parser/shared index operation.
JSON reports are capped below 1 MiB. Reduce limits when a bound is reached.
Filters accept at most 32 paths / 48 names, each at most 512 characters. A
symbol-only selection can scan more changed files than it delivers: that scan
rejects more than 256 changed files or 16 MiB of combined before/after source.
Add file filters to reduce it. The normal full-snapshot path/byte limits still
apply, even outside the report selection. An incomplete selection scan fails
explicitly rather than returning an unsupported no-match result.
Symlinks, submodules and unusual modes are not interpreted as source definitions.
Unmerged paths and unborn repositories need resolution/an initial commit first.

Collection disables hooks, fsmonitor, external diffs, textconv and configured
clean/process filters. Filter names appear in the snapshot. Evidence compares raw
source; LFS/filter transformations are not run, so this can differ from a normal
filtered Git diff. No optional tool/model acquisition occurs. Index caches use
the existing workspace lifecycle.
