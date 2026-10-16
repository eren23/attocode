# Investigate a change

Connect a Git diff to changed definitions, current caller paths, potential import
impact and candidate tests in one local report. No model or project execution is
needed. Published 0.1.6 predates this workflow; use the repository source build.

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

## MCP

Start a local full-profile session with
`attocode-code-intel --project . --profile full`.

- `change_context(mode="working", depth=2)` combines source comparison, callers,
  import impact and tests. Branch mode requires `base`; other modes reject it.
- `trace_flow(symbol_name="work", file_path="src/worker.py", line=12, depth=2)`
  follows caller evidence backward into a selected definition.

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
Symlinks, submodules and unusual modes are not interpreted as source definitions.
Unmerged paths and unborn repositories need resolution/an initial commit first.

Collection disables hooks, fsmonitor, external diffs, textconv and configured
clean/process filters. Filter names appear in the snapshot. Evidence compares raw
source; LFS/filter transformations are not run, so this can differ from a normal
filtered Git diff. No optional tool/model acquisition occurs. Index caches use
the existing workspace lifecycle.
