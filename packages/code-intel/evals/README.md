# Local evaluation

`daily.py` checks bootstrap latency, complete daily MCP output budgets, hydration and import edges on generated Python repositories of 100, 1,000 and 10,000 files. It needs no model or network connection.

`warm_cache.py` measures sequences against the same engine with a fresh process/index for every task, or a preserved index and process with explicit restart and edit boundaries. Supply an external JSON pack with `repositories` (unique `id`, local `source`, and ordered `tasks`). Each task has `id`, `operation`, `arguments`, and `checks` against compact response `data`; checks support `equals`, list-item `any`/`none`, or string `contains`. Optional `wait_until_ready: true` waits for complete background indexing after the operation, charging that time to the task and recording coverage. Optional `restart: true` starts a new OS process while retaining the index. Optional `edits` contain a relative `path` and exact complete-file `before`/`after` strings (`null` creates/deletes a file). Inputs, frozen engine/harness copies, traces and results stay outside this repository.

```sh
python packages/code-intel/evals/warm_cache.py freeze --pack /external/pack.json --study /external/warm-study
python /external/warm-study/warm_cache.py run --study /external/warm-study
python /external/warm-study/warm_cache.py report --study /external/warm-study
```

Use `freeze --lanes persistent` to measure a continuous editing session without a cold-per-operation lane. `--engine-source /external/preserved-engine` freezes an earlier engine with the current harness for a matched comparison. A task with `restart: true`, `edit_while_closed: true`, and `edits` closes the worker before modifying source, exercising changes made while the agent is offline. Readiness barriers can be applied after these restarts as well as at initial setup. Unselected lanes are not measured and cannot establish a cache crossover.

Reports include aligned cumulative timings, startup costs, evidence checks, phase percentiles and a sustained crossover against repeated cold engine use. Failed calls receive at least the fixed timeout penalty and cannot establish a speed advantage. Interrupted sequences are retained without replacement. Source-copy time is separate; OS caches are uncontrolled. This diagnostic does **not** measure agent understanding, natural tool adoption, or break-even versus native tools. Real process/cache lifecycle coverage is distinct from conversation continuity in an agent client.

`workflows.py` runs eight evidence checks each on local FastAPI, Express, ripgrep and dashboard snapshots: definitions, callers, imports, potential impact, test candidates, context, knowledge persistence and edit freshness. It archives committed files into disposable directories and preserves the originals. Reports record repository revisions and the engine source hash. Supply `--revisions` with a JSON mapping of repository names to commits to repeat specific snapshots.

```sh
uv run python packages/code-intel/evals/workflows.py \
  --repos /path/to/local/clones --precision off --output /tmp/workflows-base.json
```

These gateway checks look for known evidence, not exhaustive reference recall or complete test coverage. The legacy gateway reports readable and structured response tokens separately; daily MCP applies its budget to the complete serialized result.

`client_comparison.py` is an opt-in, metered Claude CLI experiment. It requires an authenticated client and an explicit model. Each lane gets the same prompt, native read tools and fresh repository snapshot; the intelligence source is copied once so concurrent development cannot change it between lanes. The lanes are native tools, native tools plus base intelligence, native tools plus optional precision, and an optional Serena server supplied as a revision-pinned launcher JSON. Tools that edit code, run commands or write memory are excluded.

```sh
uv run python packages/code-intel/evals/client_comparison.py \
  --repo-dir /path/to/local/clones --repos express \
  --model YOUR_MODEL --intel /path/to/attocode-code-intel \
  --output /tmp/client-comparison
```

Reports include cost, latency, token usage, actual tool calls, permission failures and known-file anchor hits. An anchor miss can be a different valid caller or test; it is not automatically a wrong answer. Inspect the private traces before interpreting results. These navigation questions do not measure successful coding changes, and single runs do not establish a competitive ranking.

By default the client chooses whether to use connected tools. Add `--require-navigation-tools` to require symbol and reference lookups through each connected server before native verification; reports record whether MCP tools were actually used.

## Repeated client study

`study.py` freezes the engine, harness, repository snapshots, explicit client models, Serena revision, prompts, and randomized paired schedule. The study contains 12 scenarios (four repositories across lookup, regression repair, and returning-session work), four lanes, three clients, and five repetitions: 720 runs. Agents choose tools naturally. Returning cases include preparation/knowledge time, a source edit, and a new conversation. Native tools and durable repository notes are available in every lane.

