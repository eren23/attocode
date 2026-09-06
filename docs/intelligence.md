# Intelligence product and operations

## Install and connect

Install only the product with `uv tool install ./packages/code-intel`. Add `[semantic]` for local embedding models, `[graph]` for graph algorithms, `[http]` for a local HTTP server, or `[service]` for the team backend. The base wheel contains no agent, TUI, swarm, or model-provider SDK. Optional embedding models may download weights on first use; keyword mode does not require them.

`attocode-code-intel init --client all --project /path/to/repo` installs managed connection settings and agent guidance. Supported clients are `codex`, `claude`, and `cursor`. Use `--dry-run` to review the managed entry and instructions. Repeating installation is idempotent; unrelated settings and TOML comments remain intact. Malformed configuration is rejected before writes. Removal restores a previous entry saved by the installer and removes its instruction block when no managed connection remains:

```sh
attocode-code-intel init --client codex --remove
attocode-code-intel init --client codex --remove --remote
```

If you edited the installed entry, removal asks you to preserve those edits rather than overwriting them. The installer saves its entry history in `.attocode-intelligence-install.json` beside the client configuration. Keep that file private, especially when replacing an entry that contained a credential. New configurations reference environment variables for credentials.

`doctor` reads the installed configuration, initializes a real MCP session, discovers tools, verifies the selected workspace, and runs a bounded project query. Run it separately for each client and use `--remote` to check the remote entry. This verifies the generated protocol connection; enabling project trust, restarting the application, and accepting client MCP prompts remain client actions.

The server accepts `--project`, `--profile daily|full`, `--no-watch`, `--watch-debounce`, and `--transport stdio|http|streamable-http|sse`. SSE and the historical CLI commands remain compatibility paths. New installations use stdio locally and native Streamable HTTP remotely. `--local-only` is accepted for old invocations; the new stdio gateway always uses local files and does not auto-load the old remote proxy configuration.

## Daily workflow and result contract

1. Bootstrap with the current task and a token budget. Check source, revision, coverage, and truncation.
2. Locate definitions using `search_symbols` and keyword or semantic search. Inspect references, dependencies, and relevant context.
3. Before changing shared code, inspect impact and test suggestions. Review explicitly selected files to avoid treating an empty Git diff as a review.
4. Local filesystem changes invalidate affected indexes automatically. Explicit notifications are available for clients and tools.
5. Record stable conventions and gotchas, recall them in later tasks, and archive outdated entries. Check entries marked stale against their current source.

`max_tokens` bounds the entire readable response, including its provenance header. MCP also returns structured data and metadata; consumers that serialize both should budget that representation separately. Coverage distinguishes a partial index from a complete one. `discovered_files` and `discovery_truncated` disclose discovery limits; `ATTOCODE_INTEL_MAX_FILES` sets the standalone selection limit (100,000 by default). The gateway retains up to eight workspaces and closes idle state when another workspace needs a slot. Zero results from an incomplete index do not establish that references or dependencies are absent. Static test suggestions and reviews do not replace running tests.

MCP tools and `POST /api/v2/operations/{tool}` use the same catalog, validation, workspace resolver, and operation gateway. `workspace` is a local root or a remote repository UUID; `revision` selects a remote branch/commit. Resources under `attocode://project/`, `attocode://symbols/`, and `attocode://learnings` accept workspace/revision query parameters and use the same authorization path.

The daily profile is intentionally small. The full catalog preserves advanced local analysis, rules, history, reproducibility, and maintenance tools. Remote catalogs omit operations that modify snapshot files, local configuration, or local artifacts. Read operations for snapshots and pins remain available; create/restore/overlay workflows run locally. Python rule plugins are loaded only for local workspaces. `capabilities` lists tools available for the selected transport and profile.

## Self-host the team service

From the repository root:

```sh
export SECRET_KEY="$(openssl rand -hex 32)"
docker compose -f docker/code-intel/docker-compose.service.yml up --build -d
```

The default image installs `attocode-code-intel[service]` and the dashboard. Embedding dependencies are opt-in with `--build-arg ATTOCODE_INTEL_EXTRAS=service,semantic`; choose the appropriate CPU/GPU model runtime for that image. PostgreSQL stores organizations, repositories, indexing metadata, and shared knowledge. Redis coordinates workers; repository clones and detached commit snapshots share a persistent volume. Schema migrations run at API startup and abort startup on failure.

