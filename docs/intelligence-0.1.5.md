# Attocode Intelligence 0.1.5

Publication is confirmed by the `intel-v0.1.5` tag and a successful
**Release intelligence** publishing workflow; these notes alone are not a
publication record.

This patch release delivers clearer source evidence and reliable shutdown for
local code search and navigation. It also makes the experimental `lean` profile
available in the standalone package. The default `daily` profile stays unchanged.

## Changes since 0.1.4

- Search previews select a contiguous source window around query terms, retain
  symbol identity and truthful line ranges, and shorten previews before dropping
  files to meet an output budget. Metadata-only selected hits can recover bounded
  source without changing candidate order or scores.
- Unknown receiver calls remain reference candidates instead of being bound to
  a same-file method solely because its name is unique. Test suggestions explicitly
  describe their evidence and the limits of the candidate list.
- Transient SQLite errors remain retryable. Failed opens release their
  connections, and schema creation is serialized with index writes.
- Shutdown cancels lexical discovery, import-graph building and index writes,
  rolls back unfinished refreshes and stops optional reindex workers. A worker
  that remains alive produces an error instead of a successful close.
- `init --profile lean` advertises seven tools with watching, or eight without
  watching. It is opt-in and supported by the installer and doctor.

No embedding model is selected or downloaded by default. No ranking default,
remote source-sharing policy or default tool profile changes.

## Install or upgrade after publication

```sh
# Install or replace an existing installation, including a pinned older version:
uv tool install --force attocode-code-intel==0.1.5

cd /path/to/your/project
attocode-code-intel init --client codex
attocode-code-intel doctor --client codex
```

Restart the MCP connection to load the new process. Use `--client claude` or
`--client cursor` for those clients. Existing project configuration does not
need to be removed before upgrading.

## Evidence and limits

The implementation at `29c7c8956811e79ee4f3305112941341df91554a` passed an
unattended Linux cloud run: 245 contract tests, 48 assertions across six pinned
Python/JavaScript/TypeScript/Go/Rust/Java workflow packs, a 10,000-file scale
case, 20 edit/restart cycles and the unchanged 68-query ranking gate. No query
changed its first five files. Source and fixture hashes remained stable.

The suite took 456.6 seconds; provisioning through verified worker deletion
took 550.1 seconds. The compute estimate was $0.0255 before tax. Those are
observations from one shared CPU worker, not general performance or price
guarantees. Earlier failed runs exposed the fetch and shutdown issues that
were fixed before this passing run.

Release checks additionally verify clean standalone wheels on Linux and macOS,
Python 3.12/3.13 product behavior, the generated tool catalog and Docker startup.
The [release guide](intelligence-release.md) describes the publishing gates;
the [quality guide](intelligence-quality.md) describes reproducible checks and
resource limits.

These are development regression checks. They do not establish that the server
improves agent completion, review accuracy or speed. The
[completed R7 pilot](../packages/code-intel/evals/results/2026-10-14-r7-completion-pilot.md)
did not meet its continuation rule; no additional model study is part of this
release.
