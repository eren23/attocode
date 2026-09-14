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
