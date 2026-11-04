# Attocode Intelligence 0.1.26

Version 0.1.26 gives Rust precision lookups more time during startup or reload,
and fixes cancelled startup cleanup that could block subsequent workspace queries.

## Rust precision budget

Rust enrichment now has a five-second deadline. Startup, document delivery,
readiness waits and definition/reference requests share that deadline; retries
do not reset it. Other languages retain two seconds. Ready servers return
without waiting for the budget to expire.

Reloads longer than five seconds still return partial evidence. A later explicit
request can retry after the existing cooldown. Null replies remain distinct from
an answer containing no references.

## Cancelled startup cleanup

An unfinished language server could take additional shutdown time after its
startup deadline expired. Killing that server could also leave the client waiting
for a child process to close inherited input or output pipes.

Cancelled startup now terminates the unfinished server, aborts buffered stdin
and closes the client's owned pipes. Task cleanup and process reaping have a
fixed 250 ms allowance. Ordinary startup errors still use graceful shutdown.

Thirteen protocol regression cases cover delayed startup and replies, readiness,
edit reloads, shared deadlines, timeout isolation, and inherited pipes. The pipe
cases also verify that the same workspace answers a subsequent query.

## Install or upgrade

Install with `uv tool install attocode-code-intel==0.1.26`, or upgrade an existing
installation with `uv tool upgrade attocode-code-intel`. Restart the MCP server
after upgrading so the running process loads the new version.
