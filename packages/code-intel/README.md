# Attocode Intelligence

Codebase understanding for **Codex, Claude Code, Cursor, and other MCP clients**. Run it on your working tree, or connect a team to a self-hosted service that analyzes committed repositories.

The intelligence engine now lives in `packages/code-intel` and ships as **`attocode-code-intel`**, independently of the legacy coding agent. AST navigation and keyword search need no model API key. Local embedding search, graph analysis, and team hosting are optional extras.

## Get started from this checkout

Requires Python 3.12+ and Git.

```sh
uv tool install /path/to/attocode/packages/code-intel
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

When you know the symbol, call `inspect_symbol(symbol_name="...", task_hint="behavior you are investigating")` directly. It bundles the definition, source, references, module relationships, and symbol-specific candidate tests. The optional hint adds up to three separate source excerpts beyond the opening preview and helps rank tests by their paths and function names. Python and JavaScript/TypeScript excerpts retain enclosing branch conditions, including alternative guards. Each excerpt and its `context_ranges` have exact contiguous line ranges; cite each range separately. Context stays with its excerpt when responses are trimmed. Selection ranks identifiers and executable literals and does not establish complete control flow, data flow, or test coverage. Unsupported or unparseable source uses a lexical fallback with `context_incomplete=true`. Without a hint, inspection retains its normal source preview. Select `file_path` and the definition's start `line` if the name is ambiguous.

Use `bootstrap(task_hint="...")` to orient in an unfamiliar repository. Long definitions provide a callable `follow_up.next_source`; `source_start_line` selects another page inside the definition. Each page reads current source, so restart inspection after an edit. `suggest_tests(files=["..."], symbol_name="...", task_hint="...")` exposes the same optional focused ranking. Native search remains useful for literal text and checking evidence. Use impact analysis and test suggestions to plan verification; `review_change` reports structured findings and identifies failed analysis passes.

Task-hinted local search now combines symbol/path terms with an incremental source-body index, even without embeddings. Any tool call starts the index build in the background. A search that comes before the index is ready waits up to 15 seconds. On a very large repository, a search can still report that the index is warming. Then retry, and do not read the empty result as proof of absence. Search hits retain file and source-line provenance. The source cache is stored in a private local directory; ordinary searches do not load or download embedding models, and vector indexing remains an explicit operation. Optional `task_hint` also orders equally matched definitions, related files, repository exploration, and budgeted context, while exact definitions and dependency/reference facts remain unchanged. Ignored Git checkouts still require selecting that checkout as the workspace.

Search results report `matched_terms` and whether a match came from path/symbol identity, an indexed source body, or symbol metadata. Ranking metadata marks a query ambiguous when multiple components provide complete matches; this prompts a component name or `file_filter`, not a claim that one interpretation is correct. For an unscoped multi-concept query, a small result page uses distinct files in their existing first-occurrence order when enough are available; this improves file coverage but does not judge semantic relevance. Exact/single-term queries, explicit file filters, and test-seeking queries keep their normal chunk order. Equal-scoring lexical candidates have stable ties across index rebuilds. Ignored checkout source still requires selecting that checkout as the workspace.

The [broad-query candidate audit](evals/results/2026-10-05-broad-candidate-audit.md) measures where known source files appear in a ready 24-file lexical pool. It is diagnostic, not proof that a proposed ranking rule is better; the attempted file-wide all-terms hint failed its frozen check and is not enabled. A [fresh source-only view trial](evals/results/2026-10-05-source-view-transfer.md) produced no known-target gain, so that view is not enabled either. When a small search page has more retrieved candidates, its `follow_up` gives a larger `top_k` and output budget for a new search of the current index; it is not a stable cursor or a relevance judgment. Compact output reports the actual delivered result count after budget trimming.

An experimental two-concept lexical reranker can be enabled with `ATTOCODE_INTEL_BROAD_RERANK=1`. It is **off by default**: a post-tuning holdout found damaging regressions, including burying a direct config implementation hit beneath incidental source-body matches. Do not treat its positive development scores as proof of an overall quality gain; see [the paired evaluation](evals/results/2026-10-04-broad-query-ranking.md). Ranking metadata reports `broad_ranker: off` or `experimental_on`.

An experimental local cross-encoder can rerank bounded search candidates after the deterministic retriever. It is **off by default**: install audited model weights yourself in an absolute local directory, compute their `model_tree_sha256`, then set `ATTOCODE_INTEL_RERANKER_PATH` and `ATTOCODE_INTEL_RERANKER_SHA256` before starting the service. Both settings are required. The model prewarms asynchronously, never downloads during a request, and falls back to deterministic order while cold, busy, or unhealthy. Do not enable it as a production default until your own graded navigation evaluation shows a quality and latency win. Code snippets stay local and are not included in timing traces.

An experimental SystemOne-compatible `choice` adapter is also available for a locally served or explicitly approved remote model. It is **off by default** and does not select or download a model. For a local endpoint, set `ATTOCODE_INTEL_RANKING_PROVIDER=systemone` and `ATTOCODE_INTEL_RANKING_ENDPOINT=http://127.0.0.1:8000/v1/systemone`; set `ATTOCODE_INTEL_RANKING_MODEL` only if your server requires a model ID. The endpoint receives one bounded query and up to 24 distinct files with query-focused, current source excerpts. When this provider is on, search retrieves `8 × ATTOCODE_INTEL_RANKING_MAX_CANDIDATES` chunks first, so the model can get that many distinct files (a small or sparse result set gives fewer); `task_hint` file weights use the same ranking. Ranking is file-level; the original retrieval scores remain attached to results, and repeated hits fill the page after distinct files. `ATTOCODE_INTEL_RANKING_TIMEOUT_MS` defaults automatically to 5000 for loopback or 800 for remote endpoints; set a positive value to override it. `ATTOCODE_INTEL_RANKING_MAX_CANDIDATES` defaults to 24 (maximum 64); 48 ranked slightly better in the blind trial below but sends twice the source excerpts. Timeouts, unavailable source, missing credentials, and invalid answers retain deterministic order with a source-free `fallback_reason` in ranking metadata.

