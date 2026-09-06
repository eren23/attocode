# Attocode Intelligence

Codebase understanding for **Codex, Claude Code, Cursor, and other MCP clients**. Run it on your working tree, or connect a team to a self-hosted service that analyzes committed repositories.

The intelligence engine now lives in `packages/code-intel` and ships as **`attocode-code-intel`**, independently of the legacy coding agent. AST navigation and keyword search need no model API key. Local embedding search, graph analysis, and team hosting are optional extras.

## Get started from this checkout

Requires Python 3.12+ and Git.

```sh
uv tool install ./packages/code-intel
cd /path/to/your/project
attocode-code-intel init --client all
attocode-code-intel doctor --client codex
```

Use `--client claude` or `--client cursor` to configure one client. `init` installs the MCP connection and managed agent instructions, preserving unrelated configuration. Restart your agent after installation. Project-level Codex configuration requires a trusted project; Claude Code may ask you to enable the project MCP server.

For an installation shared across repositories:

```sh
attocode-code-intel init --global --client codex
attocode-code-intel doctor --global --client codex --project /path/to/repo
```

Global servers select the explicit `workspace`, an advertised MCP root, or the repository containing their working directory. If a client supplies multiple roots, the agent must select one. Cursor's automatic instruction file is project-scoped even when its server connection is global; run `init --client cursor` in each project where you want those rules.

After publishing the standalone distribution, the installation command will be `uv tool install attocode-code-intel`. The source installation above works before that release.

## Everyday use

Ask your agent to start with `bootstrap(task_hint="what you are changing")`. It receives relevant code, structure, recalled knowledge, and index coverage within a token budget. Follow with symbol search, references, dependencies, impact analysis, and test suggestions. `review_change` reports structured findings and identifies failed analysis passes.

Local file watchers and per-operation filesystem checks pick up edits, new files, deletions, and import-only changes. `notify_file_changed` is also available. Learnings persist in the existing `.attocode/cache/memory.db`, so different agents can reuse them. Use `record_learning`, `recall`, `update_learning`, and `learning_feedback` to maintain knowledge.

New installations use the compact **daily** tool profile. `init --profile full` exposes the complete local catalog, including rules and security analysis, history, architecture, retrieval pins, snapshots, overlays, and cache maintenance. Direct server invocations default to `full` for compatibility. `capabilities` reports the actual catalog and optional enhancements.

## Teams and remote agents

[Self-hosting and migration](intelligence.md) covers PostgreSQL, Redis, workers, authentication, and the dashboard. Native Streamable HTTP MCP is served at `/mcp/`. The dashboard provides connection snippets and knowledge editing.

```sh
attocode-code-intel init --client all --server https://intel.example.com --repo REPOSITORY_UUID
attocode-code-intel doctor --client codex --remote
```

Set `ATTOCODE_API_KEY` in the agent's environment. Use `intelligence:read` for analysis and add `intelligence:write` for knowledge changes. Every repository operation checks membership and scope before using cached analysis. Results identify repository, source, commit, index coverage, and truncation. Shared knowledge is stored in PostgreSQL with authorship, revision, and file anchors.

Local and remote entries coexist. Remote calls analyze committed branches or explicit revisions. Local edits remain local. To copy a particular learning to your team, review and run an explicit share:

```sh
attocode-code-intel share --project . --learning 12 --server https://intel.example.com --repo REPOSITORY_UUID --dry-run
attocode-code-intel share --project . --learning 12 --server https://intel.example.com --repo REPOSITORY_UUID
```

`cross_repo_search` searches explicitly selected authorized repositories and retains provenance on each result.

## Package and development

| Component | Location | Status |
|---|---|---|
| Intelligence engine, MCP, REST, workers | `packages/code-intel/src/attocode_intel` | Active product |
| Dashboard | `frontend` | Active product |
| Agent, TUI, swarm | `src/attocode`, `src/attoswarm` | Frozen legacy |
| Old intelligence imports | `attocode.code_intel`, selected context modules | Compatibility aliases |

```sh
uv sync --extra dev --extra code-intel
uv run pytest -c packages/code-intel/pyproject.toml --confcutdir=packages/code-intel/tests packages/code-intel/tests
uv build --package attocode-code-intel
```

The standalone workflow tests Python 3.12/3.13, real stdio and HTTP MCP, repository isolation, PostgreSQL knowledge operations, budgets, and wheel independence. Releases use `intel-v*` tags; the legacy agent keeps its separate release workflow.

[Product and operations guide](intelligence.md) · [Generated tool catalog](intelligence-tools.md) · [Legacy agent documentation](legacy-agent.md) · [MIT license](https://github.com/eren23/attocode/blob/main/LICENSE)
