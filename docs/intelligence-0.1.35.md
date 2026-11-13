# Attocode Intelligence 0.1.35

Version 0.1.35 adds an optional stdio-to-HTTP client bridge for authenticated
remote MCP servers. It manages the live cancellation context and forwards a
host's MCP tool-call cancellation using the upstream SDK's actual request ID.
The bridge is opt-in; ordinary local stdio and native remote HTTP remain the
default configuration paths.

## Upgrade and configure

```sh
uv tool install --python 3.12 'attocode-code-intel==0.1.35'
attocode-code-intel --version
```

Restart the host's MCP connection after upgrading. The CLI version alone does
not identify a server that the host already has running.

To preview a bridge entry for Codex:

```sh
attocode-code-intel init --client codex --server https://your-server.example \
  --repo YOUR_REPOSITORY_ID --token-env ATTOCODE_API_KEY --http-cancellation --dry-run
```

Set the named token variable in the host environment. Remove `--dry-run` to write
the entry, then restart the host's MCP server. Claude Code and Cursor use the
same flag with their respective `--client` value. Configuration stores the token
variable's name, not its value; Codex forwards it through `env_vars`.

The server still requires the authenticated HTTP cancellation support introduced
in 0.1.34, `ATTOCODE_MCP_HTTP_CANCEL=1`, and one worker or context affinity.
That server flag remains off by default. The bridge does not enable it remotely.

`doctor --client codex --remote` checks a new connection through the configured
bridge. It uses the server's workspace and reports the reached server version;
it cannot verify an already-running host session. Managed removal restores any
previous entry, subject to the existing edited-configuration check:

```sh
attocode-code-intel init --client codex --remote --remove
```

## Cancellation and protocol contract

Each live upstream SDK session owns a fresh random UUID4 context. When the
stdio host sends MCP cancellation for an active `tools/call`, the bridge uses
the observed HTTP request ID and the same credential, workspace and profile.
The two request IDs may differ. A new upstream session gets a new context.

There is one best-effort notification enqueue attempt with a one-second budget,
after which the original caller cancellation is preserved. This bounds SDK
enqueueing, not network delivery. The SDK owns the subsequent HTTP POST and its
normal timeouts. A delayed notification can block later writes; a transport
failure can close the upstream session and bridge. Delivery may race request
registration or fail. There is no acknowledgement or cancellation-latency SLA.

Tools list/call, resource list/templates/read and prompt list/get are forwarded
only for capability groups advertised by the upstream. Typed content, resource
URIs, cursors, metadata, structured results and errors are retained. Sampling,
elicitation, tasks, subscriptions, change notifications and progress are not
relayed by this bridge.

Disconnects, process restarts and cross-worker delivery have no new guarantee.
Cancellation remains cooperative: it does not undo completed writes or interrupt
arbitrary synchronous work. Existing Rust five-second precision, other-language
two-second precision and one-second retry budgets remain unchanged; they are
not total-request SLAs.

## Release verification

The maintained release gates cover Python 3.12/3.13, PostgreSQL, combined engine
and product suites, native grammars, real language servers, macOS wheels and
clean installation/upgrades from published 0.1.34. Real SDK stdio-to-HTTP tests
exercise different local/upstream IDs, active worker cancellation, owned cleanup
and later verified recovery. Focused contracts cover concurrency, context
rotation, early/repeated cancellation, enqueue failures, protocol payloads,
reversible client configuration, redacted proxy URL errors and remote doctor.

This release makes no new search-quality or agent-speed claim. See
[HTTP cancellation setup and limits](intelligence.md#optional-http-cancellation)
and the [release process](intelligence-release.md).