For a non-loopback endpoint, use HTTPS and additionally set `ATTOCODE_INTEL_RANKING_ALLOW_REMOTE=1` **and** `ATTOCODE_INTEL_RANKING_REMOTE_WORKSPACE` to the absolute path of the one workspace allowed to send source. Other workspaces served by the same process remain local-only. If needed, `ATTOCODE_INTEL_RANKING_AUTH_ENV` names the environment variable holding its bearer token; do not put tokens in the endpoint URL. `ATTOCODE_LOCAL_ONLY=1` and multi-user service mode prohibit remote ranking even with that opt-in. Known credential patterns are redacted before remote submission, but redaction cannot guarantee that arbitrary private code contains no sensitive information: enable remote ranking only for source you approve sending. No redirect or ambient proxy is followed. Use `ATTOCODE_INTEL_RANKING_PROVIDER=off` to force deterministic ranking even when legacy local-reranker weights are configured. API compatibility does not establish quality; the [exploratory decision-model trial](evals/results/2026-10-04-decision-reranker-trial.md) is not a live-provider benchmark or a production-default justification.

To compare a configured endpoint with other rankers on the same frozen candidate pools, use the rerank stage of the eval matrix. Add a `systemone-http` entry to a rerank config, for example `{arm: systemone-http, on: graded_blind, pools: [lexical], pages: [24], endpoint: "http://127.0.0.1:8000/v1/systemone"}`. The entry also takes `model_id`, `auth_env` and `timeout_ms`. Then run `python -m eval.matrix.run run OUT --stage rerank --config CONFIG --arms systemone-http` from the repository root (`PYTHONPATH=packages/code-intel/src` if needed). An endpoint that is not a loopback IP address is remote, so it runs only on the datasets with `public: true` in the registry. Each row records the order, the status and the latency of one query. `report` compares the cell with its pool (see [the matrix rerank stage](evals/README.md#matrix-rerank-stage)). The stage does not verify the cost or the model revision of the server. The relevance labels of the existing pools are narrow. Test a provider on a new, broader held-out set before you call it generally better.

In a [local HTTP trial](evals/results/2026-10-04-systemone-http-local-trial.md), Bosun 0.6B improved MRR@5 on one 20-query pack (0.423 to 0.542) but regressed on a separate 20-query pack (0.596 to 0.554). Median inference alone was about 1.5 seconds on CPU, excluding startup and retrieval. This is evidence that the adapter works, **not** that Bosun should be the default. A [blind graded trial](evals/results/2026-10-08-blind-graded-rerank.md) on six new repositories found the same on the Mac GPU: Bosun showed no clear gain (gNDCG@5 0.476 to 0.488, 21 wins and 13 losses). On the same pools, Jev `choice` over 24 files raised gNDCG@5 to 0.701 (31 wins, 2 losses) at a 454 ms median, and a Loc-Bench issue-title check raised MRR@5 from 0.353 to 0.735. On [all 560 Loc-Bench V1 instances](evals/results/2026-10-08-locbench-560.md) with the full issue as the query, Jev over the first 48 lexical files raised file Acc@5 from 0.377 to 0.698. With file-level BM25 fused into the candidate pool, Jev reached 0.757, inside the published range (0.743 to 0.870). Search now fuses whole-file BM25 for queries of more than 20 words. With the importance and frecency weights at zero, lexical Acc@5 went from 0.388 to 0.529, and Jev over 48 files from 0.721 to 0.752. Shorter queries do not change. With the default weights, lexical Acc@5 is 0.532, and the default `auto` mode, which also expands the query, gives 0.509 ([first-stage arms](evals/results/2026-10-09-locbench-560-first-stage.md)). Jev is a remote model, so it needs the remote opt-in above. The best local model in that trial was the 4-bit MLX port of Clef-flash (gNDCG@5 0.636 against 0.652 for Jev at 12 files), but it took 8–10 s per query on a base M5. That is above the 5000 ms loopback default, so set `ATTOCODE_INTEL_RANKING_TIMEOUT_MS` (maximum 30000) if you try it. The tested `jev-compatible-server` CLI bound to `0.0.0.0`; bind explicitly to loopback before submitting private source to a local server.

Inspection, reference and call-graph queries automatically use installed language servers for an unambiguous definition, with a two-second enrichment deadline. The base engine remains usable without them; set `ATTOCODE_INTEL_PRECISION=off` to use only structural analysis. `doctor` distinguishes installed servers from verified precision queries. `capabilities` reports definitions, references, dependencies, and test heuristics separately for each language.

Daily MCP responses contain one JSON text block with `metadata` and `data`. The default `max_tokens=2000` bounds the complete serialized MCP result using an estimated tokenizer count. Provenance and ambiguity survive truncation; undersized budgets return an error. Writes require at least 512 tokens and reserve room to acknowledge their outcome before making changes. `cross_references` returns `next_cursor` when more references remain; repeat the original query with that cursor. Edits invalidate continuations. Detailed coverage and precision diagnostics are available through `capabilities`. The full profile and REST operations retain the `result`, `metadata`, and structured `data` response envelope.

Set `ATTOCODE_INTEL_TRACE` to an absolute path outside the repository to collect optional JSONL timings and response sizes. Traces contain operation names and metrics, without source or arguments. Timings for indexing, discovery, execution and precision can overlap because they include nested work.

Index readiness describes indexing progress. Analysis metadata separately reports unresolved imports, evidence sources, and precision failures. Missing relationships do not prove absence of impact, and suggested tests are candidates rather than complete coverage. Search ranking scores are not confidence percentages.

Local file watchers and per-operation filesystem checks pick up edits, new files, deletions, and import-only changes. `notify_file_changed` is also available. Learnings persist in the existing `.attocode/cache/memory.db`, so different agents can reuse them. Use `record_learning`, `recall`, `update_learning`, and `learning_feedback` to maintain knowledge.

Bootstrap excludes knowledge whose source anchors have changed; explicit `recall` still returns those entries with their stale flag.

New installations use the compact **daily** tool profile. `init --profile full` exposes the complete local catalog, including rules and security analysis, history, architecture, retrieval pins, snapshots, overlays, and cache maintenance. Direct server invocations default to `full` for compatibility. `capabilities` reports the actual catalog and optional enhancements. The local daily profile leaves out the repository learning tools and the remote-only `revision` argument. Use `--profile full` for learnings in a local session.

## Teams and remote agents

[Self-hosting and migration](https://github.com/eren23/attocode/blob/main/docs/intelligence.md) covers PostgreSQL, Redis, workers, authentication, and the dashboard. Native Streamable HTTP MCP is served at `/mcp/`. The dashboard provides connection snippets and knowledge editing.

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

[Product and operations guide](https://github.com/eren23/attocode/blob/main/docs/intelligence.md) · [Generated tool catalog](https://github.com/eren23/attocode/blob/main/docs/intelligence-tools.md) · [Legacy agent documentation](https://github.com/eren23/attocode/blob/main/docs/legacy-agent.md) · [MIT license](LICENSE)