All artifacts must be outside the source repository. `models.json` maps `codex`, `claude`, and `cursor` to explicit model IDs. The Serena launcher is a JSON object with `command` and `args`, including a full Git revision. Freeze a development pilot separately from release evidence; changing a frozen input requires a new study.

```sh
uv run python packages/code-intel/evals/study.py freeze \
  --repo-dir /path/to/clones --models /private/path/models.json \
  --serena-launcher /private/path/serena.json --study /private/path/study
PYTHONPATH=/private/path/study/engine uv run python /private/path/study/harness/study.py prepare --study /private/path/study
PYTHONPATH=/private/path/study/engine uv run python /private/path/study/harness/study.py run \
  --study /private/path/study --quota /private/path/quota.json --max-runs 12
```

Preparation installs repository dependencies in disposable snapshots and checks that each clean repository passes independent acceptance checks and its injected regression fails. Acceptance checks execute after agent completion, outside the agent's editable tests. Runs retain private traces, source evidence, changes, timing, model usage, tool choices and permission failures. Finished runs are never overwritten; interrupted attempts remain visible. Five-minute acceptance and ten-minute agent timeouts are recorded as failures. Report setup separately from agent completion and acceptance time.

Only subscription authentication is permitted; API-key/provider overrides are removed. Login alone cannot establish whether extra usage is disabled. Before running, check each client's remaining subscription allowance and billing settings, then record that observation in a local `quota.json`:

```json
{"claude":{"subscription_only":true,"extra_usage_disabled":true,"remaining":true,"checked_at":0}}
```

Replace `checked_at` with the observation's Unix timestamp and add entries for the other clients. Observations expire after one hour. Missing, expired or exhausted quota stops execution; the runner never enables extra usage or changes account settings. Cursor also requires a working login. Client adapters and output formats are tested locally; live compatibility still requires authenticated runs.

`responses.py` replays 20 fixed queries without a model and counts complete serialized results, including every reference page. This measures wire overhead, not model-visible volume or speed. `client_responses.py` repeats those queries through each real client against frozen baseline and candidate engines, correlating actual tool results and verifying reference pagination. These forced-query trials measure volume only; they do not contribute to the natural-selection speed study.

```sh
PYTHONPATH=/private/path/study/engine uv run python /private/path/study/harness/client_responses.py \
  --study /private/path/study --baseline-src /private/path/baseline-src --quota /private/path/quota.json
PYTHONPATH=/private/path/study/engine uv run python /private/path/study/harness/study.py report --study /private/path/study
python packages/code-intel/evals/release_gate.py --report /private/path/study/report.json --project .
```

The gate requires all runs, no observed success regression per repository/client/family, a 20% median paired time improvement for both intelligence lanes against native and Serena in each client/family, and a positive lower bound from a hierarchical paired 95% bootstrap interval. Failed tasks receive the timeout penalty when computing speed. Every client must also show a 40% median response-volume reduction across matched queries with required evidence preserved. Missing or incompatible evidence fails the gate; wire-only measurements cannot satisfy the client-volume requirement.

The release workflow downloads an external report using repository variables `INTELLIGENCE_EVIDENCE_URL` and `INTELLIGENCE_EVIDENCE_SHA256`. It verifies the pinned report content and candidate engine before packaging or publication. Reports, traces, billing observations and roadmap material are not committed to the repository.

## All-client lookup pilot

`freeze --mode pilot --baseline-src PATH` creates a development study of 54 scored Express lookup trials: three clients, three paired repetitions, and six setups (native, Serena, previous base/precision, current base/precision). `PATH` must contain the previous `attocode_intel` source package. Both engine copies, the selected repository, harness, models, and randomized schedule are frozen. Only Express dependencies are prepared.

```sh
uv run python packages/code-intel/evals/study.py freeze --mode pilot \
  --baseline-src /private/path/baseline-src --repo-dir /path/to/clones \
  --models /private/path/models.json --serena-launcher /private/path/serena.json \
  --study /private/path/pilot
PYTHONPATH=/private/path/pilot/engine uv run python /private/path/pilot/harness/study.py prepare --study /private/path/pilot
PYTHONPATH=/private/path/pilot/engine uv run python /private/path/pilot/harness/study.py wiring \
  --study /private/path/pilot --quota /private/path/quota.json
PYTHONPATH=/private/path/pilot/engine uv run python /private/path/pilot/harness/study.py run \
  --study /private/path/pilot --quota /private/path/quota.json
PYTHONPATH=/private/path/pilot/engine uv run python /private/path/pilot/harness/study.py report --study /private/path/pilot
```

