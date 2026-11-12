# Attocode Intelligence 0.1.34

Version 0.1.34 includes the gateway correction in
[PR #348](https://github.com/eren23/attocode/pull/348) and optional authenticated
HTTP cancellation in [PR #349](https://github.com/eren23/attocode/pull/349).

## Gateway cancellation

Cancelling a selected-symbol navigation request reaches its own precision
coroutine on the workspace thread. Pending requests and callbacks restore,
cancelled enrichment is not cached, and healthy language servers can be reused.
Cancelled queued calls do not start work. An already running workspace stays
busy until its actual worker finishes, preventing premature eviction.
Already-started synchronous work finishes normally.

Rust's precision deadline remains five seconds; other languages use two seconds.
The retry cooldown remains one second, with controlled tests just below, exactly
at and just above the boundary. Precision deadlines do not bound the whole request.

## Optional HTTP tool-call cancellation

HTTP MCP remains stateless and cancellation routing is **off by default**.
Enable `ATTOCODE_MCP_HTTP_CANCEL=1` on a server with service authentication or a
configured `ATTOCODE_API_KEY`. An authenticated client must generate a random
UUID4 and send it as `X-Attocode-Cancellation-Id` on both its tool-call POST and
its `notifications/cancelled` POST. Both requests must use the same credential,
workspace and profile. The notification's `requestId` must match the original
JSON-RPC ID and its string or integer type.

Do not reuse request IDs within a cancellation context. Generate a new UUID4 if
the client resets its ID counter; a delayed notification cannot distinguish
requests that reused an ID. Credential or resolved permission changes separate
routing. Authentication occurs before context validation. Only `tools/call`
participates; clients without the header keep ordinary stateless behavior, and
other MCP methods keep their existing cancellation behavior.

Routing is bounded and local to one server process. Use one HTTP worker or
provide affinity for the cancellation context. There is no cross-process
registry or delivery guarantee after a restart. Unknown/completed IDs have no
effect. Matching notifications reach the original SDK session after its tool
handler is active; the SDK may return its existing cancellation error response.

See [cancellation setup and limits](intelligence.md#optional-http-cancellation).
Disconnecting a client does not cancel its call. There is no arbitrary
synchronous interruption, write rollback, continuous permission monitoring or
total-request latency guarantee.

## Verification

Prospective gateway and real authenticated HTTP regressions precede their
product fixes. The maintained suites cover ownership, callback/pending cleanup,
precision boundaries, JWT authority/credential and workspace/profile isolation,
typed IDs, duplicate/capacity rejection, repeated and overlapping notifications,
SDK handler activation, stream closure and genuine server error propagation.
Real SQLite/PostgreSQL authorization composition runs with routing off and on.
The authored HTTP wire fixture uses real JWT verification but does not prove
invalid-API-key database fallback.

Both Python 3.12/3.13 candidate verifiers check clean installations and upgrades
from published 0.1.33. The release workflow verifies the actual PyPI artifacts
against source and tag, checks installed package trees and owned cleanup, then
probes the listed CLI before publishing the official MCP Registry entry.
Ranking, optional native grammars, real language servers, Linux/macOS wheels and
existing combined suites remain release gates. No new relevance, general
latency, agent-speed or broad compatibility claim is added. Embeddings remain
optional and hosted features stay off by default.

## Install or upgrade

Use `uv tool install attocode-code-intel==0.1.34` to install this version or
replace an older exact pin. Restart the MCP server after upgrading. The
[release guide](intelligence-release.md) describes publication checks.
