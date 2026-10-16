# Intelligence architecture

`packages/code-intel/src/attocode_intel` owns the standalone engine. Its entrypoint
serves the CLI and MCP gateway; operation schemas, budgets and evidence metadata
are shared across local and remote access. `_internal` contains the extracted
parser, lexical/vector index, dependency and language-server implementations.
These modules do not import the archived coding agent.

The optional service layer adds HTTP/MCP, PostgreSQL-backed repositories and
knowledge, Redis workers, membership/scope enforcement and database migrations.
`frontend` provides the service dashboard; `docker/code-intel` packages it with
the standalone distribution. Local search/navigation remains usable without
service dependencies or model APIs.

`eval/quality` supplies bounded execution, source-only corpus workflows, resource
accounting and cleanup. `eval/matrix` retains ranking inputs and replay. Historical
studies remain evidence, with their original environment/protocol limitations.
See [validation](intelligence-validation.md), [quality](intelligence-quality.md),
[service architecture](architecture-v2.md) and [the archive](legacy-agent.md).
