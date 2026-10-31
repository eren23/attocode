# Discovery file budget (unreleased)

Discovery defaults to 50,000 eligible files. For a larger repository, set
`ATTOCODE_INTEL_DISCOVERY_MAX_FILES=100000` in the server environment and start
a new server process. The value must be an integer from 1 through 100,000;
invalid values raise a configuration error. The environment is captured when
a context is constructed. This setting is not included in published 0.1.21.

The discovery budget bounds file descriptors collected before importance
scoring. `ATTOCODE_INTEL_MAX_FILES` remains a separate selection limit (100,000
by default for the service). A smaller selection limit can still omit files.
Internal Python callers can pass the keyword-only `discovery_max_files` argument
to `CodebaseContextManager`; the same range applies.

After filling the discovery budget, the walk looks for one additional eligible
file. It reports `discovery_truncated=true` if that file exists or importance
selection omits discovered files. Exactly reaching a limit does not itself
prove overflow. Ignored, hidden, oversized and outside-workspace symlink files
do not prove overflow. This lookahead may traverse an excluded suffix before
finishing; the setting bounds retained descriptors, not all directory entries
or traversal time. Existing source exclusions and snapshot guard limits apply.
A smaller-budget recipient refuses a complete snapshot larger than its budget.

Search diagnostics retain the configured selection limit, discovered and selected
counts, and the truncation receipt from discovery. `status=ready` and
`body_index_coverage=1.0` describe the selected inventory. Check truncation before
interpreting an empty search as evidence of absence from the whole repository.

The [qualification design](https://github.com/eren23/attocode/blob/da382a896f17271caba311260941a17ccd4b18b3/eval/quality/experiments/capacity.json) uses
small Python modules with an import chain: a 100,000-file workspace opened at
the default limit, expanded to 100,000 in a new process using the same persisted
index, then reopened again; an exact 50,000-file workspace; and a 100,001-file
workspace clipped at 100,000. Every phase checks AST, reference, keyword and body
path identities, scoped boundary search, source provenance, persisted database
continuity and cleanup. The aggregate payload limits are 40 minutes, 4 GiB RSS,
8 GiB scratch and 256 MiB evidence. These fixture checks do not establish memory
safety for arbitrary large source files, improved relevance, or faster restarts.