Wiring performs one excluded, forced-tool check per client, verifying source results through native reads and all three connected servers. Failed or interrupted wiring is preserved; resolve the issue and freeze a new pilot before scoring that client. Authentication and the same fresh subscription-quota observations are required for wiring and scored runs. The default pilot batch is six scored runs; resume with the same command. Release studies retain their 12-run default. `--clients` can select ready clients without removing the others from the manifest.

Client streams are recorded incrementally in private `trace.jsonl`, `events.jsonl`, and `stderr.log` files. Events have monotonic receipt times. Tool starts and completions are matched by call ID and repeated events are deduplicated. Receipt intervals can include client buffering; they are not exact server execution times. Missing results or timing boundaries remain unavailable rather than zero. Engine phase timings remain separate and may overlap.

`report` writes `report.json` and `pilot-review.md`, with per-client paired time differences, source-evidence success, actual MCP use, symbol-bundle use, discovery calls, follow-up reads/searches, separate shell calls, and observed response volume. Runs that never use intelligence stay in the comparison. Follow-up reads are not automatically classified as redundant; inspect their requested evidence against prior results. Failed attempts receive at least the 600-second timeout penalty for paired comparisons.

A complete three-pair comparison with a 20% median time reduction and no observed success regression is labeled **promising**, not a competitive ranking. Pilot reports are always rejected by the release gate. The runner stops at the pilot schedule and never launches or populates the separate release study.

## Source-grounded answer quality

`freeze --mode quality` adds seven development cases on pinned Express and FastAPI snapshots: serialization flow, impact and test selection, stale-note correction, response branching, alias propagation, validation errors, and dependency-cache discovery. The full schedule is 252 trials (seven cases × three clients × three repetitions × four setups). The default batch remains six; task and client filters can run a smaller subset. Existing frozen studies retain their original schedules and scoring.

```sh
uv run python packages/code-intel/evals/study.py freeze --mode quality \
  --repo-dir /path/to/clones --models /private/path/models.json \
  --serena-launcher /private/path/serena.json --study /private/path/quality
PYTHONPATH=/private/path/quality/engine uv run python /private/path/quality/harness/study.py prepare --study /private/path/quality
PYTHONPATH=/private/path/quality/engine uv run python /private/path/quality/harness/study.py wiring \
  --study /private/path/quality --quota /private/path/quota.json --clients codex
PYTHONPATH=/private/path/quality/engine uv run python /private/path/quality/harness/study.py run \
  --study /private/path/quality --quota /private/path/quota.json --clients codex \
  --tasks fastapi:quality_dependency_discovery --max-runs 4
PYTHONPATH=/private/path/quality/engine uv run python /private/path/quality/harness/study.py report --study /private/path/quality
```

Every client gets the same source access, claim questions, schema, and source variant. The six initial cases supply a relevance candidate pool. The dependency discovery case supplies no file paths or internal implementation symbol names: agents must locate the caching option's construction and execution path, request boundaries, and security-scope cache keys. Its partial relevance judgments remain private. Ground-truth verdicts, relevance labels, file hashes, and evidence groups live in the external frozen manifest. They are omitted from prompts and agent repository copies. The read-only task instructions prohibit reading outside the repository; this is procedural isolation, not protection against a deliberately malicious client that can read the host filesystem.

Discovery pins all Python implementation/test files for citation validation, independently of relevance judgments. A real citation to an unjudged file can require review without being called fabricated. Unjudged retrieval results leave precision-dependent metrics unavailable; required-file recall and judgment coverage remain reported. Unknown relevance cannot create a scored comparison gain. These are partial judgments, not exhaustive repository relevance labels.

Freeze rejects missing or ambiguous source anchors. Grading rejects source drift and repository escapes. Preparation also executes Express's real JSON/JSONP methods before and after a JSON-only indentation mutation: JSON must change, JSONP must stay unchanged, and an existing content type must survive. It restores the snapshot afterward. This checks a positive and negative control independently of intelligence output.

Dependency discovery preparation executes the pinned counter regression tests and a separate request where an uncached dependency runs before a cached occurrence of the same callable. A cache-write mutation must break only that independent probe; removing scopes from the cache key must break the security counter test while preserving the other controls. Both mutations restore source before agents run.

