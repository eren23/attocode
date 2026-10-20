# Attocode Intelligence 0.1.12

0.1.12 makes `doctor --client claude` read the Claude Code local scope. The
standalone distribution remains `attocode-code-intel`.

```sh
uv tool install --force attocode-code-intel==0.1.12
```

Restart the MCP connection after you upgrade.

## Changes

- **`doctor` reads the Claude Code local scope.** `claude mcp add` writes to
  the local scope by default, under the project path key in `~/.claude.json`.
  Claude Code prefers a local entry to a project entry with the same name.

  Before, `doctor --client claude` read only the project
  `.mcp.json`, so it reported "not configured" for a server that Claude Code
  ran. Now `doctor` checks the local entry first, and the result names the
  configuration file that it checked.

Search, indexes and caches do not change. `init` does not change, and client
configurations do not change.

## Evaluation since 0.1.11

- A CPU cost test of function-unit CodeRankEmbed embeddings failed its frozen
  rule. Query time passed (p95 52.9 ms), but a full index took 21.6 minutes
  for the median repository (limit 10). Product search does not add
  function-unit embeddings. See the
  [CPU cost report](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-19-cpu-fn-embed-cost.md).

After publication, the GitHub release records the install, upgrade and
publication results. No cloud benchmark, agent study or model
download is part of this release.
