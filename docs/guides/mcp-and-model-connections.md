# MCP and optional models

Configure the standalone server with `attocode-code-intel init --client codex`
(or `claude` / `cursor`) and verify it with `doctor --client codex`. Restart the
client afterward. See [getting started](../getting-started.md) for installation
and [service access](../intelligence.md) for remote MCP and authentication.

Syntax navigation and keyword search need no model credentials. Embedding and
remote-ranking integrations are optional and must be configured explicitly;
see [search](../intelligence-search.md). Do not install all extras or download a
model merely to connect MCP. The repository no longer provides its own coding
agent or provider-routing CLI. Those instructions are in the
[agent archive](../legacy-agent.md).