The machine-graded answer supplies a verdict (`supported`, `contradicted`, `insufficient`), confidence, explanation and exact source citations for each claim, plus ranked relevant files and a summary. A citation may quote up to 12 contiguous lines starting at its supplied line number; all lines must match, and required anchors anywhere inside the verified excerpt count. File dumps, shifted ranges and invented inner lines cannot earn evidence credit. Metrics are reported separately:

- Verdict accuracy and class-balanced accuracy, with omissions included in the denominator.
- Grounded claim precision/recall: a correct verdict must cover all required evidence groups. Multistep claims need evidence for each step.
- Citation validity (actual source) and `citation_anchor_precision` (matches the claim's authored evidence anchors). Repeated citations earn no extra credit. Anchor precision measures rubric agreement, not semantic citation relevance.
- Unsupported assertion rate and binary Brier score for confidence that the selected verdict is correct. Unavailable metrics remain null with observation counts.
- Retrieval precision, recall, F1, reciprocal rank, and NDCG over the explicitly judged candidate pool. Selecting every file, duplicating results, and omitting relevant files cannot obtain a perfect result.

Reports retain unsuccessful attempts, unused MCP setups, time, and tool use. Quality deltas compare matched task/client/repetition pairs. No overall quality score mixes formatting with correctness, and no result is labeled a competitive win automatically.

These are development rubrics, not held-out questions or exhaustive repository recall. The current corpus emphasizes Python and JavaScript response handling; it does not establish general architecture, security, or dead-code accuracy. Citation matching is conservative: a valid alternative citation can require human adjudication and a new rubric version. Grades identify invalid source quotes separately from exact quotes outside authored anchors. When verdicts and retrieval are correct and only unjudged citations remain, the assessment is `needs_review`; it does not count as an automatic pass or a demonstrated answer error. Reports retain both review counts and failed assessments. Frozen studies keep their original scorer and scores when the harness changes.

`report` exports `blind-review.json` containing questions and answers without client, setup, timing or automatic scores. Keep `blind-review-key.json` separate. Reviewers assess factual errors, missing reasoning, unsupported prose assertions and actionability, and flag any answer that reveals its identity. Prose review stays **pending** until reviewed; correct structured fields do not automatically make the explanation correct. No API-based judge runs. Quality development reports cannot satisfy the release gate.

### Installed guidance diagnostic

`study.py freeze --mode onboarding` freezes 12 trials: two quality tasks, Codex and Claude, and three setups (`native`, `intel_available`, `intel_installed`) with one repetition. It accepts the same private model file as the other modes; no Serena launcher is required. Run the frozen harness's `prepare`, `wiring`, `run --max-runs 12`, and `report` commands with the existing subscription quota checks. This is an onboarding diagnostic, not a competitor comparison or release gate.

Both MCP setups execute the frozen package's real project installer. The adapter replays the generated MCP entry through isolated CLI configuration, changing its executable/environment to pin the frozen engine, disable optional precision equally, and capture telemetry. The available-only setup removes the generated guidance file; the installed setup retains its exact bytes. Native tools remain available in all three setups. Guidance is not pasted into the task prompt. Installer time is included in setup time; client startup and MCP response overhead remain in answer time. Every trial starts with a fresh repository and MCP process; OS caches are uncontrolled and warm-use performance is not measured.

Claude enables `--setting-sources project` and excludes personal and ancestor memory with `claudeMdExcludes`. An empty setting-sources list failed the live instruction-loading check. Codex retains `--ignore-user-config` and `--ignore-rules`; the latter skips execpolicy rules, **not** `AGENTS.md`. The diagnostic refuses nonempty Codex global guidance and competing snapshot instruction files instead of changing personal files. These boundaries test installed project guidance under isolated CLI settings, not global config discovery, plugins, or an IDE restart.

Excluded readiness checks place a random token only in the installed project instruction file and require it back without file-reading tool calls. The token is removed before a separate forced native/MCP transport check and never appears in scored tasks. A failed check prevents scoring for that client; retain it and freeze a new diagnostic after a fix. Reports retain failed runs, guidance/config hashes, matched quality/time comparisons, raw provider usage, first tool choice, and follow-up calls. Tool use alone does not establish useful evidence reuse; review traces before attributing gains or calling later reads redundant.

## Executable understanding evaluation


`study.py freeze --mode understanding --case-pack /private/path/pack --baseline-src /private/path/starting-src` accepts a private `case_pack.py` with pinned repository revisions, public scenario inputs, counterfactual edits, repair faults, implementation roots, and an external `probe` function. Supply the usual `--repo-dir`, `--models`, and `--study` arguments. The diagnostic freezes four cases, Codex and Claude, and native/previous/current setups: 24 trials, one repetition. Run `prepare`, `wiring`, `run`, and `report` through the frozen harness with `PYTHONPATH=STUDY/versions/current/engine`. Runs default to batches of six. Private packs and study artifacts must remain outside the repository.

The versioned answer schema deduplicates source references. Analysis grades exact scenario outputs and changed/unchanged impact independently of citation formatting. Predictions are committed before evaluator execution. Repair acceptance reconstructs clean source and overlays only submitted implementation, preserving independent tests and configuration. Every fault must change intended checks while preserving negative controls. Raw citation validity, alternative test evidence, tool adoption, execution failures, and protocol review remain separate. Arbitrary shell reads need review; this is a trace audit, not an OS sandbox protecting private grading files. Single-repetition development results do not satisfy the release gate or establish an unseen-codebase advantage.

## External benchmark pilot

`study.py freeze --mode external --benchmark-pack /private/path/pack --repo-dir /private/path/pack/sources --models /private/path/models.json --study /private/path/study` freezes a prepared, external four-task pack: two SWE Atlas QA questions and two FeatureBench feature tasks. Run the frozen harness's `prepare`, `wiring`, `run --max-runs 4`, and `report` with `PYTHONPATH=STUDY/engine`. The schedule contains 16 scored attempts across Codex/Claude and native/current intelligence, plus four excluded guidance/transport checks. Existing modes and frozen studies are unchanged.

The private pack contains `pack.json`, prepared source snapshots, pinned runtime image identities, upstream provenance, preparation controls, and a private FeatureBench evaluation worker. A pack must establish reference success, intended starting failure, and unaffected behavior for feature tasks; QA requires source/rubric and runtime verification. Models never receive private task metadata. Native host CLIs retain subscription authentication while a common command helper runs repository programs against the same workspace in a network-disabled Docker container. Only the task workspace is mounted. Host filesystem access is procedurally restricted and audited, not OS-isolated from private grading material.

QA uses its required answer file and operator rubric review, with anonymous review exports. Feature patches are committed before evaluation in fresh environments. Reports retain failed/interrupted attempts, missing answers, usage, setup/runtime/evaluation timing, and review status. The 20-minute QA and 60-minute implementation limits, local runtime, and operator grading make this an adapted diagnostic, not an upstream leaderboard reproduction. Quota checks and disabled extra usage remain mandatory. External reports cannot satisfy the release gate.

After exporting a report, copy `operator-review-template.json` to `operator-review.json` in the private study directory. Keep its study and attempt identities. For each QA criterion, replace `null` with whether the criterion applies: `true` on a negative criterion records an error, not a success. A partially reviewed answer remains pending. Set each attempt's `protocol` to `pass` or `violation` after reviewing its trace, and record supporting observations in `notes`. Regenerate the report to compare positive criteria met, negative criteria triggered, executable feature acceptance, and elapsed time. These raw criterion counts are operator judgments, not an independent or upstream leaderboard score. Report generation preserves the submitted review file.

## Agent localization study

`study.py freeze --mode localize --instances /private/path/instances.jsonl --ids /private/path/ids.txt --model <explicit model ID> --study /private/path/study` freezes a file localization study for Claude Code. The input is a matrix `instances.jsonl` from `python -m eval.matrix.run ingest`. Each line is one `eval.matrix.datasets.Instance` as JSON. The ids file has one matrix id (`dataset/native`) on each line. The matrix id is the `instance_id` join key in the study output. Use `--trials` (default 2), `--setups` (default: all four) and `--config-id` (default `product`). Then use the frozen harness with `PYTHONPATH=STUDY/engine` for `prepare`, `wiring --quota QUOTA`, `run --quota QUOTA` and `summary`.

`QUOTA` is the quota file of the repeated client study. The operator writes it only after a check of the account settings: remaining subscription allowance and disabled extra usage. The harness and agents never write this file.

The issue is `queries["full"]` of the instance, and the gold files are `gold`. The frozen prompt `PROMPT_V1` gives the issue text without changes. It asks for at most 10 repository-relative paths, most likely first, as `{"files": [...]}`. Claude gets this schema with `--json-schema`. The manifest contains each rendered prompt, so a change to the prompt gives a new study id. The setups are:

- `native`: `Read`, `Grep` and `Glob`.
- `intel`: the native tools, the attocode MCP server (daily profile, frozen engine) and its installed project guidance.
- `intel_first`: the `intel` setup, and the prompt asks for `semantic_search` with the issue title first.
- `issue_only`: no tools, an empty workspace and one trial. This is the contamination control.

No setup gets `ToolSearch`. The wiring check shows that Claude can call the MCP tools without it.

`prepare` fetches each base commit. When `repo` has a `/`, it fetches from `https://github.com/{repo}.git`. Otherwise the instance is from a case pack, and `prepare` fetches from the local clone `~/Documents/ai/benchmark-repos/{repo}`. It only reads that clone.

From each base commit, `prepare` makes a snapshot with one commit and no history. It excludes an instance when the snapshot has agent guidance or configuration, for example `CLAUDE.md`, `AGENTS.md`, `.claude/` or `.mcp.json`. It also excludes an instance when no gold file is in the tree. It builds the index of each snapshot before the timed runs.

Each trial starts in a fresh copy. An intel trial copies the index and repairs it before the timer starts, because the copy changes the file times. The warm-up waits for the symbol index and for the keyword and body indexes of search. All of them persist in `.attocode`. The MCP server runs with `ATTOCODE_LOCAL_ONLY=1` and `HF_HUB_OFFLINE=1`. Each trial has a 600-second limit. A trial that changes `git status` is a `protocol_violation`.

`run` can continue after a stop. It does not run a trial again when the trial has a `result.json`. A started trial without a result becomes `interrupted` and does not run again.

Use `--jobs 2` for two parallel trials and `--max-runs` for a batch. After `--deadline-minutes` (default 100), no new trial starts. The quota check runs before each trial. The harness kills each process whose command line names a study folder. It does this at the start and end of each command and after each trial. It stops with an error when a process stays alive.

`summary` grades with `eval/metrics.py` and records the hash of that file. It writes `runs.jsonl`, `summary.md` and `review.md`. Each row of `runs.jsonl` is one run, with the join keys `dataset`, `instance_id` and `config_id`.

The grader removes the workspace root, `./` and `:line` from answer paths. It removes duplicates and keeps the first 10 paths. The `invalid_paths` field counts paths that are not in the snapshot. A failed run scores 0 and counts the full time limit.

Each row also has turns, tokens by type, `cost_usd`, tool calls by name and MCP calls. It counts the MCP results that report a warming index. The `gold_seen_s` field gives the client seconds at the first tool result that names a gold file. The `review.md` file lists the runs where a setup and `native` have different Acc@5. It also lists the failures and five random runs with their event files.

Each trial starts a new MCP server. Its first search loads the saved search indexes: on a snapshot of 2,558 files, it answered in 0.8 s. Before 2026-10-10, the warm-up waited for the symbol index only. Then the first search of a trial built the search indexes, and on medium repositories it often returned a warming status and no results. The `mcp_warming_results` field counts these results. Prompt caching can continue from one trial to the next, so compare tokens by type as well as cost. This study is a development diagnostic. It does not satisfy the release gate.

After `summary`, `python -m eval.matrix.agents STUDY --instances /private/path/instances.jsonl` writes `STUDY/agent_report.md`. The task is the unit: the report averages the trials of each task. Then it pairs each setup with `native` on the same tasks. It gives the Acc@5 of `issue_only`, but it does not pair this setup.

The primary comparisons are ΔAcc@5 and the geometric mean cost ratio. The report also gives Δseconds and Δturns. The bootstrap range and the sign-flip p-value resample repositories, and the Holm correction applies over setups. With fewer than 10 repositories, a comparison is descriptive. A sample size table gives the tasks for a ΔAcc@5 of 0.10 and of 0.05 at 80% power.

With `--matrix OUT`, the report reads the rows of one offline cell (`--offline-cell`, default `product`) at variant `full` in `OUT/results.jsonl`. For each setup, it correlates the offline reciprocal rank of the first gold file with the agent Acc@5 (Spearman). It also gives a 2×2 table of offline hit@5 and agent hit. An agent hit is a task mean Acc@5 of 0.5 or more. The report counts the tasks without an offline row and does not score them.

## Ranking gate

`python -m eval.matrix.run ci` is a regression gate for search ranking. The Ranking gate workflow runs it when a pull request changes `packages/code-intel/src/`, `eval/matrix/` or `uv.lock`. The engine hash of the matrix covers all of `packages/code-intel/src/`, so a change in any of these files can move the ranking.

The gate reads `eval/matrix/configs/ci.yaml`. It runs the free first-stage cells `product`, `kw`, `body`, `filebm25` and `grep` on 68 queries. `eval/matrix/configs/ci_instances.jsonl` holds them: the 20 queries of the broad dev pack, 13 mcp_bench search tasks and 20 small Loc-Bench instances. Search is deterministic, so the gate compares the first five files of each query with `eval/matrix/ci_baseline.json`. The gate fails when one cell crosses a limit:

- The queries that lose Acc@5 (or R@5) are 2 or more above the queries that gain.
- The mean MRR@5 drops by more than 0.01.
- A query has no result, or the query set is not the same as in the baseline.

The gate always lists the queries whose first five files changed. CI keeps the repository snapshots in a cache. It makes all search results again with the code of the pull request.

To change the ranking on purpose:

1. Push the change. The gate fails and lists the changed queries.
2. Read the list, and make sure that each change is one that you want.
3. Download the `ranking-baseline` artifact of the failed run.
4. Replace `eval/matrix/ci_baseline.json` with the file from the artifact.
5. Commit the file in the same pull request.

CI writes the committed baseline on Linux. To run the gate on your computer, use `python -m eval.matrix.run ci`. Add `--write-baseline` to write a baseline from your code. On macOS, the `kw` cell of one query (`broad_dev/gh-cli::api authentication`) puts two files with the same score in the opposite order. A local run lists that query as changed, but the gate passes.

## Matrix rerank stage

`python -m eval.matrix.run run OUT --stage rerank` reorders the first files (the page) of the pool rows in `OUT/results.jsonl`. The pool rows come from the rows stage or from `import-legacy`. The `rerank` entries of the config (default `eval/matrix/configs/full.yaml`) select the work. Each entry names an `arm` and gives `pools`, `pages`, `on` (`core`, `noise50`, a dataset name or `all`), `variants` and `query_chars` (0 or 512). The cell name is `POOL>ARM.PAGE`, with `.q512` for a cut query and `~rN` for repeat N. `configs/legacy.yaml` runs the trials of earlier result docs again.

The arms are in `eval/matrix/rerank.py`:

- `none`: the pool order, as a control.
- Local cross-encoders at pinned Hugging Face revisions: `qwen3-rr-0.6b`, `bge-rr-v2-m3`, `jina-rr-v2`, `gte-modernbert-rr` and `mxbai-rr-base-v2`. The stage loads one model at a time. `jina-rr-v2` runs model code from Hugging Face, so it needs `--allow-remote-code`. `mxbai-rr-base-v2` needs sentence-transformers 5.4.
- `systemone-http`: the product SystemOne adapter, with the endpoint of the entry.
- `jev-choice` and `haiku45-listwise`: paid arms through OpenRouter. The key is `OPENROUTER_API_KEY` from the environment or `~/.jev/env`.

The excerpts come from `focused_evidence.file_excerpt` over the snapshot in the matrix cache. The stage does not clone or check out a repository. `cache.db` in the matrix cache keeps each answer. A listwise key holds the model, its revision, the prompt version, the query sent, the hash of the ordered excerpts and the repeat index. A cross-encoder keeps one score for each query and excerpt. A request in the cache costs nothing, and `import-legacy` loads the Jev answers of old trials.

A remote arm sends excerpts out of this machine. Jev, Haiku and a SystemOne endpoint that is not a loopback IP address are remote. The stage refuses a remote arm on a dataset without `public: true` in the registry.

The cap of paid calls is `--budget-usd`, else `run.budget_usd` of the config, else 0. It applies to the spend of the run folder in the ledger table of `cache.db`. Before the calls start, the stage estimates each paid arm. Jev costs about $0.0006 a call. Haiku gets its estimate from the cost of earlier calls, or from 5 probe calls. The stage refuses to start when the spend and the estimates pass the cap.

Each call reserves its estimate, and an arm stops when the spend and the reservations reach the cap. The ledger records the cost that OpenRouter reports for each call. Every 200 calls and at the end, the stage compares the ledger with the OpenRouter usage counter. The counter can be late by a minute. Other use of the same key also moves it.

A failure is a status, never a silent pool order. A failed request is `request_failed`. An answer that is not a valid order is `invalid_output`. An example is a Haiku answer that is not a JSON list of all candidate numbers. The row keeps the pool order with that status. To send the failed requests again, add `--retry-failed`.

`repeats` in the config, for example `{arms: [jev-choice], n: 3, on: noise50}`, gives each repeat its own cache key.

The report refuses a rerank row when its pool hash or its page does not match its pool row. It marks a cell that keeps the pool order on 95% or more of its rows as a harness failure. The rerank table gives the ceiling (the best Acc@5 of an order of the page) and Acc@5. It also gives the efficiency (Acc@5 divided by the ceiling) and Δ against the pool cell with its MDE. The other columns are failures, latency, the cost of 1,000 rows and the cache share. The header gives the spend of the run folder.

On 2026-10-09, a replay of the Loc-Bench 560 trials took all Jev answers from the cache. Jev over 48 files gave the published Acc@5 of 0.7518, at a cost of $0. A paid check on 10 Loc-Bench rows cost $0.2245 in the ledger, and the OpenRouter usage counter moved by $0.2263.

## Matrix dense arm

The cell `dense` ranks files with CodeRankEmbed at a pinned revision. It ranks only the source files of product search (`dense.ranked`). These are the files that the product parses, but not prose or data files such as Markdown, YAML and JSON. This is the source-file rule of the whole-file BM25 of the product.

The model embeds the 40-line windows of each file and the query. A file keeps at most 400 windows (16,000 lines). A query can have 2,048 tokens, and a window can have 512 tokens. A file scores the best cosine of its windows. The cell `rrf(product+dense)` fuses the first 48 files of `product` and `dense` (reciprocal rank, k 60). It has no result of its own: the stages fuse the cached results of its parts.

A GPU pod makes the vectors, and the retrieve stage needs no model:

1. `python -m eval.matrix.dense plan OUT --job JOB.json` writes the snapshots and queries of `OUT/instances.jsonl`. It refuses a dataset without `public: true`.
2. On the pod, `python -m eval.matrix.dense job JOB.json --work DIR` makes the snapshots with the matrix code, then embeds the files and the queries.
3. `python -m eval.matrix.dense import DIR` compares the pod trees with the local trees and adds the vectors to `emb/` in the matrix cache.
4. `python -m eval.matrix.run run OUT --stage retrieve --arms dense` ranks the files. A query without vectors is "not ready", and the stage saves no result for it.

On 2026-10-09, one RTX 4090 pod embedded the 767 snapshots of the core mix and Loc-Bench 560. That is 3.78 million windows of 549,067 source files at about 413 windows each second. The pod cost about $2.9, with the setup. 88 files have more than 16,000 lines, and the arm does not embed their last 14,607 windows.

A trial of the fused attention of PyTorch gave 1.37 times the speed, but its lowest cosine with the model attention was 0.9993. Thus the job keeps the attention of the model code. The pod also ran the retrieve stage, and only the `ret/` results came back. The vectors did not come back.

On the full issue of Loc-Bench 560, `dense` gave Acc@5 0.602 against 0.532 for `product` (Δ +0.070, Holm p 0.009). `rrf(product+dense)` gave 0.679 (Δ +0.146, Holm p 0.0004). With only the Python files in each list, `dense` gives Acc@5 0.614 and Acc@10 0.713. SweRank reports 74.29 (Acc@10 80.36) for CodeRankEmbed alone on this set. Thus this harness is still about 13 points lower, and the cause is not clear.

The table gives the core mix on the full query. The metric is Acc@5, but gNDCG@5 on the judged rows of `graded_blind`.

| Dataset | n | `product` | `dense` | `rrf(product+dense)` |
|---|---:|---:|---:|---:|
| broad_dev | 20 | 0.100 | 0.200 | 0.150 |
| broad_external | 20 | 0.700 | 0.850 | 0.750 |
| broad_holdout | 20 | 0.500 | 0.650 | 0.700 |
| graded_blind | 36 | 0.488 | 0.373 | 0.658 |
| lca | 60 | 0.317 | 0.383 | 0.433 |
| lite | 40 | 0.600 | 0.625 | 0.650 |
| live | 60 | 0.283 | 0.300 | 0.350 |
| locbench | 80 | 0.625 | 0.650 | 0.725 |
| polybench | 60 | 0.283 | 0.233 | 0.333 |

No difference on the core mix passes the Holm test. The datasets are small.

The earlier result (v1, also on 2026-10-09) ranked all stored files. It embedded at most 40 windows (1,600 lines) of a file and cut the query at 512 tokens. Markdown, reStructuredText, YAML and text files were about a fifth of the first ten files of `dense`. On the full issue of Loc-Bench 560, `dense` gave Acc@5 0.541 and `rrf(product+dense)` 0.664, against 0.532 for `product`. With only the Python files, `dense` gave 0.609. That pod embedded 1.99 million windows for about $1.7.
