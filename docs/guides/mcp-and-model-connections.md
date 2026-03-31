# MCP And Model Connections

This guide explains the connection layers Attocode currently supports and how
local vs global configuration works for each one.

The main distinction is that there are four different systems involved:

1. `attocode` itself as an AI coding agent with provider/model settings
2. Attocode's MCP client config in `~/.attocode/` and `.attocode/`
3. `attocode-code-intel` as an MCP server you can install into other hosts
4. Swarm subprocess backends such as `claude`, `codex`, and `codex-mcp`

If you treat those as one thing, the config paths and commands stop making
sense quickly.

## Quick Audit

Use these commands to inspect your current setup before changing anything:

```bash
# Attocode code-intel installs across supported hosts
attocode-code-intel status

# Codex MCP registrations
codex mcp list

# Claude Code MCP registrations
claude mcp list

# Run the MCP server directly for the current repo
attocode-code-intel --project .
```

## Host Matrix

| Host / Surface | Local Config | Global Config | Install Command |
|---|---|---|---|
| Claude Code | CLI-managed | CLI-managed | `attocode code-intel install claude [--global]` |
| Claude Desktop | None | Platform config file | `attocode code-intel install claude-desktop` |
| Cursor | `.cursor/mcp.json` | None | `attocode code-intel install cursor` |
| Windsurf | `.windsurf/mcp.json` | None | `attocode code-intel install windsurf` |
| VS Code / GitHub Copilot | `.vscode/mcp.json` | None | `attocode code-intel install vscode` |
| Codex | `.codex/config.toml` | `~/.codex/config.toml` | `attocode code-intel install codex [--global]` |
| Zed | `.zed/settings.json` | `~/.config/zed/settings.json` | `attocode code-intel install zed [--global]` |
| Cline | None | VS Code globalStorage | `attocode code-intel install cline` |
| OpenCode | None | `~/.config/opencode/config.json` | `attocode code-intel install opencode` |
| Gemini CLI | `.gemini/settings.json` | `~/.gemini/settings.json` | `attocode code-intel install gemini-cli [--global]` |
| Roo Code | `.roo/mcp.json` | None | `attocode code-intel install roo-code` |
| Amazon Q Developer | None | `~/.aws/amazonq/mcp.json` | `attocode code-intel install amazon-q` |
| GitHub Copilot CLI | None | `~/.copilot/mcp-config.json` | `attocode code-intel install copilot-cli` |
| Junie (JetBrains) | `.junie/mcp/mcp.json` | `~/.junie/mcp/mcp.json` | `attocode code-intel install junie [--global]` |
| Kiro | `.kiro/settings/mcp.json` | None | `attocode code-intel install kiro` |
| Trae | `.trae/mcp.json` | None | `attocode code-intel install trae` |
| Firebase Studio | `.idx/mcp.json` | None | `attocode code-intel install firebase` |
| Amp (Sourcegraph) | `.amp/settings.json` | `~/.config/amp/settings.json` | `attocode code-intel install amp [--global]` |
| Continue.dev | `.continue/mcp.json` | None | `attocode code-intel install continue` |
| Hermes Agent | None | `~/.hermes/config.yaml` | `attocode code-intel install hermes` |
| Goose | None | `~/.config/goose/config.yaml` | `attocode code-intel install goose` |
| IntelliJ | Manual | Manual | `attocode code-intel install intellij` |

Important differences:

- Cursor, Windsurf, VS Code, Roo Code, Trae, Kiro, Firebase, and Continue.dev
  are project-local only.
- Claude Code, Codex, Zed, Gemini CLI, Junie, and Amp support a user-level
  install path via `--global`.
- Claude Desktop, Cline, OpenCode, Amazon Q, Copilot CLI, Hermes, and Goose
  are effectively user-level because their configs live in global locations.
- `install intellij` prints manual setup instructions instead of modifying files.

## Attocode Install Modes

These commands install the Attocode CLI itself, not an MCP registration.

### Global tool install

