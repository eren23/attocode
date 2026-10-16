# attocode-code-intel

Local code search and navigation for coding agents and for people. It runs as an MCP server for Codex, Claude Code, Cursor and other MCP clients, and as a command in your terminal. It needs no model, no API key and no network.

**Status: beta.** We measured the search quality (see [What we measured](#what-we-measured)). We have not shown that it makes agents faster or more accurate.

## Quickstart

You need Python 3.12 or later and Git.

```sh
uv tool install attocode-code-intel
cd /path/to/your/project
attocode-code-intel init
```

Then restart your agent. `init` configures Codex, Claude Code and Cursor. Use `--client claude`, `--client codex` or `--client cursor` for one client. Codex needs a trusted project for a project configuration. Claude Code can ask you to enable the project MCP server.

To check the setup, run `attocode-code-intel doctor`. It starts the configured server, calls two tools and shows the result for each client.

For other clients (VS Code, Zed, Windsurf, Claude Desktop and more), run `attocode-code-intel install <target>`. `attocode-code-intel commands` lists the targets.

To use the latest source, install from a clone of this repository: `uv tool install /path/to/attocode/packages/code-intel`.

## What your agent gets

The source build also provides `changes` and `trace` commands: investigate a diff,
follow source-backed caller paths, export JSON/Markdown, and check or refresh saved
evidence. MCP equivalents `change_context` and `trace_flow` are local full-profile
tools. See the [change investigation guide](https://github.com/eren23/attocode/blob/main/docs/guides/change-investigation.md).

The agent sees 16 tools (the `daily` profile):

| Use | Tools |
|---|---|
| Find code | `semantic_search`, `fast_search`, `search_symbols`, `bootstrap`, `relevant_context` |
| Read a symbol | `inspect_symbol`, `symbols`, `cross_references`, `call_graph` |
| See structure | `dependencies`, `explore_codebase`, `project_summary` |
| Plan a change | `impact_analysis`, `suggest_tests`, `review_change` |
| Check the server | `capabilities` |

- When the agent knows a symbol, `inspect_symbol(symbol_name="...", task_hint="...")` gives the definition, the source, the references and candidate tests in one call.
- In an unfamiliar repository, `bootstrap(task_hint="...")` finds the relevant code and gives a map.
- `impact_analysis` and `suggest_tests` help plan the checks for a change.

For all tools (about 140: rules, security scans, history, snapshots and more), add `--profile full` to `init`. The [tool catalog](https://github.com/eren23/attocode/blob/main/docs/intelligence-tools.md) lists them. The [search details](https://github.com/eren23/attocode/blob/main/docs/intelligence-search.md) page describes ranking, the response format and the experimental rerankers.

For an experimental local seven-tool surface (0.1.5 or later), use
`init --profile lean` and restart your client. It advertises `bootstrap`,
`search_symbols`, `inspect_symbol`, `semantic_search`, `impact_analysis`,
`suggest_tests` and `capabilities`, with conditional routing instructions
and 2,000-token responses. Without file watching, `notify_file_changed`
is an eighth tool. Advanced tools require a full-profile session.
This opt-in profile has no demonstrated completion benefit; see the
[completed pilot](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-14-r7-completion-pilot.md).

## Commands for people

Run these in your project:

```sh
attocode-code-intel query "parse config"      # search the code with its own words
attocode-code-intel symbols src/app.py        # the symbols of a file
attocode-code-intel symbols --search greet    # find a symbol by name
attocode-code-intel impact src/app.py         # the files that a change can affect
attocode-code-intel deps src/app.py           # what a file imports, and what imports it
attocode-code-intel hotspots                  # the files with the most risk or complexity
```

Search matches the words of the code and its paths. It does not use embeddings unless you install the `semantic` extra.

## What we measured

- **Search.** We ran the 560 issues of Loc-Bench V1, with the full issue as the query. For 53.2% of them, the first five files held all files of the fix (file Acc@5 0.532). On a mix of 10 public benchmarks, file Acc@5 was 0.425. See the [first-stage results](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-09-locbench-560-first-stage.md) and the [matrix results](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-10-matrix-r1.md).
- **Agents.** In four studies, Claude Code (Sonnet 5.5) named the files to edit for an issue. The server did not raise file Acc@5. Each run with the server cost 1.4 to 2.1 times as much. When the agent could choose, it seldom called the server. See the [agent pilot](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-10-agent-pilot.md) and [study R3](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-10-agent-r3.md).

The [R6 review study](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-13-r6-review-test-note.md)
found no demonstrated review benefit. The [completed R7 repair pilot](https://github.com/eren23/attocode/blob/main/packages/code-intel/evals/results/2026-10-14-r7-completion-pilot.md)
also found no demonstrated benefit; its reviewed decision is to stop expansion.

## Limits and troubleshooting

- **First search.** The first tool call starts the index build. A search waits up to 15 seconds for the index. On a large repository, a search can report that the index is warming. Then search again. An empty result during warm-up does not prove that the code is absent.
- **Index location.** The index is in `.attocode/` in your project. When the server makes that folder, it adds a `.gitignore`, so the index stays out of commits.
- **What the index reads.** The server reads at most 50,000 files and skips files over 1 MB. It skips files that `.gitignore` ignores, and folders that start with a dot. It also skips folders named `dist`, `build`, `out`, `output`, `target`, `env`, `tmp`, `vendor` or `coverage`, and binary, media and lock files. If a build-named folder contains real source, explicitly re-include it with a root `.gitignore` entry such as `!dist/`; discovery and edit refresh honor that override.
- **Languages.** The base install parses Bash, C, C#, C++, CSS, Elixir, Go, HCL, HTML, Java, JavaScript, JSON, Kotlin, Lua, PHP, Python, Ruby, Rust, Scala, Swift, TOML, TypeScript, YAML and Zig. Optional grammars are loaded only when already installed or cached; installing the `tree-sitter-all` extra does not trigger grammar downloads during navigation. A slow grammar falls back after a 100 ms parse budget. Static imports and references are partial evidence, not compiler/type resolution.
- **Test paths.** Search and test suggestions recognize conventional test folders and filenames, plus supported Kotlin/Android source sets directly under `src` (for example `commonTest`, `jvmTest`, `androidHostTest` and `androidDeviceTest`). Helpers in those sets count as test code even without a test filename. Custom target or flavor names are not inferred from a `Test` suffix alone. Short queries explicitly asking for tests put recognized test files first, preserving order within each group; longer issue descriptions keep source-first behavior. Suggestions can include helpers; verify the actual runnable tests.
- **Remove the setup.** Run `attocode-code-intel init --remove`. It restores an entry that existed before `init`.
- **Server does not answer.** Run `attocode-code-intel doctor`. If a client shows "not configured", run `init` for it. After a change, restart the agent. In Claude Code, `/mcp` shows the server state.
- **HTTP server.** `attocode-code-intel --transport http` needs the `http` extra. It serves only this computer unless you set `ATTOCODE_API_KEY`.

For one installation for all repositories, use `init --global`. A global server works on the repository of its working directory, or on the `workspace` that a tool call names.

## Teams and remote agents

[Self-hosting and migration](https://github.com/eren23/attocode/blob/main/docs/intelligence.md) covers PostgreSQL, Redis, workers, authentication, and the dashboard. The service serves native Streamable HTTP MCP at `/mcp/`. The dashboard provides connection snippets and knowledge editing.

```sh
attocode-code-intel init --client all --server https://intel.example.com --repo REPOSITORY_UUID
attocode-code-intel doctor --client codex --remote
```

Set `ATTOCODE_API_KEY` in the agent's environment. Use `intelligence:read` for analysis and add `intelligence:write` for knowledge changes. Every repository operation checks membership and scope before using cached analysis. Results identify repository, source, commit, index coverage, and truncation. PostgreSQL stores shared knowledge with authorship, revision, and file anchors.

Local and remote entries coexist. Remote calls analyze committed branches or explicit revisions. Local edits remain local. To copy a particular learning to your team, review and run an explicit share:

```sh
attocode-code-intel share --project . --learning 12 --server https://intel.example.com --repo REPOSITORY_UUID --dry-run
attocode-code-intel share --project . --learning 12 --server https://intel.example.com --repo REPOSITORY_UUID
```

`cross_repo_search` searches explicitly selected authorized repositories and retains provenance on each result.

## Development

The package is in `packages/code-intel` of the [attocode repository](https://github.com/eren23/attocode).

```sh
uv sync --extra dev --extra code-intel
uv run pytest -c packages/code-intel/pyproject.toml --confcutdir=packages/code-intel/tests packages/code-intel/tests
uv build --package attocode-code-intel
```

For routine work, use `.venv/bin/python -m eval.quality quick` (two minutes)
or `local` (ten minutes). They isolate scratch and caches in a monitored 5 GiB
workspace and report incomplete runs separately from passes. The
[quality guide](https://github.com/eren23/attocode/blob/main/docs/intelligence-quality.md) covers pinned multi-language
workflow checks, storage inventory, cleanup and optional CPU cloud batches.

Releases use `intel-v*` tags ([release guide](https://github.com/eren23/attocode/blob/main/docs/intelligence-release.md)).

[Product and operations guide](https://github.com/eren23/attocode/blob/main/docs/intelligence.md) · [Tool catalog](https://github.com/eren23/attocode/blob/main/docs/intelligence-tools.md) · [Search details](https://github.com/eren23/attocode/blob/main/docs/intelligence-search.md) · [Changelog](https://github.com/eren23/attocode/blob/main/CHANGELOG.md) · [MIT license](https://github.com/eren23/attocode/blob/main/packages/code-intel/LICENSE)
