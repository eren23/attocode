# Getting started

Install the published package with Python 3.12+ and Git:

```sh
uv tool install attocode-code-intel
cd /path/to/your/repository
attocode-code-intel init --client codex
attocode-code-intel doctor --client codex
```

Use `--client claude` or `--client cursor` for those clients. Restart the client
after configuration. Code navigation and keyword search require no model API key.
Use `attocode-code-intel --help` for CLI commands and [the tool catalog](intelligence-tools.md)
for MCP operations. [Search](intelligence-search.md) explains retrieval evidence
and limitations. [Self-hosting](intelligence.md) covers the API and team service.
For a source checkout, see [contributing](contributing.md). The agent is archived;
see [migration notes](legacy-agent.md).