```bash
uv tool install --force . --with anthropic --with openai
```

This puts `attocode`, `attocodepy`, `attoswarm`, and `attocode-code-intel` on
your `PATH`.

### Editable tool install

```bash
uv tool install --force --editable --no-cache --from /absolute/path/to/attocode attocode
```

Use this when you want the globally available commands to execute the code from
your local checkout directly.

### Project-local dev environment

```bash
uv sync --all-extras
```

This creates a local `.venv/` for working in the repo, but it does not install
global host integrations by itself.

## Attocode's Own MCP Client Config

This is Attocode reading MCP servers for itself.

Config precedence:

1. `~/.attocode/mcp.json`
2. `.attocode/mcp.json`
3. `.mcp.json`

Later entries override earlier ones by server name.

Example:

```json
{
  "servers": {
    "context7": {
      "command": "npx",
      "args": ["-y", "@upstash/context7-mcp@latest"]
    }
  }
}
```

Notes:

- The Attocode MCP config uses a `servers` object, not `mcpServers`.
- `.mcp.json` is backward-compatible project-level input for Attocode.
- Attocode auto-connects eager servers at startup.
- Servers marked `lazy_load: true` stay pending until a tool is needed.
- Registered MCP tools are namespaced like `mcp__server__tool`.

## `attocode-code-intel` As An MCP Server

`attocode-code-intel` is Attocode's code-intelligence server exposed over MCP.
It can also run over SSE or HTTP.

### Direct usage

```bash
# stdio MCP server
attocode-code-intel --project /path/to/repo

# same server through the attocode wrapper
attocode code-intel serve --project /path/to/repo

# HTTP mode
attocode code-intel serve --transport http --project /path/to/repo
```

### Install into hosts

```bash
attocode code-intel install claude
attocode code-intel install claude --global
attocode code-intel install cursor
attocode code-intel install codex
attocode code-intel install codex --global
attocode code-intel install zed
attocode code-intel install zed --global
```

### Scope behavior by host

#### Claude Code

`attocode code-intel install claude` shells out to `claude mcp add`.

- local scope uses Claude Code's project-scoped MCP registration
- `--global` maps to Claude Code user scope
- if you use a plain global install with no explicit project path, the server
  can resolve the working directory dynamically when Claude launches it

This is different from file-based hosts because Claude Code manages the entry
through its own CLI.

#### Codex

`attocode code-intel install codex` writes TOML to:

- `.codex/config.toml` for local scope
- `~/.codex/config.toml` for `--global`

Example shape:

```toml
[mcp_servers.attocode-code-intel]
command = "attocode-code-intel"
args = ["--project", "/absolute/path/to/repo"]
```

Important nuance:

- Codex global installs are user-level registrations
- the generated entry still includes `--project /absolute/path/to/repo`
- so the config is global, but the server target is still pinned to a specific
  repo unless you add or edit the entry manually

For live inspection, use:

```bash
codex mcp list
codex mcp get attocode-code-intel
```

Codex also has its own MCP management commands:

```bash
codex mcp add ...
codex mcp remove ...
```

#### Cursor, Windsurf, VS Code

These are simple project-local JSON writes:

- Cursor: `.cursor/mcp.json`
- Windsurf: `.windsurf/mcp.json`
- VS Code: `.vscode/mcp.json`

They all use the `mcpServers` key:

```json
{
  "mcpServers": {
    "attocode-code-intel": {
      "command": "attocode-code-intel",
      "args": ["--project", "/absolute/path/to/repo"]
    }
  }
}
```

#### Zed

Zed uses:

- `.zed/settings.json` for local scope
- `~/.config/zed/settings.json` for `--global`

Its key is `context_servers`, not `mcpServers`.

#### Claude Desktop, Cline, IntelliJ, OpenCode

- `claude-desktop` writes to the platform-specific Claude Desktop config dir
- `cline` writes to VS Code globalStorage
- `intellij` prints manual setup instructions
- `opencode` prints manual setup instructions

