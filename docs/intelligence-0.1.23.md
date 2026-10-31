# Attocode Intelligence 0.1.23

Version 0.1.23 adds a listing in the official MCP Registry and fixes the opt-in
hosted rerank. Search ranking defaults are unchanged.

## MCP Registry listing

The server is listed in the [official MCP Registry](https://registry.modelcontextprotocol.io)
as `io.github.eren23/attocode-code-intel`. Directories that import from the
registry can show it. The package README now starts with the registry ownership
marker and has a quick start that needs no installation:

```json
{
  "mcpServers": {
    "attocode-code-intel": {
      "command": "uvx",
      "args": ["attocode-code-intel", "--project", "/absolute/path/to/your/project"]
    }
  }
}
```

You can omit `--project` if the client sends one workspace root. Otherwise the
server looks for a repository marker such as `.git` in the working folder and its
parents. It never selects your home folder, and it stops with an error if it finds
no repository.

## Hosted rerank fix

The opt-in SystemOne rerank compared the model name in the response with the
configured name. OpenRouter answers with a dated snapshot, for example
`typesafe/jev-1.13-20260917` for `typesafe/jev-1.13`, so every hosted call fell
back to the unreranked order. The adapter now accepts the configured name followed
by an eight-digit date. It still rejects any other model name.

Rerank stays off by default. The [Hosted rerank](intelligence-search.md#hosted-rerank-experimental)
section gives the configuration, what leaves your machine and the cost. The only
measured gain is on long Python issue text; a trial with short agent queries is
pending.

Dependencies, discovery limits and the 100 ms native parse budget are unchanged.

Install with `uv tool install attocode-code-intel==0.1.23`, or upgrade an
existing installation with `uv tool upgrade attocode-code-intel`. Restart the
MCP server after you upgrade.