Use the dashboard to create an account and organization, connect repositories, monitor indexing, and create API keys. Organization members must have accepted invitations. API keys require `intelligence:read` or historical `read` for analysis, and `intelligence:write` or historical `write` for knowledge mutations. Empty scope lists do not grant intelligence access. User JWTs are checked against organization membership. A static legacy API key cannot access team repositories.

Remote repository registration accepts HTTP(S) and SSH Git URLs. Clients cannot bind repositories to server filesystem paths or file URLs. Local filesystem analysis uses local MCP; existing operator-managed repository paths remain readable by authorized requests.

Put the service behind HTTPS for remote use. Configure `ATTOCODE_BASE_URL` and the existing OAuth settings if using OAuth login. PostgreSQL and Redis in the compose file bind only to loopback; application traffic uses port 8080. Back up PostgreSQL and the repository volume together. Keep `SECRET_KEY` stable across restarts and consistent between API and worker. Persist model caches separately if model downloads on container replacement are undesirable.

```sh
export ATTOCODE_API_KEY="your-team-key"
attocode-code-intel init --client codex --server https://intel.example.com --repo REPOSITORY_UUID
attocode-code-intel doctor --client codex --remote
```

Remote configuration uses the separate `attocode-code-intel-remote` entry. `X-Attocode-Workspace` selects its default repository and `X-Attocode-Profile` selects `daily` or `full`. An explicit tool workspace overrides the default but always requires authorization. Detached Git worktrees identify exact commits; the server checkout is not changed. Repository symlinks that escape a snapshot are rejected. No source files are uploaded by the new local integration.

Snapshot directories are currently retained until operator cleanup. Monitor the repository volume on servers analyzing many revisions. Stop the service before pruning detached worktrees; use Git worktree commands so Git metadata stays consistent. This is a self-hosted product foundation; billing, managed hosting, and automatic storage quotas are outside this release.

## Knowledge and migration

Existing local learnings and ADR SQLite databases remain usable. Different local agents use the same `.attocode` stores, with serialized operations and file locks. Team learnings and ADRs use PostgreSQL `knowledge_entries` (migration 020), with repository identity on every query, author, status, source commit, and file anchors. Changed/deleted anchors mark an entry stale without deleting it. Remote bootstrap recalls relevant shared learnings.

Local knowledge stays private until explicitly shared. `share --learning ID --server URL --repo UUID --dry-run` previews only the selected learning; omitting `--dry-run` sends it. It does not send source files. Existing server-side SQLite learnings are not silently copied into PostgreSQL: review and share selected entries from the old project path using this command. ADRs can be exported with the existing Markdown exporter and recorded through `record_adr` after review.

The dashboard and native MCP use `/api/v2/operations` for shared knowledge. Historical v1/v2 project knowledge endpoints retain their formats and use the same PostgreSQL store in service mode. New consumers should use operations; existing file-sync/watch/connect commands retain their explicitly invoked legacy upload semantics and are not installed by `init`.

Old `attocode.code_intel` and extracted context import paths delegate to the canonical package. The root development environment installs the workspace dependency. Agent/TUI/swarm feature development is frozen; their existing entry points and tests remain. The original README is preserved as the legacy-agent guide.

## Release and evaluation

`intel-v0.1.0` identifies the standalone release, separately from legacy `v*` tags. CI builds the wheel, checks imports without the agent distribution, tests stdio/HTTP MCP, knowledge and repository authorization against PostgreSQL, and runs synthetic 100/1,000/10,000-file daily workflows. The evaluation emits cold/warm startup latency, lookup latency, output tokens, and dependency coverage; thresholds are explicit in the script. Results are uploaded as CI artifacts.

To run locally:

```sh
uv run pytest -c packages/code-intel/pyproject.toml --confcutdir=packages/code-intel/tests packages/code-intel/tests
uv run python packages/code-intel/evals/daily.py --sizes 100 1000 10000 --output /tmp/intelligence-eval.json
uv build --package attocode-code-intel
```

Set `TEST_DATABASE_URL` to a disposable PostgreSQL database to exercise the same SQL tests on PostgreSQL; otherwise the scoped CRUD tests use SQLite as a fast relational fixture. The dedicated CI service runs PostgreSQL and all migrations. Real Codex/Claude/Cursor application sessions should also be smoke-tested before promoting a release; protocol tests alone cannot prove client UI behavior.