## Claude: Three Separate Meanings

`Claude` can mean three different things in this repo.

### Claude Code as an MCP host

Use:

```bash
claude mcp list
claude mcp add ...
attocode code-intel install claude
```

This is about registering MCP servers into Claude Code.

### Claude Desktop as a separate MCP host

Use:

```bash
attocode code-intel install claude-desktop
```

This is not the same config or install path as Claude Code.

### Claude models inside Attocode or swarm

Use:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
attocode --provider anthropic --model claude-sonnet-4-20250514
```

This is model/provider routing, not MCP registration.

## Codex: Four Separate Meanings

`Codex` also appears in multiple roles.

### Codex as an MCP host

Use:

```bash
codex mcp list
attocode code-intel install codex
```

This means Codex is hosting MCP servers such as `attocode-code-intel`.

### Codex as an MCP server

Use:

```bash
codex mcp-server
```

This exposes Codex itself over MCP.

Attocode's hybrid swarm uses this through the `codex-mcp` backend for
multi-turn orchestration.

### Codex as an LLM backend

Use:

```bash
codex --model gpt-5.4
codex exec --model gpt-5.4 "..."
```

This is model selection for the Codex CLI.

### Codex local OSS mode

Use:

```bash
codex --oss
codex --local-provider lmstudio
codex --local-provider ollama
```

This is Codex connecting to a local OSS model provider. It is separate from
MCP and separate from Attocode provider routing.

## Attocode Provider And Model Routing

This is how `attocode` chooses the actual LLM provider and model.

Supported providers in the current docs and code:

- Anthropic
- OpenRouter
- OpenAI
- Azure
- ZAI

Common inputs:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENROUTER_API_KEY="sk-or-..."
export OPENAI_API_KEY="sk-..."
```

```bash
attocode --provider anthropic --model claude-opus-4-20250514
attocode --provider openai --model gpt-4o
attocode --provider openrouter --model anthropic/claude-sonnet-4
```

Config priority:

1. CLI flags
2. environment variables
3. project config
4. user config
5. built-in defaults

For project and user config, Attocode uses `config.json` under:

- `.attocode/config.json`
- `~/.attocode/config.json`

## Swarm Backends And Model Connectivity

Swarm worker/orchestrator backends are not the same as provider routing.

Currently supported subprocess backends:

- `claude`
- `codex`
- `codex-mcp`
- `aider`
- `attocode`
- `opencode`

### Backend behavior

- `claude`: runs the Claude Code CLI in prompt mode
- `codex`: runs `codex exec --json`
- `codex-mcp`: runs `codex mcp-server` and keeps a multi-turn thread per agent
- `aider`: runs the Aider CLI
- `attocode`: runs Attocode itself as a subprocess
- `opencode`: runs `opencode run --format json`

### Example swarm config snippet

```yaml
roles:
  - name: orchestrator
    backend: claude
    model: claude-sonnet-4-20250514

  - name: implementer
    backend: codex
    model: gpt-5.4

  - name: reviewer
    backend: codex-mcp
    model: gpt-5.4
```

Use `codex-mcp` when a worker needs iterative follow-up in the same thread.
Use `codex` when one-shot execution is enough.

## Recommended Mental Model

When debugging or configuring the system, ask these in order:

1. Which host is launching the MCP server: Codex, Claude Code, Cursor, Zed, or something else?
2. Is this a local repo config or a user-level config?
3. Is the thing being configured an MCP host entry, an Attocode provider/model, or a swarm backend?
4. If Codex is involved, is it acting as host, model client, local OSS client, or MCP server?
5. If Claude is involved, is it Claude Code, Claude Desktop, or an Anthropic model choice?

## Related Docs

- [MCP Integration](../MCP.md)
- [AST & Code Intelligence](../ast-and-code-intelligence.md)
- [Provider Reference](../PROVIDERS.md)
- [Hybrid Swarm](../hybrid-swarm-operations.md)
- [Getting Started](../getting-started.md)
